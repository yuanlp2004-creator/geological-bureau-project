"""Acquisition models, moved without validation changes."""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


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
    sampling_period_seconds: float = Field(default=1, ge=0.01, le=60, multiple_of=0.01)
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
