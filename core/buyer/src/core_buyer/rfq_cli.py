"""Terminal commands for the shared account-authorized RFQ operations."""

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
import json
import os
from pathlib import Path
from typing import Annotated, Literal, Never, TypeVar

import typer
from market_config.config_loader import get_dotted, load_user_config
from market_core import MarketDomainContract
from market_core.registry_descriptor import RegistryPrincipal
from market_core.rfq import (
    CloseRfq, CreateRfq, EditRfq, OfferResponse, ResponseVersion, RfqAccountRequest, RfqAudience, RfqContact, RfqDetail,
    RfqInput, RfqInputContract, RfqOperation, RfqTarget, SearchRfqs, ShareContact,
)
from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError
from registry_client.rfq_account import RfqAccountError, SyncRfqAccountClient

from core_buyer.registry_config import (
    resolve_discovery_timeout,
    resolve_indexer_urls,
    resolve_registry_authorities,
)

_JsonFile = Annotated[Path, typer.Option(help="JSON file containing the operation input.")]
_OptionalJsonFile = Annotated[Path | None, typer.Option(help="Optional JSON input file.")]
_RequestId = Annotated[str | None, typer.Option(help="Stable identifier for this operation.")]
_ContactFile = Annotated[
    Path | None, typer.Option(help="Read a chosen contact from a JSON file before confirming."),
]
_ShareInputs = Annotated[
    Path | None, typer.Option("--inputs", help="Send a complete, explicitly consented RFQ account request as JSON."),
]
_CONTACT = TypeAdapter(RfqContact)
_Version = Annotated[int, typer.Option("--version", help="Expected record version.")]
_Input = TypeVar("_Input", bound=RfqInput)


def _json_file(path: Path | None, *, code: str = "rfq_invalid_input_file") -> dict[str, JsonValue]:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        _action_error(code)
    if not isinstance(value, dict):
        _action_error(code)
    return value


def _emit(result: BaseModel) -> None:
    typer.echo(result.model_dump_json(exclude_none=True))


def _action_error(code: str, request_id: str | None = None) -> Never:
    result = {"code": code}
    if request_id is not None:
        result["request_id"] = request_id
    typer.echo(json.dumps(result), err=True)
    raise typer.Exit(1)


def _inputs(model: type[_Input], **fields: object) -> _Input:
    try:
        return model.model_validate(fields)
    except ValidationError:
        _action_error("rfq_invalid_inputs")


def _target(
    operation: RfqOperation, rfq_id: str | None = None, response_id: str | None = None,
    *, introduction_id: str | None = None,
) -> RfqTarget:
    try:
        return RfqTarget(operation, rfq_id, response_id, introduction_id)
    except ValueError:
        _action_error("rfq_invalid_target")


def _submit_consented_action(
    client: SyncRfqAccountClient,
    target: RfqTarget,
    audience: RfqAudience,
    path: Path,
    model: type[ShareContact],
) -> None:
    try:
        request = RfqAccountRequest.model_validate(_json_file(path, code="rfq_invalid_action_inputs"))
    except ValidationError:
        _action_error("rfq_invalid_action_inputs")
    if request.registry != audience:
        _action_error("rfq_action_registry_mismatch", request.request_id)
    try:
        payload = model.model_validate(request.inputs)
    except ValidationError:
        _action_error("rfq_invalid_action_inputs", request.request_id)
    _emit(client.exchange(target, payload, request_id=request.request_id))


def _confirmed_contact(
    request: RfqDetail, party: str, path: Path | None, *, version: int, offer: dict[str, JsonValue],
) -> dict[str, str]:
    chosen = _json_file(path, code="rfq_invalid_contact") if path else {
        "email": typer.prompt("Contact email", hide_input=True, err=True),
    }
    try:
        contact = _CONTACT.validate_python(chosen, strict=True)
    except ValidationError:
        _action_error("rfq_invalid_contact")
    typer.echo(
        f"Registry {request.registry.name} "
        f"({request.registry.principal.scheme}:{request.registry.principal.identifier})"
        f"\nRFQ {request.rfq_id}, terms revision {request.terms_revision}, record version {version}"
        f"\nRequirements {json.dumps(request.requirements, ensure_ascii=True)}"
        f"\nOffer {json.dumps(offer, ensure_ascii=True)}"
        f"\nCounterparty {party}\nContact {json.dumps(contact, ensure_ascii=True)}",
        err=True,
    )
    if not typer.confirm("Share this contact with that party?", default=False, err=True):
        typer.echo("Contact sharing cancelled.", err=True)
        raise typer.Exit(1)
    return contact


def _configured_client(
    selected: str | None, principal: str | None, *, allow_public: bool,
) -> tuple[SyncRfqAccountClient, RfqAudience]:
    urls = resolve_indexer_urls()
    authorities = resolve_registry_authorities(urls)
    registry_url = selected.rstrip("/") if selected else (urls[0] if len(urls) == 1 else None)
    if registry_url is None or registry_url not in authorities:
        raise ValueError("select one configured registry using --registry")
    registry = authorities[registry_url]
    pins = tuple(
        identity for identity in registry.principals.identities
        if principal is None or principal == f"{identity.scheme.value}:{identity.identifier}"
    )
    if len(pins) != 1:
        raise ValueError("select one configured registry signer using --principal")
    audience = RfqAudience(
        name=registry.authority,
        principal=RegistryPrincipal.model_validate(pins[0].model_dump(mode="json")),
    )
    origin = get_dotted(load_user_config(), "rfq.account_origin")
    credential = os.environ.get("ARKHAI_RFQ_ACCOUNT_TOKEN") or None
    if not isinstance(origin, str):
        raise ValueError("set rfq.account_origin to the account service")
    if credential is None and not allow_public:
        raise ValueError("set a scoped ARKHAI_RFQ_ACCOUNT_TOKEN for this operation")
    return SyncRfqAccountClient(
        origin, credential=credential, registry=audience, timeout=resolve_discovery_timeout(),
    ), audience


def build_rfq_app(domains: Sequence[MarketDomainContract]) -> typer.Typer:
    contracts: dict[str, RfqInputContract] = {}
    for domain in domains:
        for declared in getattr(domain.buyer, "rfq_inputs", ()):
            existing = contracts.setdefault(declared.kind, declared)
            if existing != declared:
                raise ValueError(f"conflicting buyer RFQ inputs for {declared.kind!r}")

    app = typer.Typer(no_args_is_help=True, help="Post, discover and respond to requests for quotes.")

    @app.callback()
    def initialize(
        ctx: typer.Context,
        registry: Annotated[str | None, typer.Option(help="Select a configured registry URL.")] = None,
        principal: Annotated[str | None, typer.Option(help="Exact scheme:identifier during signer rotation.")] = None,
    ) -> None:
        ctx.obj = (registry, principal)

    @contextmanager
    def connect(
        ctx: typer.Context, *, allow_public: bool = False,
    ) -> Iterator[tuple[SyncRfqAccountClient, RfqAudience]]:
        selected, principal = ctx.obj
        try:
            configured, audience = _configured_client(selected, principal, allow_public=allow_public)
            with configured as client:
                yield client, audience
        except RfqAccountError as error:
            _action_error(error.code, error.request_id)
        except typer.Exit:
            raise
        except (ValueError, RuntimeError):
            _action_error("rfq_client_configuration_invalid")

    def validated(
        kind: str, area: Literal["requirements", "filters", "offer"], body: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        contract = contracts.get(kind)
        if contract is None:
            _action_error("rfq_kind_not_installed")
        validate: Callable[[object], object] = getattr(contract, area)
        try:
            validate(body)
        except ValueError:
            _action_error("rfq_invalid_inputs")
        return body

    def send(
        ctx: typer.Context, target: RfqTarget, args: RfqInput, request_id: str | None = None,
    ) -> None:
        open_discovery = target.operation in {RfqOperation.SEARCH, RfqOperation.READ}
        with connect(ctx, allow_public=open_discovery) as (client, _):
            _emit(client.exchange(target, args, request_id=request_id))

    @app.command("create")
    def create(ctx: typer.Context, kind: str, inputs: _JsonFile, request_id: _RequestId = None) -> None:
        send(ctx, _target(RfqOperation.CREATE), _inputs(CreateRfq,
            kind=kind, requirements=validated(kind, "requirements", _json_file(inputs)),
        ), request_id)

    @app.command("search")
    def search(ctx: typer.Context, kind: str, inputs: _OptionalJsonFile = None, cursor: str | None = None) -> None:
        send(ctx, _target(RfqOperation.SEARCH), _inputs(SearchRfqs,
            kind=kind, filters=validated(kind, "filters", _json_file(inputs)), cursor=cursor,
        ))

    @app.command("show")
    def show(ctx: typer.Context, rfq_id: str) -> None:
        send(ctx, _target(RfqOperation.READ, rfq_id), RfqInput())

    @app.command("edit")
    def edit(ctx: typer.Context, rfq_id: str, inputs: _JsonFile, version: _Version, request_id: _RequestId = None) -> None:
        with connect(ctx) as (client, _):
            rfq = client.read_detail(rfq_id)
            payload = _inputs(EditRfq,
                version=version, requirements=validated(rfq.kind, "requirements", _json_file(inputs)),
            )
            _emit(client.exchange(_target(RfqOperation.EDIT, rfq_id), payload, request_id=request_id))

    @app.command("close")
    def close(ctx: typer.Context, rfq_id: str, version: _Version, request_id: _RequestId = None) -> None:
        send(ctx, _target(RfqOperation.CLOSE, rfq_id), _inputs(CloseRfq, version=version), request_id)

    def respond_to(
        ctx: typer.Context, rfq_id: str, offer_file: Path | None, request_id: str | None,
        contact_file: Path | None, action_file: Path | None, response_id: str | None = None,
    ) -> None:
        operation = RfqOperation.RESPOND if response_id is None else RfqOperation.RECONFIRM
        target = _target(operation, rfq_id, response_id)
        if action_file is not None and (offer_file is not None or contact_file is not None or request_id is not None):
            _action_error("rfq_conflicting_action_inputs")
        with connect(ctx) as (client, audience):
            if action_file is not None:
                _submit_consented_action(client, target, audience, action_file, OfferResponse)
                return
            request = client.read_detail(rfq_id)
            offer = validated(request.kind, "offer", _json_file(offer_file))
            version = request.version
            if response_id is not None:
                previous = client.read_response(rfq_id, response_id)
                version = previous.version
            contact = _confirmed_contact(
                request, request.buyer_reference, contact_file, version=version, offer=offer,
            )
            payload = OfferResponse(
                version=version, terms_revision=request.terms_revision, counterparty=request.buyer_reference,
                consent_to_share=True, contact=contact, offer=offer,
            )
            _emit(client.exchange(target, payload, request_id=request_id))

    @app.command("respond")
    def respond(
        ctx: typer.Context, rfq_id: str, offer: _OptionalJsonFile = None,
        request_id: _RequestId = None, contact_file: _ContactFile = None, action_file: _ShareInputs = None,
    ) -> None:
        respond_to(ctx, rfq_id, offer, request_id, contact_file, action_file)

    @app.command("reconfirm")
    def reconfirm(
        ctx: typer.Context, rfq_id: str, response_id: str,
        offer: _OptionalJsonFile = None, request_id: _RequestId = None, contact_file: _ContactFile = None,
        action_file: _ShareInputs = None,
    ) -> None:
        respond_to(ctx, rfq_id, offer, request_id, contact_file, action_file, response_id)

    @app.command("responses")
    def responses(ctx: typer.Context, rfq_id: str) -> None:
        send(ctx, _target(RfqOperation.LIST_RESPONSES, rfq_id), RfqInput())

    @app.command("show-response")
    def show_response(ctx: typer.Context, rfq_id: str, response_id: str) -> None:
        send(ctx, _target(RfqOperation.READ_RESPONSE, rfq_id, response_id), RfqInput())

    @app.command("withdraw")
    def withdraw(ctx: typer.Context, rfq_id: str, response_id: str, version: _Version, request_id: _RequestId = None) -> None:
        send(ctx, _target(RfqOperation.WITHDRAW, rfq_id, response_id), _inputs(ResponseVersion, version=version), request_id)

    @app.command("dismiss")
    def dismiss(ctx: typer.Context, rfq_id: str, response_id: str, version: _Version, request_id: _RequestId = None) -> None:
        send(ctx, _target(RfqOperation.DISMISS, rfq_id, response_id), _inputs(ResponseVersion, version=version), request_id)

    @app.command("select")
    def select(
        ctx: typer.Context, rfq_id: str, response_id: str,
        request_id: _RequestId = None, contact_file: _ContactFile = None, action_file: _ShareInputs = None,
    ) -> None:
        target = _target(RfqOperation.SELECT, rfq_id, response_id)
        if action_file is not None and (contact_file is not None or request_id is not None):
            _action_error("rfq_conflicting_action_inputs")
        with connect(ctx) as (client, audience):
            if action_file is not None:
                _submit_consented_action(client, target, audience, action_file, ShareContact)
                return
            response = client.read_response(rfq_id, response_id)
            request = client.read_detail(rfq_id)
            if request.terms_revision != response.terms_revision:
                _action_error("stale_rfq_terms", request_id)
            offer: dict[str, JsonValue] = {} if response.offered_quantity is None else {
                "offered_quantity": response.offered_quantity,
            }
            contact = _confirmed_contact(
                request, response.respondent_reference, contact_file, version=response.version, offer=offer,
            )
            payload = ShareContact(
                version=response.version, terms_revision=response.terms_revision,
                counterparty=response.respondent_reference, consent_to_share=True, contact=contact,
            )
            _emit(client.exchange(target, payload, request_id=request_id))

    @app.command("show-introduction")
    def show_introduction(ctx: typer.Context, introduction_id: str, request_id: _RequestId = None) -> None:
        send(
            ctx, _target(RfqOperation.READ_INTRODUCTION, introduction_id=introduction_id), RfqInput(), request_id,
        )

    @app.command("end-introduction")
    def end_introduction(
        ctx: typer.Context, introduction_id: str, version: _Version, request_id: _RequestId = None,
    ) -> None:
        send(
            ctx, _target(RfqOperation.END_INTRODUCTION, introduction_id=introduction_id),
            _inputs(ResponseVersion, version=version), request_id,
        )

    return app
