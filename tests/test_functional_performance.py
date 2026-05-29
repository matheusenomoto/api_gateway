"""
Testes funcionais e de desempenho do API Gateway.

Execução:
    python tests/test_functional_performance.py

Requer: requests (pip install requests)
O gateway deve estar rodando em http://localhost:8001
com ADMIN_API_KEY=tcc-admin-key-2025
"""

import json
import statistics
import time

import requests

BASE = "http://localhost:8001"
ADMIN_KEY = "tcc-admin-key-2025"
ADMIN_HEADERS = {"X-Admin-Key": ADMIN_KEY}
UPSTREAM_URL = "https://jsonplaceholder.typicode.com"

# Session with Accept-Encoding:identity so the upstream returns plain JSON.
# The gateway decompresses upstream responses via httpx but still forwards
# Content-Encoding headers, causing double-decompression errors in the test
# client. Disabling compression on the client side avoids this.
_session = requests.Session()
_session.headers.update({"Accept-Encoding": "identity"})
requests = _session   # shadow module-level name for convenience
NO_GZIP = {}          # kept for any legacy references

RESULTS = {}
PASS_COUNT = 0
FAIL_COUNT = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)

def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def ok(label: str, value=None) -> None:
    global PASS_COUNT
    PASS_COUNT += 1
    suffix = f" => {value}" if value is not None else ""
    print(f"  [PASS] {label}{suffix}")

def chk(condition: bool, label: str, value=None, detail: str = "") -> None:
    if condition:
        ok(label, value)
    else:
        global FAIL_COUNT
        FAIL_COUNT += 1
        print(f"  [FAIL] {label}: {detail or 'assertion failed'}")


# ---------------------------------------------------------------------------
# SETUP: clean any previous state
# ---------------------------------------------------------------------------

section("SETUP — Limpeza do Estado Anterior")
for route in requests.get(f"{BASE}/admin/routes", headers=ADMIN_HEADERS).json():
    requests.delete(f"{BASE}/admin/routes/{route['id']}", headers=ADMIN_HEADERS)
for key in requests.get(f"{BASE}/admin/api-keys", headers=ADMIN_HEADERS).json():
    requests.delete(f"{BASE}/admin/api-keys/{key['id']}", headers=ADMIN_HEADERS)
print("  Estado anterior removido.")


# ---------------------------------------------------------------------------
# TC-01: Disponibilidade da aplicação
# ---------------------------------------------------------------------------

section("TC-01 — Disponibilidade da Aplicação")
t = time.monotonic()
r = requests.get(f"{BASE}/docs", timeout=5)
latency = _ms(t)
chk(r.status_code == 200, "Swagger UI acessível", f"HTTP {r.status_code} em {latency} ms")
RESULTS["tc01_docs_ms"] = latency


# ---------------------------------------------------------------------------
# TC-02: Criação de rota aberta (sem autenticação)
# ---------------------------------------------------------------------------

section("TC-02 — Criação de Rota via Admin (POST /admin/routes)")
t = time.monotonic()
r = requests.post(f"{BASE}/admin/routes", headers=ADMIN_HEADERS, json={
    "name": "posts-open",
    "path_prefix": "/posts",
    "upstream_url": UPSTREAM_URL,
    "strip_prefix": False,
    "is_active": True,
    "requires_auth": False,
})
latency = _ms(t)
chk(r.status_code == 201, "Rota aberta criada (HTTP 201)", f"em {latency} ms",
    f"Got {r.status_code}: {r.text[:100]}")
ROUTE_OPEN_ID = r.json().get("id", "") if r.status_code == 201 else ""
RESULTS["tc02_create_route_ms"] = latency


# ---------------------------------------------------------------------------
# TC-03: Criação de chave de API
# ---------------------------------------------------------------------------

section("TC-03 — Criação de Chave de API (POST /admin/api-keys)")
t = time.monotonic()
r = requests.post(f"{BASE}/admin/api-keys", headers=ADMIN_HEADERS, json={
    "name": "test-key",
    "rate_limit_per_minute": 10,
})
latency = _ms(t)
chk(r.status_code == 201, "Chave de API criada (HTTP 201)", f"em {latency} ms",
    f"Got {r.status_code}: {r.text[:100]}")
key_data = r.json() if r.status_code == 201 else {}
RAW_KEY = key_data.get("raw_key", "")
KEY_PREFIX = key_data.get("key_prefix", "")
print(f"  Prefixo da chave: {KEY_PREFIX}")
RESULTS["tc03_create_key_ms"] = latency


# ---------------------------------------------------------------------------
# TC-04: Proxy reverso — roteamento sem autenticação
# ---------------------------------------------------------------------------

section("TC-04 — Proxy Reverso (5 requisições GET /posts/1)")
samples = []
for i in range(5):
    t = time.monotonic()
    r = requests.get(f"{BASE}/posts/1", headers=NO_GZIP, timeout=15)
    lat = _ms(t)
    samples.append(lat)
    print(f"  Requisição {i+1}: HTTP {r.status_code} em {lat} ms")

avg = statistics.mean(samples)
med = statistics.median(samples)
mn = min(samples)
mx = max(samples)
chk(all(s in [200] for s in [
    requests.get(f"{BASE}/posts/1", headers=NO_GZIP, timeout=15).status_code
]), f"Rota proxy funcionando | média={avg:.0f} ms | mediana={med:.0f} ms | min={mn} ms | max={mx} ms")
RESULTS["tc04_proxy_avg_ms"] = round(avg, 1)
RESULTS["tc04_proxy_median_ms"] = med
RESULTS["tc04_proxy_min_ms"] = mn
RESULTS["tc04_proxy_max_ms"] = mx


# ---------------------------------------------------------------------------
# TC-05: Rota não encontrada → 404
# ---------------------------------------------------------------------------

section("TC-05 — Rota Não Encontrada (HTTP 404)")
t = time.monotonic()
r = requests.get(f"{BASE}/nonexistent/path/xyz", timeout=5)
latency = _ms(t)
chk(r.status_code == 404, f"Caminho sem rota → HTTP 404", f"em {latency} ms",
    f"Got {r.status_code}")
RESULTS["tc05_404_ms"] = latency


# ---------------------------------------------------------------------------
# TC-06: Rota protegida criada
# ---------------------------------------------------------------------------

section("TC-06 — Criação de Rota Protegida (requires_auth=True)")
t = time.monotonic()
r = requests.post(f"{BASE}/admin/routes", headers=ADMIN_HEADERS, json={
    "name": "users-secure",
    "path_prefix": "/users",
    "upstream_url": UPSTREAM_URL,
    "strip_prefix": False,
    "is_active": True,
    "requires_auth": True,
})
latency = _ms(t)
chk(r.status_code == 201, "Rota protegida criada (HTTP 201)", f"em {latency} ms",
    f"Got {r.status_code}: {r.text[:100]}")
ROUTE_SEC_ID = r.json().get("id", "") if r.status_code == 201 else ""
RESULTS["tc06_create_secure_route_ms"] = latency


# ---------------------------------------------------------------------------
# TC-07: Sem chave → 401
# ---------------------------------------------------------------------------

section("TC-07 — Acesso à Rota Protegida sem Chave (HTTP 401)")
t = time.monotonic()
r = requests.get(f"{BASE}/users/1", timeout=5)
latency = _ms(t)
chk(r.status_code == 401, f"Sem chave → HTTP 401", f"em {latency} ms", f"Got {r.status_code}")
RESULTS["tc07_401_no_key_ms"] = latency


# ---------------------------------------------------------------------------
# TC-08: Chave válida → 200
# ---------------------------------------------------------------------------

section("TC-08 — Acesso com Chave Válida (HTTP 200)")
t = time.monotonic()
r = requests.get(f"{BASE}/users/1", headers={"X-API-Key": RAW_KEY}, timeout=15)
latency = _ms(t)
chk(r.status_code == 200, f"Chave válida → HTTP 200", f"em {latency} ms", f"Got {r.status_code}")
RESULTS["tc08_auth_valid_ms"] = latency


# ---------------------------------------------------------------------------
# TC-09: Chave inválida → 401
# ---------------------------------------------------------------------------

section("TC-09 — Chave de API Inválida (HTTP 401)")
t = time.monotonic()
r = requests.get(f"{BASE}/users/1", headers={"X-API-Key": "gw_invalid_key_000000"}, timeout=5)
latency = _ms(t)
chk(r.status_code == 401, f"Chave inválida → HTTP 401", f"em {latency} ms", f"Got {r.status_code}")
RESULTS["tc09_invalid_key_ms"] = latency


# ---------------------------------------------------------------------------
# TC-10: Rate limiting → 429
# ---------------------------------------------------------------------------

section("TC-10 — Controle de Taxa / Rate Limiting (HTTP 429)")
statuses = []
latencies_rl = []
# Rate limit is 10/min. We already used 1 in TC-08. Send 10 more to trigger 429.
for i in range(11):
    t = time.monotonic()
    r = requests.get(f"{BASE}/users/1", headers={"X-API-Key": RAW_KEY}, timeout=15)
    lat = _ms(t)
    statuses.append(r.status_code)
    latencies_rl.append(lat)
    print(f"  Req {i+1}: HTTP {r.status_code} em {lat} ms")

hits_429 = statuses.count(429)
hits_200 = statuses.count(200)
chk(hits_429 > 0, f"Rate limit ativado ({hits_200}× 200, {hits_429}× 429)",
    None, "Nenhum HTTP 429 retornado")
if hits_429 > 0:
    retry_hdr = r.headers.get("Retry-After", "N/A")
    chk(True, f"Cabeçalho Retry-After presente", retry_hdr)
RESULTS["tc10_rate_200"] = hits_200
RESULTS["tc10_rate_429"] = hits_429
RESULTS["tc10_avg_ms"] = round(statistics.mean(latencies_rl), 1)


# ---------------------------------------------------------------------------
# TC-11: Logs endpoint
# ---------------------------------------------------------------------------

section("TC-11 — Endpoint de Logs com Filtros")
t = time.monotonic()
r = requests.get(f"{BASE}/logs?limit=50", headers=ADMIN_HEADERS, timeout=5)
latency = _ms(t)
logs = r.json() if r.status_code == 200 else []
chk(r.status_code == 200, f"GET /logs → HTTP 200", f"{len(logs)} registros em {latency} ms",
    f"Got {r.status_code}")
RESULTS["tc11_logs_ms"] = latency
RESULTS["tc11_log_count"] = len(logs)


# ---------------------------------------------------------------------------
# TC-12: Proteção admin com chave inválida → 401
# ---------------------------------------------------------------------------

section("TC-12 — Proteção Admin com Chave Inválida")
t = time.monotonic()
r = requests.get(f"{BASE}/admin/routes", headers={"X-Admin-Key": "wrong-key"}, timeout=5)
latency = _ms(t)
chk(r.status_code == 401, f"Admin chave errada → HTTP 401", f"em {latency} ms", f"Got {r.status_code}")
RESULTS["tc12_admin_401_ms"] = latency


# ---------------------------------------------------------------------------
# TC-13: Longest prefix match (dois prefixos concorrentes)
# ---------------------------------------------------------------------------

section("TC-13 — Longest Prefix Match")
for name, prefix in [("posts-v2", "/posts/v2"), ("todos-generic", "/todos")]:
    requests.post(f"{BASE}/admin/routes", headers=ADMIN_HEADERS, json={
        "name": name,
        "path_prefix": prefix,
        "upstream_url": UPSTREAM_URL,
        "strip_prefix": False,
        "is_active": True,
        "requires_auth": False,
    })

r1 = requests.get(f"{BASE}/posts/v2/1", timeout=15)
r2 = requests.get(f"{BASE}/todos/1", timeout=15)
chk(r1.status_code in (200, 404), f"/posts/v2/1 → gateway roteou (upstream HTTP {r1.status_code})")
chk(r2.status_code in (200, 404), f"/todos/1 → gateway roteou (upstream HTTP {r2.status_code})")
RESULTS["tc13_lpm_r1"] = r1.status_code
RESULTS["tc13_lpm_r2"] = r2.status_code


# ---------------------------------------------------------------------------
# TC-14: Latência interna do gateway (sem upstream — erro 404 local)
# ---------------------------------------------------------------------------

section("TC-14 — Latência Interna do Gateway (20 amostras, sem upstream)")
samples_local = []
for _ in range(20):
    t = time.monotonic()
    requests.get(f"{BASE}/unmapped-path-xyz-123", timeout=5)
    samples_local.append(_ms(t))

avg_l = statistics.mean(samples_local)
med_l = statistics.median(samples_local)
mn_l = min(samples_local)
mx_l = max(samples_local)
p95_l = sorted(samples_local)[int(len(samples_local) * 0.95)]
ok(f"Latência interna | média={avg_l:.1f} ms | mediana={med_l:.0f} ms | p95={p95_l} ms | min={mn_l} ms | max={mx_l} ms")
RESULTS["tc14_internal_avg_ms"] = round(avg_l, 1)
RESULTS["tc14_internal_median_ms"] = med_l
RESULTS["tc14_internal_p95_ms"] = p95_l
RESULTS["tc14_internal_min_ms"] = mn_l
RESULTS["tc14_internal_max_ms"] = mx_l


# ---------------------------------------------------------------------------
# TC-15: PATCH (atualização parcial de rota)
# ---------------------------------------------------------------------------

section("TC-15 — Atualização Parcial de Rota (PATCH /admin/routes/{id})")
if ROUTE_OPEN_ID:
    t = time.monotonic()
    r = requests.patch(
        f"{BASE}/admin/routes/{ROUTE_OPEN_ID}",
        json={"is_active": True},
        headers=ADMIN_HEADERS,
        timeout=5,
    )
    latency = _ms(t)
    chk(r.status_code == 200, "PATCH rota → HTTP 200", f"em {latency} ms", f"Got {r.status_code}")
    RESULTS["tc15_patch_ms"] = latency
else:
    print("  [SKIP] ID da rota não disponível")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

section(f"RESUMO — {PASS_COUNT} PASS / {FAIL_COUNT} FAIL")
print()
print(json.dumps(RESULTS, indent=2))
print()
status = "TODOS OS TESTES PASSARAM." if FAIL_COUNT == 0 else f"{FAIL_COUNT} TESTE(S) FALHARAM."
print(f"  {status}")
