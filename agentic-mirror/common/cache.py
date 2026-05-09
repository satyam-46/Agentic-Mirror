import hashlib
import json
from typing import Any


def deterministic_cache_key(tool_name: str, params: dict[str, Any]) -> str:
    """Build deterministic cache key from tool + sorted JSON params."""
    payload = {
        "tool_name": tool_name,
        "params": params,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return f"tool-cache:{digest}"
