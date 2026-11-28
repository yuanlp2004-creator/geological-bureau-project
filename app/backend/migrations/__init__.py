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

from .v21_calibration_metadata import _migrate_v21

from .v22_contract_samples import _migrate_v22
from .v23_contract_closure import _migrate_v23
from .v24_acquisition_turns import _migrate_v24
from .v25_manual_turns import _migrate_v25
from .v26_dispersion_locate_anchor import _migrate_v26
from .v27_capture_context import _migrate_v27
from .v28_prepared_import import _migrate_v28
from .v29_bluetooth_hidden import _migrate_v29
from .v30_sample_turn_bands import _migrate_v30
from .v31_analysis_numbering import _migrate_v31
from .v32_capture_disposals import _migrate_v32
from .v33_acquisition_monitoring import _migrate_v33

SCHEMA_VERSION = 33
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
    (21, "calibration_metadata", _migrate_v21),
    (22, "contract_samples", _migrate_v22),
    (23, "contract_closure", _migrate_v23),
    (24, "acquisition", _migrate_v24),
    (25, "hardware_acquisition", _migrate_v25),
    (26, "dispersion", _migrate_v26),
    (27, "capture_context", _migrate_v27),
    (28, "postprocessing", _migrate_v28),
    (29, "devices", _migrate_v29),
    (30, "acquisition", _migrate_v30),
    (31, "analysis", _migrate_v31),
    (32, "capture_context", _migrate_v32),
    (33, "acquisition", _migrate_v33),
)
