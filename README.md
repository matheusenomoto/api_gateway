# API Gateway

A lightweight API Gateway built with **FastAPI** and **PostgreSQL**. Handles dynamic routing, API key authentication, per-key rate limiting, and full request logging — all configured at runtime via a REST admin API.

## Features

- **Dynamic routing** — longest prefix match across database-backed routes; no restart needed to add or remove routes
- **API key authentication** — keys stored as SHA-256 hashes; never persisted in plain text
- **Rate limiting** — fixed-window per key via atomic PostgreSQL upsert (`ON CONFLICT DO UPDATE`); returns `HTTP 429` with `Retry-After: 60`
- **Reverse proxy** — forwards any HTTP method to upstream, strips hop-by-hop headers, injects `X-Forwarded-*`
- **Request logging** — every proxied request is logged (method, path, status, latency, client IP) in the `request_logs` table, queryable via `/logs`
- **Admin API** — full CRUD for routes and API keys, protected by a shared admin key
- **Schema migrations** — managed by Alembic; single revision creates all four tables
- **Docker Compose** — one command to start the app and a PostgreSQL 16 instance

## Architecture

```
Client
  │
  ▼
proxy.router  /{full_path:path}   ← catch-all, registered last
  │
  ├─ _find_route()     longest prefix match against routes table
  ├─ requires_auth?    → 401 if key missing or invalid
  ├─ _check_rate_limit()  atomic upsert → 429 if exceeded
  ├─ strip hop-by-hop headers
  ├─ httpx.AsyncClient.request() → upstream
  └─ finally: INSERT INTO request_logs

admin.router  /admin/*            ← CRUD for routes and API keys (X-Admin-Key)
logs.router   /logs               ← paginated log query (X-Admin-Key)
```

## Data Model

| Table | Purpose |
|---|---|
| `routes` | Proxy route config: prefix, upstream URL, auth flag, strip-prefix flag |
| `api_keys` | Hashed API keys with per-key rate limit and optional expiry |
| `request_logs` | Immutable audit log of every proxied request |
| `rate_limit_windows` | Per-key per-minute counters; auto-cleaned after 2 minutes |

## Quick Start

### Prerequisites

- Docker and Docker Compose

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env — set a strong ADMIN_API_KEY
```

`.env.example`:
```
DATABASE_URL=postgresql+asyncpg://gateway:gateway@db:5432/gateway
ADMIN_API_KEY=change-me-to-a-long-random-secret
```

### 2. Start the stack

```bash
docker compose up -d
```

The app waits for PostgreSQL to pass its health check before starting.

### 3. Run database migrations

```bash
docker compose exec app alembic upgrade head
```

### 4. Create a route

```bash
curl -X POST http://localhost:8000/admin/routes \
  -H "X-Admin-Key: <your-admin-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "jsonplaceholder",
    "path_prefix": "/posts",
    "upstream_url": "https://jsonplaceholder.typicode.com",
    "strip_prefix": false,
    "is_active": true,
    "requires_auth": false
  }'
```

### 5. Test the proxy

```bash
curl http://localhost:8000/posts/1
```

## Admin API Reference

All `/admin/*` and `/logs` endpoints require the `X-Admin-Key` header.

### Routes

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/routes` | List all routes |
| `POST` | `/admin/routes` | Create a route |
| `GET` | `/admin/routes/{id}` | Get a route |
| `PATCH` | `/admin/routes/{id}` | Update a route |
| `DELETE` | `/admin/routes/{id}` | Delete a route |

**Route fields:**

| Field | Type | Description |
|---|---|---|
| `name` | string | Unique human-readable name |
| `path_prefix` | string | URL prefix to match (e.g. `/api/v1`) |
| `upstream_url` | string | Base URL of the upstream service |
| `strip_prefix` | bool | Remove the prefix before forwarding |
| `is_active` | bool | Enable/disable without deleting |
| `requires_auth` | bool | Enforce `X-API-Key` header |

### API Keys

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/api-keys` | List all keys |
| `POST` | `/admin/api-keys` | Create a key (returns raw value once) |
| `GET` | `/admin/api-keys/{id}` | Get key metadata |
| `DELETE` | `/admin/api-keys/{id}` | Revoke a key |

**Create key body:**

```json
{
  "name": "my-service",
  "rate_limit_per_minute": 60,
  "expires_at": null
}
```

The response includes `raw_key` — store it securely, it is never returned again.

### Logs

```
GET /logs
```

Query params: `api_key_id`, `route_id`, `since`, `until`, `limit` (max 1000), `offset`.

## Using API Key Authentication

For routes with `requires_auth: true`, pass the key in the request header:

```bash
curl http://localhost:8000/secure/endpoint \
  -H "X-API-Key: gw_<your-key>"
```

- Missing or invalid key → `HTTP 401`
- Expired key → `HTTP 401`
- Rate limit exceeded → `HTTP 429` with `Retry-After: 60`

## Routing: Longest Prefix Match

When a request arrives, the gateway selects the active route whose `path_prefix` is the longest match for the request path. This allows overlapping prefixes:

| Request path | Matches route | Forwarded to |
|---|---|---|
| `/api/v1/users` | `/api/v1` | `upstream-v1/api/v1/users` |
| `/api/health` | `/api` | `upstream/api/health` |
| `/other` | — | `HTTP 404` |

## Running Tests

The functional and performance test suite (`tests/test_functional_performance.py`) runs against a live gateway instance.

```bash
# Start the stack first
docker compose up -d
docker compose exec app alembic upgrade head

# Install dependencies
pip install requests

# Run tests (15 cases, 17 assertions)
python tests/test_functional_performance.py
```

Test coverage:

- Application availability
- Route and API key CRUD
- Reverse proxy (authenticated and unauthenticated)
- Auth enforcement (401 without key, 200 with valid key, 401 with invalid key)
- Rate limiting (HTTP 429 + Retry-After header)
- Request log retrieval
- Admin protection
- Longest prefix match
- Internal gateway latency (20 samples)
- Partial route update (PATCH)

## Project Structure

```
api_gateway/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 0001_initial_schema.py
├── app/
│   ├── main.py           # FastAPI instance and lifespan
│   ├── config.py         # Settings via pydantic-settings
│   ├── database.py       # Async engine and session
│   ├── dependencies.py   # Auth dependencies (require_admin, get_api_key)
│   ├── models/
│   │   ├── api_key.py
│   │   ├── rate_limit_window.py
│   │   ├── request_log.py
│   │   └── route.py
│   ├── schemas/
│   │   ├── api_key.py
│   │   ├── request_log.py
│   │   └── route.py
│   └── routers/
│       ├── admin.py      # Route and API key management
│       ├── logs.py       # Log query endpoint
│       └── proxy.py      # Reverse proxy with auth and rate limiting
└── tests/
    └── test_functional_performance.py
```

## Tech Stack

| Component | Technology | Version |
|---|---|---|
| Web framework | FastAPI | 0.115.6 |
| ASGI server | Uvicorn | 0.32.1 |
| ORM | SQLAlchemy (async) | 2.0.36 |
| DB driver | asyncpg | 0.30.0 |
| Migrations | Alembic | 1.14.0 |
| HTTP client | httpx | 0.28.1 |
| Validation | Pydantic | 2.10.3 |
| Database | PostgreSQL | 16 |
| Runtime | Python | 3.12 |
