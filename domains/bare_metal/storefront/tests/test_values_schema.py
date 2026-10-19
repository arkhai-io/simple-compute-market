"""The bare-metal chart's values schema carries the definition its typed models generate.

The definition keeps secret-marked fields out of the chart's pass-through
``config`` and closes every typed section, so a key the storefront does not read
is refused where the configuration is written. These tests fail when the
committed schema is stale, so a model or registration change cannot reach the
chart without regenerating it (``make helm-values-schema``). The generator's own
rules are tested with ``market_config.values_schema``; these cover the
definition the bare-metal storefront's settings produce. The chart's render
tests assert what Helm then refuses and accepts.
"""

from __future__ import annotations

from pathlib import Path

from market_config.values_schema import any_case, stale_files
from market_delivery import RESERVED_SECTION_KEYS

from arkhai_bare_metal_storefront import values_schema
from arkhai_bare_metal_storefront.config import BareMetalStorefrontSettings

REPO = Path(__file__).resolve().parents[4]
SCHEMAS = tuple(REPO / relative for relative in values_schema.SCHEMA_FILES)


def _field(node: dict, name: str):
    """A field's schema, keyed by the any-case pattern for ``name``."""
    return node["patternProperties"][any_case(name)]


def _allowed(node: dict, *names: str) -> bool:
    patterns = {p for p, schema in node["patternProperties"].items() if schema is not False}
    return patterns == {any_case(n) for n in names}


def _walk(node):
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def test_the_committed_values_schema_carries_the_generated_definition() -> None:
    definition = values_schema.storefront_config_definition()
    stale = stale_files(SCHEMAS, definition, name=values_schema.DEFINITION)
    assert not stale, f"regenerate with `make helm-values-schema`: {[str(p) for p in stale]}"


def test_the_command_checks_the_schema_file_the_storefront_names() -> None:
    """The command ``make helm-values-schema`` runs finds the one file the
    storefront names, its own chart's, under the repository root it is given."""
    assert values_schema.SCHEMA_FILES == ("helm/charts/bare-metal-storefront/values.schema.json",)
    assert values_schema.main(["check", "--root", str(REPO)]) == 0


def test_the_document_is_closed_to_the_settings_the_storefront_reads() -> None:
    definition = values_schema.storefront_config_definition()

    assert definition["additionalProperties"] is False
    assert _allowed(definition, *BareMetalStorefrontSettings.model_fields)
    for section in ("Identity", "registry", "capacity", "pricing", "negotiation", "Wallet"):
        assert _field(definition, section)["additionalProperties"] is False, section
    peer = _field(_field(definition, "Identity"), "service_peers")["additionalProperties"]
    assert peer["additionalProperties"] is False
    assert _allowed(peer, "role", "site_id", "principals")
    chain = _field(definition, "Chains")["additionalProperties"]
    assert chain["additionalProperties"] is False
    assert _allowed(chain, "rpc_url", "chain_id", "alkahest_address_config_path")


def test_the_wallet_key_is_refused_and_the_registry_takes_no_write_token() -> None:
    definition = values_schema.storefront_config_definition()

    wallet = _field(definition, "Wallet")
    assert _field(wallet, "private_key") is False
    assert _allowed(wallet, "address")
    assert _allowed(_field(definition, "registry"), "urls", "authorities")


def test_the_durations_carry_their_bounds_from_the_shared_type() -> None:
    capacity = _field(values_schema.storefront_config_definition(), "capacity")

    poll = _field(capacity, "poll_interval")
    assert poll["type"] == "number"
    assert poll["exclusiveMinimum"] == 0
    assert poll["maximum"] > 0


def test_settlement_is_closed_to_the_registered_mechanisms() -> None:
    settlement = _field(values_schema.storefront_config_definition(), "Settlement")

    assert settlement["additionalProperties"] is False
    assert _allowed(
        settlement, "schema_version", "priority", "alkahest", "arkhai_payments", "contact"
    )


def test_delivery_states_the_kits_own_settings_and_types_installed_sinks() -> None:
    delivery = _field(values_schema.storefront_config_definition(), "Delivery")

    assert set(values_schema.DELIVERY_SETTINGS) == RESERVED_SECTION_KEYS
    for name in RESERVED_SECTION_KEYS:
        assert _field(delivery, name) is not False
    for sink in ("apprise", "file", "smtp", "webhook"):
        assert _field(delivery, sink)["additionalProperties"] is False


def test_the_definition_carries_no_defaults_references_or_markers() -> None:
    for node in _walk(values_schema.storefront_config_definition()):
        if isinstance(node, dict):
            assert not {"default", "$ref", "$defs", "secret", "required"} & set(node), node
