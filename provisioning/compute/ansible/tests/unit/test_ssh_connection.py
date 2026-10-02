"""The ssh connection codec the host authority validates host connections with."""

from __future__ import annotations

import pytest
from compute_provisioning.hosts import ConnectionCodec

from compute_provisioning_ansible import SshConnectionCodec

_PATH_KEY = {"ssh_host": "10.0.0.1", "ssh_key_value": "/keys/id_ed25519"}


def test_the_codec_satisfies_the_host_authority_protocol() -> None:
    codec: ConnectionCodec = SshConnectionCodec()

    assert (codec.kind, codec.version) == ("ssh", 1)


def test_a_payload_is_completed_with_its_defaults() -> None:
    assert SshConnectionCodec().validate(_PATH_KEY) == {
        "ssh_host": "10.0.0.1",
        "public_host": None,
        "ssh_port": 22,
        "ssh_user": "root",
        "ssh_key_type": "path",
        "ssh_key_value": "/keys/id_ed25519",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"ssh_key_value": "/k"},
        {"ssh_host": " ", "ssh_key_value": "/k"},
        {**_PATH_KEY, "ssh_port": 0},
        {**_PATH_KEY, "ssh_key_type": "agent"},
        {**_PATH_KEY, "gpu_count": 2},
    ],
    ids=["no host", "blank host", "port", "key type", "unknown field"],
)
def test_an_invalid_payload_is_refused(payload) -> None:
    with pytest.raises(ValueError, match="invalid ssh connection"):
        SshConnectionCodec().validate(payload)


def test_only_embedded_key_material_is_secret() -> None:
    codec = SshConnectionCodec()
    embedded = codec.validate({**_PATH_KEY, "ssh_key_type": "embedded"})

    assert codec.secret_fields(codec.validate(_PATH_KEY)) == frozenset()
    assert codec.secret_fields(embedded) == frozenset({"ssh_key_value"})


def test_an_executor_reads_the_typed_connection() -> None:
    codec = SshConnectionCodec()

    connection = codec.parse(codec.validate({**_PATH_KEY, "ssh_port": 2201}))

    assert (connection.ssh_host, connection.ssh_port) == ("10.0.0.1", 2201)
