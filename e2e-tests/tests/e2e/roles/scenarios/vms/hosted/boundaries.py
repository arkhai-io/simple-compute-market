from __future__ import annotations

import importlib
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_FORBIDDEN_CONFIG_TOKENS = frozenset(
    {
        "wallet",
        "chains",
        "rpc",
        "rpc_url",
        "chain_signer",
        "provider",
        "control_url",
        "webhook",
        "database",
        "administrator",
        "credential",
        "secret",
    }
)


class HostedBoundaryError(AssertionError):
    pass


def assert_wallet_free_config(path: Path) -> Mapping[str, Any]:
    """Validate the public, wallet-free hosted settlement profile."""

    with path.open("rb") as source:
        document = tomllib.load(source)
    forbidden: list[str] = []

    def visit(value: object, prefix: str) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                normalized = str(key).lower().replace("-", "_")
                current = f"{prefix}.{key}" if prefix else str(key)
                if normalized in _FORBIDDEN_CONFIG_TOKENS or any(
                    token in normalized for token in ("private_key", "api_key", "webhook_secret")
                ):
                    forbidden.append(current)
                visit(child, current)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{prefix}[{index}]")

    visit(document, "")
    if forbidden:
        raise HostedBoundaryError(
            "wallet-free hosted profile contains forbidden field(s): "
            + ", ".join(sorted(forbidden))
        )
    buyer_profile = document.get("BuyerProfile")
    settlement = document.get("Settlement")
    if not isinstance(buyer_profile, Mapping):
        raise HostedBoundaryError("hosted profile requires [BuyerProfile]")
    store_path = buyer_profile.get("store_path")
    if not isinstance(store_path, str) or not Path(store_path).is_absolute():
        raise HostedBoundaryError("hosted profile requires an absolute profile-store path")
    if not isinstance(settlement, Mapping):
        raise HostedBoundaryError("hosted profile requires [Settlement]")
    stripe = settlement.get("stripe")
    if not isinstance(stripe, Mapping) or stripe.get("enabled") is not True:
        raise HostedBoundaryError("hosted profile requires enabled [Settlement.stripe]")
    priority = settlement.get("priority")
    if not isinstance(priority, list) or "fiat.stripe.v1" not in priority:
        raise HostedBoundaryError(
            "hosted profile must select fiat.stripe.v1 in Settlement.priority"
        )
    return document


def assert_import_boundary(
    modules: tuple[str, ...],
    *,
    forbidden_prefixes: tuple[str, ...] = ("tests.support",),
) -> None:
    """Prove ordinary runtime imports do not load test-only collaborators."""

    before = frozenset(sys.modules)
    for module in modules:
        importlib.import_module(module)
    imported = frozenset(sys.modules).difference(before)
    leaked = sorted(
        name
        for name in imported
        if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes)
    )
    if leaked:
        raise HostedBoundaryError(
            "ordinary runtime import loaded test-only modules: " + ", ".join(leaked)
        )


def hosted_selection_requested(
    *,
    invocation_args: tuple[str, ...],
    marker_expression: str,
    environment_enabled: bool,
) -> bool:
    if environment_enabled or "e2e_hosted_stripe_test" in marker_expression:
        return True
    return any("hosted-stripe-test" in argument for argument in invocation_args)
