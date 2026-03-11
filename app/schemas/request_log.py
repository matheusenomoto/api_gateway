import uuid
from datetime import datetime

from pydantic import BaseModel


class RequestLogResponse(BaseModel):
    id: uuid.UUID
    api_key_id: uuid.UUID | None
    route_id: uuid.UUID | None
    method: str
    path: str
    query_string: str
    status_code: int
    response_time_ms: int
    client_ip: str
    created_at: datetime

    model_config = {"from_attributes": True}
