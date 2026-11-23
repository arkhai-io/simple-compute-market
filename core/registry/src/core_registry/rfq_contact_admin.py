"""Rotate persisted RFQ contacts while the registry's writers are stopped."""

import argparse

from core_registry.config import settings
from core_registry.db.database import SessionLocal
from core_registry.db.migrations import require_compatible_database
from core_registry.rfq_contact_crypto import RfqContactKeys, RfqContactUnavailable
from core_registry.rfq_contact_store import require_retained_keys, rotate_contact_batch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("rotate",))
    parser.parse_args()

    key_file = settings.registry_rfq_contact_keys_file
    authority = settings.registry_authority_id
    if not key_file or not authority or settings.registry_rfq_redact_restored_contacts:
        parser.error("rotation requires an authority and contact keyring in normal service configuration")
    require_compatible_database(settings.database_url)
    keys = RfqContactKeys.load(key_file)
    try:
        with SessionLocal() as db:
            require_retained_keys(db, keys)
        changed = 0
        while True:
            with SessionLocal.begin() as db:
                count = rotate_contact_batch(db, authority, keys)
            changed += count
            if not count:
                break
    except RfqContactUnavailable:
        parser.exit(1, "RFQ contact rotation refused because a retained payload could not be opened\n")
    print(f"RFQ contact rotation complete. Re-encrypted payloads: {changed}.")
