"""Rendered file references select the installed startup loaders, not a Helm parser."""

import asyncio
import copy
import json
import smtplib
import sqlite3
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from arkhai_bare_metal_storefront import contact_offers
from arkhai_bare_metal_storefront.contact_offers import (
    DECLARATION_NOTICE,
    DECLARATIONS_PATH_ENV,
    NOTICE,
    OFFERS_PATH_ENV,
    ContactPublicationError,
)
from arkhai_bare_metal_storefront.runtime import build_runtime_from_environment
from arkhai_bare_metal_storefront.server import _start_runtime, _stop_runtime
from market_contact_exchange.fixtures.delivery import DELIVERY_CONFIG, POLICY
from test_contact_only_runtime import CONFIG, SELLER
from test_contact_only_runtime import environment as environment

ROOT = Path(__file__).resolve().parents[4]
CHART = ROOT / "helm/charts/bare-metal-storefront"
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def fixture_document(version):
    name = "contact-declarations.json" if version == 3 else "contact-offers.json"
    document = json.loads((EXAMPLES / name).read_text())
    if version == 2:
        document["schema_version"] = 2
        document["delivery_policy"] = POLICY
        for offer in document["offers"]:
            offer["listing_id"] = offer["listing_id"].replace(
                "synthetic-contact-", "synthetic-contact-delivery-"
            )
    return document


def configure_rendered_environment(tmp_path, monkeypatch, environment, version):
    mode = "contactDeclarations" if version == 3 else "contactOffers"
    config = copy.deepcopy(CONFIG)
    config["contact"]["profiles"]["default"] = {
        "channel": "email", "terms": DECLARATION_NOTICE if version == 3 else NOTICE,
    }
    if version >= 2:
        config["contact"]["profiles"]["default"]["delivery_policy"] = POLICY
    if version == 3:
        config["contact"]["profiles"]["default"]["context_contract"] = "accepted-listing.v1"
    # Deterministic disposable Secret contents, never deployment credentials.
    secrets = {
        ("test-identity", "credential"): environment["ARKHAI_IDENTITY_CREDENTIAL"],
        ("test-settlement", "config"): json.dumps(config),
        ("test-delivery", "config"): json.dumps(DELIVERY_CONFIG),
        ("test-registry-write", "key"): "TEST-REGISTRY-WRITE-KEY-NEVER-LIVE",
    }
    document = json.dumps(fixture_document(version))
    values = {
        "identity": {"principal": SELLER.identity.model_dump(mode="json"),
                     "credentialSecret": {"name": "test-identity", "key": "credential"}},
        "adminPrincipals": json.loads(environment["BARE_METAL_STOREFRONT_ADMIN_IDENTITIES"]),
        "publicUrl": environment["BARE_METAL_STOREFRONT_PUBLIC_URL"],
        "databasePath": environment["BARE_METAL_STOREFRONT_DB_PATH"],
        "settlementConfigSecret": {"name": "test-settlement", "key": "config"},
        "deliveryConfigSecret": {"name": "test-delivery", "key": "config"} if version >= 2 else None,
        mode: {
            "configMap": {"name": "test-public-file", "key": "document.json"},
            "registry": {
                "url": "https://registry.example.invalid", "authority": "test-registry",
                "principals": [SELLER.identity.model_dump(mode="json")],
                "apiKeySecret": {"name": "test-registry-write", "key": "key"},
            },
        },
    }
    values_file = tmp_path / "values.json"
    values_file.write_text(json.dumps(values))
    rendered = subprocess.check_output(
        ["helm", "template", "test", str(CHART), "--values", str(values_file)], text=True,
    )
    for value in secrets.values():
        assert value not in rendered
    for value in (
        *config["contact"]["contact_payload"].values(),
        DELIVERY_CONFIG["seller_route"]["address"],
        *(value for value in DELIVERY_CONFIG["smtp"].values() if isinstance(value, str)),
    ):
        assert value not in rendered
    deployment = next(obj for obj in yaml.safe_load_all(rendered) if obj["kind"] == "Deployment")
    pod = deployment["spec"]["template"]["spec"]
    container = pod["containers"][0]
    mounts = {mount["name"]: mount for mount in container["volumeMounts"]}
    projected = {}
    for volume in pod["volumes"]:
        source = volume.get("configMap") or volume.get("secret")
        if source is None:
            continue
        mount = mounts[volume["name"]]
        assert mount["readOnly"]
        for item in source["items"]:
            target = tmp_path / volume["name"] / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if "configMap" in volume:
                assert (source["name"], item["key"]) == ("test-public-file", "document.json")
                target.write_text(document)
            else:
                target.write_text(secrets[(source["secretName"], item["key"])])
            projected[str(Path(mount["mountPath"]) / item["path"])] = str(target)
    for entry in container["env"]:
        if "valueFrom" in entry:
            ref = entry["valueFrom"]["secretKeyRef"]
            value = secrets[(ref["name"], ref["key"])]
        else:
            value = projected.get(entry["value"], entry["value"])
        monkeypatch.setenv(entry["name"], value)
    selected = DECLARATIONS_PATH_ENV if version == 3 else OFFERS_PATH_ENV
    other = OFFERS_PATH_ENV if version == 3 else DECLARATIONS_PATH_ENV
    assert selected in {entry["name"] for entry in container["env"]}
    assert other not in {entry["name"] for entry in container["env"]}
    assert "BARE_METAL_STOREFRONT_SITES" not in {entry["name"] for entry in container["env"]}
    return Path(projected["/etc/arkhai/contact-offers/offers.json"])


@pytest.fixture
def registry_boundary(monkeypatch):
    """Only external registry I/O is replaced; startup, parsing and intent stay real."""
    schema = yaml.safe_load((ROOT / "core/registry/filter-spec.yaml").read_text())
    published = []

    def publish(request):
        published.append(request)
        return {"listing_id": request.listing_id, "status": "open"}

    @contextmanager
    def registry(runtime):
        yield SimpleNamespace(
            get_filter_spec=lambda: SimpleNamespace(
                schema_id=schema["schema"]["id"], schema_version=schema["schema"]["version"],
                listing_shape=schema["listing_shape"],
            ),
            publish_listing=publish,
        )

    def forbidden_smtp(*args, **kwargs):
        pytest.fail("startup publication attempted SMTP")

    monkeypatch.setattr(contact_offers, "contact_registry", registry)
    monkeypatch.setattr(smtplib, "SMTP", forbidden_smtp)
    return published


async def start_and_stop(runtime):
    try:
        await _start_runtime(runtime)
    finally:
        await _stop_runtime(runtime)


@pytest.mark.parametrize("version", [1, 2, 3])
def test_rendered_hook_drives_actual_startup_loader(
    tmp_path, monkeypatch, environment, registry_boundary, version,
):
    configure_rendered_environment(tmp_path, monkeypatch, environment, version)
    runtime = build_runtime_from_environment()
    assert runtime.introduction_only
    assert runtime.site_bindings == ()
    assert runtime.capacity_client is runtime.fulfillment_client is None
    asyncio.run(start_and_stop(runtime))
    assert len(registry_boundary) == (6 if version == 3 else 5)
    for request in registry_boundary:
        binding = asyncio.run(runtime.db.load_listing_binding(listing_id=request.listing_id))
        assert binding.site_id is binding.pool_id is binding.physical_resource_id is None
        intent = json.loads(binding.source_envelope_json)["publication_intent"]
        assert intent.get("schema_version", 1) == version
    with sqlite3.connect(runtime.db.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM negotiation_threads").fetchone()[0] == 0


@pytest.mark.parametrize("case", ["duplicate-key", "coercion", "legacy-file", "mixed-paths", "general-on-legacy"])
def test_rendered_startup_refuses_invalid_or_mixed_files_before_publication(
    tmp_path, monkeypatch, environment, registry_boundary, case,
):
    version = 1 if case == "general-on-legacy" else 3
    path = configure_rendered_environment(tmp_path, monkeypatch, environment, version)
    if case == "duplicate-key":
        path.write_text(path.read_text().replace('"schema_version": 3', '"schema_version": 3, "schema_version": 3', 1))
    elif case == "coercion":
        value = fixture_document(3)
        value["schema_version"] = "3"
        path.write_text(json.dumps(value))
    elif case == "legacy-file":
        path.write_text(json.dumps(fixture_document(1)))
    elif case == "general-on-legacy":
        path.write_text(json.dumps(fixture_document(3)))
    else:
        monkeypatch.setenv(OFFERS_PATH_ENV, str(path))
    runtime = build_runtime_from_environment()
    with pytest.raises(RuntimeError) as error:
        asyncio.run(start_and_stop(runtime))
    if case == "general-on-legacy":
        assert str(error.value) == "contact publication: invalid offer file"
    else:
        assert isinstance(error.value, ContactPublicationError)
        assert error.value.stage == ("conflicting_publication_paths" if case == "mixed-paths" else "invalid_declaration_file")
    assert registry_boundary == []
    with sqlite3.connect(runtime.db.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 0
