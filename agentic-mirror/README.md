# Agentic Mirror

Distributed MCP Registry and Tool Routing MVP using FastAPI, Redis, async routing, round-robin balancing, and token-bucket rate limiting with comprehensive logging.

## Project Structure

```
agentic-mirror/
  gateway/
  worker/
  common/
  scripts/
  k8s/
  docker-compose.yml
  README.md
```

## Architecture

```
+------------+       +--------------------+       +----------------+
|  AI Agent  | ----> | Gateway (FastAPI)  | ----> | Worker A/B ... |
+------------+       | - registry         |       | /execute       |
                     | - load balancing   |       +----------------+
                     | - rate limiting    |
                     | - Redis cache      | <----> Redis
                     +--------------------+
```

## Request Flow

1. Client calls `POST /call-tool` on gateway.
2. Gateway applies per-client token bucket limit.
3. Gateway applies per-tool token bucket limit (`max_rps` from registration).
4. Gateway computes deterministic cache key from `tool_name + sorted params`.
5. If cache hit in Redis, response is returned with `cached=true`.
6. If cache miss, gateway picks a healthy worker with round-robin.
7. Gateway calls worker `/execute` asynchronously using `httpx`.
8. Gateway stores response in Redis (`TTL` default `60s`) and returns payload.

## Caching

- Key: SHA256 hash of JSON `{tool_name, params}` with sorted keys.
- Store: Redis.
- TTL: configurable via `CACHE_TTL_SECONDS` (default `60`).

## Rate Limiting

Token bucket algorithm:
- Per-client bucket in gateway dependency.
- Per-tool bucket derived from `max_rps` at registration.
- Exceeding limit returns HTTP `429`.

## Health Checks + Load Balancing

- Worker registry is in-memory in gateway.
- Health loop probes `GET /health` on each registered worker.
- Round-robin selection over currently healthy workers.
- Unhealthy workers are skipped until healthy again.

## Logging

Both gateway and worker services include comprehensive logging:
- Info level logs for major operations (registration, tool execution)
- Warning level logs for recoverable issues (rate limits, health check failures)
- Error level logs for unrecoverable issues (no healthy workers)
- Debug level logs for detailed tracing (only in health checks when enabled)

## Local Run (Docker)

From `agentic-mirror/`:

```bash
docker compose up --build
```

Gateway: `http://localhost:8000`

## Register Workers

```bash
curl -X POST http://localhost:8000/register-tool \
  -H "Content-Type: application/json" \
  -d '{"tool_name":"weather","endpoint_url":"http://worker-1:8001","max_rps":100}'

curl -X POST http://localhost:8000/register-tool \
  -H "Content-Type: application/json" \
  -d '{"tool_name":"weather","endpoint_url":"http://worker-2:8001","max_rps":100}'
```

## Call Tool

```bash
curl -X POST http://localhost:8000/call-tool \
  -H "Content-Type: application/json" \
  -d '{"tool_name":"weather","params":{"city":"Mumbai","unit":"C"}}'
```

## Benchmark

Install benchmark dependency:

```bash
pip install -r scripts/requirements.txt
```

Run:

```bash
python scripts/benchmark.py --gateway-url http://localhost:8000 --requests 1000 --concurrency 100
```

If running gateway/workers outside Docker networking, pass worker URLs explicitly:

```bash
python scripts/benchmark.py \
  --gateway-url http://localhost:8000 \
  --worker-url http://localhost:8001 \
  --worker-url http://localhost:8002
```

Output includes:
- throughput
- cache hit rate
- latency p50/p95/p99

## Full Validation Script

Run Docker end-to-end validation and Kubernetes checks in one command:

```bash
./scripts/full_validation.sh
```

What it does:
- builds and starts Docker services
- waits for gateway readiness
- validates register + call + cache-hit flow
- runs low-load and high-load behavior tests
- applies Kubernetes checks when a `kubectl` context is configured

## Kubernetes (Optional)

Manifests in `k8s/`:
- `gateway-deployment.yaml`
- `worker-deployment.yaml`
- `worker-hpa.yaml`
- `redis.yaml`

Apply:

```bash
kubectl apply -f k8s/
```

## Benchmark Results

Sample output shape from a local run:

```text
Throughput: 620.45 req/s
Cache hit rate: 93.80%
Latency p50: 22.14 ms
Latency p95: 88.42 ms
Latency p99: 142.76 ms
```

Numbers vary by machine, worker count, and configured rate limits.

## Notes

- Workers are stateless and horizontally scalable.
- Endpoints are async and suitable for concurrent calls.
- Includes retry with exponential backoff in gateway worker invocation.
- Comprehensive logging for monitoring and debugging.
