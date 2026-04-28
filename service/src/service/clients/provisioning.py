"""Provisioning service HTTP client — re-export shim.

The canonical implementation lives in the provisioning-service package at:

    client.provisioning_client

All symbols are re-exported here so storefront imports of the form:

    from service.clients.provisioning import ProvisioningClient

continue to work without modification.

Note on import path: the provisioning-service package uses setuptools with
``package-dir = {"" = "src"}``, which means the package root is ``src/``
directly. The top-level importable name is therefore ``client``, not
``provisioning_service.client``.
"""

from client.provisioning_client import (  # noqa: F401
    ProvisioningClient,
    ProvisioningError,
    ProvisioningJobError,
    ProvisioningTimeoutError,
)
