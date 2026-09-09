"""The delivery hook admits only an optional main-container Secret reference."""

import json
import shutil
import subprocess
from pathlib import Path

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "helm/charts/bare-metal-storefront"


def values():
    return yaml.safe_load((CHART / "values.yaml").read_text())


@pytest.mark.parametrize(
    "secret", [None, {"name": "synthetic-contact-delivery", "key": "config.json"}]
)
def test_delivery_secret_schema_accepts_only_private_reference(secret):
    config = values()
    config["deliveryConfigSecret"] = secret
    jsonschema.Draft7Validator(
        json.loads((CHART / "values.schema.json").read_text())
    ).validate(config)


@pytest.mark.parametrize(
    "secret",
    [
        {},
        {"name": "", "key": "config"},
        {"name": "BAD NAME", "key": "config"},
        {"name": "safe", "key": "../file"},
        {"name": "safe", "key": "config", "password": "synthetic-canary"},
        {"name": "a" * 64, "key": "config"},
    ],
)
def test_delivery_secret_schema_rejects_malformed_or_plaintext_config(secret):
    config = values()
    config["deliveryConfigSecret"] = secret
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft7Validator(
            json.loads((CHART / "values.schema.json").read_text())
        ).validate(config)


def test_render_projects_delivery_only_into_main_runtime():
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is required for render validation")
    baseline = subprocess.check_output(
        [helm, "template", "synthetic", str(CHART)], text=True
    )
    assert "BARE_METAL_STOREFRONT_DELIVERY" not in baseline
    rendered = subprocess.check_output(
        [
            helm,
            "template",
            "synthetic",
            str(CHART),
            "--set",
            "deliveryConfigSecret.name=synthetic-contact-delivery",
            "--set",
            "deliveryConfigSecret.key=config",
        ],
        text=True,
    )
    resources = list(yaml.safe_load_all(rendered))
    deployment = next(r for r in resources if r and r["kind"] == "Deployment")
    env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    entry = next(e for e in env if e["name"] == "BARE_METAL_STOREFRONT_DELIVERY")
    assert entry == {
        "name": "BARE_METAL_STOREFRONT_DELIVERY",
        "valueFrom": {
            "secretKeyRef": {"name": "synthetic-contact-delivery", "key": "config"}
        },
    }
    env.remove(entry)
    assert list(yaml.safe_load_all(baseline)) == resources
