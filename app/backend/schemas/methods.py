"""Methods request and response models, moved without rule changes."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
