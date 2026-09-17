"""Spectrum Viewer models, moved without validation changes."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


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
