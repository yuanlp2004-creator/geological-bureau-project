"""Explicit historical migration order; importing never opens a database."""

from .v11_devices import _migrate_v11
from .v12_dispersion import _migrate_v12
from .v13_acquisition import _migrate_v13
from .v14_hardware_acquisition import _migrate_v14
from .v15_mercury_calibration import _migrate_v15
from .v16_analysis import _migrate_v16
from .v17_analysis_quality_curves import _migrate_v17
from .v18_postprocessing import _migrate_v18
from .v19_reports import _migrate_v19
from .v20_maintenance import _migrate_v20

SCHEMA_VERSION = 20
SCHEMA_BASELINE_VERSION = 10

MIGRATIONS = (
    (11, "devices", _migrate_v11),
    (12, "dispersion", _migrate_v12),
    (13, "acquisition", _migrate_v13),
    (14, "hardware_acquisition", _migrate_v14),
    (15, "mercury_calibration", _migrate_v15),
    (16, "analysis", _migrate_v16),
    (17, "analysis_quality_curves", _migrate_v17),
    (18, "postprocessing", _migrate_v18),
    (19, "reports", _migrate_v19),
    (20, "maintenance", _migrate_v20),
)
