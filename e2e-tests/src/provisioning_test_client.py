"""Synchronous HTTP client for the provisioning service test controller.

This client is **test infrastructure only** — it targets the ``/test/*``
endpoints that are only mounted when ``ACTIVE_PROFILES`` includes ``mock``.
It is intentionally separate from the canonical ``SyncProvisioningClient``
because the test controller is not part of the provisioning service's
public API contract.

Usage::

    client = ProvisioningTestClient(
        "http://provisioning:8081",
        signer=admin_signer,
        expected_authorities=provisioning_trust,
    )

    # Add a rule that pauses before returning
    client.add_mock_rule(
        rule_id="pause-create",
        match={"vm_action": "create", "vm_host": "kvm1"},
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
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from compute_provisioning import (
    canonical_provisioning_request_body,
    resolve_provisioning_route_contract,
)
from market_identity import (
    EMPTY_BODY,
    AuthenticatedResponse,
    Identity,
    RequestEnvelope,
    SignatureProof,
    Signer,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_request,
    verify_response,
)

SIGNATURE_VERSION_HEADER = "X-Market-Signature-Version"
IDENTITY_SCHEME_HEADER = "X-Market-Identity-Scheme"
IDENTITY_IDENTIFIER_HEADER = "X-Market-Identity-Identifier"
ROLE_HEADER = "X-Market-Role"
REQUEST_ID_HEADER = "X-Market-Request-ID"
TIMESTAMP_HEADER = "X-Market-Timestamp"
SIGNATURE_HEADER = "X-Market-Signature"

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
    signer:
        Signer for the principal the provisioning service trusts in the role
        each route requires. The ``/test/*`` routes sit behind the same
        authenticated route contract as the rest of the API — their operations
        are administrator operations — so each request is signed per caller
        rather than presenting a shared secret.
    expected_authorities:
        The provisioning service's own signing principal, so responses are
        verified as well as requests.
    """

    def __init__(
        self,
        base_url: str,
        *,
        signer: Signer,
        expected_authorities: TrustedIdentitySet,
        timeout: float = 15.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._signer = signer
        self._expected_authorities = expected_authorities
        self._client = httpx.Client(base_url=self._base, timeout=timeout)

    # ------------------------------------------------------------------
    # Request authentication
    # ------------------------------------------------------------------

    def _signed(
        self,
        method: str,
        path: str,
        *,
        body: Any = EMPTY_BODY,
        query: dict[str, Any] | None = None,
    ) -> tuple[dict[str, str], str, str, str]:
        """Build v2 authentication headers for one request.

        The operation, resource, and required role all come from the shared
        route contract rather than being restated here, so this client cannot
        drift from the table the service authorizes against. Query values are
        stringified because that is how they reach the service, and the signed
        body must match what the service recomputes.
        """
        contract, resource = resolve_provisioning_route_contract(
            method, path, body if body is not EMPTY_BODY else EMPTY_BODY
        )
        canonical_query = {
            key: str(value) for key, value in (query or {}).items() if value is not None
        }
        canonical = canonical_provisioning_request_body(
            method, path, body, query=canonical_query
        )
        request_id = uuid.uuid4().hex
        authenticated = sign_request(
            signer=self._signer,
            envelope=RequestEnvelope(
                role=contract.required_role,
                principal=self._signer.identity,
                method=method.upper(),
                operation=contract.operation,
                resource=resource,
                request_id=request_id,
                timestamp=int(datetime.now(timezone.utc).timestamp()),
                body_hash=canonical_body_hash(canonical),
            ),
        )
        return {
            SIGNATURE_VERSION_HEADER: authenticated.protocol,
            IDENTITY_SCHEME_HEADER: authenticated.principal.scheme.value,
            IDENTITY_IDENTIFIER_HEADER: authenticated.principal.identifier,
            ROLE_HEADER: authenticated.role,
            REQUEST_ID_HEADER: authenticated.request_id,
            TIMESTAMP_HEADER: str(authenticated.timestamp),
            SIGNATURE_HEADER: authenticated.proof.value,
        }, request_id, contract.operation, resource

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
        headers, request_id, operation, resource = self._signed(
            "GET", path, query=params
        )
        resp = self._client.get(
            path,
            params={k: str(v) for k, v in (params or {}).items()},
            timeout=timeout or self._timeout,
            headers=headers,
        )
        body = self._verify(
            resp, method="GET", operation=operation,
            resource=resource, request_id=request_id,
        )
        if resp.status_code >= 400:
            raise ProvisioningTestClientError(
                f"GET {self._base}{path} returned {resp.status_code}: {resp.text[:200]}"
            )
        return body

    def _post(self, path: str, body: dict | None = None) -> dict:
        payload = body if body is not None else {}
        headers, request_id, operation, resource = self._signed(
            "POST", path, body=payload
        )
        resp = self._client.post(
            path, json=payload, timeout=self._timeout, headers=headers
        )
        body = self._verify(
            resp, method="POST", operation=operation,
            resource=resource, request_id=request_id,
        )
        if resp.status_code >= 400:
            raise ProvisioningTestClientError(
                f"POST {self._base}{path} returned {resp.status_code}: {resp.text[:200]}"
            )
        return body

    def _delete(self, path: str) -> dict:
        headers, request_id, operation, resource = self._signed("DELETE", path)
        resp = self._client.delete(path, timeout=self._timeout, headers=headers)
        body = self._verify(
            resp, method="DELETE", operation=operation,
            resource=resource, request_id=request_id,
        )
        if resp.status_code >= 400:
            raise ProvisioningTestClientError(
                f"DELETE {self._base}{path} returned {resp.status_code}: {resp.text[:200]}"
            )
        return body

    def _verify(
        self,
        resp: httpx.Response,
        *,
        method: str,
        operation: str,
        resource: str,
        request_id: str,
    ) -> Any:
        """Verify the service's response proof before reading the body.

        A refusal is authenticated too, so this runs before the status check:
        an unverified 4xx is not trustworthy evidence about why the call failed.
        """
        body = resp.json() if resp.content else EMPTY_BODY
        try:
            principal = Identity(
                scheme=resp.headers[IDENTITY_SCHEME_HEADER],
                identifier=resp.headers[IDENTITY_IDENTIFIER_HEADER],
            )
            authenticated = AuthenticatedResponse(
                protocol=resp.headers[SIGNATURE_VERSION_HEADER],
                role=resp.headers[ROLE_HEADER],
                principal=principal,
                method=method,
                operation=operation,
                resource=resource,
                request_id=resp.headers[REQUEST_ID_HEADER],
                timestamp=int(resp.headers[TIMESTAMP_HEADER]),
                status=resp.status_code,
                body_hash=canonical_body_hash(body),
                proof=SignatureProof(
                    scheme=principal.scheme,
                    value=resp.headers[SIGNATURE_HEADER],
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProvisioningTestClientError(
                f"{method} {self._base}{resp.request.url.path} returned "
                f"{resp.status_code} without usable response authentication"
            ) from exc
        result = verify_response(
            authenticated,
            body=body,
            now=int(datetime.now(timezone.utc).timestamp()),
            expected_role="service",
            expected_principals=self._expected_authorities,
            expected_method=method,
            expected_operation=operation,
            expected_resource=resource,
            expected_request_id=request_id,
        )
        if not result.verified:
            raise ProvisioningTestClientError(
                f"{method} {self._base}{resp.request.url.path} response failed "
                f"verification: {getattr(result, 'reason', 'unverified')}"
            )
        return body

    def run_lease_cycle(self) -> dict:
        """Run one production lease-lifecycle cycle."""
        return self._post("/api/v1/system/check-leases")

    def run_fulfillment_convergence_cycle(self) -> dict:
        """Run one production fulfillment-convergence cycle."""
        return self._post("/api/v1/system/fulfillment-convergence/run-cycle")

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

    def evaluate_job(
        self,
        host: str,
        *,
        vm_target: str = "eval-target",
        ssh_pubkey: str | None = None,
        vm_action: str = "create",
    ) -> dict:
        """POST /test/evaluate-job — dry-run job evaluation.

        Returns a dict with:
          params_valid: bool
          host_exists: bool
          rule_matched: str | None  — rule_id of the first matching mock rule
          would_pause: bool         — True when the matched rule has pause_before_result
          errors: list[str]

        Use this in e2e stage 9a to confirm the provisioning gate is correctly
        armed before calling POST /api/v1/settle/{uid}.
        """
        body: dict[str, Any] = {
            "host": host,
            "vm_target": vm_target,
            "vm_action": vm_action,
        }
        if ssh_pubkey is not None:
            body["ssh_pubkey"] = ssh_pubkey
        return self._post("/test/evaluate-job", body)

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


