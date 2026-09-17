"""Result Migration models, moved without validation changes."""
from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field


class ResultMigrationStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2048)


class ResultMigrationCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=64)
