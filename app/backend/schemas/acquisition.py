"""Acquisition models, moved without validation changes."""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class AcquisitionMonitoringOptions(BaseModel):
    anomaly_policy: Literal["warn", "stop", "manual"] = "warn"
    retry_limit: int = Field(default=0, ge=0, le=5, strict=True)
    thresholds: dict[str, float] | None = None
    search_radius_points: int | None = Field(default=None, ge=1, le=1024, strict=True)


class SampleSessionCreate(AcquisitionMonitoringOptions):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=120)

    @field_validator('name')
    @classmethod
    def valid_number(cls, value: str) -> str:
        value = value.strip()
        if not value or any(char in '\\/:*?<>|"' or ord(char) < 32 for char in value):
            raise ValueError('摄谱编号不能为空或包含文件名非法字符')
        return value


class AcquisitionTaskCreate(AcquisitionMonitoringOptions):
    # 旧客户端字段保留兼容；样品的已有方法条件始终优先，不再提供切换语义。
    use_method_conditions: bool = True
    use_method_intervals: bool = False
    management_sample: bool = False
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
    name_length: Literal[12, 20] | None = None
    sample_kind: Literal["blank", "normal", "standard", "test", "preheat"] = "test"
    naming_mode: Literal["pre_recorded", "temporary", "post"] = "temporary"
    storage_mode: Literal["averaged", "full_interval"] = "averaged"
    repeat_count: int | None = Field(default=None, ge=1, le=10)
    burn_frame_count: int = Field(default=3, ge=1, le=255)
    dark_frame_count: int = Field(default=1, ge=0, le=20)
    countdown_seconds: float = Field(default=0, ge=0, le=600)
    pre_excitation_seconds: float | None = Field(default=None, ge=0, le=600)
    sampling_period_seconds: float = Field(default=1, ge=0.01, le=60, multiple_of=0.01)
    burn_cycle_seconds: float = Field(default=1, gt=0, le=60)
    dark_cycle_seconds: float = Field(default=1, gt=0, le=60)
    excitation_conditions: dict[str, Any] = Field(default_factory=dict)
    evaporation_conditions: dict[str, Any] = Field(default_factory=dict)
    simulator_sample: str = Field(default="280-288.acq", min_length=1, max_length=100)
    seed: int = Field(default=0, ge=0, le=2_147_483_647)
    fault_frame: int | None = Field(default=None, ge=0, le=10_000)


class AcquisitionIntervention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["accept", "retry", "stop"]
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('reason', mode='before')
    @classmethod
    def trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class AcquisitionMonitoringState(BaseModel):
    model_config = ConfigDict(extra='allow')

    status: Literal['pending', 'unmonitored', 'normal', 'alert', 'retrying', 'manual', 'accepted',
                    'safety_stopped', 'stop_unconfirmed']
    attempt: int
    retry_count: int
    awaiting_intervention: bool
    can_accept: bool
    accept_blocked_reason: str | None
    last_anomalies: list[str]
    last_summary: str | None


class AcquisitionMonitoringDecision(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: int
    repeat_index: int
    turn_index: int
    attempt: int
    frame_index: int
    anomaly_kinds: list[str]
    decision: Literal['accept', 'warn', 'correct', 'retry', 'manual', 'stop']
    correction_offset: float | None
    reason: str


class AcquisitionMonitoringSummary(AcquisitionMonitoringOptions):
    model_config = ConfigDict(extra='allow')

    monitored: bool
    state: AcquisitionMonitoringState
    decisions: list[AcquisitionMonitoringDecision]


class AcquisitionInterventionResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: int
    status: str
    monitoring: AcquisitionMonitoringSummary


class AcquisitionIntervalMark(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repeat_index: int = Field(default=0, ge=0, le=10)
    label: str = Field(min_length=1, max_length=50)
    start_frame_index: int = Field(ge=0, le=255)
    end_frame_index: int = Field(ge=0, le=255)


class AcquisitionRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post_name: str = Field(min_length=1, max_length=100)
    name_length: Literal[12, 20] | None = None


class AcquisitionDiscard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="激发能量不足", min_length=1, max_length=200)
