"""Explicit API registry; business modules are never discovered by filesystem scanning."""
from fastapi import FastAPI
from .system import router as system_router
from .auth import router as auth_router
from .methods import router as methods_router
from .legacy_migration import router as legacy_migration_router
from .spectrum_migration import router as spectrum_migration_router
from .result_migration import router as result_migration_router
from .spectrum_viewer import router as spectrum_viewer_router
from .sample_queues import router as sample_queues_router
from .devices import router as devices_router
from .dispersion import router as dispersion_router
from .acquisition import router as acquisition_router
from .hardware_acquisition import router as hardware_acquisition_router
from .mercury_calibration import router as mercury_calibration_router
from .maintenance import router as maintenance_router
from .postprocessing import router as postprocessing_router
from .reports import router as reports_router
from .analysis import router as analysis_router
from .events import router as events_router
from .extensions import register_extensions


def register_api(app: FastAPI) -> None:
    register_extensions(app)
    for router in (
        system_router,
        auth_router,
        methods_router,
        legacy_migration_router,
        spectrum_migration_router,
        result_migration_router,
        spectrum_viewer_router,
        sample_queues_router,
        devices_router,
        dispersion_router,
        acquisition_router,
        hardware_acquisition_router,
        mercury_calibration_router,
        maintenance_router,
        postprocessing_router,
        reports_router,
        analysis_router,
        events_router,
    ):
        app.include_router(router)
