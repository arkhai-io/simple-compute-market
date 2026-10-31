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
)

# A key generated for this test module only; it protects nothing real.
_KEY = Fernet.generate_key().decode()
_PATH_KEY = {"ssh_host": "10.0.0.1", "key_path": "/keys/id_ed25519"}
_PEM = "-----BEGIN OPENSSH PRIVATE KEY-----\nmaterial\n-----END OPENSSH PRIVATE KEY-----\n"


def test_the_codec_satisfies_the_host_authority_protocol() -> None:
    codec: ConnectionCodec = SshConnectionCodec(_KEY)

    assert (codec.kind, codec.version) == ("ssh", 2)
    assert SSH_CONNECTION_VERSION == SshConnectionCodec.version == 2


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
        version=2,
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
# port: no ``public_port`` key, never a null one. Addresses here are development
# fixture values that must never be used on a public network.
_STORED_WITHOUT_PUBLIC_PORT = {
    "ssh_host": "10.0.0.1",
    "public_host": None,
    "ssh_port": 22,
    "ssh_user": "root",
    "key_path": "/keys/id_ed25519",
}


def test_a_connection_stating_no_public_port_is_stored_at_version_2_without_the_key() -> None:
    codec = SshConnectionCodec(_KEY)
    stored = ConnectionEnvelope(kind="ssh", version=2, public=_STORED_WITHOUT_PUBLIC_PORT)

    built = codec.build(_PATH_KEY, {})
    assert (built.version, dict(built.public)) == (2, _STORED_WITHOUT_PUBLIC_PORT)
    assert dict(codec.validate(stored).public) == _STORED_WITHOUT_PUBLIC_PORT
    assert SshConnectionCodec.parse(stored).public_port is None


def test_a_null_public_port_is_stored_as_absent() -> None:
    envelope = SshConnectionCodec(_KEY).build({**_PATH_KEY, "public_port": None}, {})

    assert envelope.version == 2
    assert dict(envelope.public) == _STORED_WITHOUT_PUBLIC_PORT


def test_a_public_port_is_kept_beside_the_public_host() -> None:
    codec = SshConnectionCodec(_KEY)
    submission = ssh_connection(**_PATH_KEY, public_host="192.0.2.10", public_port=2222)

    envelope = codec.build(submission.public, submission.secrets)

    assert submission.public["public_port"] == 2222
    assert dict(envelope.public) == {
        **_STORED_WITHOUT_PUBLIC_PORT,
        "public_host": "192.0.2.10",
        "public_port": 2222,
    }
    connection = SshConnectionCodec.parse(codec.validate(envelope))
    assert (connection.public_host, connection.public_port) == ("192.0.2.10", 2222)


def test_a_public_port_may_be_stated_without_a_public_host() -> None:
    envelope = SshConnectionCodec(_KEY).build({**_PATH_KEY, "public_port": 2222}, {})

    assert envelope.public["public_host"] is None
    assert envelope.public["public_port"] == 2222


@pytest.mark.parametrize("port", [0, 65536, -1, "22x"], ids=["zero", "too large", "negative", "not a number"])
def test_a_malformed_public_port_is_refused(port) -> None:
    with pytest.raises(ValueError, match="ssh connection"):
        SshConnectionCodec(_KEY).build({**_PATH_KEY, "public_port": port}, {})
    with pytest.raises(ValueError):
        ssh_connection(**_PATH_KEY, public_port=port)


@pytest.mark.parametrize("port", [None, 22], ids=["no port", "a port"])
def test_every_operator_submission_is_at_version_2(port) -> None:
    submission = ssh_connection(**_PATH_KEY, public_port=port)

    assert submission.version == 2
    assert ("public_port" in submission.public) is (port is not None)


@pytest.mark.parametrize(
    "kind,version",
    [("ssh", 1), ("ssh", 3), ("other", 2)],
    ids=["the retired version 1", "a later version", "another kind"],
)
def test_a_stored_connection_at_another_kind_or_version_is_refused(kind, version) -> None:
    stored = ConnectionEnvelope(kind=kind, version=version, public=_STORED_WITHOUT_PUBLIC_PORT)

    with pytest.raises(ValueError, match="not an ssh connection at version 2.*re-register"):
        SshConnectionCodec.parse(stored)
    with pytest.raises(ValueError, match="not an ssh connection at version 2"):
        SshConnectionCodec(_KEY).validate(stored)


# A host stored at version 1 with a protected key, as the service stored it
# before it served version 2; built directly, since nothing registers version 1.
_LEGACY = ConnectionEnvelope(
    kind="ssh",
    version=1,
    public={"ssh_host": "10.0.0.1", "public_host": None, "ssh_port": 22, "ssh_user": "root", "key_path": None},
    protected={"private_key": ProtectedValue(scheme=FERNET_SCHEME, ciphertext="opaque-ciphertext")},
)


def test_a_version_1_host_re_registered_at_version_2_keeps_its_protected_key() -> None:
    codecs = ConnectionCodecs([SshConnectionCodec(_KEY)])

    upgraded = codecs.build("ssh", 2, {"ssh_host": "10.0.0.1"}, {}, previous=_LEGACY)

    assert upgraded.version == 2
    assert upgraded.protected["private_key"] == _LEGACY.protected["private_key"]
    assert "public_port" not in upgraded.public


def test_a_version_1_submission_is_refused_naming_the_served_version() -> None:
    codecs = ConnectionCodecs([SshConnectionCodec(_KEY)])

    with pytest.raises(ValueError, match="'ssh' is at version 2, not 1"):
        codecs.build("ssh", 1, _PATH_KEY, {})
