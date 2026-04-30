"""Synchronous HTTP client for the provisioning service test controller.

This client is **test infrastructure only** — it targets the ``/test/*``
endpoints that are only mounted when ``ACTIVE_PROFILES`` includes ``mock``.
It is intentionally separate from the canonical ``SyncProvisioningClient``
because the test controller is not part of the provisioning service's
public API contract.

Usage::

    client = ProvisioningTestClient("http://provisioning:8081")

    # Add a rule that pauses before returning
    client.add_mock_rule(
        rule_id="pause-create",
        match={"vm_action": "create", "vm_host": "ww1"},
        pause_before_result=True,
    )

    # ... submit job via normal API ...

    # Release the gate
    client.resume_rule("pause-create")

    # Wait deterministically for terminal state
    result = client.wait_for_job(job_id, timeout=15)
    assert result["status"] == "succeeded"
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)


class ProvisioningTestClientError(Exception):
    """Non-2xx response from the provisioning test controller."""


class ProvisioningTestClient:
    """Sync HTTP client for ``/test/*`` endpoints on the provisioning service.

    Parameters
    ----------
    base_url:
        Base URL of the provisioning service (e.g. ``http://provisioning:8081``).
    timeout:
        Default HTTP timeout in seconds.  ``wait_for_job`` and ``drain``
        use a longer per-call timeout matching the server-side ``timeout``
        query parameter.
    """

    def __init__(self, base_url: str, *, timeout: float = 15.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._client = httpx.Client(base_url=self._base, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ProvisioningTestClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get(self, path: str, *, params: dict | None = None, timeout: float | None = None) -> dict:
        resp = self._client.get(path, params=params or {}, timeout=timeout or self._timeout)
        if resp.status_code >= 400:
            raise ProvisioningTestClientError(
                f"GET {self._base}{path} returned {resp.status_code}: {resp.text[:200]}"
            )
        return resp.json()

    def _post(self, path: str, body: dict | None = None) -> dict:
        resp = self._client.post(path, json=body or {}, timeout=self._timeout)
        if resp.status_code >= 400:
            raise ProvisioningTestClientError(
                f"POST {self._base}{path} returned {resp.status_code}: {resp.text[:200]}"
            )
        return resp.json()

    def _delete(self, path: str) -> dict:
        resp = self._client.delete(path, timeout=self._timeout)
        if resp.status_code >= 400:
            raise ProvisioningTestClientError(
                f"DELETE {self._base}{path} returned {resp.status_code}: {resp.text[:200]}"
            )
        return resp.json()

    # ------------------------------------------------------------------
    # Mock rule management
    # ------------------------------------------------------------------

    def add_mock_rule(
        self,
        *,
        rule_id: str = "",
        match: dict[str, Any] | None = None,
        pause_before_result: bool = False,
        result_stdout: Optional[str] = None,
        fail_with: Optional[str] = None,
    ) -> dict:
        """POST /test/mock-rules — add a when→then rule.

        Parameters
        ----------
        rule_id:
            Caller-chosen identifier for resume/delete.  Auto-assigned
            if empty.
        match:
            Subset of ``AnsibleJobParams`` fields.  A job matches when all
            keys in ``match`` are present and equal in the job params.
            Empty dict is a catch-all.
        pause_before_result:
            If True, the mock blocks at ``wait_for_playbook`` until
            ``resume_rule`` is called.
        result_stdout:
            Ansible stdout to inject on success.  Falls back to the
            default fake stdout if None.
        fail_with:
            If set, the mock raises ``AnsibleError`` with this message
            instead of returning a result.
        """
        body: dict[str, Any] = {
            "rule_id": rule_id,
            "match": match or {},
            "pause_before_result": pause_before_result,
        }
        if result_stdout is not None:
            body["result_stdout"] = result_stdout
        if fail_with is not None:
            body["fail_with"] = fail_with
        return self._post("/test/mock-rules", body)

    def list_mock_rules(self) -> list[dict]:
        """GET /test/mock-rules — return active rules in evaluation order."""
        return self._get("/test/mock-rules")  # type: ignore[return-value]

    def delete_mock_rule(self, rule_id: str) -> dict:
        """DELETE /test/mock-rules/{rule_id} — remove a rule."""
        return self._delete(f"/test/mock-rules/{rule_id}")

    def resume_rule(self, rule_id: str) -> dict:
        """POST /test/mock-rules/{rule_id}/resume — release a paused job gate."""
        return self._post(f"/test/mock-rules/{rule_id}/resume")

    # ------------------------------------------------------------------
    # Job observation
    # ------------------------------------------------------------------

    def job_summary(self) -> dict:
        """GET /test/jobs/summary — status counts, non-blocking."""
        return self._get("/test/jobs/summary")

    def wait_for_job(self, job_id: str, *, timeout: float = 30.0) -> dict:
        """GET /test/jobs/{job_id}/wait — block until terminal state.

        Returns the terminal job dict.  Raises ``ProvisioningTestClientError``
        on timeout (HTTP 408) or if the job is not found (HTTP 404).

        The server holds the connection open until the job completes or
        the ``timeout`` elapses — this is a long-poll, not a polling loop.
        """
        # Add a small buffer so the httpx client timeout doesn't fire
        # before the server-side timeout returns 408.
        http_timeout = timeout + 5.0
        return self._get(
            f"/test/jobs/{job_id}/wait",
            params={"timeout": timeout},
            timeout=http_timeout,
        )

    def drain(self, *, timeout: float = 60.0) -> dict:
        """GET /test/jobs/drain — long-poll until all jobs are terminal.

        Useful for test teardown: call drain before making final assertions
        to ensure no background jobs are still running.
        """
        http_timeout = timeout + 5.0
        return self._get(
            "/test/jobs/drain",
            params={"timeout": timeout},
            timeout=http_timeout,
        )
