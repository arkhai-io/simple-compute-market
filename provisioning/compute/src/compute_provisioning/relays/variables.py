"""The relay playbook variables owned by the compute family.

Each domain's codec includes the secret subset in the fields the executor
redacts from logged output. The reserved set also covers role inputs and
control results that provider options must never override.
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

# Global extra-vars outrank include_role vars and registered task results.
# Provider options therefore cannot select another proxy or runtime client,
# even when a direct job emits none of the relay inputs itself. Operators may
# still configure host preparation and inventory outside provider extra-vars.
RELAY_JOB_RESERVED_VARIABLES = RELAY_SECRET_VARIABLES | frozenset({
    "relay_proxy_action", "relay_proxy_name", "relay_proxy_local_ip",
    "relay_proxy_local_port", "relay_proxy_remote_port", "relay_client_config",
    "relay_proxy_library_path", "relay_proxy_teardown_library",
    "relay_admin_credentials", "relay_proxy_status", "relay_proxy_removal",
    "relay_client_baseline", "relay_privileged_port_start",
    "frp_server_addr", "frp_server_port", "frp_admin_port",
    "frp_binary_name", "frp_binary_path", "frp_install_root", "frp_version",
    "frp_platform", "frp_archives", "frp_installed", "frp_workspace",
})

__all__ = [
    "RELAY_JOB_RESERVED_VARIABLES",
    "RELAY_ADMIN_PASSWORD_VARIABLE",
    "RELAY_GRANT_VARIABLE",
    "RELAY_SECRET_VARIABLES",
    "RELAY_TOKEN_VARIABLE",
]
