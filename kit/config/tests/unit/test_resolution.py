from __future__ import annotations

import ast
from pathlib import Path

import pytest
from market_config import (
    ConfigLayer,
    ConfigResolutionError,
    model_surface,
    resolve_model,
)
from pydantic import BaseModel, ConfigDict, Field, SecretStr


class MechanismPolicy(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    priority: list[str] = []
    request_secret: SecretStr | None = Field(
        default=None,
        json_schema_extra={"secret": True, "environment": "MARKET_REQUEST_SECRET"},
    )
    seller_account: str | None = Field(
        default=None,
        json_schema_extra={"roles": ["seller"]},
    )


class EndpointConfig(BaseModel):
    url: str
    retries: int = 1


class RoleConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    endpoints: dict[str, EndpointConfig] = Field(default_factory=dict)

    settlement: MechanismPolicy = Field(default_factory=MechanismPolicy)
    label: str = "default"


def test_higher_lists_replace_lower_lists_and_sources_are_safe() -> None:
    secret = "never-report-this-value"

    resolved = resolve_model(
        RoleConfig,
        defaults={"settlement": {"priority": ["default.v1"]}},
        toml={
            "settlement": {"enabled": True, "priority": ["toml-a.v1", "toml-b.v1"]},
            "label": "toml",
        },
        secrets={"settlement": {"request_secret": secret}},
        environment={"settlement": {"priority": ["environment-only.v1"]}},
        cli={"label": "cli"},
        role="buyer",
    )

    assert resolved.value.settlement.priority == ["environment-only.v1"]
    assert resolved.value.label == "cli"
    assert resolved.sources["settlement.priority"].layer is ConfigLayer.ENVIRONMENT
    assert resolved.sources["label"].layer is ConfigLayer.CLI
    assert resolved.sources["settlement.request_secret"].secret is True
    assert secret not in repr(resolved.source_projection())
    assert (
        resolved.redacted_projection()["settlement"]["request_secret"] == "<redacted>"
    )
    assert "request_secret" not in resolved.public_projection()["settlement"]
    assert secret not in resolved.public_fingerprint()


def test_unknown_keys_are_rejected_even_when_model_would_ignore_them() -> None:
    with pytest.raises(ConfigResolutionError, match="unknown settlement keys"):
        resolve_model(
            RoleConfig,
            toml={"settlement": {"enabled": True, "provider_admin_secret": "bad"}},
            role="seller",
        )


def test_role_inapplicable_fields_and_unsafe_secret_sources_fail() -> None:
    with pytest.raises(ConfigResolutionError, match="does not apply to role 'buyer'"):
        resolve_model(
            RoleConfig,
            toml={"settlement": {"seller_account": "seller-main"}},
            role="buyer",
        )
    with pytest.raises(
        ConfigResolutionError, match=r"secret field.*cannot come from toml"
    ):
        resolve_model(
            RoleConfig,
            toml={"settlement": {"request_secret": "ordinary-file-secret"}},
            role="seller",
        )


def test_environment_and_secret_overlap_at_same_tier_fails() -> None:
    with pytest.raises(ConfigResolutionError, match="same-precedence fields"):
        resolve_model(
            RoleConfig,
            secrets={"settlement": {"request_secret": "secret-file"}},
            environment={"settlement": {"request_secret": "environment"}},
            role="seller",
        )


def test_model_surface_is_role_specific_and_secret_aware() -> None:
    buyer_public = model_surface(RoleConfig, role="buyer")
    buyer_all = model_surface(RoleConfig, role="buyer", include_secrets=True)
    seller_public = model_surface(RoleConfig, role="seller")

    assert "settlement.request_secret" not in {field.path for field in buyer_public}
    assert "settlement.request_secret" in {field.path for field in buyer_all}
    assert "settlement.seller_account" not in {field.path for field in buyer_all}
    assert "settlement.seller_account" in {field.path for field in seller_public}
    priority = next(
        field for field in buyer_public if field.path == "settlement.priority"
    )
    assert priority.list_replaces is True
    secret_field = next(
        field for field in buyer_all if field.path == "settlement.request_secret"
    )
    assert secret_field.environment == "MARKET_REQUEST_SECRET"
    assert secret_field.safe_projection()["default"] is None


def test_dynamic_nested_models_are_strict_and_report_dotted_sources() -> None:
    resolved = resolve_model(
        RoleConfig,
        toml={"endpoints": {"primary": {"url": "https://public.example"}}},
        role="buyer",
    )

    assert resolved.value.endpoints["primary"].url == "https://public.example"
    assert resolved.sources["endpoints.primary.url"].layer is ConfigLayer.TOML
    surface_paths = {field.path for field in model_surface(RoleConfig, role="buyer")}
    assert "endpoints.*.url" in surface_paths
    with pytest.raises(ConfigResolutionError, match=r"unknown endpoints\.primary keys"):
        resolve_model(
            RoleConfig,
            toml={
                "endpoints": {"primary": {"url": "https://public.example", "typo": 1}}
            },
            role="buyer",
        )


def test_common_config_has_no_concrete_mechanism_imports() -> None:
    package = Path(__file__).parents[2] / "src" / "market_config"
    forbidden = {"market_alkahest", "market_hosted_settlement", "stripe", "web3"}
    imports: list[tuple[str, int, str]] = []
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name.split(".", 1)[0] in forbidden:
                    imports.append((path.name, node.lineno, name))
    assert imports == []
