import uuid
from datetime import datetime

from pydantic import BaseModel


class APIKeyCreate(BaseModel):
    name: str
    rate_limit_per_minute: int = 60
    expires_at: datetime | None = None


class APIKeyResponse(BaseModel):
    id: uuid.UUID
    key_prefix: str
    name: str
    is_active: bool
    rate_limit_per_minute: int
    created_at: datetime
    expires_at: datetime | None

    model_config = {"from_attributes": True}


class APIKeyCreatedResponse(APIKeyResponse):
    raw_key: str
