"""Legacy Migration models, moved without validation changes."""
from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field


class LegacyMigrationStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mtd_path: str = Field(min_length=1, max_length=2048)
    cfg_path: str = Field(min_length=1, max_length=2048)
    opt_path: str = Field(min_length=1, max_length=2048)


class LegacyMigrationCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=64)
