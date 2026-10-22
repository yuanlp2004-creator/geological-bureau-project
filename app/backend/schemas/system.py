"""System models, moved without validation changes."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    license: str = ""
    copyright: str = ""
    build: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def current_stage(self) -> "AboutResponse":
        if self.name == "geospectrum":
            self.stage = "S21 · Windows 内部测试发布"
        return self


class ModuleDiagnostic(BaseModel):
    key: str
    title: str
    version: str
    route: str
    enabled: bool
    status: Literal["active", "disabled", "error", "restricted", "unchecked"]
    message: str
    probe_path: str | None = None
    http_status: int | None = None
    note: str = ""


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
    manifest_error: str | None = None
    checked_at: datetime | None = None
    modules: list[ModuleDiagnostic] = Field(default_factory=list)


class Capability(BaseModel):
    key: str
    version: str
    title: str
    api_prefix: str
    route: str
    enabled: bool
    permissions: list[str] = Field(default_factory=list)
    audit_actions: list[str] = Field(default_factory=list)
    navigation_entries: list[dict[str, Any]] = Field(default_factory=list)


class CapabilitiesResponse(BaseModel):
    api_version: str
    generated_at: datetime
    capabilities: list[Capability]


class _SettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SettingsDirectories(_SettingsModel):
    data: str = Field(min_length=1, max_length=2048)
    methods: str = Field(min_length=1, max_length=2048)
    samples: str = Field(min_length=1, max_length=2048)
    exports: str = Field(min_length=1, max_length=2048)
    backups: str = Field(min_length=1, max_length=2048)


class SettingsDirectoriesPatch(_SettingsModel):
    data: str | None = Field(default=None, min_length=1, max_length=2048)
    methods: str | None = Field(default=None, min_length=1, max_length=2048)
    samples: str | None = Field(default=None, min_length=1, max_length=2048)
    exports: str | None = Field(default=None, min_length=1, max_length=2048)
    backups: str | None = Field(default=None, min_length=1, max_length=2048)


class SettingsLogging(_SettingsModel):
    level: Literal["debug", "info", "warning"]
    max_bytes: int = Field(ge=1024, le=1_073_741_824)
    retention_days: int = Field(ge=1, le=365)


class SettingsLoggingPatch(_SettingsModel):
    level: Literal["debug", "info", "warning"] | None = None
    max_bytes: int | None = Field(default=None, ge=1024, le=1_073_741_824)
    retention_days: int | None = Field(default=None, ge=1, le=365)


class SettingsDisplay(_SettingsModel):
    screen_width_mm: float = Field(default=409.2,ge=254,le=1227.6)
    screen_resolution_px: int = Field(default=1920,ge=320,le=16384)
    theme: Literal["light", "dark"]
    density: Literal["comfortable", "compact"]
    show_status_bar: bool


class SettingsDisplayPatch(_SettingsModel):
    screen_width_mm: float | None = Field(default=None,ge=254,le=1227.6)
    screen_resolution_px: int | None = Field(default=None,ge=320,le=16384)
    theme: Literal["light", "dark"] | None = None
    density: Literal["comfortable", "compact"] | None = None
    show_status_bar: bool | None = None


class SettingsPrinting(_SettingsModel):
    elements_per_line: int = Field(default=15,ge=1,le=50)
    samples_per_page: int = Field(default=50,ge=1,le=1000)
    time_mode: Literal['analysis','system'] = 'analysis'
    default_printer: str = Field(min_length=1, max_length=255)
    paper: str = Field(pattern=r"^(?:A4|A3|Letter|win:[1-9][0-9]{0,4}:[1-9][0-9]{1,4}:[1-9][0-9]{1,4})$")
    orientation: Literal["portrait", "landscape"]
    margin_top_mm: float = Field(ge=5, le=40)
    margin_right_mm: float = Field(ge=5, le=40)
    margin_bottom_mm: float = Field(ge=5, le=40)
    margin_left_mm: float = Field(ge=5, le=40)
    layout: Literal["standard", "compact"]
    font_size_pt: int = Field(ge=8, le=13)
    copies: int = Field(ge=1, le=99)
    duplex: Literal["none", "long_edge", "short_edge"]
    color: bool
    preview_before_print: bool


class SettingsPrintingPatch(_SettingsModel):
    elements_per_line: int | None = Field(default=None,ge=1,le=50)
    samples_per_page: int | None = Field(default=None,ge=1,le=1000)
    time_mode: Literal['analysis','system'] | None = None
    default_printer: str | None = Field(default=None, min_length=1, max_length=255)
    paper: str | None = Field(default=None, pattern=r"^(?:A4|A3|Letter|win:[1-9][0-9]{0,4}:[1-9][0-9]{1,4}:[1-9][0-9]{1,4})$")
    orientation: Literal["portrait", "landscape"] | None = None
    margin_top_mm: float | None = Field(default=None, ge=5, le=40)
    margin_right_mm: float | None = Field(default=None, ge=5, le=40)
    margin_bottom_mm: float | None = Field(default=None, ge=5, le=40)
    margin_left_mm: float | None = Field(default=None, ge=5, le=40)
    layout: Literal["standard", "compact"] | None = None
    font_size_pt: int | None = Field(default=None, ge=8, le=13)
    copies: int | None = Field(default=None, ge=1, le=99)
    duplex: Literal["none", "long_edge", "short_edge"] | None = None
    color: bool | None = None
    preview_before_print: bool | None = None


class SettingsTime(_SettingsModel):
    timezone: Literal["Asia/Shanghai", "UTC"]
    format: Literal["YYYY-MM-DD HH:mm:ss"]


class SettingsTimePatch(_SettingsModel):
    timezone: Literal["Asia/Shanghai", "UTC"] | None = None
    format: Literal["YYYY-MM-DD HH:mm:ss"] | None = None


class SettingsAnalysis(_SettingsModel):
    dispersion_allow_gap_error_um: float = Field(default=150, gt=0, le=10000)
    dark_round_time_seconds: int = Field(default=8, ge=6, le=20)
    log_analysis: bool = True
    look_band: bool = True
    wait_time_ms: int = Field(default=100,ge=0,le=5000)
    cmt_band_mean: bool = False


class SettingsIntensityOutput(_SettingsModel):
    save_intensity: bool = True
    print_intensity: bool = True
    print_to_text: bool = False
    save_positions: bool = True


class SettingsAnalysisPatch(_SettingsModel):
    dispersion_allow_gap_error_um: float | None = Field(default=None, gt=0, le=10000)
    dark_round_time_seconds: int | None = Field(default=None,ge=6,le=20)
    log_analysis: bool | None = None
    look_band: bool | None = None
    wait_time_ms: int | None = Field(default=None,ge=0,le=5000)
    cmt_band_mean: bool | None = None


class PreliminaryConditions(_SettingsModel):
    pre_excitation_seconds: float = Field(default=1, ge=0, le=600)
    sampling_period_seconds: float = Field(default=1, ge=0.01, le=60, multiple_of=0.01)
    frame_count: int = Field(default=3, ge=1, le=255)
    dark_frame_count: int = Field(default=1, ge=0, le=20)


class SettingsPreliminary(_SettingsModel):
    evaporation: PreliminaryConditions = Field(default_factory=PreliminaryConditions)
    dispersion: PreliminaryConditions = Field(default_factory=lambda: PreliminaryConditions(pre_excitation_seconds=3))


class SettingsPreliminaryPatch(_SettingsModel):
    evaporation: PreliminaryConditions | None = None
    dispersion: PreliminaryConditions | None = None


class SettingsResponse(_SettingsModel):
    intensity_output: SettingsIntensityOutput = Field(default_factory=SettingsIntensityOutput)
    directories: SettingsDirectories
    logging: SettingsLogging
    display: SettingsDisplay
    printing: SettingsPrinting
    time: SettingsTime
    analysis: SettingsAnalysis = Field(default_factory=SettingsAnalysis)
    preliminary: SettingsPreliminary = Field(default_factory=SettingsPreliminary)


class SettingsPatch(_SettingsModel):
    intensity_output: SettingsIntensityOutput | None = None
    directories: SettingsDirectoriesPatch | None = None
    logging: SettingsLoggingPatch | None = None
    display: SettingsDisplayPatch | None = None
    printing: SettingsPrintingPatch | None = None
    time: SettingsTimePatch | None = None
    analysis: SettingsAnalysisPatch | None = None
    preliminary: SettingsPreliminaryPatch | None = None


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
