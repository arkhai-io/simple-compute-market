"""Importing hosts from an Ansible inventory file.

Host import belongs to the Ansible implementation rather than the family's host
routes: it takes an INI inventory, a format only this implementation reads, so
a domain served by another executor never sees it in the family contract.

``HOST_IMPORT_ROUTES`` is the route's signed contract as plain data, which the
provisioning service assembles into the table its request authentication reads.
The request is multipart, so it is signed over a descriptor of its content
(type and SHA-256) rather than a JSON body.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from compute_provisioning_contracts import HostListResponse

HOST_IMPORT_PATH = "/api/v1/hosts/import"

HOST_IMPORT_ROUTES = (
    {
        "method": "POST",
        "path": HOST_IMPORT_PATH,
        "operation": "provisioning_hosts_import",
        "roles": ("admin",),
    },
)



class _Transport(Protocol):
    def authenticated_request(self, method: str, path: str, *args: Any, **kwargs: Any) -> Any: ...


def _upload(content: bytes, filename: str, ssh_key_type: str) -> dict[str, Any]:
    return {
        "files": {"file": (filename, content, "text/plain")},
        "data": {"ssh_key_type": ssh_key_type},
        "route": HOST_IMPORT_ROUTES[0],
    }


class AnsibleHostImportClient:
    """Host import over an async signing transport, such as the family's client.

    ``ssh_key_type`` says how the inventory names each host's key: ``path``
    for a key file the service reads at execution, ``embedded`` for key
    material the service reads from the file the inventory names now and
    protects before storing.
    """

    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    async def import_hosts_from_text(
        self, ini_text: str, ssh_key_type: str = "path", filename: str = "hosts"
    ) -> HostListResponse:
        return HostListResponse.model_validate(
            await self._transport.authenticated_request(
                "POST", HOST_IMPORT_PATH, **_upload(ini_text.encode("utf-8"), filename, ssh_key_type)
            )
        )

    async def import_hosts_from_path(self, path: Path, ssh_key_type: str = "path") -> HostListResponse:
        return HostListResponse.model_validate(
            await self._transport.authenticated_request(
                "POST", HOST_IMPORT_PATH, **_upload(Path(path).read_bytes(), Path(path).name, ssh_key_type)
            )
        )


class SyncAnsibleHostImportClient:
    """Host import over a sync signing transport; see ``AnsibleHostImportClient``."""

    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    def import_hosts_from_text(
        self, ini_text: str, ssh_key_type: str = "path", filename: str = "hosts"
    ) -> HostListResponse:
        return HostListResponse.model_validate(
            self._transport.authenticated_request(
                "POST", HOST_IMPORT_PATH, **_upload(ini_text.encode("utf-8"), filename, ssh_key_type)
            )
        )

    def import_hosts_from_path(self, path: Path, ssh_key_type: str = "path") -> HostListResponse:
        return HostListResponse.model_validate(
            self._transport.authenticated_request(
                "POST", HOST_IMPORT_PATH, **_upload(Path(path).read_bytes(), Path(path).name, ssh_key_type)
            )
        )


__all__ = [
    "AnsibleHostImportClient",
    "HOST_IMPORT_PATH",
    "HOST_IMPORT_ROUTES",
    "SyncAnsibleHostImportClient",
]
