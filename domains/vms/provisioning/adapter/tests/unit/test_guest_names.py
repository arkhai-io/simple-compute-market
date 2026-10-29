"""The rules a guest name must satisfy, whoever chose it."""

from __future__ import annotations

import pytest

from vm_provisioning_adapter.guest_names import check_guest_name, fulfillment_guest_name


@pytest.mark.parametrize(
    "name",
    (
        "Agent-VM",  # upper case
        "agent_vm",  # an underscore
        "-agent",  # a leading hyphen
        "agent-",  # a trailing hyphen
        "agent vm",  # a space, which the shell would split
        "a" * 64,  # longer than a label
        "",
    ),
)
def test_a_name_that_is_not_a_hostname_label_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match="hostname label"):
        check_guest_name(name)


@pytest.mark.parametrize(
    "name",
    (
        "a" * 33,  # a 33-character login
        "agent-" + "b" * 28,  # 'agent' and 28 more: a 33-character login
        "1agent",  # a login starting with a digit
        "9-vm",
    ),
)
def test_a_name_whose_login_useradd_refuses_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match="useradd"):
        check_guest_name(name)


@pytest.mark.parametrize(
    "name",
    (
        "agent-vm-01",
        "a" * 32,  # a 32-character login
        "vm-" + "x" * 29,
        "a" + "-" * 61 + "b",  # a 63-character label, whose login is 'ab'
    ),
)
def test_a_name_satisfying_every_rule_passes(name: str) -> None:
    assert check_guest_name(name) == name


@pytest.mark.parametrize(
    "reservation", ("alloc-1", "01890a5d-ac96-774b-bcce-b302099a8057", "x" * 200)
)
def test_provisionings_own_names_pass(reservation: str) -> None:
    name = fulfillment_guest_name(reservation)
    assert check_guest_name(name) == name
