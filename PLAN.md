You are a senior backend engineer and system designer. Build a production-quality MVP for a project called:

"Agentic Mirror – Distributed MCP Registry and Tool Routing System"

## 🎯 Goal
Design and implement a scalable backend system that allows multiple AI agents (LLMs) to discover and call tools via a centralized registry and routing layer.

The system should simulate high-scale tool-calling infrastructure with caching, load balancing, and rate limiting.

---

## 🏗️ Core Requirements

### 1. Gateway Service (FastAPI)
Build a FastAPI service that acts as the central entry point.

Endpoints:
- POST /register-tool  
  Register a tool with:
  - tool_name
  - endpoint URL
  - max_rps (rate limit per tool)

- POST /call-tool  
  Input:
  - tool_name
  - params (JSON)

  Behavior:
  - Check Redis cache first
  - If cache hit → return cached response
  - Else:
    - Discover available workers for the tool
    - Load balance request
    - Call worker
    - Cache response with TTL
    - Return result

---

### 2. Tool Worker Service
Create a separate FastAPI service acting as a tool server.

- Expose endpoint: POST /execute
- Simulate tool logic (e.g., weather API, math API)
- Add artificial latency (50–200ms) to simulate real-world API

Workers must be stateless and horizontally scalable.

---

### 3. Redis Integration
Use Redis for:

1. Caching
   - Deterministic key = hash(tool_name + sorted params)
   - TTL = configurable (default 60s)

2. (Optional but preferred) Request queue or metadata storage

---

### 4. Load Balancing Strategy
Implement simple but explicit logic:
- Round-robin OR least-connections
- Maintain in-memory registry of active workers
- Include health check mechanism

---

### 5. Rate Limiting (Token Bucket)
Implement per-client rate limiting:
- Token bucket algorithm
- Configurable rate and burst
- Reject requests with HTTP 429 when exceeded

---

### 6. Concurrency + Performance
- Use async FastAPI endpoints
- Use httpx or aiohttp for async calls
- Ensure system handles concurrent requests correctly

---

## 🐳 Docker Setup
Provide:
- Dockerfile for gateway
- Dockerfile for worker
- docker-compose.yml to run:
  - gateway
  - multiple workers
  - Redis

---

## ☸️ Kubernetes (Optional but preferred)
Provide basic manifests:
- Deployment for workers (replicas=2+)
- Service for gateway
- HPA config (scale on CPU or request count)

---

## 📊 Benchmarking Script
Create a script (Python or k6) to:
- Simulate concurrent tool calls
- Measure:
  - latency (p50, p95, p99)
  - cache hit rate
  - throughput

---

## 📁 Project Structure

agentic-mirror/
- gateway/
- worker/
- common/
- scripts/
- docker-compose.yml
- README.md

---

## 📘 README Requirements
Explain clearly:
- Architecture diagram (ASCII is fine)
- How requests flow
- How caching works
- How rate limiting works
- How to run locally
- Benchmark results

---

## ⚠️ Constraints
- Keep MVP simple but correct
- Avoid unnecessary abstractions
- Focus on clarity + correctness over overengineering
- Code must be clean, readable, and modular

---

## ✅ Deliverables
- Working code for gateway + worker
- Docker setup
- Redis integration
- Rate limiter
- Benchmark script
- README with explanation

---

## 💡 Bonus (if time permits)
- Retry logic with exponential backoff
- Circuit breaker for failing workers
- Logging + request tracing

---

## 🧠 Important
Do NOT just scaffold files. Implement working logic with clear flow and comments explaining key decision