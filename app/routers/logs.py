import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_admin
from app.models.request_log import RequestLog
from app.schemas.request_log import RequestLogResponse

router = APIRouter(prefix="/logs", dependencies=[Depends(require_admin)])


@router.get("", response_model=list[RequestLogResponse])
async def list_logs(
    api_key_id: uuid.UUID | None = Query(None),
    route_id: uuid.UUID | None = Query(None),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    q = select(RequestLog).order_by(RequestLog.created_at.desc())
    if api_key_id:
        q = q.where(RequestLog.api_key_id == api_key_id)
    if route_id:
        q = q.where(RequestLog.route_id == route_id)
    if since:
        q = q.where(RequestLog.created_at >= since)
    if until:
        q = q.where(RequestLog.created_at <= until)
    q = q.limit(limit).offset(offset)
    result = await db.execute(q)
    return result.scalars().all()
