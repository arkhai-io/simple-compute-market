"""The ssh connection codec the host authority stores host connections with."""

from __future__ import annotations

import pytest
from compute_provisioning.hosts import ConnectionCodec, ConnectionEnvelope, ProtectedValue
from cryptography.fernet import Fernet
from market_config import decrypt_secret

from compute_provisioning_ansible import FERNET_SCHEME, SshConnectionCodec, ssh_connection

# A key generated for this test module only; it protects nothing real.
_KEY = Fernet.generate_key().decode()
_PATH_KEY = {"ssh_host": "10.0.0.1", "key_path": "/keys/id_ed25519"}
_PEM = "-----BEGIN OPENSSH PRIVATE KEY-----\nmaterial\n-----END OPENSSH PRIVATE KEY-----\n"


def test_the_codec_satisfies_the_host_authority_protocol() -> None:
    codec: ConnectionCodec = SshConnectionCodec(_KEY)

    assert (codec.kind, codec.version) == ("ssh", 1)


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
