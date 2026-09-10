"""Installed seller publication against the real signed registry and seller HTTP apps."""

from __future__ import annotations

import asyncio
import base64
import copy
import json
import os
import selectors
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import uvicorn
from arkhai_bare_metal import BareMetalProvisionTerms
from arkhai_bare_metal_storefront.cli import app as cli_app
from arkhai_bare_metal_storefront.contact_offers import (
    DECLARATION_NOTICE,
    DECLARATIONS_PATH_ENV,
    NOTICE,
    OFFERS_PATH_ENV,
    ContactPublicationError,
    contact_registry,
    load_contact_offers,
    load_contact_declarations,
    reconcile_contact_declarations,
    reconcile_contact_offers,
)
from arkhai_bare_metal_storefront.contact_context import (
    context_digest,
    listing_binding_digest,
    validate_accepted_contact_context,
)
from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.runtime import build_runtime_from_environment
from arkhai_bare_metal_storefront.server import (
    build_bare_metal_storefront_app,
    build_bare_metal_storefront_registry,
)
from fastapi.testclient import TestClient
from core_buyer.introductions import IntroductionTransport
from core_buyer.negotiation_client import load_buyer_chain, negotiate_with_seller
from market_contact_exchange import validate_contact_payload
from market_contact_exchange.fixtures.delivery import DELIVERY_CONFIG, POLICY
from market_core.schemas import SettlementSelection, derive_settlement_option_id
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_settlement_runtime import derive_obligation_ref
from registry_client import ListingRequest
from typer.testing import CliRunner

# Deterministic synthetic test-only keys and bearer value. NEVER deploy live.
SELLER_SEED = bytes([17]) * 32
SELLER = Ed25519Signer(SELLER_SEED)
BUYER = Ed25519Signer(bytes([34]) * 32)
OUTSIDER = Ed25519Signer(bytes([68]) * 32)
WRITE_KEY = "synthetic-contact-write-key-never-live"
CONTACT = {"email": "synthetic-seller@example.invalid"}


@contextmanager
def serve(application, *, lifespan="on", before_start=None):
    ready = threading.Event()

    class ReadyServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            ready.set()

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        if before_start is not None:
            before_start(url)
        server = ReadyServer(uvicorn.Config(application, log_level="error", lifespan=lifespan, ws="none"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            assert ready.wait(15) and server.started
            yield url
        finally:
            server.should_exit = True
            thread.join(10)
            assert not thread.is_alive()


@contextmanager
def registry_process(tmp_path, signer):
    root = Path(__file__).resolve().parents[4]
    directory = root / "core/registry"
    python = Path(os.environ.get("REGISTRY_TEST_PYTHON", directory / ".venv/bin/python"))
    if not python.exists():
        pytest.skip("initialize the registry's independent locked environment")
    credential = tmp_path / "registry-credential"
    credential.write_text(base64.urlsafe_b64encode(bytes([99]) * 32).rstrip(b"=").decode())
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("REGISTRY_") and key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}}
    env.update({
        "DATABASE_URL": f"sqlite:///{tmp_path / 'registry.db'}",
        "REGISTRY_AUTHORITY_ID": "test-registry",
        "REGISTRY_AUTHORITY_SCHEME": "ed25519",
        "REGISTRY_AUTHORITY_IDENTIFIER": signer.identity.identifier,
        "REGISTRY_AUTHORITY_CREDENTIAL_FILE": str(credential),
        "REGISTRY_DESCRIPTOR_BASE_URL": url,
        "REGISTRY_DESCRIPTOR_DISPLAY_NAME": "Synthetic registry",
        "REGISTRY_DESCRIPTOR_OPERATOR_IDENTITY": "synthetic-test-operator",
        "REGISTRY_BOOTSTRAP_API_KEY": WRITE_KEY,
        "REGISTRY_REQUIRE_WRITE_API_KEY": "true",
        "REGISTRY_REQUIRE_READ_API_KEY": "false",
        "REGISTRY_FILTER_SPEC_PATH": str(directory / "filter-spec.yaml"),
    })
    process = subprocess.Popen(
        [str(python), "-m", "uvicorn", "src.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=directory, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    output = ""
    deadline = time.monotonic() + 20
    try:
        while "Uvicorn running" not in output:
            assert selector.select(max(0, deadline - time.monotonic())), output
            chunk = os.read(process.stdout.fileno(), 65536).decode()
            assert chunk, output
            output += chunk
        yield url
    finally:
        process.terminate()
        process.wait(timeout=10)
        selector.close()
        process.stdout.close()


def remote_count(runtime):
    with contact_registry(runtime) as client:
        return len(client.list_listings().listings)


@pytest.fixture
def publication_environment(tmp_path, monkeypatch):
    for key in tuple(os.environ):
        if key.startswith("BARE_METAL_") or key == "ARKHAI_IDENTITY_CREDENTIAL" or key.lower() in {"http_proxy", "https_proxy", "all_proxy"}:
            monkeypatch.delenv(key)
    key_file = tmp_path / "write-key"
    key_file.write_text(WRITE_KEY)
    offer_file = tmp_path / "offers.json"
    offer_file.write_bytes((Path(__file__).parents[1] / "examples/contact-offers.json").read_bytes())
    config = {
        "priority": ["contact-exchange.v1"],
        "contact": {"enabled": True, "contact_payload": CONTACT,
                    "profiles": {"default": {"channel": "email", "terms": NOTICE}}},
    }
    registry_authority = Ed25519Signer(bytes([99]) * 32)
    with registry_process(tmp_path, registry_authority) as registry_url:
        values = {
            "BARE_METAL_STOREFRONT_IDENTITY_SCHEME": "ed25519",
            "BARE_METAL_STOREFRONT_IDENTITY_IDENTIFIER": SELLER.identity.identifier,
            "ARKHAI_IDENTITY_CREDENTIAL": base64.urlsafe_b64encode(SELLER_SEED).rstrip(b"=").decode(),
            "BARE_METAL_STOREFRONT_ADMIN_IDENTITIES": json.dumps([BUYER.identity.model_dump(mode="json")]),
            "BARE_METAL_STOREFRONT_PUBLIC_URL": "http://127.0.0.1:8000",
            "BARE_METAL_STOREFRONT_DB_PATH": str(tmp_path / "seller.db"),
            "BARE_METAL_STOREFRONT_SETTLEMENT": json.dumps(config),
            "BARE_METAL_STOREFRONT_REGISTRY_URL": registry_url,
            "BARE_METAL_STOREFRONT_REGISTRY_AUTHORITY": "test-registry",
            "BARE_METAL_STOREFRONT_REGISTRY_PRINCIPALS": json.dumps([registry_authority.identity.model_dump(mode="json")]),
            "BARE_METAL_STOREFRONT_REGISTRY_API_KEY_FILE": str(key_file),
        }
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        yield offer_file, key_file, config


def reconcile(runtime, document, *, transport=None):
    with contact_registry(runtime, transport=transport) as client:
        return asyncio.run(reconcile_contact_offers(runtime, document, client))


class LostAcknowledgement(httpx.BaseTransport):
    def __init__(self, runtime):
        self.inner = httpx.HTTPTransport()
        self.runtime = runtime
        self.dropped = 0

    def handle_request(self, request):
        response = self.inner.handle_request(request)
        if request.method == "POST" and request.url.path == "/listings" and self.dropped < 3:
            assert asyncio.run(self.runtime.db.count_open_bare_metal_resources()) == 5
            assert response.status_code == 201
            response.close()
            self.dropped += 1
            raise httpx.ReadError("synthetic lost acknowledgement")
        return response

    def close(self):
        self.inner.close()


def test_contact_publication_lost_ack_restart_filters_and_immutable_intent(publication_environment):
    offer_file, _, _ = publication_environment
    document = load_contact_offers(offer_file)
    runtime = build_runtime_from_environment()
    lost = LostAcknowledgement(runtime)
    with pytest.raises(ContactPublicationError) as failure:
        reconcile(runtime, document, transport=lost)
    assert failure.value.confirmed == 0
    assert lost.dropped == 3
    assert remote_count(runtime) == 1

    restarted = build_runtime_from_environment()
    assert reconcile(restarted, document)["confirmed"] == 5
    assert reconcile(restarted, document)["confirmed"] == 5
    assert remote_count(runtime) == 5
    with contact_registry(restarted) as client:
        spec = client.get_filter_spec()
        assert (spec.version, spec.schema_id, spec.schema_version) == (4, "vms.compute", 1)
        selected = client.list_listings(etag=spec.etag, gpu_model="H100").listings
        assert [item.id for item in selected] == ["synthetic-contact-h100"]
        all_offers = client.list_listings().listings
        assert len(all_offers) == 5
        assert CONTACT["email"] not in str(all_offers)
        for item in all_offers:
            assert item.offer["kind"] == "bare_metal.v1"
            assert item.offer["virtualization_type"] == "bare_metal"
            assert item.offer["gpu_count"] > 0
            assert item.offer["vcpu_count"] > 0
            assert item.offer["ram_gb"] > 0
            assert item.offer["disk_gb"] > 0
            assert item.accepted_escrows == []
        client.publish_listing(ListingRequest(
            listing_id="unrelated-listing", offer={"gpu_model": "H100", "region": "test"},
            accepted_escrows=[], storefront_url=runtime.storefront_url,
        ))
    fewer = document.model_copy(update={"offers": document.offers[:4]})
    assert reconcile(restarted, fewer)["confirmed"] == 4
    assert remote_count(runtime) == 6
    changed = document.model_copy(update={"offers": [document.offers[0].model_copy(update={"gpu_count": 99})]})
    with pytest.raises(ContactPublicationError, match="immutable_intent_conflict"):
        reconcile(restarted, changed)
    asyncio.run(restarted.db.update_listing(listing_id=document.offers[0].listing_id, status="closed"))
    with pytest.raises(ContactPublicationError, match="local_offer_inactive"):
        reconcile(restarted, document)


def test_contact_publication_refuses_key_schema_and_contact_leaks(publication_environment, monkeypatch):
    offer_file, key_file, _ = publication_environment
    document = load_contact_offers(offer_file)
    runtime = build_runtime_from_environment()
    invalid = document.model_copy(update={"offers": document.offers[:-1] + [document.offers[-1].model_copy(update={"gpu_model": "NOT A GPU"})]})
    with pytest.raises(ContactPublicationError, match="registry_schema"):
        reconcile(runtime, invalid)
    assert asyncio.run(runtime.db.count_open_bare_metal_resources()) == 0
    leaked = document.model_copy(update={"offers": [document.offers[0].model_copy(update={"name": "SYNTHETIC TEST " + CONTACT["email"]})]})
    with pytest.raises(ContactPublicationError, match="private_contact_in_public_offer"):
        reconcile(runtime, leaked)
    key_file.write_text("synthetic-wrong-key")
    with pytest.raises(ContactPublicationError, match="registry_publish") as failure:
        reconcile(runtime, document)
    assert "synthetic-wrong-key" not in str(failure.value)
    assert CONTACT["email"] not in str(failure.value)
    assert remote_count(runtime) == 0
    key_file.write_text(WRITE_KEY)
    monkeypatch.setenv("BARE_METAL_STOREFRONT_REGISTRY_PRINCIPALS", json.dumps([OUTSIDER.identity.model_dump(mode="json")]))
    with pytest.raises(ContactPublicationError, match="registry_schema"):
        reconcile(runtime, document)


def introduction(url, signer):
    return IntroductionTransport(
        seller_url=url, principal=signer.identity, signer=signer,
        resolve_seller_principals=lambda: TrustedIdentitySet(identities=(SELLER.identity,)),
    )


def test_contact_offer_startup_negotiation_reveal_and_restart(publication_environment, monkeypatch):
    offer_file, _, config = publication_environment
    monkeypatch.setenv(OFFERS_PATH_ENV, str(offer_file))
    runtimes = []
    domain = get_market_domain_contract()

    def factory():
        runtime = build_runtime_from_environment(domain=domain)
        runtimes.append(runtime)
        return runtime

    def application():
        return build_bare_metal_storefront_app(
            registry=build_bare_metal_storefront_registry(domain=domain), runtime_factory=factory,
        )

    def bind_url(url):
        monkeypatch.setenv("BARE_METAL_STOREFRONT_PUBLIC_URL", url)

    with serve(application(), before_start=bind_url) as seller_url:
        runtime = runtimes[-1]
        with contact_registry(runtime) as registry:
            listing = registry.get_listing("synthetic-contact-h100")
            option = listing.settlement_options[0]
            outcome = negotiate_with_seller(
                seller_url=listing.storefront_url, principal=BUYER.identity, signer=BUYER,
                listing_id=listing.id,
                resolve_seller_principals=lambda: listing.publisher_principals,
                initial_price=None, max_price=None, unit_count=1,
                policy_params={"_selected_settlement_option": option},
                provision_terms=BareMetalProvisionTerms(payload={"duration_seconds": 3600, "access_method": "none"}),
                settlement_selection=SettlementSelection(
                    mechanism="contact-exchange.v1", option_id=option["option_id"], expiration_unix=int(time.time()) + 3600,
                ),
                chain=load_buyer_chain(policy_mode="listed_price"),
            )
            assert outcome.status == "agreed"
            plan = outcome.settlement_plan.model_dump(mode="json")
            ref = derive_obligation_ref(outcome.negotiation_id, 0, plan["obligations"][0])
            assert asyncio.run(runtime.db.load_contact_introduction(obligation_ref=ref)) is None
            reveal = introduction(seller_url, BUYER).start(
                negotiation_id=outcome.negotiation_id, obligation_ref=ref,
                contact_payload={"email": "synthetic-buyer@example.invalid"},
            )
            assert reveal["counterparty_contact"] == CONTACT
            with pytest.raises(RuntimeError, match="HTTP 403"):
                introduction(seller_url, OUTSIDER).read(obligation_ref=ref)
    config["contact"]["contact_payload"] = {"email": "changed@example.invalid"}
    monkeypatch.setenv("BARE_METAL_STOREFRONT_SETTLEMENT", json.dumps(config))
    with serve(application(), before_start=bind_url) as seller_url:
        restarted = runtimes[-1]
        with contact_registry(restarted) as registry:
            assert len(registry.list_listings().listings) == 5
            assert introduction(seller_url, BUYER).read(obligation_ref=ref) == reveal
            assert asyncio.run(restarted.settlement_runtime.get_status(outcome.negotiation_id)).status == "complete"
            assert restarted.capacity_client is restarted.fulfillment_client is None


def test_offer_file_and_packaged_command_validation(tmp_path, monkeypatch):
    source = Path(__file__).parents[1] / "examples/contact-offers.json"
    document = json.loads(source.read_text())
    document["offers"][1] = document["offers"][0]
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(document))
    with pytest.raises(RuntimeError, match="invalid offer file"):
        load_contact_offers(path)
    monkeypatch.delenv(OFFERS_PATH_ENV, raising=False)
    result = CliRunner().invoke(cli_app, ["publish-contacts"])
    assert result.exit_code == 1
    assert "offer_path_required" in result.output
    assert CliRunner().invoke(cli_app, ["publish-contacts", "--help"]).exit_code == 0


# Opaque synthetic test-only contacts, never real delivery destinations.
_CONTACT_CANARIES = {
    "unicode": "Zoë@example.invalid",
    "quote": 'quote"@example.invalid',
    "slash": "slash/@example.invalid",
    "backslash": "slash\\@example.invalid",
    "newline": "line\nbreak@example.invalid",
}


@pytest.mark.parametrize("placement,contact", [
    pytest.param(placement, contact, id=f"{placement}-{label}")
    for label, contact in _CONTACT_CANARIES.items()
    for placement in ("first_name", "last_name")
])
def test_full_file_refuses_escaped_contact_before_intent_or_publication(
    publication_environment, monkeypatch, contact, placement,
):
    offer_file, _, config = publication_environment
    contact_payload = validate_contact_payload({"email": contact})
    assert contact_payload["email"] == contact
    config["contact"]["contact_payload"] = contact_payload
    document = json.loads(offer_file.read_text())
    index = 0 if placement == "first_name" else -1
    contaminated = document["offers"][index]
    contaminated["name"] = "SYNTHETIC TEST " + contact
    offer_file.write_text(json.dumps(document))
    monkeypatch.setenv("BARE_METAL_STOREFRONT_SETTLEMENT", json.dumps(config))
    runtime = build_runtime_from_environment()
    loaded = load_contact_offers(offer_file)
    assert len(loaded.offers) == 5
    requests = []

    class RecordingTransport(httpx.HTTPTransport):
        def handle_request(self, request):
            requests.append(request.method)
            return super().handle_request(request)

    with contact_registry(runtime, transport=RecordingTransport()) as registry:
        with pytest.raises(ContactPublicationError) as rejected:
            asyncio.run(reconcile_contact_offers(runtime, loaded, registry))
    assert rejected.value.stage == "private_contact_in_public_offer"
    assert rejected.value.listing_id is None
    assert rejected.value.confirmed == 0
    assert contact not in str(rejected.value)
    assert requests == []
    with sqlite3.connect(runtime.db.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM storefront_listing_bindings").fetchone()[0] == 0
    assert remote_count(runtime) == 0


@pytest.fixture
def declaration_environment(publication_environment, monkeypatch):
    path, _, config = publication_environment
    path.write_bytes((Path(__file__).parents[1] / "examples/contact-declarations.json").read_bytes())
    config["contact"]["contact_payload"] = {"text": "TEST authored blurb without an invented contact method"}
    config["contact"]["profiles"]["default"] = {
        "channel": "email", "terms": DECLARATION_NOTICE,
        "delivery_policy": POLICY, "context_contract": "accepted-listing.v1",
    }
    monkeypatch.setenv("BARE_METAL_STOREFRONT_SETTLEMENT", json.dumps(config))
    monkeypatch.setenv("BARE_METAL_STOREFRONT_DELIVERY", json.dumps(DELIVERY_CONFIG))
    return path, config


class RecordingPublicationTransport(httpx.HTTPTransport):
    def __init__(self):
        super().__init__()
        self.methods = []

    def handle_request(self, request):
        self.methods.append(request.method)
        return super().handle_request(request)


def reconcile_declarations(runtime, document, *, transport=None):
    with contact_registry(runtime, transport=transport) as client:
        return asyncio.run(reconcile_contact_declarations(runtime, document, client))


def publication_rows(runtime):
    with sqlite3.connect(runtime.db.db_path) as conn:
        return tuple(conn.execute(f"SELECT * FROM {table} ORDER BY listing_id").fetchall()
                     for table in ("listings", "storefront_listing_bindings"))


def test_general_declarations_installed_command_and_exact_signed_discovery(declaration_environment):
    path, config = declaration_environment
    command = Path(sys.executable).parent / "bare-metal-storefront"
    result = subprocess.run([str(command), "publish-declarations", "--offers", str(path)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["confirmed"] == 6
    runtime = build_runtime_from_environment()
    assert runtime.capacity_client is runtime.fulfillment_client is None
    assert runtime.site_bindings == ()
    document = load_contact_declarations(path)
    with contact_registry(runtime) as registry:
        spec = registry.get_filter_spec()
        assert (spec.version, spec.schema_id, spec.schema_version) == (4, "vms.compute", 1)
        remote = registry.list_listings().listings
        assert len(remote) == 6
        for entry in document.offers:
            listing = registry.get_listing(entry.declaration.listing_id)
            assert listing.offer["description"] == DECLARATION_NOTICE
            assert listing.offer["name"] == entry.declaration.name
            assert listing.offer["kind"] == "bare_metal.v1"
            assert listing.offer["virtualization_type"] == "bare_metal"
            assert listing.offer["access_methods"] == ["none"]
            assert "machine_id" not in listing.offer and "physical_host_id" not in listing.offer
            for field, value in entry.declaration.machine_details.model_dump().items():
                assert listing.offer[field] == value
            assert listing.accepted_escrows == []
            option, = listing.settlement_options
            assert option["mechanism"] == "contact-exchange.v1" and option["rates"] == []
            assert option["params"]["context_contract"] == "accepted-listing.v1"
            assert option["params"]["delivery_policy"] == POLICY
            binding = asyncio.run(runtime.db.load_listing_binding(listing_id=listing.id))
            assert binding.site_id is binding.pool_id is binding.physical_resource_id is None
            source = json.loads(binding.source_envelope_json)
            assert source["kind"] == "bare_metal.introduction-declaration.v1"
            assert source["declaration_id"] == entry.declaration.declaration_id
            assert source["publication_intent"] == {
                "schema_version": 3, "declaration": entry.declaration.model_dump(mode="json"),
                "settlement_options": [option],
            }
        assert len(registry.list_listings(etag=spec.etag, gpu_model="H100").listings) == 2
    public = str(publication_rows(runtime)) + str(remote) + result.stdout + result.stderr
    for value in [*config["contact"]["contact_payload"].values(),
                  DELIVERY_CONFIG["seller_route"]["address"], *DELIVERY_CONFIG["smtp"].values()]:
        if isinstance(value, str):
            assert value not in public


def test_general_invalid_tail_duplicates_bounds_and_profiles_before_writes(
    declaration_environment, monkeypatch,
):
    path, config = declaration_environment
    original = json.loads(path.read_text())
    runtime = build_runtime_from_environment()
    mutations = [
        lambda rows: rows[-1]["declaration"]["machine_details"].update(gpu_count=0),
        lambda rows: rows[-1]["declaration"].update(listing_id=rows[0]["declaration"]["listing_id"]),
        lambda rows: rows[-1]["declaration"].update(declaration_id=rows[0]["declaration"]["declaration_id"]),
        lambda rows: rows[-1]["declaration"].update(listing_id="synthetic-contact-h100"),
        lambda rows: rows[-1]["declaration"].update(machine_id="invented-machine"),
        lambda rows: rows[-1]["declaration"].update(contact_payload={"text": "private"}),
    ]
    for mutate in mutations:
        raw = copy.deepcopy(original)
        mutate(raw["offers"])
        path.write_text(json.dumps(raw))
        with pytest.raises(ContactPublicationError, match="invalid_declaration_file"):
            load_contact_declarations(path)
        assert publication_rows(runtime) == ([], [])
    for data in (b" " * 1048577, b'{"schema_version":3,"schema_version":3,"offers":[]}',
                 b'\xff', b'{"schema_version":NaN}', b'{"schema_version":2,"offers":[]}'):
        path.write_bytes(data)
        with pytest.raises(ContactPublicationError, match="invalid_declaration_file"):
            load_contact_declarations(path)
    for field, value, stage in (("gpu_model", "NOT A GPU", "registry_schema"),
                                ("profile", "missing", "declaration_profile_notice_required")):
        raw = copy.deepcopy(original)
        if field == "profile":
            raw["offers"][-1][field] = value
        else:
            raw["offers"][-1]["declaration"]["machine_details"][field] = value
        path.write_text(json.dumps(raw))
        transport = RecordingPublicationTransport()
        with pytest.raises(ContactPublicationError, match=stage):
            reconcile_declarations(runtime, load_contact_declarations(path), transport=transport)
        assert "POST" not in transport.methods
        assert publication_rows(runtime) == ([], [])
    path.write_text(json.dumps(original))
    for change, stage in (({"terms": "No notice"}, "declaration_profile_notice_required"),
                          ({"context_contract": None}, "context_profile_required")):
        candidate = copy.deepcopy(config)
        profile = candidate["contact"]["profiles"]["default"]
        if change.get("context_contract", "absent") is None:
            profile.pop("context_contract")
        else:
            profile.update(change)
        monkeypatch.setenv("BARE_METAL_STOREFRONT_SETTLEMENT", json.dumps(candidate))
        changed_runtime = build_runtime_from_environment()
        transport = RecordingPublicationTransport()
        with pytest.raises(ContactPublicationError, match=stage):
            reconcile_declarations(changed_runtime, load_contact_declarations(path), transport=transport)
        assert transport.methods == []
    without_contact = copy.deepcopy(config)
    without_contact["contact"].pop("contact_payload")
    monkeypatch.setenv("BARE_METAL_STOREFRONT_SETTLEMENT", json.dumps(without_contact))
    with pytest.raises(ContactPublicationError, match="contact_configuration_incomplete"):
        reconcile_declarations(build_runtime_from_environment(), load_contact_declarations(path))
    monkeypatch.setenv("BARE_METAL_STOREFRONT_SETTLEMENT", json.dumps(config))
    monkeypatch.delenv("BARE_METAL_STOREFRONT_DELIVERY")
    with pytest.raises(ContactPublicationError, match="delivery_configuration_unavailable"):
        reconcile_declarations(build_runtime_from_environment(), load_contact_declarations(path))
    assert publication_rows(runtime) == ([], [])
    assert remote_count(runtime) == 0


def test_general_private_literals_anywhere_in_last_declaration(declaration_environment):
    path, config = declaration_environment
    original = json.loads(path.read_text())
    runtime = build_runtime_from_environment()
    values = [*config["contact"]["contact_payload"].values(), DELIVERY_CONFIG["seller_route"]["address"],
              *(v for v in DELIVERY_CONFIG["smtp"].values() if isinstance(v, str))]
    for value in values:
        raw = copy.deepcopy(original)
        raw["offers"][-1]["declaration"]["name"] = "TEST " + value
        path.write_text(json.dumps(raw))
        transport = RecordingPublicationTransport()
        with pytest.raises(ContactPublicationError) as rejected:
            reconcile_declarations(runtime, load_contact_declarations(path), transport=transport)
        assert rejected.value.stage == "private_contact_in_public_offer"
        assert value not in str(rejected.value)
        assert rejected.value.listing_id is None and rejected.value.confirmed == 0
        assert transport.methods == []
        assert publication_rows(runtime) == ([], [])
    assert remote_count(runtime) == 0


class LostDeclarationAcknowledgement(RecordingPublicationTransport):
    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime
        self.dropped = 0

    def handle_request(self, request):
        response = super().handle_request(request)
        if request.method == "POST":
            assert len(publication_rows(self.runtime)[0]) == 6
            if json.loads(request.content)["listing_id"] == "declared-contact-test-2":
                assert response.status_code == 201
                response.close()
                self.dropped += 1
                raise httpx.ReadError("TEST lost acknowledgement")
        return response


def test_general_partial_remote_effect_restart_immutable_and_omitted_ids(declaration_environment):
    path, _ = declaration_environment
    runtime = build_runtime_from_environment()
    document = load_contact_declarations(path)
    transport = LostDeclarationAcknowledgement(runtime)
    with pytest.raises(ContactPublicationError) as rejected:
        reconcile_declarations(runtime, document, transport=transport)
    assert rejected.value.confirmed == 1 and transport.dropped == 3
    assert "uncertain" in str(rejected.value)
    assert remote_count(runtime) == 2
    rows = publication_rows(runtime)
    restarted = build_runtime_from_environment()
    assert reconcile_declarations(restarted, document)["confirmed"] == 6
    assert reconcile_declarations(restarted, document)["confirmed"] == 6
    assert publication_rows(restarted) == rows
    assert remote_count(restarted) == 6
    raw = document.model_dump(mode="json")
    raw["offers"][-1]["declaration"]["machine_details"]["gpu_count"] += 1
    path.write_text(json.dumps(raw))
    transport = RecordingPublicationTransport()
    with pytest.raises(ContactPublicationError, match="immutable_intent_conflict"):
        reconcile_declarations(restarted, load_contact_declarations(path), transport=transport)
    assert "POST" not in transport.methods and publication_rows(restarted) == rows
    raw["offers"] = raw["offers"][:1]
    path.write_text(json.dumps(raw))
    assert reconcile_declarations(restarted, load_contact_declarations(path))["confirmed"] == 1
    assert remote_count(restarted) == 6
    asyncio.run(restarted.db.update_listing(listing_id=document.offers[-1].declaration.listing_id, status="closed"))
    transport = RecordingPublicationTransport()
    with pytest.raises(ContactPublicationError, match="local_offer_inactive"):
        reconcile_declarations(restarted, document, transport=transport)
    assert "POST" not in transport.methods


def test_general_existing_legacy_intent_collision_refuses_whole_file(declaration_environment):
    path, _ = declaration_environment
    runtime = build_runtime_from_environment()
    document = load_contact_declarations(path)
    historical = load_contact_offers(Path(__file__).parents[1] / "examples/contact-offers.json")
    # Persistence-only fixture: no API admits an old publication under a general ID.
    option = {
        "mechanism": "contact-exchange.v1", "asset": "introduction", "rates": [],
        "params": {"profile": "legacy", "channel": "email", "terms": NOTICE},
    }
    option["option_id"] = derive_settlement_option_id(**option)
    asyncio.run(runtime.db.upsert_bare_metal_listing(
        listing_id=document.offers[-1].declaration.listing_id,
        status="open", created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
        seller_principal=runtime.seller_principal, storefront_url=runtime.storefront_url,
        listing=historical.offers[0].listing(), accepted_escrows=[],
        settlement_options=[option], site_id=None, pool_id=None, physical_resource_id=None,
        publication_intent={"offer": historical.offers[0].registry_offer(), "settlement_options": [option]},
    ))
    before = publication_rows(runtime)
    transport = RecordingPublicationTransport()
    with pytest.raises(ContactPublicationError, match="immutable_intent_conflict"):
        reconcile_declarations(runtime, document, transport=transport)
    assert "POST" not in transport.methods
    assert publication_rows(runtime) == before
    assert remote_count(runtime) == 0


def test_general_startup_opt_in_and_conflicting_paths(declaration_environment, monkeypatch):
    path, _ = declaration_environment
    domain = get_market_domain_contract()
    runtimes = []

    def factory():
        runtime = build_runtime_from_environment(domain=domain)
        runtimes.append(runtime)
        return runtime

    def application():
        return build_bare_metal_storefront_app(
            registry=build_bare_metal_storefront_registry(domain=domain), runtime_factory=factory,
        )

    with serve(application(), before_start=lambda url: monkeypatch.setenv("BARE_METAL_STOREFRONT_PUBLIC_URL", url)):
        assert remote_count(runtimes[-1]) == 0
        assert publication_rows(runtimes[-1]) == ([], [])
    monkeypatch.setenv(DECLARATIONS_PATH_ENV, str(path))
    monkeypatch.setenv(OFFERS_PATH_ENV, str(path))
    # Real lifespan refusal must happen before either file can publish.
    with pytest.raises(ContactPublicationError, match="conflicting_publication_paths"):
        with TestClient(application()):
            pytest.fail("conflicting startup paths served HTTP")
    assert publication_rows(runtimes[-1]) == ([], [])
    assert remote_count(runtimes[-1]) == 0
    monkeypatch.delenv(OFFERS_PATH_ENV)
    with serve(application(), before_start=lambda url: monkeypatch.setenv("BARE_METAL_STOREFRONT_PUBLIC_URL", url)):
        assert remote_count(runtimes[-1]) == 6
        runtime = runtimes[-1]
        rows = publication_rows(runtime)
        with contact_registry(runtime) as registry:
            listing = registry.get_listing("declared-contact-test-1")
        option, = listing.settlement_options
        declaration = load_contact_declarations(path).offers[0].declaration.model_dump(mode="json")
        binding = asyncio.run(runtime.db.load_listing_binding(listing_id=listing.id))
        source = json.loads(binding.source_envelope_json)
        expected_context = {
            "schema_version": 1, "discovery_schema": "vms.compute", "negotiation_schema": "bare_metal.v1",
            "declaration": declaration,
            "accepted_terms": {"duration_seconds": 3600, "access_method": "none"},
            "option_id": option["option_id"],
            "publication_intent_digest": context_digest(source["publication_intent"]),
            "source_envelope_digest": context_digest(source),
            "listing_binding_digest": listing_binding_digest(binding),
        }
        expected_params = {
            **option["params"], "payer_principal": BUYER.identity.model_dump(mode="json"),
            "accepted_context_digest": context_digest(expected_context),
        }
        expected_package = {
            **{key: option["params"][key] for key in (
                "profile", "channel", "terms", "delivery_policy", "context_contract",
            )},
            "option_id": option["option_id"], "listing_id": listing.id,
            "accepted_context": expected_context,
        }

        def validate_advertised_plan(plan):
            # A test-owned adapter checks retained advertised semantics independently
            # of the seller's response; internal digest consistency alone is not enough.
            validate_accepted_contact_context(plan)
            assert plan.obligations[0].params == expected_params
            assert plan.obligations[0].conditions == []
            assert plan.service_terms == {"contact-exchange.v1": expected_package}

        request = dict(
            seller_url=listing.storefront_url, principal=BUYER.identity, signer=BUYER,
            listing_id=listing.id, resolve_seller_principals=lambda: listing.publisher_principals,
            initial_price=None, max_price=None, unit_count=1,
            policy_params={"_selected_settlement_option": option},
            provision_terms=BareMetalProvisionTerms(payload={"duration_seconds": 3600, "access_method": "none"}),
            settlement_selection=SettlementSelection(
                mechanism="contact-exchange.v1", option_id=option["option_id"],
                expiration_unix=int(time.time()) + 3600,
            ),
            chain=load_buyer_chain(policy_mode="listed_price"),
        )
        with pytest.raises(RuntimeError, match="params differ from the advertised option"):
            negotiate_with_seller(**request)
        outcome = negotiate_with_seller(**request, validate_advertised_plan=validate_advertised_plan)
        assert outcome.status == "agreed"
        context = outcome.settlement_plan.service_terms["contact-exchange.v1"]["accepted_context"]
        assert context["declaration"] == load_contact_declarations(path).offers[0].declaration.model_dump(mode="json")
        assert context["accepted_terms"] == {"duration_seconds": 3600, "access_method": "none"}
        assert "accepted_context_digest" in outcome.settlement_plan.obligations[0].params
        ref = derive_obligation_ref(outcome.negotiation_id, 0, outcome.settlement_plan.obligations[0].model_dump(mode="json"))
        assert asyncio.run(runtime.db.load_contact_introduction(obligation_ref=ref)) is None
    with serve(application(), before_start=lambda url: monkeypatch.setenv("BARE_METAL_STOREFRONT_PUBLIC_URL", url)):
        assert remote_count(runtimes[-1]) == 6
        assert publication_rows(runtimes[-1]) == rows


def test_general_signed_schema_trust_refusal_before_intent(declaration_environment, monkeypatch):
    path, _ = declaration_environment
    runtime = build_runtime_from_environment()
    monkeypatch.setenv("BARE_METAL_STOREFRONT_REGISTRY_PRINCIPALS", json.dumps([OUTSIDER.identity.model_dump(mode="json")]))
    transport = RecordingPublicationTransport()
    with pytest.raises(ContactPublicationError, match="registry_schema"):
        reconcile_declarations(runtime, load_contact_declarations(path), transport=transport)
    assert transport.methods and "POST" not in transport.methods
    assert publication_rows(runtime) == ([], [])
