"""Provisioning service HTTP client.

This module is a thin re-export shim.  The canonical implementation lives in
the provisioning-service package at:

    client.provisioning_client

All symbols are re-exported here so existing agent imports of the form:

    from service.clients.provisioning import provision_machine_async

continue to work without modification.

Note on import path: the provisioning-service package uses setuptools with
``package-dir = {"" = "src"}``, which means the package root is ``src/``
directly. The top-level importable name is therefore ``client``, not
``provisioning_service.client``.

TODO(client-compat): Once the provisioning-service package is restructured to
expose a ``provisioning_service`` namespace (requiring all internal imports to
be made relative), update this shim and all consumer imports to use
``provisioning_service.client.provisioning_client``.
"""

from client.provisioning_client import (  # noqa: F401
    ProvisioningClient,
    ProvisioningError,
    ProvisioningJobError,
    ProvisioningTimeoutError,
    get_job_credentials_async,
    get_vm_available_resources,
    provision_machine_async,
    provision_machine_async_with_id,
    schedule_vm_expiry_async,
    schedule_vm_shutdown_async,
)