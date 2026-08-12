from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


Severity = Literal["debug", "info", "success", "warning", "error"]
EventCategory = Literal["system", "action", "import", "acquisition", "analysis", "export"]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app: str
    version: str
    schema_version: int
    database: Literal["ok"]
    uptime_seconds: float


class AboutResponse(BaseModel):
    name: str
    display_name: str
    version: str
    api_version: str
    stage: str
    description: str
    runtime: str
    database: str
    modules: list[dict[str, Any]]


class DiagnosticsResponse(BaseModel):
    service: str
    database_path: str
    runtime_log_path: str
    schema_version: int
    sqlite_integrity: str
    journal_mode: str
    foreign_keys: int
    event_count: int
    manifest_valid: bool


class Capability(BaseModel):
    key: str
    version: str
    title: str
    api_prefix: str
    route: str
    enabled: bool
    permissions: list[str] = Field(default_factory=list)
    audit_actions: list[str] = Field(default_factory=list)


class CapabilitiesResponse(BaseModel):
    api_version: str
    generated_at: datetime
    capabilities: list[Capability]


class SettingsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    directories: dict[str, str]
    logging: dict[str, Any]
    display: dict[str, Any]
    printing: dict[str, Any]
    time: dict[str, Any]


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="allow")

    directories: dict[str, str] | None = None
    logging: dict[str, Any] | None = None
    display: dict[str, Any] | None = None
    printing: dict[str, Any] | None = None
    time: dict[str, Any] | None = None


class RuntimeEventCreate(BaseModel):
    category: EventCategory = "system"
    severity: Severity = "info"
    message: str = Field(min_length=1, max_length=500)
    details: dict[str, Any] | None = None
    correlation_id: str | None = Field(default=None, max_length=100)


class RuntimeEvent(BaseModel):
    id: int
    category: str
    severity: str
    message: str
    details: dict[str, Any] | None
    correlation_id: str | None
    created_at: datetime

class BootstrapRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=200)
class LoginRequest(BootstrapRequest):
    pass
class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=200)
    role_ids: list[int] = Field(default_factory=list)
class UserUpdate(BaseModel):
    enabled: bool | None = None
    role_ids: list[int] | None = None
class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    permission_keys: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    description: str | None = None
    permission_keys: list[str] | None = None

class MethodCondition(BaseModel):
    """Editable method conditions.

    Numeric bounds are deliberately checked by the method domain service rather
    than Pydantic.  A draft must be able to retain invalid values and return
    field-level errors until the operator fixes it before publishing.
    """

    model_config = ConfigDict(extra="allow")

    ccd_layout_id: str | int = "default"
    selected_ccds: list[int] = Field(default_factory=lambda: [0, 1, 2, 4, 5])
    dispersion_calibration_id: str | int = "default"
    reference_wavelength_nm: float = 253.65
    actual_reference_wavelength_nm: float = 253.65
    reference_width_points: int = 21
    analysis_unit: str = "ug/g"
    calculation_profile: Literal["legacy_2_0_2", "modern_v1"] = "modern_v1"
    pre_excitation_seconds: float = 3.0
    sampling_period_seconds: float = 1.0
    frame_count: int = 20
    dark_frame_count: int = 8
    sample_repeats: int = 1
    standard_repeats: int = 3
    control_repeats: int = 1
    standard_sample_name: str = Field(default="", max_length=100)
    maximum_id_deviation: float = 5.0
    rsd_enabled: bool = True
    rsd_threshold: float = 5.0
    calibration_threshold: float = 5.0
    qc_threshold: float = 0.0
    abnormal_threshold: float = 0.0
    angle_exposures: list[dict[str, Any]] = Field(
        default_factory=lambda: [
            {
                "angle_deg": 0.0,
                "storage_mode": "averaged",
                "start_frame": 1,
                "end_frame": 20,
            }
        ]
    )

class MethodCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    work_type: str = Field(default="spectral", min_length=1, max_length=50)
    conditions: MethodCondition | dict[str, Any] = Field(default_factory=MethodCondition)

class MethodUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    work_type: str | None = Field(default=None, min_length=1, max_length=50)
    conditions: MethodCondition | dict[str, Any] | None = None


class MethodActionRequest(BaseModel):
    method_id: int | None = None


class MethodVersion(BaseModel):
    id: int
    version: int
    state: Literal["draft", "published"]
    conditions: dict[str, Any]
    lines: list[dict[str, Any]] = Field(default_factory=list)
    validation_errors: list[dict[str, Any]]
    content_sha256: str
    created_at: datetime


class StandardPointInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=50)
    value: float
    active: bool = True


class SpectralLineInput(BaseModel):
    """Complete editable spectral-line payload.

    Domain bounds stay in the service so invalid references and numeric rules
    return stable S04 error codes instead of generic request parsing errors.
    """

    model_config = ConfigDict(extra="forbid")

    line_type: Literal["baseline", "analysis", "internal_standard", "positioning"] = "analysis"
    element: str = Field(min_length=1, max_length=20)
    wavelength_nm: float
    actual_wavelength_nm: float | None = None
    enabled: bool = True
    critical_band: bool = False
    priority: int = 0
    background_line_id: str | None = None
    alignment_line_id: str | None = None
    internal_standard_mode: Literal["none", "background", "line"] = "none"
    internal_standard_line_id: str | None = None
    scan_width_points: int = 9
    background_offset_points: int = 0
    peak_mode: Literal["max_single_point", "gaussian"] = "max_single_point"
    peak_width_points: int = 1
    fit_mode: Literal["linear", "quadratic", "cubic", "spline"] = "linear"
    coordinate_type: Literal["normal", "logarithmic"] = "normal"
    unit: Literal["ug/g", "mg/g", "%"] = "ug/g"
    value_kind: Literal["content", "concentration"] = "content"
    decimal_places: int = 2
    lower_peak: int = 300
    minimum_peak_ratio: float = 1.5
    valid_range_min: float = 0.0
    valid_range_max: float = 9_999_999.0
    over_limit_tolerance_percent: float = 0.0
    standard_points: list[StandardPointInput] = Field(default_factory=list)


class SpectralLineReorder(BaseModel):
    line_ids: list[str]


class SpectralLineDetectRequest(BaseModel):
    wavelength_nm: float
    actual_wavelength_nm: float | None = None
    scan_width_points: int = 9


class MethodPrintSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_printer: str = Field(default="geospectrum-pdf", min_length=1, max_length=255)
    paper: Literal["A4", "A3", "Letter"] = "A4"
    orientation: Literal["portrait", "landscape"] = "portrait"
    margin_top_mm: float = Field(default=12, ge=5, le=40)
    margin_right_mm: float = Field(default=12, ge=5, le=40)
    margin_bottom_mm: float = Field(default=12, ge=5, le=40)
    margin_left_mm: float = Field(default=12, ge=5, le=40)
    layout: Literal["standard", "compact"] = "standard"
    font_size_pt: int = Field(default=9, ge=8, le=12)
    copies: int = Field(default=1, ge=1, le=99)
    duplex: Literal["none", "long_edge", "short_edge"] = "none"
    color: bool = False
    preview_before_print: bool = True


class MethodRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int | None = Field(default=None, ge=1)
    settings: MethodPrintSettings | None = None


class MethodPrintRequest(MethodRenderRequest):
    printer_name: str | None = Field(default=None, min_length=1, max_length=255)


class LegacyMigrationStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mtd_path: str = Field(min_length=1, max_length=2048)
    cfg_path: str = Field(min_length=1, max_length=2048)
    opt_path: str = Field(min_length=1, max_length=2048)


class LegacyMigrationCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=64)


class SpectrumMigrationStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2048)


class SpectrumMigrationCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=64)


class SpectrumPrintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visible_x_min: float
    visible_x_max: float
    visible_y_min: float
    visible_y_max: float
    ccd: int = Field(default=0, ge=0, le=255)
    line: int = Field(default=0, ge=0, le=4095)
    mode: Literal["mean", "peak", "back", "value", "frame"] = "mean"
    reference_shift: float = 0.0
    selected_record_ids: list[str] = Field(default_factory=list, max_length=8)
    priority_record_id: str | None = Field(default=None, min_length=1, max_length=64)
    frame_phase: Literal["burn", "dark"] = "burn"
    frame_index: int = Field(default=0, ge=0)
    exposure_start: int | None = Field(default=None, ge=1)
    exposure_end: int | None = Field(default=None, ge=1)


class ResultMigrationStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2048)


class ResultMigrationCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=64)


class SampleQueueItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pre_name: str = Field(default="", max_length=100)
    repeats: int = Field(default=0, ge=0, le=10)
    post_name: str | None = Field(default=None, max_length=100)
    spectrum_hash: str | None = Field(default=None, max_length=128)


class SampleQueueCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="未命名队列", min_length=1, max_length=120)
    items: list[SampleQueueItemInput] = Field(default_factory=list, max_length=1000)


class SampleQueueUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[SampleQueueItemInput] = Field(default_factory=list, max_length=1000)


class SampleQueueRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    post_name: str = Field(min_length=1, max_length=100)


class SampleQueueImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(default="queue.sam", min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=5_000_000)
    queue_name: str | None = Field(default=None, max_length=120)


class DeviceProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    transport: Literal["simulator", "serial"] = "simulator"
    port: int = Field(default=3, ge=1, le=256)
    baud_rate: int = Field(default=460800, ge=1)
    mirror: bool = False
    frame_count: int = Field(default=3, ge=1, le=32)
    ccds_per_frame: int = Field(default=2, ge=1, le=8)
    points_per_ccd: int = Field(default=2048, ge=1, le=4096)
    ccd_indices: list[int] = Field(default_factory=lambda: [0, 1, 2, 4, 5], min_length=1, max_length=256)
    point_width_um: float = Field(default=14.0, gt=0, le=1000)
    protection_time_ms: float = Field(default=200.0, ge=0, le=60000)
    screen_width_mm: float = Field(default=40.92, gt=0, le=10000)
    screen_resolution_px: int = Field(default=1920, ge=320, le=16000)
    enabled: bool = True


class DeviceProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    transport: Literal["simulator", "serial"] | None = None
    port: int | None = Field(default=None, ge=1, le=256)
    baud_rate: int | None = Field(default=None, ge=1)
    mirror: bool | None = None
    frame_count: int | None = Field(default=None, ge=1, le=32)
    ccds_per_frame: int | None = Field(default=None, ge=1, le=8)
    points_per_ccd: int | None = Field(default=None, ge=1, le=4096)
    ccd_indices: list[int] | None = Field(default=None, min_length=1, max_length=256)
    point_width_um: float | None = Field(default=None, gt=0, le=1000)
    protection_time_ms: float | None = Field(default=None, ge=0, le=60000)
    screen_width_mm: float | None = Field(default=None, gt=0, le=10000)
    screen_resolution_px: int | None = Field(default=None, ge=320, le=16000)
    enabled: bool | None = None


class DeviceConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: int = Field(ge=1)


class DeviceDebugStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample: str = Field(default="280-288.acq", min_length=1, max_length=100)
    seed: int = Field(default=0, ge=0, le=2_147_483_647)
    fault_frame: int | None = Field(default=None, ge=0, le=10_000)


class DispersionLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element: str = Field(min_length=1, max_length=20)
    wavelength_nm: float = Field(gt=0, le=2000)
    ccd_index: int = Field(default=0, ge=0, le=255)
    actual_position: float | None = Field(default=None, ge=0, le=100000)


class DispersionTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="S12 色散校准", min_length=1, max_length=120)
    device_profile_id: int = Field(default=1, ge=1)
    ccd_layout_id: str | int = "default"
    method_id: int | None = Field(default=None, ge=1)
    method_version: int | None = Field(default=None, ge=1)
    sample: str = Field(default="280-288.acq", min_length=1, max_length=100)
    seed: int = Field(default=0, ge=0, le=2_147_483_647)
    frame_count: int = Field(default=3, ge=1, le=255)
    dark_frame_count: int = Field(default=1, ge=0, le=20)
    pre_excitation_seconds: float = Field(default=3.0, ge=0, le=600)
    sampling_period_seconds: float = Field(default=1.0, gt=0, le=60)
    residual_limit_points: float = Field(default=2.0, gt=0, le=1000)
    ccd_indices: list[int] | None = Field(default=None, min_length=1, max_length=256)
    lines: list[DispersionLineInput] = Field(default_factory=list, max_length=100)


class DispersionLineMoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: Literal["short", "long"]
    steps: float = Field(default=1.0, gt=0, le=1000)


class DispersionCalibrationFitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    degree: int = Field(default=2, ge=1, le=3)
    residual_limit_points: float | None = Field(default=None, gt=0, le=1000)


class DispersionCalibrationBindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method_id: int = Field(ge=1)
    method_version: int | None = Field(default=None, ge=1)


class AcquisitionTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_kind: Literal["evaporation", "sample"] = "sample"
    name: str = Field(default="S13 样品采集", min_length=1, max_length=120)
    device_profile_id: int = Field(default=1, ge=1)
    ccd_layout_id: str | int = "default"
    ccd_indices: list[int] | None = Field(default=None, min_length=1, max_length=256)
    method_id: int | None = Field(default=None, ge=1)
    method_version: int | None = Field(default=None, ge=1)
    queue_id: int | None = Field(default=None, ge=1)
    queue_item_id: int | None = Field(default=None, ge=1)
    sample_name: str = Field(default="", max_length=100)
    sample_kind: Literal["blank", "normal", "standard", "test", "preheat"] = "test"
    naming_mode: Literal["pre_recorded", "temporary", "post"] = "temporary"
    storage_mode: Literal["averaged", "full_interval"] = "averaged"
    repeat_count: int = Field(default=1, ge=1, le=10)
    burn_frame_count: int = Field(default=3, ge=1, le=255)
    dark_frame_count: int = Field(default=1, ge=0, le=20)
    countdown_seconds: float = Field(default=0, ge=0, le=600)
    pre_excitation_seconds: float = Field(default=1, ge=0, le=600)
    sampling_period_seconds: float = Field(default=1, gt=0, le=60)
    burn_cycle_seconds: float = Field(default=1, gt=0, le=60)
    dark_cycle_seconds: float = Field(default=1, gt=0, le=60)
    excitation_conditions: dict[str, Any] = Field(default_factory=dict)
    evaporation_conditions: dict[str, Any] = Field(default_factory=dict)
    simulator_sample: str = Field(default="280-288.acq", min_length=1, max_length=100)
    seed: int = Field(default=0, ge=0, le=2_147_483_647)
    fault_frame: int | None = Field(default=None, ge=0, le=10_000)


class AcquisitionIntervalMark(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repeat_index: int = Field(default=0, ge=0, le=10)
    label: str = Field(min_length=1, max_length=50)
    start_frame_index: int = Field(ge=0, le=255)
    end_frame_index: int = Field(ge=0, le=255)


class AcquisitionRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post_name: str = Field(min_length=1, max_length=100)


class AnalysisRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="S16 定量分析", min_length=1, max_length=120)
    acquisition_sample_ids: list[int] = Field(min_length=1, max_length=200)
    method_version_id: int | None = Field(default=None, ge=1)
    calculation_profile: Literal["legacy_2_0_2", "modern_v1"] | None = None
    slow_mode: bool = False
    intervention_timeout_seconds: float = Field(default=300, ge=0.05, le=86_400)


class AnalysisIntervention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["accept", "discard"]
    adjusted_position: int | None = Field(default=None, ge=0, le=65_535)
    reason: str = Field(default="", max_length=500)


class HardwareTurnInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    angle_deg: float = Field(ge=-360, le=360)
    wavelength_nm: float = Field(ge=160, le=800)
    priority: int = Field(default=0, ge=0, le=100)
    key_band: bool = False
    expected_peak_position: float = Field(default=1024, ge=0, le=4096)


class HardwareTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="S14 真实设备与自动转角", min_length=1, max_length=120)
    device_profile_id: int = Field(default=1, ge=1)
    ccd_layout_id: str | int = "default"
    method_id: int | None = Field(default=None, ge=1)
    method_version: int | None = Field(default=None, ge=1)
    sample_name: str = Field(default="", max_length=100)
    strategy: Literal["short_to_long", "key_first"] = "short_to_long"
    anomaly_policy: Literal["retry_then_stop", "manual"] = "retry_then_stop"
    retry_limit: int = Field(default=1, ge=0, le=5)
    pre_excitation_seconds: float = Field(default=1, ge=0, le=600)
    sampling_period_seconds: float = Field(default=1, gt=0, le=60)
    ccd_indices: list[int] | None = Field(default=None, min_length=1, max_length=256)
    turns: list[HardwareTurnInput] = Field(min_length=1, max_length=300)
    thresholds: dict[str, float] = Field(default_factory=dict)
    simulator_sample: str = Field(default="280-288.acq", min_length=1, max_length=100)
    seed: int = Field(default=0, ge=0, le=2_147_483_647)
    simulator_anomalies: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class HardwareIntervention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["accept", "retry", "stop"]
    note: str = Field(default="", max_length=300)


class MercurySessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="S15 汞灯调试与光学校准", min_length=1, max_length=120)
    device_profile_id: int = Field(default=1, ge=1)
    ccd_layout_id: str | int = "default"
    line_ids: list[int] = Field(min_length=2, max_length=20)
    stabilization_frames: int = Field(default=2, ge=1, le=20)
    tolerance_points: float = Field(default=1.0, gt=0, le=100)
    search_radius_points: int = Field(default=40, ge=1, le=500)
    correction_limit_points: float = Field(default=25.0, gt=0, le=500)
    simulator_offset_points: float = Field(default=6.0, ge=-100, le=100)
    simulator_seed: int = Field(default=0, ge=0, le=2_147_483_647)
    simulator_fault: Literal["none", "switch_failure", "stability_failure", "capture_failure"] = "none"

class MethodResponse(BaseModel):
    id: int
    name: str
    description: str
    work_type: str
    status: str
    current_version: int | None
    latest_version: int | None
    version: MethodVersion | None = None
    published_version: MethodVersion | None = None
    is_current: bool = False
    created_at: datetime
    updated_at: datetime


class MethodCurrentResponse(BaseModel):
    method_id: int | None
    version: int | None
    work_type: str | None
    title: str | None
    status: str | None
    action_state: str
    actions: dict[str, bool]
    method: MethodResponse | None = None
    referenced_version: MethodVersion | None = None
