"""Devices models, moved without validation changes."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


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
