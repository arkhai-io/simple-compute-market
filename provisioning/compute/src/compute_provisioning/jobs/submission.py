"""How every job reaches the job authority.

``JobSubmissionService`` is the one way a job is submitted, for a fulfillment
and for an operator's route alike. It checks the host the job runs against,
fixes the job's identity, and hands the job to the engine and the queue. What a
job runs is its parameters, which it passes through without reading.

Every job needs a registered host: the engine resolves the host again just
before execution, and a job naming none could only fail there. Only a
fulfillment's create also needs the host enabled. Disabling a host stops new
delivery to it; it must not stop the teardown of what is already on it, or an
operator's work there.

A fulfillment's job is submitted under its contract, and its operation id is
derived from that contract's identity, so a retried dispatch names the job it
already submitted. An operator's job keeps the operation id its request names,
or none.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from compute_provisioning_contracts import HostResponse, JobSubmitResponse

from compute_provisioning.hosts.service import HostNotFoundError
from compute_provisioning.jobs.action_request import JobActionRequest
from compute_provisioning.jobs.engine import JobEngine
from compute_provisioning.jobs.queue import AsyncJobQueue

# Fixed so a contract's operation id is the same in every process and release.
_CONTRACT_OPERATION_NAMESPACE = uuid.UUID("6f0c5a52-4f7e-4f0e-9a39-7d2a8f1b3c41")


class HostDisabledError(Exception):
    """A fulfillment's create named a host that is registered but disabled."""


class HostReader(Protocol):
    def get_host(self, host_id: str) -> HostResponse | None: ...


def contract_operation_id(contract: JobActionRequest) -> str:
    """The operation id of the job a fulfillment contract submits.

    Derived from the contract's whole identity (reservation, action kind,
    idempotency key), so every dispatch of one operation names one job.
    """
    return str(
        uuid.uuid5(
            _CONTRACT_OPERATION_NAMESPACE,
            "\0".join(
                (
                    contract.capacity_reservation_id,
                    contract.action_kind,
                    contract.idempotency_key,
                )
            ),
        )
    )


class JobSubmissionService:
    def __init__(
        self,
        *,
        engine: JobEngine,
        hosts: HostReader,
        job_queue_provider: Callable[[], AsyncJobQueue],
    ) -> None:
        self._engine = engine
        self._hosts = hosts
        # A provider rather than the queue: the queue is created when the
        # service starts, after composition has built this service.
        self._job_queue_provider = job_queue_provider

    async def submit(
        self,
        *,
        offering_mode: str,
        action: str,
        host_id: str,
        params: Mapping[str, Any],
        contract: JobActionRequest | None = None,
        operation_id: str | None = None,
        require_enabled_host: bool = False,
        max_retries: int | None = None,
    ) -> JobSubmitResponse:
        """Submit one job, refusing a host it may not run against.

        Raises ``HostNotFoundError`` for an unregistered host, and
        ``HostDisabledError`` for a disabled one when ``require_enabled_host``.
        A job under a contract takes the contract's operation id; passing
        another is refused, since one operation must name one job.
        """
        host = self._hosts.get_host(host_id)
        if host is None:
            raise HostNotFoundError(f"host {host_id!r} is not registered")
        if require_enabled_host and not host.enabled:
            raise HostDisabledError(f"host {host_id!r} is disabled")
        if contract is not None:
            derived = contract_operation_id(contract)
            if operation_id is not None and operation_id != derived:
                raise ValueError(
                    "a job submitted under a contract takes the contract's operation id"
                )
            operation_id = derived
        return await self._engine.submit(
            offering_mode=offering_mode,
            action=action,
            host_id=host_id,
            params=params,
            job_queue=self._job_queue_provider(),
            max_retries=max_retries,
            contract=contract,
            operation_id=operation_id,
        )


__all__ = [
    "HostDisabledError",
    "HostReader",
    "JobSubmissionService",
    "contract_operation_id",
]
