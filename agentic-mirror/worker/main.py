import asyncio
import logging
import random
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ExecuteRequest(BaseModel):
    tool_name: str
    params: dict[str, Any] = Field(default_factory=dict)


app = FastAPI(title="Agentic Mirror Worker", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    logger.info("Health check")
    return {"status": "ok"}


async def simulate_weather(params: dict[str, Any]) -> dict[str, Any]:
    city = str(params.get("city", "unknown"))
    unit = str(params.get("unit", "C"))
    base = 22.0 if city.lower() in {"mumbai", "bangalore", "delhi"} else 18.0
    temp = round(base + random.uniform(-5, 5), 1)
    return {
        "city": city,
        "temperature": temp,
        "unit": unit,
        "condition": random.choice(["sunny", "cloudy", "rainy", "windy"]),
    }


async def simulate_math(params: dict[str, Any]) -> dict[str, Any]:
    operation = str(params.get("operation", "add"))
    a = float(params.get("a", 0))
    b = float(params.get("b", 0))

    if operation == "add":
        result = a + b
    elif operation == "sub":
        result = a - b
    elif operation == "mul":
        result = a * b
    elif operation == "div":
        result = a / b if b != 0 else None
    else:
        result = None

    return {"operation": operation, "a": a, "b": b, "result": result}


@app.post("/execute")
async def execute(request: ExecuteRequest) -> dict[str, Any]:
    logger.info(f"Executing tool: {request.tool_name} with params: {request.params}")
    await asyncio.sleep(random.uniform(0.05, 0.2))

    if request.tool_name == "weather":
        payload = await simulate_weather(request.params)
        logger.info(f"Weather tool executed for city: {request.params.get('city', 'unknown')}")
    elif request.tool_name == "math":
        payload = await simulate_math(request.params)
        logger.info(f"Math tool executed: {request.params.get('operation', 'unknown')}")
    else:
        payload = {
            "echo": request.params,
            "message": f"tool '{request.tool_name}' is generic",
        }
        logger.info(f"Generic tool executed: {request.tool_name}")

    return {"ok": True, "data": payload}
