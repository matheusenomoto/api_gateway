from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.database import engine
from app.models import APIKey, RateLimitWindow, RequestLog, Route  # noqa: F401 — ensure models registered
from app.routers import admin, logs, proxy


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    app.state.http_client = httpx.AsyncClient(timeout=30.0)
    yield
    # Shutdown
    await app.state.http_client.aclose()
    await engine.dispose()


app = FastAPI(title="API Gateway", lifespan=lifespan)

# Registration order matters — proxy catch-all must be last
app.include_router(admin.router)
app.include_router(logs.router)
app.include_router(proxy.router)
