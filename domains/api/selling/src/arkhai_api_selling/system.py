"""A quota-backed storefront's health, and the administrator's status read with every loop's state."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from core_storefront.models.system_models import LoopStatus
from market_storefront_kit import StorefrontLoopController

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SystemSettings:
    """What the health checks probe, as configured when a check runs."""

    registry_urls: tuple[str, ...]
    registry_auth: Mapping[str, str]
    authority_url: str


def lifecycle_status(
    loops: StorefrontLoopController | None,
) -> dict[str, LoopStatus] | None:
    """Every lifecycle loop by name: its controller state and the outcome of its
    last cycle, whether its timer or an operator's step ran it."""
    if loops is None:
        return None
    return {
        name: LoopStatus.model_validate(loop.to_dict())
        for name, loop in loops.snapshot().items()
    }


async def _probe(url: str, headers: Mapping[str, str] | None = None) -> str:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{url}/health", headers=dict(headers or {}))
        return "ok" if response.status_code < 500 else f"http_{response.status_code}"
    except httpx.ConnectError:
        return "unreachable"
    except httpx.TimeoutException:
        return "timeout"
    except Exception as exc:
        return f"error: {exc}"


class SystemService:
    def __init__(
        self,
        *,
        sqlite_client: Any,
        settings: Callable[[], SystemSettings],
        mechanism_checks: Callable[[], Mapping[str, str]],
        signer: Callable[[], Any | None],
    ) -> None:
        self._db = sqlite_client
        self._settings = settings
        self._mechanism_checks = mechanism_checks
        self._signer = signer

    async def get_health(self, *, include_registry: bool = False) -> dict[str, Any]:
        """Each check's state; a mechanism's check is healthy unless it reports an error."""
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
            checks["credits_service"] = await self._authority_check()

        mechanisms = dict(self._mechanism_checks())
        checks.update(mechanisms)

        def healthy(key: str, value: str) -> bool:
            if value in ("ok", "unconfigured"):
                return True
            if key in mechanisms:
                return bool(value) and not value.startswith(("unknown:", "error:"))
            return False

        result: dict[str, Any] = {
            "status": "ok" if all(healthy(k, v) for k, v in checks.items()) else "degraded",
            "checks": checks,
        }
        if include_registry:
            signer = self._signer()
            result["principal"] = signer.identity.model_dump(mode="json") if signer else None
        return result

    async def status(
        self, *, paused: bool, loops: StorefrontLoopController | None
    ) -> dict[str, Any]:
        """The administrator's status read: health with the registries and the
        authority, the storefront's principal, the trading pause, and every loop."""
        body = await self.get_health(include_registry=True)
        body["paused"] = paused
        body["lifecycle"] = lifecycle_status(loops)
        return body

    async def _registry_check(self) -> str:
        settings = self._settings()
        urls = [url.rstrip("/") for url in settings.registry_urls if url]
        if not urls:
            return "unconfigured"
        auth = settings.registry_auth or {}

        def headers(url: str) -> dict[str, str]:
            token = auth.get(url) or auth.get(url + "/")
            return {"Authorization": f"Bearer {token}"} if token else {}

        results = await asyncio.gather(*[_probe(url, headers(url)) for url in urls])
        if any(result == "ok" for result in results):
            return "ok"
        return results[-1]

    async def _authority_check(self) -> str:
        url = self._settings().authority_url
        if not url:
            return "unconfigured"
        return await _probe(url)
