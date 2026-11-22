"""Postprocessing models, moved without validation changes."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class FullTimeExportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    source_id: str = Field(pattern=r'^(?:raw:[0-9a-f]{64}|task:[1-9][0-9]*)$')
    start_frame: int = Field(ge=1)
    end_frame: int = Field(ge=1)
    method_version_id: int | None = Field(default=None, ge=1)


class PostProcessingIntervalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ccd: int = Field(default=0, ge=0, le=255)
    start_frame: int = Field(default=1, ge=1, le=255)
    end_frame: int | None = Field(default=None, ge=1, le=255)
    phase: Literal["burn", "dark"] = "burn"


class PostProcessingConversionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_ids: list[str] = Field(min_length=1, max_length=200)
    storage_mode: Literal['averaged', 'full_interval'] = 'full_interval'
    start_frame: int = Field(default=1, ge=1, le=255)
    end_frame: int | None = Field(default=None, ge=1, le=255)
    target_ccd_layout_id: int = Field(ge=1)
    target_ccd_indices: list[int] | None = Field(default=None, min_length=1, max_length=256)
    method_version_id: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, max_length=120)


class PreparedImportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    request_id: str = Field(min_length=16, max_length=80)
    source_sha256: str = Field(min_length=1, max_length=128)
    record_ids: list[str] = Field(min_length=1, max_length=5000)
    target_name: str = Field(min_length=1, max_length=120)
    storage_mode: Literal['averaged', 'full_interval'] = 'averaged'
    start_frame: int = Field(ge=1, le=255)
    end_frame: int = Field(ge=1, le=255)
    use_method_id: bool = True
    same_name_strategy: Literal['error', 'replace', 'append'] = 'error'
    expected_target_revision: int | None = Field(default=None, ge=1)
    expected_method_version_id: int = Field(ge=1)


class PreparedDispersionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    source_sha256: str = Field(min_length=1, max_length=128)
    expected_method_version_id: int = Field(ge=1)


class CurveDraftPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point_index: int = Field(ge=0)
    active: bool
    adjusted_intensity: float | None = Field(allow_inf_nan=False)


class RecalculationCurveDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fit_mode: Literal["linear", "quadratic", "cubic", "spline"]
    coordinate_type: Literal["normal", "logarithmic"]
    points: list[CurveDraftPoint] = Field(max_length=200)


class PostProcessingRecalculateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_record_ids: list[str] = Field(min_length=1, max_length=200)
    allow_older_method: bool = False
    method_version_id: int = Field(ge=1)
    calculation_profile: Literal["legacy_2_0_2", "modern_v1"] = "legacy_2_0_2"
    curve_snapshot_ids: list[int] = Field(default_factory=list, max_length=200)
    curve_drafts: dict[int, RecalculationCurveDraft] = Field(default_factory=dict, max_length=200)
    expected_measure_time: str | None = Field(default=None, max_length=80)


class PostProcessingExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_ids: list[str] = Field(min_length=1, max_length=200)
    kind: Literal["raw_intensity", "processed_intensity", "result_matrix"]
    format: Literal["txt", "csv", "excel"]
    output_directory: str = Field(min_length=1, max_length=2048)
    filename: str = Field(default="s18-export", min_length=1, max_length=255)
    same_name_strategy: Literal["suffix", "error", "overwrite"] = "suffix"
