import time
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_api_key
from app.models.api_key import APIKey
from app.models.request_log import RequestLog
from app.models.route import Route

router = APIRouter()

HOP_BY_HOP = frozenset(
    [
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
    ]
)

PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


def _get_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


async def _find_route(path: str, db: AsyncSession) -> Route | None:
    from sqlalchemy import select

    result = await db.execute(select(Route).where(Route.is_active.is_(True)))
    routes = result.scalars().all()

    best: Route | None = None
    for route in routes:
        prefix = route.path_prefix
        if path == prefix or path.startswith(prefix.rstrip("/") + "/"):
            if best is None or len(prefix) > len(best.path_prefix):
                best = route
    return best


async def _check_rate_limit(api_key: APIKey, db: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    window_start = now.replace(second=0, microsecond=0)

    result = await db.execute(
        text(
            """
            INSERT INTO rate_limit_windows (id, api_key_id, window_start, request_count)
            VALUES (:id, :api_key_id, :window_start, 1)
            ON CONFLICT ON CONSTRAINT uq_rate_limit_key_window
            DO UPDATE SET request_count = rate_limit_windows.request_count + 1
            RETURNING request_count
            """
        ),
        {"id": str(uuid.uuid4()), "api_key_id": str(api_key.id), "window_start": window_start},
    )
    count = result.scalar_one()
    await db.commit()

    if count > api_key.rate_limit_per_minute:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": "60"},
        )


async def _cleanup_old_windows(db: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    cutoff = now.replace(second=0, microsecond=0)
    await db.execute(
        text("DELETE FROM rate_limit_windows WHERE window_start < :cutoff - interval '2 minutes'"),
        {"cutoff": cutoff},
    )
    await db.commit()


@router.api_route("/{full_path:path}", methods=PROXY_METHODS)
async def proxy(
    full_path: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey | None = Depends(get_api_key),
):
    path = "/" + full_path
    route = await _find_route(path, db)

    if route is None:
        raise HTTPException(status_code=404, detail="No matching route")

    if route.requires_auth and api_key is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    if api_key is not None:
        await _check_rate_limit(api_key, db)

    # Build upstream path
    if route.strip_prefix:
        upstream_path = path[len(route.path_prefix):] or "/"
    else:
        upstream_path = path

    upstream_url = route.upstream_url.rstrip("/") + upstream_path
    if request.url.query:
        upstream_url += "?" + request.url.query

    # Filter headers
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP
    }
    client_ip = request.client.host if request.client else "unknown"
    headers["X-Forwarded-For"] = client_ip
    headers["X-Forwarded-Proto"] = request.url.scheme
    headers["X-Forwarded-Host"] = request.headers.get("host", "")

    body = await request.body()
    client: httpx.AsyncClient = _get_client(request)

    start = time.monotonic()
    status_code = 502
    try:
        upstream_response = await client.request(
            method=request.method,
            url=upstream_url,
            headers=headers,
            content=body,
            follow_redirects=False,
        )
        status_code = upstream_response.status_code
    except httpx.TimeoutException:
        status_code = 504
        raise HTTPException(status_code=504, detail="Upstream timeout")
    except httpx.RequestError:
        status_code = 502
        raise HTTPException(status_code=502, detail="Upstream error")
    finally:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        log = RequestLog(
            api_key_id=api_key.id if api_key else None,
            route_id=route.id,
            method=request.method,
            path=path,
            query_string=request.url.query,
            status_code=status_code,
            response_time_ms=elapsed_ms,
            client_ip=client_ip,
        )
        db.add(log)
        await db.commit()

    response_headers = {
        k: v
        for k, v in upstream_response.headers.items()
        if k.lower() not in HOP_BY_HOP
    }

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=response_headers,
        media_type=upstream_response.headers.get("content-type"),
    )
