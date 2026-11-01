"""The names of the playbook variables that carry a relay's secrets.

Each domain's codec names these among the secret fields the Ansible executor
redacts from a job's logged output, so the redaction covers every domain's
relayed jobs alike; a domain naming its own subset would leave the others'
secrets in a job read.
"""

from __future__ import annotations

#: The relay's admission token, which a relayed job's variables carry.
RELAY_TOKEN_VARIABLE = "frp_auth_token"
#: The grant a proxy carries in its metadata, which a create's variables carry.
RELAY_GRANT_VARIABLE = "relay_grant"
#: The name under which a task holds the buyer-facing client's admin password.
RELAY_ADMIN_PASSWORD_VARIABLE = "relay_admin_password"

#: Every variable a relayed job's tasks carry a relay secret in.
RELAY_SECRET_VARIABLES = frozenset(
    {RELAY_TOKEN_VARIABLE, RELAY_GRANT_VARIABLE, RELAY_ADMIN_PASSWORD_VARIABLE}
)

__all__ = [
    "RELAY_ADMIN_PASSWORD_VARIABLE",
    "RELAY_GRANT_VARIABLE",
    "RELAY_SECRET_VARIABLES",
    "RELAY_TOKEN_VARIABLE",
]
