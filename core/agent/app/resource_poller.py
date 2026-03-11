"""Background resource availability poller.

Runs a periodic asyncio loop that queries each registered compute resource
for live slot availability (via the configured provisioning client) and writes
the result to the SQLite ``resources`` table via idempotent state transitions.

All three provisioning modes (http / ansible / mock) are supported. The mock
mode's scheduled auto-free ensures state changes are visible on the next poll
cycle without requiring real infrastructure.

Wire into startup via::

    asyncio.create_task(resource_poller_loop())
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from core.agent.app.utils.config import CONFIG
from core.agent.app.utils.sqlite_client import SQLiteClient

logger = logging.getLogger(__name__)


def _get_resources_fn() -> Callable[..., Coroutine[Any, Any, dict[str, Any]]]:
    """Return the ``get_vm_available_resources`` coroutine for the active provisioning mode."""
    mode = CONFIG.provisioning_mode
    if mode == "ansible":
        from service.clients.ansible_provisioning import get_vm_available_resources
    elif mode == "mock":
        from service.clients.mock_provisioning import get_vm_available_resources
    else:
        from service.clients.provisioning import get_vm_available_resources  # type: ignore[assignment]
    return get_vm_available_resources  # type: ignore[return-value]


async def _poll_once(sqlite_client: SQLiteClient, provisioning_fn: Callable) -> None:
    """Run one availability check for every registered compute.gpu resource."""
    resources = await sqlite_client.list_resources(resource_type="compute.gpu")
    if not resources:
        logger.debug("resource_poller: no compute.gpu resources registered — skipping poll")
        return

    now = datetime.now(timezone.utc)

    for r in resources:
        if r.get("state") == "leased":
            lease_end_str: str | None = (r.get("attributes") or {}).get("lease_end_utc")
            if lease_end_str:
                try:
                    lease_end = datetime.strptime(lease_end_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
                    if now < lease_end:
                        logger.debug(
                            "resource_poller: resource %s is leased until %s — skipping poll",
                            r.get("resource_id"),
                            lease_end_str,
                        )
                        continue
                    # Lease window has passed — poll to confirm VM is down, then free.
                    logger.info(
                        "resource_poller: resource %s lease ended at %s — polling to confirm VM is down",
                        r.get("resource_id"),
                        lease_end_str,
                    )
                except ValueError:
                    logger.warning(
                        "resource_poller: resource %s has unparseable lease_end_utc %r — skipping poll",
                        r.get("resource_id"),
                        lease_end_str,
                    )
                    continue
            else:
                logger.debug(
                    "resource_poller: resource %s is leased with no lease_end_utc — skipping poll",
                    r.get("resource_id"),
                )
                continue

        vm_host: str | None = (r.get("attributes") or {}).get("vm_host")
        if not vm_host:
            logger.debug(
                "resource_poller: resource %s has no vm_host attribute — skipping",
                r.get("resource_id"),
            )
            continue

        try:
            result = await provisioning_fn(
                CONFIG.provisioning_service_url,
                vm_host=vm_host,
                timeout=60,
                poll_interval=5,
                agent_id=CONFIG.onchain_agent_id,
            )
        except Exception as exc:
            logger.warning(
                "resource_poller: failed to check %s via %s: %s",
                vm_host,
                CONFIG.provisioning_mode,
                exc,
            )
            continue

        available: bool = bool(result.get("available", False))
        running_vms = result.get("running_vms", "?")
        new_state = "available" if available else "reserved"
        idempotency_key = (
            f"resource-poll-{r['resource_id']}-{running_vms}-{new_state}"
        )

        # When freeing a post-lease resource, clear lease_end_utc so it's clean for next use.
        was_leased = r.get("state") == "leased"
        clear_lease_attr = {"$.lease_end_utc": None} if (was_leased and available) else None

        transition = await sqlite_client.apply_resource_transition(
            resource_id=r["resource_id"],
            event_type="resource_availability_poll",
            idempotency_key=idempotency_key,
            set_state=new_state,
            set_attribute=clear_lease_attr,
        )

        if transition.get("applied", True):
            logger.info(
                "resource_poller: %s (%s) → %s (running_vms=%s)",
                r["resource_id"],
                vm_host,
                new_state,
                running_vms,
            )
        else:
            logger.debug(
                "resource_poller: %s (%s) unchanged (%s) — duplicate idempotency key",
                r["resource_id"],
                vm_host,
                new_state,
            )


async def resource_poller_loop() -> None:
    """Continuously poll resource availability and persist state to SQLite.

    Sleeps for an initial 10 s to allow the agent to finish startup, then
    polls every ``CONFIG.resource_check_interval`` seconds.
    """
    await asyncio.sleep(10)  # let agent finish startup
    sqlite_client = SQLiteClient(db_path=CONFIG.agent_db_path)
    logger.info(
        "resource_poller_loop: started (interval=%ds, mode=%s)",
        CONFIG.resource_check_interval,
        CONFIG.provisioning_mode,
    )
    if CONFIG.provisioning_mode == "ansible":
        from service.clients.ansible_provisioning import validate_ansible_prerequisites
        errors = validate_ansible_prerequisites()
        if errors:
            for err in errors:
                logger.error("resource_poller [ansible pre-flight]: %s", err)
            logger.error(
                "resource_poller [ansible pre-flight]: FAILED — provisioning will not work until the above are resolved"
            )
        else:
            logger.info("resource_poller [ansible pre-flight]: all prerequisites found")
    while True:
        try:
            await asyncio.sleep(CONFIG.resource_check_interval)
            await _poll_once(sqlite_client, _get_resources_fn())
        except asyncio.CancelledError:
            logger.info("resource_poller_loop: cancelled, shutting down")
            break
        except Exception as exc:
            logger.exception("resource_poller_loop error: %s", exc)
