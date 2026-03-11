import hashlib
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_admin
from app.models.api_key import APIKey
from app.models.route import Route
from app.schemas.api_key import APIKeyCreate, APIKeyCreatedResponse, APIKeyResponse
from app.schemas.route import RouteCreate, RouteResponse, RouteUpdate

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


# --- Routes ---

@router.get("/routes", response_model=list[RouteResponse])
async def list_routes(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Route).order_by(Route.created_at))
    return result.scalars().all()


@router.post("/routes", response_model=RouteResponse, status_code=status.HTTP_201_CREATED)
async def create_route(body: RouteCreate, db: AsyncSession = Depends(get_db)):
    route = Route(**body.model_dump())
    db.add(route)
    await db.commit()
    await db.refresh(route)
    return route


@router.get("/routes/{route_id}", response_model=RouteResponse)
async def get_route(route_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    route = await db.get(Route, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return route


@router.patch("/routes/{route_id}", response_model=RouteResponse)
async def update_route(
    route_id: uuid.UUID, body: RouteUpdate, db: AsyncSession = Depends(get_db)
):
    route = await db.get(Route, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(route, field, value)
    await db.commit()
    await db.refresh(route)
    return route


@router.delete("/routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route(route_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    route = await db.get(Route, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    await db.delete(route)
    await db.commit()


# --- API Keys ---

@router.get("/api-keys", response_model=list[APIKeyResponse])
async def list_api_keys(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(APIKey).order_by(APIKey.created_at))
    return result.scalars().all()


@router.post("/api-keys", response_model=APIKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(body: APIKeyCreate, db: AsyncSession = Depends(get_db)):
    raw_key = "gw_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]

    api_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=body.name,
        rate_limit_per_minute=body.rate_limit_per_minute,
        expires_at=body.expires_at,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return APIKeyCreatedResponse(
        id=api_key.id,
        key_prefix=api_key.key_prefix,
        name=api_key.name,
        is_active=api_key.is_active,
        rate_limit_per_minute=api_key.rate_limit_per_minute,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
        raw_key=raw_key,
    )


@router.get("/api-keys/{key_id}", response_model=APIKeyResponse)
async def get_api_key_admin(key_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    api_key = await db.get(APIKey, key_id)
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    return api_key


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(key_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    api_key = await db.get(APIKey, key_id)
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    await db.delete(api_key)
    await db.commit()
