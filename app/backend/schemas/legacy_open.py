"""One selected legacy file, opened from its consuming workspace."""
from typing import Literal
from pydantic import BaseModel, Field


class LegacyOpenRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2048)
    purpose: Literal['methods', 'spectra', 'analysis', 'dispersion', 'evaporation',
                     'recalculate', 'reports', 'intensity', 'edt-conversion',
                     'batch-methods', 'batch-spectra', 'batch-results']

