"""Operator-facing conditions from the legacy EDT/WDT creation dialog."""
from pydantic import BaseModel, ConfigDict, Field, field_validator


class PreliminaryCaptureCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=120)
    pre_excitation_seconds: float = Field(default=1, ge=1, le=10)
    sampling_period_seconds: float = Field(default=1, ge=1, le=2)
    frame_count: int = Field(default=20, ge=1, le=255)
    dark_frame_count: int = Field(default=8, ge=0, le=20)
    save_conditions: bool = False

    @field_validator('name')
    @classmethod
    def valid_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(char in '\\/:*?<>|"' or ord(char) < 32 for char in value):
            raise ValueError('曲线名不能为空或包含文件名非法字符')
        return value
