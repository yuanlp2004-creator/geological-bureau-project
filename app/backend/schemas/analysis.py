"""Analysis models, moved without validation changes."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .system import SettingsIntensityOutput


class AnalysisIntensityOutputRequest(SettingsIntensityOutput):
    export_format: Literal['excel', 'pdf'] | None = None
    printer_name: str | None = Field(default=None, max_length=255)


class AnalysisCalibrationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['measured', 'theoretical', 'stored'] = 'measured'
    scope: Literal['reference', 'all'] = 'all'
    measured_line_ids: list[str] | None = None


class AnalysisTimeSeriesRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    include_mean: bool = True


class AnalysisSampleNumber(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=20)
    repeats: int = Field(ge=0, le=10)


class AnalysisSampleNumbersFile(BaseModel):
    content_base64: str = Field(max_length=100_000)
    encoding: Literal['gb18030', 'utf-8-sig'] | None = None


class AnalysisSampleNumbersExport(BaseModel):
    entries: list[AnalysisSampleNumber] = Field(min_length=1, max_length=200)


class AnalysisRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="S17 定量与曲线分析", min_length=1, max_length=120)
    acquisition_sample_ids: list[int] = Field(min_length=1, max_length=200)
    sample_names: list[str] | None = Field(default=None, max_length=200)
    sample_numbering: list[AnalysisSampleNumber] | None = Field(default=None, min_length=1, max_length=200)
    method_version_id: int | None = Field(default=None, ge=1)
    calculation_profile: Literal["legacy_2_0_2", "modern_v1"] | None = None
    slow_mode: bool = False
    intervention_timeout_seconds: float = Field(default=300, ge=0.05, le=86_400)


class AnalysisIntervention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["accept", "discard"]
    adjusted_position: int | None = Field(default=None, ge=0, le=65_535)
    reason: str = Field(default="", max_length=500)


class AnalysisQcDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acquisition_task_id: int = Field(ge=1)
    sample_group_position: int | None = Field(default=None, ge=0)
    line_id: str = Field(min_length=1, max_length=100)
    action: Literal["accept", "exclude", "restore"]
    line_result_id: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=1, max_length=500)


class AnalysisCurveAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["set_fit", "set_coordinate", "set_active", "adjust", "restore", "restore_all", "adapt_control"]
    control_task_id: int | None = Field(default=None, ge=1)
    control_sample_group_position: int | None = Field(default=None, ge=0)
    control_value: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    point_index: int | None = Field(default=None, ge=0, le=49)
    fit_mode: Literal["linear", "quadratic", "cubic", "spline"] | None = None
    coordinate_type: Literal["normal", "logarithmic"] | None = None
    active: bool | None = None
    adjusted_intensity: float | None = None
    restore_activation: bool = True
    reason: str = Field(min_length=1, max_length=500)


class AnalysisCurveFit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fit_mode: Literal["linear", "quadratic", "cubic", "spline"] | None = None
    coordinate_type: Literal["normal", "logarithmic"] | None = None
    reason: str = Field(default="重新计算标准曲线", min_length=1, max_length=500)


class AnalysisCurvePublish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    curve_snapshot_id: int = Field(ge=1)
    reason: str = Field(default="复核后发布曲线快照", min_length=1, max_length=500)


class AnalysisMergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="保存当前批次合并结果", min_length=1, max_length=500)


class AnalysisSpectrumPrintRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ccd: int = Field(ge=0, le=255)
    band_position: int | None = Field(default=None, ge=0, le=65535)
    line_id: str | None = Field(default=None, max_length=100)
    exposure_start: int | None = Field(default=None, ge=1)
    exposure_end: int | None = Field(default=None, ge=1)
    x_min: float = Field(allow_inf_nan=False)
    x_max: float = Field(allow_inf_nan=False)
    y_min: float = Field(allow_inf_nan=False)
    y_max: float = Field(allow_inf_nan=False)
