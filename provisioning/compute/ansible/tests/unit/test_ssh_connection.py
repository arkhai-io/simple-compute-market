"""The ssh connection codec the host authority stores host connections with."""

from __future__ import annotations

import pytest
from compute_provisioning.hosts import (
    ConnectionCodec,
    ConnectionCodecs,
    ConnectionEnvelope,
    ProtectedValue,
)
from cryptography.fernet import Fernet
from market_config import decrypt_secret

from compute_provisioning_ansible import (
    FERNET_SCHEME,
    SSH_CONNECTION_VERSION,
    SshConnectionCodec,
    ssh_connection,
    ssh_connection_codecs,
)
from compute_provisioning_ansible import connection as connection_module

# A key generated for this test module only; it protects nothing real.
_KEY = Fernet.generate_key().decode()
_PATH_KEY = {"ssh_host": "10.0.0.1", "key_path": "/keys/id_ed25519"}
_PEM = "-----BEGIN OPENSSH PRIVATE KEY-----\nmaterial\n-----END OPENSSH PRIVATE KEY-----\n"


def test_the_codec_satisfies_the_host_authority_protocol() -> None:
    codec: ConnectionCodec = SshConnectionCodec(_KEY)

    assert (codec.kind, codec.version) == ("ssh", 1)
    assert [(c.kind, c.version) for c in ssh_connection_codecs(_KEY)] == [("ssh", 1), ("ssh", 2)]


def test_the_no_port_version_and_the_codecs_default_stay_version_1() -> None:
    assert SSH_CONNECTION_VERSION == connection_module.SSH_CONNECTION_VERSION == 1
    assert SshConnectionCodec.version == SshConnectionCodec().version == SSH_CONNECTION_VERSION
    assert SshConnectionCodec(version=2).version == 2
    assert SshConnectionCodec.version == SSH_CONNECTION_VERSION
    assert ssh_connection(**_PATH_KEY).version == SSH_CONNECTION_VERSION


def test_a_codec_is_built_only_for_a_served_version() -> None:
    with pytest.raises(ValueError, match=r"served at versions \[1, 2\], not 3"):
        SshConnectionCodec(_KEY, version=3)


def test_public_fields_are_completed_with_their_defaults() -> None:
    envelope = SshConnectionCodec(_KEY).build(_PATH_KEY, {})

    assert dict(envelope.public) == {
        "ssh_host": "10.0.0.1",
        "public_host": None,
        "ssh_port": 22,
        "ssh_user": "root",
        "key_path": "/keys/id_ed25519",
    }
    assert dict(envelope.protected) == {}


def test_a_submitted_private_key_is_protected_and_never_kept_in_plaintext() -> None:
    envelope = SshConnectionCodec(_KEY).build({"ssh_host": "10.0.0.1"}, {"private_key": _PEM})

    protected = envelope.protected["private_key"]
    assert protected.scheme == FERNET_SCHEME
    assert _PEM not in protected.ciphertext
    assert decrypt_secret(protected.ciphertext, _KEY) == _PEM
    assert "ciphertext" not in repr(protected) and protected.ciphertext not in repr(envelope)
    assert envelope.protected_schemes() == {"private_key": FERNET_SCHEME}


def test_a_private_key_cannot_be_submitted_without_a_protecting_key() -> None:
    with pytest.raises(ValueError, match="no key is configured"):
        SshConnectionCodec(None).build({"ssh_host": "10.0.0.1"}, {"private_key": _PEM})


def test_an_update_without_the_secret_keeps_the_stored_one() -> None:
    codec = SshConnectionCodec(_KEY)
    first = codec.build({"ssh_host": "10.0.0.1"}, {"private_key": _PEM})

    second = codec.build({"ssh_host": "10.0.0.2", "ssh_port": 2201}, {}, previous=first)

    assert second.protected["private_key"] == first.protected["private_key"]
    assert second.public["ssh_port"] == 2201


@pytest.mark.parametrize(
    "public,secrets",
    [
        ({"key_path": "/k"}, {}),
        ({"ssh_host": " ", "key_path": "/k"}, {}),
        ({**_PATH_KEY, "ssh_port": 0}, {}),
        ({**_PATH_KEY, "gpu_count": 2}, {}),
        ({"ssh_host": "10.0.0.1"}, {}),
        (_PATH_KEY, {"private_key": _PEM}),
        (_PATH_KEY, {"password": "x"}),
    ],
    ids=["no host", "blank host", "port", "unknown field", "no key", "two keys", "unknown secret"],
)
def test_an_invalid_connection_is_refused(public, secrets) -> None:
    with pytest.raises(ValueError, match="ssh connection"):
        SshConnectionCodec(_KEY).build(public, secrets)


def test_a_stored_envelope_in_another_scheme_is_refused() -> None:
    envelope = ConnectionEnvelope(
        kind="ssh",
        version=1,
        public={"ssh_host": "10.0.0.1"},
        protected={"private_key": ProtectedValue(scheme="sealed-box-v1", ciphertext="x")},
    )

    with pytest.raises(ValueError, match="scheme"):
        SshConnectionCodec(_KEY).validate(envelope)


def test_an_operator_submission_names_only_what_was_given() -> None:
    submission = ssh_connection(ssh_host="10.0.0.1", private_key=_PEM)

    assert submission.kind == "ssh"
    assert submission.secrets == {"private_key": _PEM}
    assert _PEM not in repr(submission)


# The public fields ``_PATH_KEY`` is stored with when it states no tenant-facing
# port: the same mapping a reader that does not know ``public_port`` accepts,
# since it refuses any key it does not know, a null one included. Addresses here
# are development fixture values that must never be used on a public network.
_STORED_WITHOUT_PUBLIC_PORT = {
    "ssh_host": "10.0.0.1",
    "public_host": None,
    "ssh_port": 22,
    "ssh_user": "root",
    "key_path": "/keys/id_ed25519",
}


def test_a_connection_stating_no_public_port_is_stored_as_before() -> None:
    codec = SshConnectionCodec(_KEY)
    stored = ConnectionEnvelope(kind="ssh", version=1, public=_STORED_WITHOUT_PUBLIC_PORT)

    assert dict(codec.build(_PATH_KEY, {}).public) == _STORED_WITHOUT_PUBLIC_PORT
    assert dict(codec.validate(stored).public) == _STORED_WITHOUT_PUBLIC_PORT
    assert "public_port" not in ssh_connection(**_PATH_KEY).public
    assert SshConnectionCodec.parse(stored).public_port is None


_V2 = SshConnectionCodec(_KEY, version=2)


@pytest.mark.parametrize("port", [2222, None], ids=["a port", "a null"])
def test_version_1_refuses_a_public_port_even_as_null(port) -> None:
    with pytest.raises(ValueError, match="ssh connection at version 1"):
        SshConnectionCodec(_KEY).build({**_PATH_KEY, "public_port": port}, {})
    stored = ConnectionEnvelope(kind="ssh", version=1, public={**_STORED_WITHOUT_PUBLIC_PORT, "public_port": port})
    with pytest.raises(ValueError, match="ssh connection at version 1"):
        SshConnectionCodec.parse(stored)


def test_version_2_stores_a_null_public_port_as_absent_and_stays_version_2() -> None:
    envelope = _V2.build({**_PATH_KEY, "public_port": None}, {})

    assert envelope.version == 2
    assert dict(envelope.public) == _STORED_WITHOUT_PUBLIC_PORT


def test_a_public_port_is_kept_beside_the_public_host() -> None:
    submission = ssh_connection(**_PATH_KEY, public_host="192.0.2.10", public_port=2222)

    envelope = _V2.build(submission.public, submission.secrets)

    assert (submission.version, submission.public["public_port"]) == (2, 2222)
    assert dict(envelope.public) == {
        **_STORED_WITHOUT_PUBLIC_PORT,
        "public_host": "192.0.2.10",
        "public_port": 2222,
    }
    connection = SshConnectionCodec.parse(_V2.validate(envelope))
    assert (connection.public_host, connection.public_port) == ("192.0.2.10", 2222)


def test_a_public_port_may_be_stated_without_a_public_host() -> None:
    envelope = _V2.build({**_PATH_KEY, "public_port": 2222}, {})

    assert envelope.public["public_host"] is None
    assert envelope.public["public_port"] == 2222


@pytest.mark.parametrize("port", [0, 65536, -1, "22x"], ids=["zero", "too large", "negative", "not a number"])
def test_a_malformed_public_port_is_refused(port) -> None:
    with pytest.raises(ValueError, match="ssh connection"):
        _V2.build({**_PATH_KEY, "public_port": port}, {})
    with pytest.raises(ValueError):
        ssh_connection(**_PATH_KEY, public_port=port)


def test_the_operator_submission_states_version_2_only_with_a_port() -> None:
    assert ssh_connection(**_PATH_KEY).version == 1
    assert ssh_connection(**_PATH_KEY, public_port=22).version == 2


@pytest.mark.parametrize(
    "kind,version", [("ssh", 3), ("other", 1)], ids=["a later version", "another kind"]
)
def test_a_stored_connection_at_an_unserved_kind_or_version_is_refused(kind, version) -> None:
    stored = ConnectionEnvelope(kind=kind, version=version, public=_STORED_WITHOUT_PUBLIC_PORT)

    with pytest.raises(ValueError, match="not an ssh connection at a served version"):
        SshConnectionCodec.parse(stored)
    with pytest.raises(ValueError, match="not an ssh connection at version"):
        _V2.validate(stored)


def test_a_stored_version_1_connection_reads_with_no_public_port() -> None:
    stored = ConnectionEnvelope(kind="ssh", version=1, public=_STORED_WITHOUT_PUBLIC_PORT)

    connection = SshConnectionCodec.parse(stored)

    assert (connection.ssh_host, connection.public_port) == ("10.0.0.1", None)


def test_a_protected_key_is_kept_when_a_version_1_host_moves_to_version_2() -> None:
    codecs = ConnectionCodecs(ssh_connection_codecs(_KEY))
    first = codecs.build("ssh", 1, {"ssh_host": "10.0.0.1"}, {"private_key": _PEM})

    second = codecs.build(
        "ssh", 2, {"ssh_host": "10.0.0.1", "public_port": 22}, {}, previous=first
    )

    assert (second.version, second.public["public_port"]) == (2, 22)
    assert second.protected["private_key"] == first.protected["private_key"]
