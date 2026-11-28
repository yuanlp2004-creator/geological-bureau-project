"""Input for converting a historical turn result into an analysis sample."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class HardwareAnalysisSample(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sample_name: str = Field(min_length=1, max_length=20)
    sample_kind: Literal['test', 'standard'] = 'test'
    name_length: Literal[12, 20] = 12
