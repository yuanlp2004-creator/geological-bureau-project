"""Auth request and response models, moved without rule changes."""
from __future__ import annotations


from pydantic import BaseModel, Field


class BootstrapRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(BootstrapRequest):
    pass


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=200)
    role_ids: list[int] = Field(default_factory=list)


class UserUpdate(BaseModel):
    enabled: bool | None = None
    role_ids: list[int] | None = None


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    permission_keys: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    description: str | None = None
    permission_keys: list[str] | None = None
