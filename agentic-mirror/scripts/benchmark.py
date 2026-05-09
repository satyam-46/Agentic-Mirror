import argparse
import asyncio
import statistics
import time
from collections import Counter

import httpx


async def setup_tools(client: httpx.AsyncClient, gateway_url: str, worker_urls: list[str]) -> None:
    for worker in worker_urls:
        payload = {
            "tool_name": "weather",
            "endpoint_url": worker,
            "max_rps": 200,
        }
        resp = await client.post(f"{gateway_url}/register-tool", json=payload)
        resp.raise_for_status()


async def one_call(client: httpx.AsyncClient, gateway_url: str, idx: int) -> tuple[float, bool, int]:
    params = {
        "city": "Mumbai" if idx % 3 else "Delhi",
        "unit": "C",
    }
    start = time.perf_counter()
    resp = await client.post(f"{gateway_url}/call-tool", json={"tool_name": "weather", "params": params})
    elapsed_ms = (time.perf_counter() - start) * 1000

    if resp.status_code != 200:
        return elapsed_ms, False, resp.status_code

    data = resp.json()
    return elapsed_ms, bool(data.get("cached", False)), 200


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    k = int((len(values) - 1) * p)
    return sorted(values)[k]


async def run_benchmark(gateway_url: str, total_requests: int, concurrency: int, worker_urls: list[str]) -> None:
    timeout = httpx.Timeout(15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        await setup_tools(client, gateway_url, worker_urls)

        sem = asyncio.Semaphore(concurrency)
        latencies: list[float] = []
        cached_count = 0
        status_counter: Counter[int] = Counter()

        async def runner(i: int) -> None:
            nonlocal cached_count
            async with sem:
                latency, cached, status_code = await one_call(client, gateway_url, i)
                latencies.append(latency)
                status_counter[status_code] += 1
                if cached:
                    cached_count += 1

        begin = time.perf_counter()
        await asyncio.gather(*(runner(i) for i in range(total_requests)))
        duration = time.perf_counter() - begin

        ok = status_counter[200]
        throughput = ok / duration if duration > 0 else 0.0
        hit_rate = (cached_count / ok) * 100 if ok else 0.0

        print("Benchmark complete")
        print(f"Total requests: {total_requests}")
        print(f"Concurrency: {concurrency}")
        print(f"Success count: {ok}")
        print(f"Status counts: {dict(status_counter)}")
        print(f"Throughput: {throughput:.2f} req/s")
        print(f"Cache hit rate: {hit_rate:.2f}%")
        print(f"Latency p50: {percentile(latencies, 0.50):.2f} ms")
        print(f"Latency p95: {percentile(latencies, 0.95):.2f} ms")
        print(f"Latency p99: {percentile(latencies, 0.99):.2f} ms")
        print(f"Latency mean: {statistics.mean(latencies):.2f} ms")


def main() -> None:
    parser = argparse.ArgumentParser(description="Agentic Mirror benchmark")
    parser.add_argument("--gateway-url", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument(
        "--worker-url",
        action="append",
        default=["http://worker-1:8001", "http://worker-2:8001"],
        help="Worker endpoint URL to register. Can be provided multiple times.",
    )
    args = parser.parse_args()

    asyncio.run(run_benchmark(args.gateway_url, args.requests, args.concurrency, args.worker_url))


if __name__ == "__main__":
    main()
