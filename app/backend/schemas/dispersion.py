"""Dispersion models, moved without validation changes."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


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
