import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator


class RouteCreate(BaseModel):
    name: str
    path_prefix: str
    upstream_url: str
    strip_prefix: bool = False
    is_active: bool = True
    requires_auth: bool = True

    @field_validator("path_prefix")
    @classmethod
    def path_prefix_must_start_with_slash(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("path_prefix must start with /")
        return v


class RouteUpdate(BaseModel):
    name: str | None = None
    path_prefix: str | None = None
    upstream_url: str | None = None
    strip_prefix: bool | None = None
    is_active: bool | None = None
    requires_auth: bool | None = None

    @field_validator("path_prefix")
    @classmethod
    def path_prefix_must_start_with_slash(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("/"):
            raise ValueError("path_prefix must start with /")
        return v


class RouteResponse(BaseModel):
    id: uuid.UUID
    name: str
    path_prefix: str
    upstream_url: str
    strip_prefix: bool
    is_active: bool
    requires_auth: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
