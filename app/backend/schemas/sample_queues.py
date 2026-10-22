"""Sample Queues models, moved without validation changes."""
from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


class SampleQueueItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int | None = Field(default=None, gt=0)
    pre_name: str = Field(default="", max_length=100)
    repeats: int = Field(default=0, ge=0, le=10)
    post_name: str | None = Field(default=None, max_length=100)
    spectrum_hash: str | None = Field(default=None, max_length=128)


class SampleQueueCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="未命名队列", min_length=1, max_length=120)
    items: list[SampleQueueItemInput] = Field(default_factory=list, max_length=1000)
    name_length: Literal[12, 20] | None = None


class SampleQueueUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[SampleQueueItemInput] = Field(default_factory=list, max_length=1000)
    name_length: Literal[12, 20] | None = None


class SampleQueueRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    post_name: str = Field(min_length=1, max_length=100)


class SampleQueueImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(default="queue.sam", min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1, max_length=5_000_000)
    last_modified_ms: int | None = Field(default=None, ge=0)
    content_base64: str | None = Field(default=None, max_length=7_000_000)
    queue_name: str | None = Field(default=None, max_length=120)
    encoding: Literal['gb18030','utf-8-sig'] | None = None
