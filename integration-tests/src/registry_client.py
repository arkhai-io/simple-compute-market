"""Convenience re-export of SyncRegistryClient as RegistryClient.

Smoke tests import ``from src.registry_client import RegistryClient`` and
call it synchronously against real deployed endpoints.  ``SyncRegistryClient``
from the canonical wheel provides that interface directly — no shim logic
needed.

See TODO(registry-client-migration) in ARCHITECTURE.md: when the smoke tests
are converted to async, replace this file with a direct import from
``registry_client`` and delete this module.
"""

from registry_client import SyncRegistryClient as RegistryClient  # noqa: F401
from registry_client import RegistryClientError  # noqa: F401

__all__ = ["RegistryClient", "RegistryClientError"]
