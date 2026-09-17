"""Sample Queues models, moved without validation changes."""
from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field


class SampleQueueItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pre_name: str = Field(default="", max_length=100)
    repeats: int = Field(default=0, ge=0, le=10)
    post_name: str | None = Field(default=None, max_length=100)
    spectrum_hash: str | None = Field(default=None, max_length=128)


class SampleQueueCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="未命名队列", min_length=1, max_length=120)
    items: list[SampleQueueItemInput] = Field(default_factory=list, max_length=1000)


class SampleQueueUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[SampleQueueItemInput] = Field(default_factory=list, max_length=1000)


class SampleQueueRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    post_name: str = Field(min_length=1, max_length=100)


class SampleQueueImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(default="queue.sam", min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=5_000_000)
    queue_name: str | None = Field(default=None, max_length=120)
