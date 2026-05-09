#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[1/6] Starting Docker stack"
docker compose up -d --build >/tmp/agentic_mirror_compose.log 2>&1
echo "Docker stack started"

echo "[2/6] Verifying Docker services"
docker compose ps

echo "Waiting for gateway readiness"
docker compose exec -T gateway python - <<'PY'
import time
import httpx

client = httpx.Client(timeout=2.0)
for attempt in range(30):
    try:
        r = client.get("http://127.0.0.1:8000/health")
        if r.status_code == 200:
            print("Gateway is ready")
            break
    except Exception:
        pass
    time.sleep(1)
else:
    raise SystemExit("Gateway did not become ready within 30 seconds")
PY

echo "Resetting Redis cache for deterministic validation"
docker compose exec -T redis redis-cli FLUSHDB >/dev/null

echo "[3/6] Running gateway smoke test"
docker compose exec -T gateway python - <<'PY'
import httpx

c = httpx.Client(timeout=10.0)

health = c.get("http://127.0.0.1:8000/health")
assert health.status_code == 200, health.text

for worker in ("http://worker-1:8001", "http://worker-2:8001"):
    r = c.post(
        "http://127.0.0.1:8000/register-tool",
        json={"tool_name": "weather", "endpoint_url": worker, "max_rps": 100},
    )
    assert r.status_code == 200, r.text

first = c.post(
    "http://127.0.0.1:8000/call-tool",
    json={"tool_name": "weather", "params": {"city": "Mumbai", "unit": "C"}},
)
second = c.post(
    "http://127.0.0.1:8000/call-tool",
    json={"tool_name": "weather", "params": {"city": "Mumbai", "unit": "C"}},
)
assert first.status_code == 200, first.text
assert second.status_code == 200, second.text

first_json = first.json()
second_json = second.json()
assert first_json.get("cached") is False, first_json
assert second_json.get("cached") is True, second_json
print("Smoke test passed: first miss then cache hit")
PY

echo "[4/6] Running low-load reliability test"
docker compose exec -T gateway python - <<'PY'
import concurrent.futures as futures
import time
import httpx

c = httpx.Client(timeout=10.0)
total = 100
start = time.time()

def call(i: int) -> int:
    r = c.post(
        "http://127.0.0.1:8000/call-tool",
        json={"tool_name": "weather", "params": {"city": "Mumbai" if i % 2 else "Delhi", "unit": "C"}},
    )
    return r.status_code

with futures.ThreadPoolExecutor(max_workers=10) as ex:
    codes = list(ex.map(call, range(total)))

ok = sum(1 for code in codes if code == 200)
elapsed = time.time() - start
assert ok == total, {"ok": ok, "total": total}
print({"total": total, "ok": ok, "throughput_rps": round(ok / elapsed, 2)})
PY

echo "[5/6] Running high-load behavior test (expect some 429 due rate limits)"
docker compose exec -T gateway python - <<'PY'
import concurrent.futures as futures
import time
import httpx

c = httpx.Client(timeout=10.0)
for worker in ("http://worker-1:8001", "http://worker-2:8001"):
    c.post(
        "http://127.0.0.1:8000/register-tool",
        json={"tool_name": "weather", "endpoint_url": worker, "max_rps": 500},
    )

total = 200
start = time.time()

def call(i: int) -> int:
    r = c.post(
        "http://127.0.0.1:8000/call-tool",
        json={"tool_name": "weather", "params": {"city": "Mumbai" if i % 2 else "Delhi", "unit": "C"}},
    )
    return r.status_code

with futures.ThreadPoolExecutor(max_workers=40) as ex:
    codes = list(ex.map(call, range(total)))

elapsed = time.time() - start
summary = {}
for code in sorted(set(codes)):
    summary[code] = sum(1 for c in codes if c == code)
print({"total": total, "status_counts": summary, "requests_per_sec": round(total / elapsed, 2)})
PY

echo "[6/6] Kubernetes checks"
if ! kubectl config current-context >/dev/null 2>&1; then
  echo "Kubernetes skipped: no current context configured."
  exit 0
fi

echo "Applying Kubernetes manifests"
kubectl apply -f k8s/
kubectl rollout status deployment/agentic-worker --timeout=180s
kubectl rollout status deployment/agentic-gateway --timeout=180s
kubectl get pods -o wide
kubectl get svc

echo "Kubernetes deployment checks passed"
