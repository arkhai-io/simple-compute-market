"""
FastMCP Redis MCP Server
------------------------
Implements three tools that interact with Redis:
- redis_get(key): fetch JSON or raw value + TTL
- redis_set(key, value, expire_seconds?, if_not_exists?): set JSON-safe value with optional TTL
- redis_delete(key): delete a key

Highlights
- Async Redis client (redis.asyncio)
- Server-side key/namespace validation
- Typed payload envelope with version + timestamps
- Cloud Run–ready (HTTP transport, 0.0.0.0, PORT)
- Minimal optimistic concurrency (NX/XX semantics via flags)

Run
- REDIS_URL="redis://localhost:6379/0" python server.py

Dependencies
- fastmcp
- redis>=5.0
- pydantic>=2.7
- httpx (optional, only if you add HTTP tools)

"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional, Union

from fastmcp import FastMCP
from pydantic import BaseModel, Field, constr, ValidationError
from redis.asyncio import Redis

# -------------------------- Logging --------------------------
logger = logging.getLogger("fastmcp_redis")
logging.basicConfig(format="[%(levelname)s]: %(message)s", level=logging.INFO)

# -------------------------- Config ---------------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
NAMESPACE = os.getenv("REDIS_NAMESPACE", "mcp")
ALLOW_RAW_STRING = os.getenv("ALLOW_RAW_STRING", "0") == "1"

# Keys are namespaced as: {NAMESPACE}:{key}
KeyStr = constr(pattern=r"^[a-zA-Z0-9:_\-\.]{1,128}$")


class Envelope(BaseModel):
    """Wrapper we store as JSON in Redis so values remain typed.

    If you prefer storing raw strings (no JSON), set ALLOW_RAW_STRING=1 and
    pass strings to redis_set(value). redis_get(as_json=False) will return raw.
    """

    key: str
    value: Any
    version: int = Field(default=1, ge=1)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# --------------------- MCP Server + Redis --------------------

mcp = FastMCP("Redis MCP Server ⚙️")
redis_client: Optional[Redis] = None


async def get_redis() -> Redis:
    global redis_client
    if redis_client is None:
        logger.info(f"Connecting to Redis: {REDIS_URL}")
        redis_client = Redis.from_url(REDIS_URL, decode_responses=True)
    return redis_client


def full_key(key: str) -> str:
    return f"{NAMESPACE}:{key}"


# --------------------------- Tools ---------------------------

@mcp.tool()
async def redis_get(key: KeyStr, as_json: bool = True) -> dict:
    """Get a value from Redis.

    Args:
        key: The application key (no namespace). Allowed chars: a-zA-Z0-9:_-.
        as_json: If true, returns the stored JSON envelope; otherwise returns raw string.

    Returns:
        {"key": str, "value": Any|str|None, "exists": bool, "ttl": int|None}
    """
    try:
        r = await get_redis()
        k = full_key(key)
        val = await r.get(k)
        ttl = await r.ttl(k)
        exists = val is not None
        if not exists:
            return {"key": key, "value": None, "exists": False, "ttl": None}

        if as_json:
            try:
                return {
                    "key": key,
                    "value": json.loads(val),
                    "exists": True,
                    "ttl": ttl if ttl >= 0 else None,
                }
            except json.JSONDecodeError:
                # Fallback if value was stored as raw string
                return {
                    "key": key,
                    "value": {"raw": val},
                    "exists": True,
                    "ttl": ttl if ttl >= 0 else None,
                }
        else:
            return {
                "key": key,
                "value": val,
                "exists": True,
                "ttl": ttl if ttl >= 0 else None,
            }
    except ValidationError as e:
        return {"error": f"Validation error: {e.errors()}"}
    except Exception as e:
        logger.exception("redis_get failed")
        return {"error": f"redis_get failed: {e}"}


@mcp.tool()
async def redis_set(
    key: KeyStr,
    value: Union[str, int, float, dict, list],
    expire_seconds: Optional[int] = None,
    if_not_exists: bool = False,
    store_raw: Optional[bool] = None,
) -> dict:
    """Set a value in Redis with optional TTL and NX semantics.

    Args:
        key: Application key (validated, no namespace).
        value: JSON-serializable value or raw string.
        expire_seconds: Optional TTL.
        if_not_exists: If true, only set when key does not yet exist (NX).
        store_raw: Force raw string storage for this call (overrides ALLOW_RAW_STRING env).

    Returns:
        {"key": str, "status": "created"|"updated"|"skipped", "version": int, "ttl": int|None}
    """
    try:
        r = await get_redis()
        k = full_key(key)

        # Determine storage mode
        raw = (store_raw is True) or (ALLOW_RAW_STRING and isinstance(value, str))

        # Prepare payload
        if raw:
            payload = str(value)
            version = 1
        else:
            # If replacing, bump version; if new, version=1
            existing = await r.get(k)
            if existing:
                try:
                    env = json.loads(existing)
                    version = int(env.get("version", 1)) + 1
                except Exception:
                    version = 2
            else:
                version = 1

            envelope = Envelope(key=key, value=value, version=version)
            payload = envelope.model_dump_json()

        # Write to Redis
        set_result: bool
        if expire_seconds is not None and expire_seconds > 0:
            set_result = await r.set(k, payload, ex=expire_seconds, nx=if_not_exists or None)
        else:
            set_result = await r.set(k, payload, nx=if_not_exists or None)

        if set_result is False:
            # NX prevented overwrite
            return {"key": key, "status": "skipped", "version": None, "ttl": await _safe_ttl(r, k)}

        ttl = await _safe_ttl(r, k)
        return {"key": key, "status": ("created" if version == 1 else "updated"), "version": version, "ttl": ttl}

    except ValidationError as e:
        return {"error": f"Validation error: {e.errors()}"}
    except Exception as e:
        logger.exception("redis_set failed")
        return {"error": f"redis_set failed: {e}"}


async def _safe_ttl(r: Redis, k: str) -> Optional[int]:
    try:
        t = await r.ttl(k)
        return t if t and t >= 0 else None
    except Exception:
        return None


@mcp.tool()
async def redis_delete(key: KeyStr, missing_ok: bool = True) -> dict:
    """Delete a key from Redis.

    Args:
        key: Application key (validated, no namespace).
        missing_ok: If true, return success when key is absent.

    Returns:
        {"key": str, "deleted": bool}
    """
    try:
        r = await get_redis()
        k = full_key(key)
        deleted = await r.delete(k)
        if deleted == 0 and not missing_ok:
            return {"key": key, "deleted": False, "error": "Key not found"}
        return {"key": key, "deleted": bool(deleted)}
    except ValidationError as e:
        return {"error": f"Validation error: {e.errors()}"}
    except Exception as e:
        logger.exception("redis_delete failed")
        return {"error": f"redis_delete failed: {e}"}


# ----------------------- Server Entrypoint -------------------

if __name__ == "__main__":
    logger.info(f"🚀 MCP server started on port {os.getenv('PORT', '8080')} (namespace='{NAMESPACE}')")
    asyncio.run(
        mcp.run_async(
            transport="http",  # also supports 'sse'
            host="0.0.0.0",     # Cloud Run requires 0.0.0.0
            port=int(os.getenv("PORT", "8080")),
        )
    )
