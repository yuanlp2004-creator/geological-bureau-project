"""Hardware Acquisition models, moved without validation changes."""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class HardwareTurnInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    angle_deg: float = Field(ge=-360, le=360)
    wavelength_nm: float = Field(ge=160, le=800)
    priority: int = Field(default=0, ge=0, le=100)
    key_band: bool = False
    expected_peak_position: float = Field(default=1024, ge=0, le=4096)


class HardwareTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="S14 真实设备与自动转角", min_length=1, max_length=120)
    device_profile_id: int = Field(default=1, ge=1)
    ccd_layout_id: str | int = "default"
    method_id: int | None = Field(default=None, ge=1)
    method_version: int | None = Field(default=None, ge=1)
    sample_name: str = Field(default="", max_length=100)
    strategy: Literal["short_to_long", "key_first"] = "short_to_long"
    anomaly_policy: Literal["retry_then_stop", "manual"] = "retry_then_stop"
    retry_limit: int = Field(default=1, ge=0, le=5)
    pre_excitation_seconds: float = Field(default=1, ge=0, le=600)
    sampling_period_seconds: float = Field(default=1, gt=0, le=60)
    ccd_indices: list[int] | None = Field(default=None, min_length=1, max_length=256)
    turns: list[HardwareTurnInput] = Field(min_length=1, max_length=300)
    thresholds: dict[str, float] = Field(default_factory=dict)
    simulator_sample: str = Field(default="280-288.acq", min_length=1, max_length=100)
    seed: int = Field(default=0, ge=0, le=2_147_483_647)
    simulator_anomalies: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class HardwareIntervention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["accept", "retry", "stop"]
    note: str = Field(default="", max_length=300)
