"""Re-export shim for the Arkhai agent HTTP client.

The canonical implementation lives in the ``agent-client`` package
(``agent-client/src/agent_client/client.py``), distributed as a
pure-Python wheel.  This shim preserves the historical import path::

    from agent.client.agent_client import AgentClient

so that existing callers inside ``core/`` (e.g. tests) continue to work
without modification.

Do not add logic here.  Changes to the client go in ``agent-client/``.
"""

from agent_client.client import AgentClient, AgentClientError, _build_auth_headers

__all__ = ["AgentClient", "AgentClientError", "_build_auth_headers"]
