"""Mercury Calibration models, moved without validation changes."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


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
