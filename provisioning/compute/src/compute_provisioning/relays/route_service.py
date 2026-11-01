"""The relay administration routes, without a web framework.

``RelayRouteService`` serves list, create, read, update, token rotation,
enable and disable, the holdings read, and grant-key staging and activation over
the relay service, reporting a refusal as a ``ProvisioningRouteError``. Every
relay route admits only the administrator: relays are operator infrastructure,
and no storefront administers them.

Deletion is deliberately absent. A relay carrying live port leases cannot
simply be removed: the proxies it carries outlive the row, and a deletion that
orphans leases loses the record of which ports on that rendezvous are bound.
Disable is the operator's answer to "stop using this relay".
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from compute_provisioning_contracts import (
    RelayCreate,
    RelayGrantKeyStage,
    RelayLeaseListResponse,
    RelayLeaseView,
    RelayListResponse,
    RelayResponse,
    RelayStagedGrantKey,
    RelayTokenRotate,
    RelayUpdate,
)
from pydantic import ValidationError

from ..route_errors import ProvisioningRouteError
from .rebinding import ManagementRouteRefused, RelayRebindingRefused
from .service import (
    UNSET,
    RelayEndpointConflictError,
    RelayGrantKeyNotStagedError,
    RelayNotFoundError,
    RelayService,
    RelayValidationError,
    RelayView,
)


def _response(view: RelayView) -> RelayResponse:
    """The wire model built from the service view.

    The view is the type that structurally cannot carry a token or a private
    key; this only renames it for the wire.
    """
    return RelayResponse(**asdict(view))


def _missing(relay_id: str) -> ProvisioningRouteError:
    return ProvisioningRouteError(404, f"Relay '{relay_id}' not found")


def _stage_request(payload: Any) -> RelayGrantKeyStage:
    """The stage request, or a 422 locating each problem without its input.

    An unknown field is located at the body alone: its name is caller input
    too, and a key pasted where a field name belongs would otherwise come back
    as the error's location.
    """
    try:
        return RelayGrantKeyStage.model_validate({} if payload is None else payload)
    except ValidationError as exc:
        problems = [
            {
                "loc": ["body"]
                if error["type"] == "extra_forbidden"
                else ["body", *error["loc"]],
                "msg": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors(
                include_url=False, include_context=False, include_input=False
            )
        ]
        raise ProvisioningRouteError(422, problems) from None


class RelayRouteService:
    def __init__(self, relays: RelayService) -> None:
        self._relays = relays

    def list_relays(self) -> RelayListResponse:
        return RelayListResponse(relays=[_response(v) for v in self._relays.list_relays()])

    def create_relay(self, body: RelayCreate) -> RelayResponse:
        try:
            view = self._relays.create_relay(
                relay_id=body.id,
                label=body.label,
                relay_addr=body.relay_addr,
                relay_port=body.relay_port,
                vm_port_range_start=body.vm_port_range_start,
                vm_port_range_count=body.vm_port_range_count,
                token=body.token,
                enabled=body.enabled,
            )
        except RelayEndpointConflictError as exc:
            raise ProvisioningRouteError(409, str(exc)) from exc
        except RelayValidationError as exc:
            raise ProvisioningRouteError(422, str(exc)) from exc
        return _response(view)

    def get_relay(self, relay_id: str) -> RelayResponse:
        try:
            return _response(self._relays.get_relay(relay_id))
        except RelayNotFoundError as exc:
            raise _missing(relay_id) from exc

    def update_relay(self, relay_id: str, body: RelayUpdate) -> RelayResponse:
        fields = body.model_dump(exclude_unset=True)
        try:
            view = self._relays.update_relay(
                relay_id,
                label=fields.get("label", UNSET),
                relay_addr=body.relay_addr,
                relay_port=body.relay_port,
                vm_port_range_start=body.vm_port_range_start,
                vm_port_range_count=body.vm_port_range_count,
            )
        except RelayNotFoundError as exc:
            raise _missing(relay_id) from exc
        except RelayEndpointConflictError as exc:
            raise ProvisioningRouteError(409, str(exc)) from exc
        except RelayRebindingRefused as exc:
            # 409, not 422: the request is well-formed and would be valid once
            # the relay is drained. The message carries the drain sequence, so
            # it must reach the caller rather than becoming a 500.
            raise ProvisioningRouteError(409, str(exc)) from exc
        except ManagementRouteRefused as exc:
            raise ProvisioningRouteError(409, str(exc)) from exc
        except RelayValidationError as exc:
            raise ProvisioningRouteError(422, str(exc)) from exc
        return _response(view)

    def rotate_token(self, relay_id: str, body: RelayTokenRotate) -> RelayResponse:
        try:
            view = self._relays.rotate_token(relay_id, body.token)
        except RelayNotFoundError as exc:
            raise _missing(relay_id) from exc
        except RelayRebindingRefused as exc:
            raise ProvisioningRouteError(409, str(exc)) from exc
        except RelayValidationError as exc:
            raise ProvisioningRouteError(422, str(exc)) from exc
        return _response(view)

    def set_enabled(self, relay_id: str, enabled: bool) -> RelayResponse:
        try:
            return _response(self._relays.set_enabled(relay_id, enabled))
        except RelayNotFoundError as exc:
            raise _missing(relay_id) from exc

    def list_leases(self, relay_id: str) -> RelayLeaseListResponse:
        """The relay's holdings: each lease's port, host, owner, and release."""
        try:
            records = self._relays.list_leases(relay_id)
        except RelayNotFoundError as exc:
            raise _missing(relay_id) from exc
        return RelayLeaseListResponse(
            relay_id=relay_id,
            leases=[RelayLeaseView(**record.__dict__) for record in records],
        )

    def stage_grant_key(self, relay_id: str, payload: Any) -> RelayStagedGrantKey:
        """Stage the relay's next grant key and answer its id and public half.

        ``payload`` is the request's decoded JSON body, validated here rather
        than by the binding: the framework's own validation answer quotes the
        input it refuses, and this input may be a private key. A malformed
        body, or a key the loader refuses, answers 422 saying what was wrong,
        never what was sent.
        """
        body = _stage_request(payload)
        supplied = (
            None if body.private_key is None else body.private_key.get_secret_value()
        )
        try:
            staged = self._relays.stage_grant_key(relay_id, supplied)
        except RelayNotFoundError as exc:
            raise _missing(relay_id) from exc
        except RelayValidationError as exc:
            raise ProvisioningRouteError(422, str(exc)) from None
        return RelayStagedGrantKey(kid=staged.kid, public_key=staged.public_key)

    def activate_grant_key(self, relay_id: str) -> RelayResponse:
        try:
            view = self._relays.activate_grant_key(relay_id)
        except RelayNotFoundError as exc:
            raise _missing(relay_id) from exc
        except RelayGrantKeyNotStagedError as exc:
            # 409: the request is well-formed, and is valid once a key is staged.
            raise ProvisioningRouteError(409, str(exc)) from exc
        return _response(view)


__all__ = ["RelayRouteService"]
