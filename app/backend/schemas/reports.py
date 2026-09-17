"""Reports models, moved without validation changes."""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_run_ids: list[int] = Field(min_length=1, max_length=200)
    template_key: str = Field(default="analysis-standard", min_length=1, max_length=100)
    report_number: str | None = Field(default=None, max_length=100)
    arrangement: Literal["standard", "exchange"] = "standard"
    filters: dict[str, Any] = Field(default_factory=dict)


class ReportExport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["txt", "csv", "excel", "pdf", "print"] = "pdf"
    output_directory: str | None = None
    filename: str | None = None
    printer_name: str | None = Field(default=None, max_length=255)
    same_name_strategy: Literal["suffix", "error", "overwrite"] = "suffix"
