"""The names the service's event store keeps its events and consumers under.

Its events' source and data-schema prefix, and the storefront peer's consumers
and their destinations. The runtime and the migration that carries a released
database's storefront outboxes into the store read them from here, so a
migrated event or delivery is one the running consumers find.
"""

from __future__ import annotations

from urllib.parse import urlsplit

#: The service named in every event's source.
EVENT_SOURCE_SERVICE = "compute-provisioning"

#: The data schema prefix of every kind this service records.
EVENT_SCHEMA_PREFIX = "urn:arkhai:event"

#: The consumer delivering signed lease-end reports.
LEASE_END_REPORT_CONSUMER = "lease-end-reports"

#: The consumer delivering capacity-released callbacks.
CAPACITY_RELEASED_CONSUMER = "capacity-released"

#: The capacity-released consumer's one destination: the configured storefront.
CAPACITY_RELEASED_DESTINATION = "storefront"


def peer_destination(url: str) -> str:
    """The lease-end report destination of the storefront peer at ``url``.

    The peer's host, port and path, with each ``/`` of the path written ``~``
    so the name is one segment of the resume route's path: another URL names
    another peer, and so another destination. Any credentials the URL carries
    are left out, since the name is shown on the delivery status read.
    """
    parts = urlsplit(url.rstrip("/"))
    host = parts.netloc.rpartition("@")[2]
    return "storefront@" + host + parts.path.replace("/", "~")


__all__ = [
    "CAPACITY_RELEASED_CONSUMER",
    "CAPACITY_RELEASED_DESTINATION",
    "EVENT_SCHEMA_PREFIX",
    "EVENT_SOURCE_SERVICE",
    "LEASE_END_REPORT_CONSUMER",
    "peer_destination",
]
