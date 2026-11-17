"""A relay definitions document's `enabled`, as the parser reads it.

Parsing reads nothing stored, so it is proved here. A listed relay is drained
through its entry's `enabled`, so a value that is not a YAML boolean is refused,
naming the entry, as a host entry's is, rather than coerced: a quoted "false"
read as true would leave the relay selling with no error.
"""

from __future__ import annotations

import pytest
import yaml

from compute_provisioning.relays import RelayDefinitionError, parse_relay_definitions


def _yaml(**overrides) -> str:
    entry = {
        "id": "site-a",
        "relay_addr": "10.0.0.9",
        "relay_port": 7000,
        "vm_port_range_start": 6100,
        "vm_port_range_count": 100,
        "grant_key_secret_key": "relay_grant_key",
    }
    entry.update(overrides)
    return yaml.safe_dump({"relays": [entry]})


@pytest.mark.parametrize(
    "value", ["false", "no", 0, None], ids=["quoted-false", "quoted-no", "zero", "null"]
)
def test_a_non_boolean_enabled_is_refused_naming_the_entry(value) -> None:
    with pytest.raises(RelayDefinitionError) as excinfo:
        parse_relay_definitions(_yaml(enabled=value))
    message = str(excinfo.value)
    assert "relays[0]" in message and "'site-a'" in message
    assert "enabled" in message


@pytest.mark.parametrize("value", [True, False])
def test_a_boolean_enabled_is_read_as_written(value) -> None:
    (definition,) = parse_relay_definitions(_yaml(enabled=value))
    assert definition.enabled is value


def test_an_entry_omitting_enabled_is_enabled() -> None:
    (definition,) = parse_relay_definitions(_yaml())
    assert definition.enabled is True
