"""Symmetric encryption for secret material this service stores at rest.

Two kinds of material use it: a host registered with
``ssh_key_type='embedded'`` carries its own SSH private key, and a relay
carries its admission token. Both are encrypted under one key, so a deployment
has one thing to rotate rather than one per subsystem.

It lives here rather than in a domain adapter because the key is a setting of
this service and the ciphertext sits in tables this service owns. Adapters may
import it; the reverse would invert the dependency the import-boundary test
enforces.

The encryption key is a URL-safe base64-encoded 32-byte Fernet key supplied
via the ``SSH_DECRYPTION_KEY`` setting (env var ``PROVISIONING_SSH_DECRYPTION_KEY``).

Generating a key::

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Both functions raise ``ValueError`` on a missing or malformed key, and
``cryptography.fernet.InvalidToken`` if the ciphertext is corrupt or was
encrypted with a different key.
"""

from __future__ import annotations


def _fernet(secret: str):
    """Return a ``Fernet`` instance from *secret*.

    Raises ``ValueError`` if *secret* is empty or not a valid Fernet key.
    """
    if not secret:
        raise ValueError(
            "SSH_DECRYPTION_KEY is not set. It is required to store embedded host "
            "key material or a relay admission token."
        )
    from cryptography.fernet import Fernet

    try:
        return Fernet(secret.encode() if isinstance(secret, str) else secret)
    except Exception as exc:
        raise ValueError(f"SSH_DECRYPTION_KEY is not a valid Fernet key: {exc}") from exc


def encrypt_key(plaintext: str, secret: str) -> str:
    """Encrypt *plaintext* and return a base64 token string."""
    f = _fernet(secret)
    return f.encrypt(plaintext.encode()).decode()


def decrypt_key(ciphertext: str, secret: str) -> str:
    """Decrypt a token produced by ``encrypt_key`` and return the plaintext."""
    f = _fernet(secret)
    return f.decrypt(ciphertext.encode()).decode()
