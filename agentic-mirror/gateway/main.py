import asyncio
import json
import logging
import os
from collections import defaultdict
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Any

import httpx
import redis.asyncio as redis
from fastapi import Depends, FastAPI, HTTPException, Request, status
from pydantic import BaseModel, Field, HttpUrl

from common.cache import deterministic_cache_key
from common.rate_limiter import TokenBucketLimiter

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "60"))
HEALTH_CHECK_INTERVAL_SECONDS = float(os.getenv("HEALTH_CHECK_INTERVAL_SECONDS", "5"))
CLIENT_RATE = float(os.getenv("CLIENT_RATE", "30"))
CLIENT_BURST = float(os.getenv("CLIENT_BURST", "60"))


class RegisterToolRequest(BaseModel):
    tool_name: str = Field(..., min_length=1)
    endpoint_url: HttpUrl
    max_rps: int = Field(..., gt=0)


class CallToolRequest(BaseModel):
    tool_name: str = Field(..., min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


@dataclass
class ToolConfig:
    max_rps: int


class WorkerRegistry:
    def __init__(self) -> None:
        self._workers: dict[str, list[str]] = defaultdict(list)
        self._active_workers: dict[str, list[str]] = defaultdict(list)
        self._rr_index: dict[str, int] = defaultdict(int)
        self._tools: dict[str, ToolConfig] = {}
        self._lock = asyncio.Lock()

    async def register(self, tool_name: str, endpoint_url: str, max_rps: int) -> None:
        async with self._lock:
            if endpoint_url not in self._workers[tool_name]:
                self._workers[tool_name].append(endpoint_url)
                self._active_workers[tool_name].append(endpoint_url)
            self._tools[tool_name] = ToolConfig(max_rps=max_rps)

    async def get_tool_config(self, tool_name: str) -> ToolConfig | None:
        async with self._lock:
            return self._tools.get(tool_name)

    async def pick_worker(self, tool_name: str) -> str | None:
        async with self._lock:
            active_workers = self._active_workers.get(tool_name, [])
            if not active_workers:
                return None

            idx = self._rr_index[tool_name] % len(active_workers)
            self._rr_index[tool_name] = (idx + 1) % len(active_workers)
            return active_workers[idx]

    async def all_registered_workers(self) -> dict[str, list[str]]:
        async with self._lock:
            return {tool: list(urls) for tool, urls in self._workers.items()}

    async def set_active_workers(self, tool_name: str, workers: list[str]) -> None:
        async with self._lock:
            self._active_workers[tool_name] = workers
            if self._rr_index[tool_name] >= max(1, len(workers)):
                self._rr_index[tool_name] = 0


registry = WorkerRegistry()
redis_client: redis.Redis | None = None
http_client: httpx.AsyncClient | None = None
client_limiter = TokenBucketLimiter(rate=CLIENT_RATE, burst=CLIENT_BURST)
tool_limiters: dict[str, TokenBucketLimiter] = {}


async def health_check_loop() -> None:
    while True:
        logger.info("Starting health check cycle")
        snapshot = await registry.all_registered_workers()
        for tool_name, workers in snapshot.items():
            healthy: list[str] = []
            for worker_url in workers:
                try:
                    assert http_client is not None
                    r = await http_client.get(f"{worker_url}/health", timeout=1.0)
                    if r.status_code == 200:
                        healthy.append(worker_url)
                        logger.debug(f"Worker {worker_url} is healthy")
                    else:
                        logger.warning(f"Worker {worker_url} health check failed with status {r.status_code}")
                except Exception as e:
                    logger.warning(f"Worker {worker_url} health check failed: {e}")
                    continue
            await registry.set_active_workers(tool_name, healthy)
            logger.info(f"Health check completed for {tool_name}: {len(healthy)}/{len(workers)} workers healthy")
        await asyncio.sleep(HEALTH_CHECK_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global redis_client, http_client
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    http_client = httpx.AsyncClient()
    task = asyncio.create_task(health_check_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        if http_client is not None:
            await http_client.aclose()
        if redis_client is not None:
            await redis_client.aclose()


app = FastAPI(title="Agentic Mirror Gateway", version="0.1.0", lifespan=lifespan)


async def enforce_client_rate_limit(request: Request) -> None:
    client_ip = request.headers.get("x-forwarded-for") or (request.client.host if request.client else "unknown")
    allowed = await client_limiter.allow(client_ip)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Client rate limit exceeded")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/register-tool", dependencies=[Depends(enforce_client_rate_limit)])
async def register_tool(payload: RegisterToolRequest) -> dict[str, Any]:
    logger.info(f"Registering tool: {payload.tool_name} at {payload.endpoint_url} with max_rps={payload.max_rps}")
    await registry.register(payload.tool_name, str(payload.endpoint_url).rstrip("/"), payload.max_rps)
    tool_limiters[payload.tool_name] = TokenBucketLimiter(rate=float(payload.max_rps), burst=float(payload.max_rps))
    logger.info(f"Successfully registered tool: {payload.tool_name}")
    return {"ok": True, "tool_name": payload.tool_name, "endpoint_url": str(payload.endpoint_url), "max_rps": payload.max_rps}


@app.post("/call-tool", dependencies=[Depends(enforce_client_rate_limit)])
async def call_tool(payload: CallToolRequest) -> dict[str, Any]:
    logger.info(f"Calling tool: {payload.tool_name} with params: {payload.params}")
    tool_config = await registry.get_tool_config(payload.tool_name)
    if tool_config is None:
        logger.warning(f"Tool not registered: {payload.tool_name}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not registered")

    limiter = tool_limiters.setdefault(
        payload.tool_name,
        TokenBucketLimiter(rate=float(tool_config.max_rps), burst=float(tool_config.max_rps)),
    )
    if not await limiter.allow(payload.tool_name):
        logger.warning(f"Tool rate limit exceeded for: {payload.tool_name}")
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Tool rate limit exceeded")

    key = deterministic_cache_key(payload.tool_name, payload.params)
    assert redis_client is not None
    cached = await redis_client.get(key)
    if cached is not None:
        logger.info(f"Cache hit for tool: {payload.tool_name}")
        return {
            "ok": True,
            "cached": True,
            "tool_name": payload.tool_name,
            "result": json.loads(cached),
        }

    worker = await registry.pick_worker(payload.tool_name)
    if worker is None:
        logger.error(f"No healthy worker available for tool: {payload.tool_name}")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="No healthy worker available")

    body = {"tool_name": payload.tool_name, "params": payload.params}
    assert http_client is not None

    logger.info(f"Calling worker {worker} for tool: {payload.tool_name}")
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = await http_client.post(f"{worker}/execute", json=body, timeout=5.0)
            response.raise_for_status()
            data = response.json()
            await redis_client.setex(key, CACHE_TTL_SECONDS, json.dumps(data))
            logger.info(f"Successfully executed tool: {payload.tool_name} on worker: {worker}")
            return {
                "ok": True,
                "cached": False,
                "tool_name": payload.tool_name,
                "worker": worker,
                "result": data,
            }
        except Exception as exc:
            last_error = exc
            logger.warning(f"Attempt {attempt + 1} failed for worker {worker}: {exc}")
            await asyncio.sleep(0.05 * (2**attempt))

    logger.error(f"All attempts failed for tool: {payload.tool_name}, last error: {last_error}")
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Worker call failed: {last_error}")
