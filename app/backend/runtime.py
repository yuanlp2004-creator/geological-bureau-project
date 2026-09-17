"""Per-application services and event state; no FastAPI or entry-point imports."""
from __future__ import annotations

import asyncio

from .config import AppConfig
from .db import Database
from .printing import SystemPrinters
from .services import AppService
from .auth import AuthService
from .modules.methods import MethodService
from .modules.method_printing import MethodPrintService
from .modules.spectral_lines import SpectralLineService
from .modules.legacy_migration import LegacyMigrationService
from .modules.sample_queues import SampleQueueService
from .modules.spectrum_migration import SpectrumMigrationService
from .modules.result_migration import ResultMigrationService
from .modules.spectrum_viewer import SpectrumViewerService
from .modules.devices import DeviceService
from .modules.dispersion import DispersionService
from .modules.acquisition import AcquisitionService
from .modules.acquisition_import import AcquisitionRecordImporter
from .modules.hardware_acquisition import HardwareAcquisitionService
from .modules.mercury_calibration import MercuryCalibrationService
from .modules.analysis import AnalysisService
from .modules.postprocessing import PostProcessingService
from .modules.reports import ReportService
from .modules.maintenance import MaintenanceService


class Runtime:
    def __init__(self, config: AppConfig, *, database: Database | None = None, process_key: str = ""):
        self.config = config
        self.database = database if database is not None else Database(config.database_path)
        self.service = AppService(self.database, config.runtime_log_path)
        self.auth_service = AuthService(self.database)
        self.process_key = process_key
        self.event_subscribers: set[asyncio.Queue[dict]] = set()
        self._device_service_instance = None
        self._dispersion_service_instance = None
        self._acquisition_service_instance = None
        self._hardware_acquisition_service_instance = None
        self._mercury_calibration_service_instance = None

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
        return PostProcessingService(self.database, analysis=self.analysis_service(), methods=self.methods_service(), acquisitions=AcquisitionRecordImporter())

    def devices_service(self) -> DeviceService:
        if self._device_service_instance is None or self._device_service_instance.database is not self.database:
            self._device_service_instance = DeviceService(self.database)
        return self._device_service_instance

    def dispersion_service(self) -> DispersionService:
        if self._dispersion_service_instance is None or self._dispersion_service_instance.database is not self.database:
            self._dispersion_service_instance = DispersionService(self.database)
        return self._dispersion_service_instance

    def acquisition_service(self) -> AcquisitionService:
        if self._acquisition_service_instance is None or self._acquisition_service_instance.database is not self.database:
            self._acquisition_service_instance = AcquisitionService(self.database)
        return self._acquisition_service_instance

    def hardware_acquisition_service(self) -> HardwareAcquisitionService:
        if self._hardware_acquisition_service_instance is None or self._hardware_acquisition_service_instance.database is not self.database:
            self._hardware_acquisition_service_instance = HardwareAcquisitionService(self.database)
        return self._hardware_acquisition_service_instance

    def mercury_calibration_service(self) -> MercuryCalibrationService:
        if self._mercury_calibration_service_instance is None or self._mercury_calibration_service_instance.database is not self.database:
            self._mercury_calibration_service_instance = MercuryCalibrationService(self.database)
        return self._mercury_calibration_service_instance

    def analysis_service(self) -> AnalysisService:
        return AnalysisService(self.database, methods=self.methods_service())

    def reports_service(self) -> ReportService:
        return ReportService(self.database, printers=SystemPrinters())

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
