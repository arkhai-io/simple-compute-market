"""Symmetric encryption for configured secrets held at rest.

Some secret material cannot live only in a deployment's configuration profile,
because it is administered at runtime rather than declared at deploy time — a
host's own SSH key, a relay's admission token. That material goes in the
database, and the database must not hold anything usable on its own.

So the profile holds one key and the database holds ciphertext. Recovering a
secret needs both, and the key never leaves the profile.

This lives with configuration loading rather than with any service or domain
because it is a property of how this system carries configured secrets, not of
what any particular secret protects. A second copy of it beside a second
subsystem would be a second thing to rotate and a second thing to get wrong.

The key is a URL-safe base64-encoded 32-byte Fernet key. Generating one::

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Both functions raise ``ValueError`` on a missing or malformed key, and
``cryptography.fernet.InvalidToken`` when the ciphertext is corrupt or was
written under a different key. A wrong key is deliberately not recoverable:
returning something on a key mismatch is how a rotation quietly loses data.
"""

from __future__ import annotations

__all__ = ["decrypt_secret", "encrypt_secret"]


def _fernet(key: str):
    """Return a ``Fernet`` for *key*, or explain why there isn't one."""
    if not key:
        raise ValueError(
            "No at-rest encryption key is configured. It is required to store "
            "or read any secret this system holds in a database."
        )
    from cryptography.fernet import Fernet

    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:
        raise ValueError(f"at-rest encryption key is not a valid Fernet key: {exc}") from exc


def encrypt_secret(plaintext: str, key: str) -> str:
    """Encrypt *plaintext* under *key* and return a base64 token string."""
    return _fernet(key).encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str, key: str) -> str:
    """Decrypt a token produced by :func:`encrypt_secret` under the same key."""
    return _fernet(key).decrypt(ciphertext.encode()).decode()
