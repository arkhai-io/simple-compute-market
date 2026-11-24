"""The connection's public data stays immutable through a caller's snapshot."""

from compute_provisioning.hosts import ConnectionEnvelope


def test_retained_public_fields_cannot_be_mutated_through_the_execution_connection():
    values = {"address": "192.0.2.10", "pins": ["original"]}
    connection = ConnectionEnvelope("fake", 1, public=values)
    values["pins"].append("other")
    connection.public["pins"].append("third")
    assert connection.public["pins"] == ["original"]
