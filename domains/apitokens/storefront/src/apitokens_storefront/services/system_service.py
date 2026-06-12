"""SystemService — health and connectivity checks."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SystemService:
    def __init__(self, *, sqlite_client, agent_id: str | None = None) -> None:
        from apitokens_storefront.utils.config import AGENT_ID

        self._db = sqlite_client
        self._agent_id = agent_id or AGENT_ID or "agent"

    async def get_health(self, *, include_registry: bool = False) -> dict:
        import sqlite3

        import apitokens_storefront.container as _container

        checks: dict[str, str] = {"api": "ok"}
        try:
            conn = sqlite3.connect(self._db.db_path, timeout=2)
            try:
                conn.execute("SELECT 1")
            finally:
                conn.close()
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {exc}"

        if include_registry:
            checks["registry"] = await self._registry_check()
            checks["tokens_service"] = await self._tokens_service_check()

        configured = _container.configured_chain_names()
        checks["alkahest"] = ",".join(sorted(configured)) if configured else "unconfigured"

        def _check_is_healthy(key: str, value: str) -> bool:
            if value in ("ok", "unconfigured"):
                return True
            if key == "alkahest":
                return bool(value) and not value.startswith(("unknown:", "error:"))
            return False

        all_ok = all(_check_is_healthy(k, v) for k, v in checks.items())
        result: dict[str, Any] = {
            "status": "ok" if all_ok else "degraded",
            "checks": checks,
        }
        if include_registry:
            from apitokens_storefront.utils.config import settings

            wallet = (settings.wallet.address or "").lower() or None
            result["agent_id"] = wallet
        return result

    async def _registry_check(self) -> str:
        import asyncio

        import httpx

        from apitokens_storefront.utils.config import settings

        urls = [u.rstrip("/") for u in (settings.registry.urls or []) if u]
        if not urls:
            return "unconfigured"
        auth = settings.registry.auth or {}

        async def _probe(url: str) -> str:
            headers = {}
            token = auth.get(url) or auth.get(url + "/")
            if token:
                headers["Authorization"] = f"Bearer {token}"
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    resp = await client.get(f"{url}/health", headers=headers)
                return "ok" if resp.status_code < 500 else f"http_{resp.status_code}"
            except httpx.ConnectError:
                return "unreachable"
            except httpx.TimeoutException:
                return "timeout"
            except Exception as exc:
                return f"error: {exc}"

        results = await asyncio.gather(*[_probe(u) for u in urls])
        if any(r == "ok" for r in results):
            return "ok"
        return results[-1]

    async def _tokens_service_check(self) -> str:
        import httpx

        from apitokens_storefront.utils import config

        url = config.tokens_service_url()
        if not url:
            return "unconfigured"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{url}/health")
            return "ok" if resp.status_code < 500 else f"http_{resp.status_code}"
        except httpx.ConnectError:
            return "unreachable"
        except httpx.TimeoutException:
            return "timeout"
        except Exception as exc:
            return f"error: {exc}"
