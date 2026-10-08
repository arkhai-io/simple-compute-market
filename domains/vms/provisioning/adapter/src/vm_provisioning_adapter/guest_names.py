"""The name of the guest a VM fulfillment creates.

Provisioning names the guest, never the storefront: the name is derived from the
capacity reservation, so every retry of one fulfillment names the same guest and
two fulfillments never share one. The reservation id stays opaque: it is hashed
into a UUIDv5 rather than read, and does not appear inside the buyer's guest.

The name must satisfy every use VM's playbooks make of it
(``roles/vm-management/tasks/vm-create.yml`` and ``vm-undefine.yml``):

- the guest's hostname, through cloud-init and ``hostnamectl``, so a hostname
  label: lowercase letters, digits, and hyphens, starting and ending with a
  letter or digit, at most 63 characters;
- unquoted shell text, so nothing outside that character set;
- the tenant's login: the name stripped to letters and digits and lowercased is
  passed to ``useradd``, which refuses a login over 32 characters or one not
  starting with a letter;
- a substring match: every create ends by deleting each ``/tmp`` file whose name
  contains the guest's, so no guest's name may contain another's. Every derived
  name has the same length, which guarantees it.

domains/vms/provisioning/iac/README.md, "Guest names", states the same rules for
operators.
"""

from __future__ import annotations

import re
import uuid

# Fixed for good: changing it renames every guest a retry would prepare.
_GUEST_NAMESPACE = uuid.UUID("7a2fad3b-39c3-4698-b47e-68e19e792ff6")
_PREFIX = "tenant-"
# 96 bits: a collision among one host's guests is negligible, and the login
# derived from the name (30 characters) stays under useradd's 32.
_HEX_CHARACTERS = 24

GUEST_NAME_LENGTH = len(_PREFIX) + _HEX_CHARACTERS

_HOSTNAME_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_LOGIN = re.compile(r"^[a-z][a-z0-9]{0,31}$")


def guest_login(name: str) -> str:
    """The tenant login the playbook derives from a guest name."""
    return re.sub(r"[^a-zA-Z0-9]", "", name).lower()


def check_guest_name(name: str) -> str:
    """Return ``name`` if every playbook use of it accepts it; raise otherwise."""
    if not _HOSTNAME_LABEL.match(name):
        raise ValueError(
            f"guest name {name!r} is not a hostname label of lowercase letters, "
            "digits, and hyphens"
        )
    if not _LOGIN.match(guest_login(name)):
        raise ValueError(
            f"guest name {name!r} gives the login {guest_login(name)!r}, which "
            "useradd refuses: a login starts with a letter and has at most 32 "
            "characters"
        )
    return name


def fulfillment_guest_name(capacity_reservation_id: str) -> str:
    """The guest name for the fulfillment of one capacity reservation."""
    if not capacity_reservation_id:
        raise ValueError("a guest is named from a capacity reservation id")
    digest = uuid.uuid5(_GUEST_NAMESPACE, capacity_reservation_id).hex
    return check_guest_name(_PREFIX + digest[:_HEX_CHARACTERS])


__all__ = [
    "GUEST_NAME_LENGTH",
    "check_guest_name",
    "fulfillment_guest_name",
    "guest_login",
]
