"""Analysis models, moved without validation changes."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class AnalysisRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="S17 定量与曲线分析", min_length=1, max_length=120)
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


class AnalysisQcDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acquisition_task_id: int = Field(ge=1)
    line_id: str = Field(min_length=1, max_length=100)
    action: Literal["accept", "exclude", "restore"]
    line_result_id: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=1, max_length=500)


class AnalysisCurveAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["set_fit", "set_coordinate", "set_active", "adjust", "restore", "restore_all"]
    point_index: int | None = Field(default=None, ge=0, le=49)
    fit_mode: Literal["linear", "quadratic", "cubic", "spline"] | None = None
    coordinate_type: Literal["normal", "logarithmic"] | None = None
    active: bool | None = None
    adjusted_intensity: float | None = None
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
