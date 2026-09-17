"""Postprocessing models, moved without validation changes."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class PostProcessingIntervalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ccd: int = Field(default=0, ge=0, le=255)
    start_frame: int = Field(default=1, ge=1, le=255)
    end_frame: int | None = Field(default=None, ge=1, le=255)
    phase: Literal["burn", "dark"] = "burn"


class PostProcessingConversionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_ids: list[str] = Field(min_length=1, max_length=200)
    start_frame: int = Field(default=1, ge=1, le=255)
    end_frame: int | None = Field(default=None, ge=1, le=255)
    target_ccd_layout_id: int = Field(ge=1)
    target_ccd_indices: list[int] | None = Field(default=None, min_length=1, max_length=256)
    method_version_id: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, max_length=120)


class PostProcessingRecalculateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_record_ids: list[str] = Field(min_length=1, max_length=200)
    method_version_id: int = Field(ge=1)
    calculation_profile: Literal["legacy_2_0_2", "modern_v1"] = "legacy_2_0_2"
    curve_snapshot_ids: list[int] = Field(default_factory=list, max_length=200)
    expected_measure_time: str | None = Field(default=None, max_length=80)


class PostProcessingExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_ids: list[str] = Field(min_length=1, max_length=200)
    kind: Literal["raw_intensity", "processed_intensity", "result_matrix"]
    format: Literal["txt", "csv", "excel"]
    output_directory: str = Field(min_length=1, max_length=2048)
    filename: str = Field(default="s18-export", min_length=1, max_length=255)
    same_name_strategy: Literal["suffix", "error", "overwrite"] = "suffix"
