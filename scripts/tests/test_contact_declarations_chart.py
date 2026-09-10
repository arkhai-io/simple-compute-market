"""Explicit file-publication enrollment at the Helm boundary."""

import copy
import json
import shutil
import subprocess
from pathlib import Path

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "helm/charts/bare-metal-storefront"
# Public deterministic fixtures; these are not deployment credentials or hosts.
PUBLICATION = {
    "configMap": {"name": "test-public-declarations", "key": "declarations.json"},
    "registry": {
        "url": "https://registry.example.invalid",
        "authority": "test-registry",
        "principals": [{"scheme": "ed25519", "identifier": "A" * 43}],
        "apiKeySecret": {"name": "test-registry-write", "key": "api-key"},
    },
}
DELIVERY = {"name": "test-private-delivery", "key": "delivery.json"}
# Kubernetes cannot address these object names or data keys, so the general hook
# refuses them instead of rendering an unusable ConfigMap/Secret reference. The
# long values sit one character either side of the 253-character limit.
MALFORMED_NAMES = ("INVALID NAME", "Uppercase", "-leading", "trailing-", "under_score",
                   ".".join(["a" * 63] * 3 + ["b" * 63]))
MALFORMED_KEYS = ("../file", "bad key", "nested/key", "k" * 254)
# Reserved data keys: the pod projects a key as a file name, so Kubernetes rejects
# exactly "." and anything starting with ".." even though every character is legal
# (apimachinery IsConfigMapKey via hasChDirPrefix). Only a leading ".." is reserved,
# so a single leading dot or an embedded double dot stays valid.
RESERVED_KEYS = (".", "..", "...", "..declarations", "..hidden.json")
UNUSABLE_KEYS = MALFORMED_KEYS + RESERVED_KEYS
VALID_NAMES = ("a", "test-declarations.public-0", ".".join(["a" * 63] * 3 + ["b" * 61]))
VALID_KEYS = ("k", ".hidden", "declarations..json", "Declarations_v3.public-0.json",
              "k" * 253)
# Reference field, and the rendered volume and name attribute it feeds.
REFERENCES = (
    (("configMap",), "contact-offers", "configMap", "name"),
    (("registry", "apiKeySecret"), "contact-registry-key", "secret", "secretName"),
)


def render(tmp_path, values, chart=CHART):
    path = tmp_path / "values.json"
    path.write_text(json.dumps(values))
    return subprocess.run(
        ["helm", "template", "test", str(chart), "--values", str(path)],
        capture_output=True, text=True, check=False,
    )


def publication_with(path, attribute, value):
    publication = copy.deepcopy(PUBLICATION)
    reference = publication
    for key in path:
        reference = reference[key]
    reference[attribute] = value
    return publication


def validate(values):
    defaults = yaml.safe_load((CHART / "values.yaml").read_text())
    defaults.update(values)
    jsonschema.Draft7Validator(
        json.loads((CHART / "values.schema.json").read_text())
    ).validate(defaults)


@pytest.mark.parametrize("existing_claim", ["", "test-existing-data"])
def test_general_hook_reuses_publication_wiring_and_independent_delivery(tmp_path, existing_claim):
    for delivery in (None, DELIVERY):
        values = {"contactDeclarations": PUBLICATION, "deliveryConfigSecret": delivery}
        if existing_claim:
            values["persistence"] = {
                **yaml.safe_load((CHART / "values.yaml").read_text())["persistence"],
                "enabled": False, "existingClaim": existing_claim,
            }
        validate(values)
        result = render(tmp_path, values)
        assert result.returncode == 0, result.stderr
        legacy_values = {key: value for key, value in values.items() if key != "contactDeclarations"}
        legacy = render(tmp_path, {**legacy_values, "contactOffers": PUBLICATION})
        assert legacy.returncode == 0, legacy.stderr
        # The mode selects only the startup loader; all other bytes are identical.
        assert result.stdout == legacy.stdout.replace("CONTACT_OFFERS_PATH", "CONTACT_DECLARATIONS_PATH")
        objects = list(yaml.safe_load_all(result.stdout))
        assert {obj["kind"] for obj in objects} <= {"Deployment", "Service", "PersistentVolumeClaim", "Pod"}
        deployment = next(obj for obj in objects if obj["kind"] == "Deployment")
        pod = deployment["spec"]["template"]["spec"]
        container = pod["containers"][0]
        env = {entry["name"]: entry for entry in container["env"]}
        assert "BARE_METAL_STOREFRONT_CONTACT_OFFERS_PATH" not in env
        assert "BARE_METAL_STOREFRONT_SITES" not in env
        mounts = {mount["name"]: mount for mount in container["volumeMounts"]}
        volumes = {volume["name"]: volume for volume in pod["volumes"]}
        for volume_name, source, env_name in (
            ("contact-offers", "configMap", "BARE_METAL_STOREFRONT_CONTACT_DECLARATIONS_PATH"),
            ("contact-registry-key", "secret", "BARE_METAL_STOREFRONT_REGISTRY_API_KEY_FILE"),
        ):
            assert mounts[volume_name]["readOnly"] is True
            projection = volumes[volume_name][source]
            assert env[env_name]["value"] == str(Path(mounts[volume_name]["mountPath"]) / projection["items"][0]["path"])
        assert volumes["contact-offers"]["configMap"] == {
            "name": PUBLICATION["configMap"]["name"],
            "items": [{"key": PUBLICATION["configMap"]["key"], "path": "offers.json"}],
        }
        assert volumes["contact-registry-key"]["secret"] == {
            "secretName": PUBLICATION["registry"]["apiKeySecret"]["name"],
            "defaultMode": 0o440,
            "items": [{"key": "api-key", "path": "api-key"}],
        }
        assert container["command"][:2] == ["bare-metal-storefront", "serve"]
        assert container["startupProbe"]["failureThreshold"] == 100
        assert deployment["spec"]["replicas"] == 1
        assert deployment["spec"]["strategy"] == {"type": "Recreate"}
        delivery_entry = env.get("BARE_METAL_STOREFRONT_DELIVERY")
        assert delivery_entry == (None if delivery is None else {
            "name": "BARE_METAL_STOREFRONT_DELIVERY", "valueFrom": {"secretKeyRef": delivery},
        })
        assert "contact_payload" not in result.stdout
        assert "smtp" not in result.stdout


def test_default_hooks_do_not_enroll_publication(tmp_path):
    defaults = yaml.safe_load((CHART / "values.yaml").read_text())
    assert defaults["contactOffers"] is defaults["contactDeclarations"] is None
    result = render(tmp_path, {})
    assert result.returncode == 0, result.stderr
    assert "CONTACT_DECLARATIONS_PATH" not in result.stdout
    assert "CONTACT_OFFERS_PATH" not in result.stdout
    assert "BARE_METAL_STOREFRONT_SITES" in result.stdout
    assert "failureThreshold: 30" in result.stdout


def invalid_values():
    yield {"contactDeclarations": PUBLICATION, "contactOffers": PUBLICATION}
    yield {"contactDeclarations": {}}
    yield {"contactDeclarations": "declarations.json"}
    for path in (("configMap",), ("registry",), ("configMap", "name"), ("configMap", "key"),
                 ("registry", "url"), ("registry", "authority"), ("registry", "principals"),
                 ("registry", "apiKeySecret"), ("registry", "apiKeySecret", "name"),
                 ("registry", "apiKeySecret", "key")):
        value = copy.deepcopy(PUBLICATION)
        parent = value
        for key in path[:-1]:
            parent = parent[key]
        del parent[path[-1]]
        yield {"contactDeclarations": copy.deepcopy(value)}
        parent[path[-1]] = ""
        yield {"contactDeclarations": value}
    for path, _, _, _ in REFERENCES:
        for attribute, unusable in (("name", MALFORMED_NAMES), ("key", UNUSABLE_KEYS)):
            for value in unusable:
                yield {"contactDeclarations": publication_with(path, attribute, value)}
    for field in ("declaration", "contact_payload", "seller_route", "password"):
        yield {"contactDeclarations": {**PUBLICATION, field: "TEST-PRIVATE-CANARY"}}
    yield {"contactDeclarations": PUBLICATION, "alkahestEnabled": True}
    yield {"contactDeclarations": PUBLICATION, "persistence": {"enabled": False, "existingClaim": ""}}
    for secret in ({}, {"name": "INVALID NAME", "key": "config"},
                   {"name": "test-delivery", "key": "../file"},
                   {**DELIVERY, "password": "TEST-PRIVATE-CANARY"}):
        yield {"contactDeclarations": PUBLICATION, "deliveryConfigSecret": secret}


@pytest.mark.parametrize("values", list(invalid_values()))
def test_invalid_general_configuration_refuses_schema_and_render(tmp_path, values):
    with pytest.raises(jsonschema.ValidationError):
        validate(values)
    result = render(tmp_path, values)
    assert result.returncode != 0
    assert not result.stdout


def test_conflicting_modes_fail_template_even_without_schema(tmp_path):
    chart = tmp_path / "chart"
    shutil.copytree(CHART, chart)
    (chart / "values.schema.json").unlink()
    result = render(tmp_path, {"contactOffers": PUBLICATION, "contactDeclarations": PUBLICATION}, chart)
    assert result.returncode != 0
    assert "mutually exclusive" in result.stderr
    assert not result.stdout


@pytest.mark.parametrize("path,volume,source,name_attribute", REFERENCES)
def test_valid_general_references_reach_the_rendered_manifest(tmp_path, path, volume, source, name_attribute):
    for attribute, values in (("name", VALID_NAMES), ("key", VALID_KEYS)):
        for value in values:
            publication = publication_with(path, attribute, value)
            validate({"contactDeclarations": publication})
            result = render(tmp_path, {"contactDeclarations": publication})
            assert result.returncode == 0, result.stderr
            deployment = next(obj for obj in yaml.safe_load_all(result.stdout) if obj["kind"] == "Deployment")
            projection = next(
                entry for entry in deployment["spec"]["template"]["spec"]["volumes"]
                if entry["name"] == volume
            )[source]
            rendered = projection[name_attribute] if attribute == "name" else projection["items"][0]["key"]
            assert rendered == value


@pytest.mark.parametrize("path", [reference[0] for reference in REFERENCES])
def test_historical_hook_keeps_its_existing_reference_checks(tmp_path, path):
    # The general hook's name/key constraints are deliberately not retroactive:
    # tightening contactOffers would refuse manifests that render today.
    for attribute, unusable in (("name", MALFORMED_NAMES), ("key", UNUSABLE_KEYS)):
        for value in unusable:
            values = {"contactOffers": publication_with(path, attribute, value)}
            validate(values)
            assert render(tmp_path, values).returncode == 0


@pytest.mark.parametrize("key", RESERVED_KEYS)
def test_delivery_reference_keeps_its_existing_acceptance(tmp_path, key):
    # Delivery shares the strict reference definition but not the general hook's
    # reserved-key overlay, so its acceptance is unchanged by that overlay.
    values = {"deliveryConfigSecret": {**DELIVERY, "key": key}}
    validate(values)
    assert render(tmp_path, values).returncode == 0
