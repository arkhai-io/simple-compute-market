"""Re-export of the provisioning service's at-rest encryption primitives.

The implementation lives in ``compute_provisioning_service.crypto`` because the
encryption key is a setting of that service and the ciphertext sits in tables it
owns. This module remains so that the adapter's call sites read against their
own package, and so that a future adapter with a different key source has an
obvious place to diverge.
"""

from __future__ import annotations

from compute_provisioning_service.crypto import decrypt_key, encrypt_key

__all__ = ["decrypt_key", "encrypt_key"]
