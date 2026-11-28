"""Per-application services and event state; no FastAPI or entry-point imports."""

from __future__ import annotations

import asyncio
import logging
import threading
from functools import partial

from .config import AppConfig
from .db import Database
from .printing import SystemPrinters
from .services import AppService
from .runtime_messages import RuntimeMessages
from .auth import AuthService
from .modules.activation import ActivationService
from .modules.support_diagnostics import SupportDiagnostics
from .modules.methods import MethodService
from .modules.method_printing import MethodPrintService
from .modules.spectral_lines import SpectralLineService
from .modules.legacy_migration import LegacyMigrationService
from .modules.sample_queues import SampleQueueService
from .modules.spectrum_migration import SpectrumMigrationService
from .modules.result_migration import ResultMigrationService
from .modules.spectrum_viewer import SpectrumViewerService
from .modules.devices import DeviceError, DeviceService
from .modules.devices.ownership import DeviceOwnership
from .modules.dispersion import DispersionService
from .modules.acquisition import AcquisitionService
from .modules.acquisition_import import AcquisitionRecordImporter
from .modules.analysis import AnalysisService
from .modules.postprocessing import PostProcessingService
from .modules.reports import ReportService
from .modules.maintenance import MaintenanceService

_READ_OWNERSHIP = object()


class Runtime:
    def __init__(self, config: AppConfig, *, database: Database | None = None, process_key: str = ""):
        self.config = config
        self.database = database if database is not None else Database(config.database_path)
        self.service = AppService(self.database, config.runtime_log_path)
        self.messages = RuntimeMessages(self.service)
        self.auth_service = AuthService(self.database)
        self.activation = ActivationService(config.data_dir, config.activation_public_key)
        self.support_diagnostics = SupportDiagnostics()
        self.process_key = process_key
        self.device_exit_gate = threading.Event()
        self.device_ownership = DeviceOwnership(self.device_exit_gate)
        self._service_lock = threading.Lock()
        self._shutdown_lock = threading.Lock()
        self.event_subscribers: set[asyncio.Queue[dict]] = set()
        self._device_service_instance = None
        self._dispersion_service_instance = None
        self._acquisition_service_instance = None

    def methods_service(self) -> MethodService:
        return MethodService(self.database)

    def spectral_lines_service(self) -> SpectralLineService:
        return SpectralLineService(self.database)

    def method_print_service(self) -> MethodPrintService:
        return MethodPrintService(self.database, methods=self.methods_service(), printers=SystemPrinters())

    def legacy_migration_service(self) -> LegacyMigrationService:
        return LegacyMigrationService(self.database)

    def sample_queue_service(self) -> SampleQueueService:
        return SampleQueueService(self.database)

    def spectrum_migration_service(self) -> SpectrumMigrationService:
        return SpectrumMigrationService(self.database)

    def result_migration_service(self) -> ResultMigrationService:
        return ResultMigrationService(self.database)

    def spectrum_viewer_service(self) -> SpectrumViewerService:
        return SpectrumViewerService(self.database)

    def postprocessing_service(self) -> PostProcessingService:
        return PostProcessingService(
            self.database,
            analysis=self.analysis_service(),
            methods=self.methods_service(),
            acquisitions=AcquisitionRecordImporter(),
        )

    def _stateful_service(self, name, factory, **options):
        with self._service_lock:
            instance = getattr(self, name)
            if instance is None:
                instance = factory(self.database, **options)
                setattr(self, name, instance)
            return instance

    def devices_service(self) -> DeviceService:
        return self._stateful_service(
            '_device_service_instance', DeviceService, exit_gate=self.device_exit_gate,
            ownership=self.device_ownership,
            on_serial_notice=partial(self.messages.serial_notice, source='devices'),
        )

    def active_serial_captures(self, *, ownership=_READ_OWNERSHIP) -> list[dict]:
        use = self.device_ownership.snapshot() if ownership is _READ_OWNERSHIP else ownership
        if not use or use['transport'] != 'serial' or use['task_id'] is None:
            return []
        service = (self._dispersion_service_instance if use['owner'] == 'dispersion'
                   else self._acquisition_service_instance)
        connections = service.active_serial_connections() if service is not None else []
        details = next((item for item in connections if item['task_id'] == use['task_id']), {})
        return [{**details, **use, 'last_error': use['last_error'] or details.get('last_error')}]

    def _release_alignment(self, profile_id, actor):
        self.devices_service().release_for_capture(profile_id, actor)

    def dispersion_service(self) -> DispersionService:
        return self._stateful_service(
            '_dispersion_service_instance', DispersionService, exit_gate=self.device_exit_gate,
            ownership=self.device_ownership, handoff=self._release_alignment,
            on_frame_saved=partial(self.messages.capture_frame, source='dispersion'),
            on_serial_notice=partial(self.messages.serial_notice, source='dispersion'),
        )

    def acquisition_service(self) -> AcquisitionService:
        return self._stateful_service(
            '_acquisition_service_instance', AcquisitionService, exit_gate=self.device_exit_gate,
            ownership=self.device_ownership, handoff=self._release_alignment,
            on_frame_saved=partial(self.messages.capture_frame, source='acquisition'),
            on_serial_notice=partial(self.messages.serial_notice, source='acquisition'),
        )

    def _stop_captures(self):
        errors = []
        for service in (self._acquisition_service_instance, self._dispersion_service_instance):
            if service is not None:
                try:
                    errors.extend(service.shutdown() or [])
                except Exception as exc:
                    errors.append({"message": str(exc)})
                    logging.getLogger(__name__).exception("Device shutdown did not confirm instrument stop")
        return errors

    def disconnect_devices(self, actor):
        with self._shutdown_lock:
            if self.device_exit_gate.is_set():
                raise DeviceError('device_exit_in_progress', '正在停止设备', status_code=409)
            self.device_exit_gate.set()
            self.device_ownership.interrupt()
            try:
                errors = self._stop_captures()
                result = self.devices_service().disconnect(actor)
                if errors or self.device_ownership.snapshot() is not None:
                    raise DeviceError('capture_stop_unconfirmed', '未确认摄谱装置已停止',
                                      details={'errors': errors}, status_code=409)
                return result
            finally:
                self.device_exit_gate.clear()

    def shutdown(self, *, resume_on_failure=False) -> list[dict]:
        with self._shutdown_lock:
            self.support_diagnostics.close()
            self.device_exit_gate.set()
            self.device_ownership.interrupt()
            errors = self._stop_captures()
            if self._device_service_instance is not None:
                try:
                    errors.extend(self._device_service_instance.shutdown())
                except Exception as exc:
                    errors.append({"message": str(exc)})
                    logging.getLogger(__name__).exception("Device shutdown did not confirm instrument stop")
            if not errors and self.device_ownership.snapshot() is not None:
                errors.append({"code": "capture_stop_unconfirmed", "message": "设备操作尚未完成收尾"})
            if not errors:
                self.messages.close()
            elif resume_on_failure:
                self.device_exit_gate.clear()
            return errors

    def analysis_service(self) -> AnalysisService:
        return AnalysisService(self.database, methods=self.methods_service())

    def reports_service(self) -> ReportService:
        return ReportService(self.database, printers=SystemPrinters(), analysis=self.analysis_service(), results=self.result_migration_service())

    def maintenance_service(self) -> MaintenanceService:
        return MaintenanceService(self.database, self.config.runtime_log_path)

    async def publish(self, event: dict) -> None:
        if event.get("category") not in {"acquisition", "analysis", "import", "export"}:
            return
        for queue in tuple(self.event_subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass
