"""Maintenance models, moved without validation changes."""
from __future__ import annotations
from pydantic import BaseModel, Field


class BackupCreate(BaseModel):
    output_directory: str = Field(min_length=1, max_length=500)
    filename: str | None = Field(default=None, max_length=180)
    retention_days: int = Field(default=30, ge=1, le=3650)


class MaintenanceActionRequest(BaseModel):
    mode: str = Field(default="PASSIVE", max_length=20)
    retention_days: int = Field(default=30, ge=1, le=3650)


class HelpTopicResponse(BaseModel):
    slug: str
    title: str
    section: str
    keywords: list[str]
    body: str
    related_routes: list[str]
    updated_at: str
