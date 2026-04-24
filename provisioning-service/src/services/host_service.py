"""CRUD service for the KVM host registry.

The ``hosts`` table is the single source of truth for host inventory.
All host lookups during job execution and all ``GET /hosts`` queries
read from this table — never from the Ansible INI file on disk.

The INI file is an *input* format only:
  - ``seed_from_ini`` parses an INI block and upserts rows (append-only).
  - ``render_inventory_ini`` produces an INI string from DB rows for
    consumption by ``AnsibleService.write_inventory``.

SSH key handling
----------------
``path`` hosts:   ``ssh_key_value`` is stored verbatim as a filesystem path.
``embedded`` hosts: ``ssh_key_value`` is stored as a Fernet-encrypted PEM
                    string.  ``SSH_DECRYPTION_KEY`` must be set at runtime.
                    ``register_host`` encrypts on write; callers that need the
                    plaintext key (e.g. ``write_inventory``) call
                    ``get_decrypted_key_value``.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from sqlalchemy.orm import Session, sessionmaker

from db.models import Host
from models.host_model import HostCreate, HostUpdate

logger = logging.getLogger(__name__)

# Default SSH key path used when the INI entry has no
# ansible_ssh_private_key_file variable.
_DEFAULT_KEY_PATH = "/home/appuser/.ssh/id_ed25519"


class HostNotFoundError(Exception):
    """Raised when a requested host name does not exist in the DB."""


class HostService:
    """CRUD operations and inventory helpers for the ``hosts`` table."""

    def __init__(self, session_factory: sessionmaker[Session], settings) -> None:
        self._session_factory = session_factory
        self._settings = settings

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_hosts(
        self,
        search: Optional[str] = None,
        enabled_only: bool = True,
    ) -> list[Host]:
        """Return hosts from the DB, optionally filtered.

        Args:
            search: Case-insensitive substring filter on ``name``.
            enabled_only: When True (default) only ``enabled=True`` rows are returned.
        """
        with self._session_factory() as db:
            q = db.query(Host)
            if enabled_only:
                q = q.filter(Host.enabled.is_(True))
            if search:
                q = q.filter(Host.name.ilike(f"%{search}%"))
            return q.order_by(Host.name).all()

    def get_host(self, name: str) -> Optional[Host]:
        """Return the host row for *name*, or ``None`` if not found."""
        with self._session_factory() as db:
            return db.query(Host).filter(Host.name == name).one_or_none()

    def _require_host(self, db: Session, name: str) -> Host:
        host = db.query(Host).filter(Host.name == name).one_or_none()
        if host is None:
            raise HostNotFoundError(f"Host '{name}' not found")
        return host

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def register_host(self, data: HostCreate) -> Host:
        """Insert a new host row.

        If ``ssh_key_type`` is ``'embedded'``, the raw PEM in
        ``ssh_key_value`` is encrypted via :func:`crypto.encrypt_key`
        before storage.

        Raises:
            ValueError: If an ``embedded`` host is registered without
                ``SSH_DECRYPTION_KEY`` being set.
        """
        key_value = data.ssh_key_value
        if data.ssh_key_type == "embedded":
            from crypto import encrypt_key
            key_value = encrypt_key(key_value, self._settings.ssh_decryption_key)

        host = Host(
            name=data.name,
            kvm_host=data.kvm_host,
            ssh_user=data.ssh_user,
            ssh_key_type=data.ssh_key_type,
            ssh_key_value=key_value,
            gpu_count=data.gpu_count,
            enabled=data.enabled,
        )
        with self._session_factory() as db:
            db.add(host)
            db.commit()
            db.refresh(host)
            db.expunge(host)
            return host

    def update_host(self, name: str, data: HostUpdate) -> Host:
        """Update mutable fields on an existing host.

        If ``ssh_key_type`` is changed to ``'embedded'`` and
        ``ssh_key_value`` is also supplied, the value is encrypted.
        If only ``ssh_key_value`` is supplied (without changing the type),
        the current ``ssh_key_type`` determines whether to encrypt.
        """
        with self._session_factory() as db:
            host = self._require_host(db, name)

            if data.kvm_host is not None:
                host.kvm_host = data.kvm_host
            if data.ssh_user is not None:
                host.ssh_user = data.ssh_user
            if data.gpu_count is not None:
                host.gpu_count = data.gpu_count

            # Resolve the effective key type after any update
            effective_type = data.ssh_key_type or host.ssh_key_type
            if data.ssh_key_type is not None:
                host.ssh_key_type = data.ssh_key_type
            if data.ssh_key_value is not None:
                key_value = data.ssh_key_value
                if effective_type == "embedded":
                    from crypto import encrypt_key
                    key_value = encrypt_key(key_value, self._settings.ssh_decryption_key)
                host.ssh_key_value = key_value

            db.commit()
            db.refresh(host)
            db.expunge(host)
            return host

    def enable_host(self, name: str) -> Host:
        """Set ``enabled=True`` on *name*."""
        with self._session_factory() as db:
            host = self._require_host(db, name)
            host.enabled = True
            db.commit()
            db.refresh(host)
            db.expunge(host)
            return host

    def disable_host(self, name: str) -> Host:
        """Set ``enabled=False`` on *name*.

        Hosts are never hard-deleted so that job history references
        (``vm_host`` name) remain resolvable.
        """
        with self._session_factory() as db:
            host = self._require_host(db, name)
            host.enabled = False
            db.commit()
            db.refresh(host)
            db.expunge(host)
            return host

    # ------------------------------------------------------------------
    # INI import
    # ------------------------------------------------------------------

    def seed_from_ini(self, ini_text: str, ssh_key_type: str = "path") -> list[Host]:
        """Parse an Ansible INI inventory block and upsert host rows.

        Upsert semantics (append-only): hosts present in the INI are
        inserted or updated; hosts absent from the INI are not touched.
        This is safe to call repeatedly — it is idempotent for the same
        input.

        The INI is expected to contain a ``[kvm_hosts]`` group.  Lines
        in other groups or without a group header are also parsed.

        For ``ssh_key_type='path'``: ``ansible_ssh_private_key_file`` is
        stored verbatim.  Defaults to ``_DEFAULT_KEY_PATH`` if absent.

        For ``ssh_key_type='embedded'``: the path is read from disk and
        the contents are encrypted before storage.  Requires
        ``SSH_DECRYPTION_KEY`` to be set.

        Returns the list of upserted ``Host`` ORM rows.
        """
        parsed = _parse_ini(ini_text)
        if not parsed:
            logger.warning("seed_from_ini: no host entries found in INI input")
            return []

        upserted_names: list[str] = []
        with self._session_factory() as db:
            for entry in parsed:
                key_value = entry.get("ansible_ssh_private_key_file", _DEFAULT_KEY_PATH)

                if ssh_key_type == "embedded":
                    from pathlib import Path
                    from crypto import encrypt_key
                    raw = Path(key_value).read_text(encoding="utf-8")
                    key_value = encrypt_key(raw, self._settings.ssh_decryption_key)

                existing = db.query(Host).filter(Host.name == entry["name"]).one_or_none()
                if existing is not None:
                    existing.kvm_host = entry["kvm_host"]
                    existing.ssh_user = entry["ssh_user"]
                    existing.ssh_key_type = ssh_key_type
                    existing.ssh_key_value = key_value
                else:
                    db.add(Host(
                        name=entry["name"],
                        kvm_host=entry["kvm_host"],
                        ssh_user=entry["ssh_user"],
                        ssh_key_type=ssh_key_type,
                        ssh_key_value=key_value,
                        gpu_count=0,
                        enabled=True,
                    ))

                upserted_names.append(entry["name"])

            db.commit()

        # Re-query after the session closes so callers receive fully-loaded,
        # session-independent objects.  (commit() expires all attributes; objects
        # accessed after the with-block exits raise DetachedInstanceError.)
        upserted = []
        with self._session_factory() as db:
            for name in upserted_names:
                host = db.query(Host).filter(Host.name == name).one_or_none()
                if host is not None:
                    db.expunge(host)
                    upserted.append(host)

        logger.info("seed_from_ini: upserted %d host(s)", len(upserted))
        return upserted

    # ------------------------------------------------------------------
    # Inventory rendering
    # ------------------------------------------------------------------

    def render_inventory_ini(self, hosts: list[Host]) -> str:
        """Render *hosts* as an Ansible INI inventory string.

        Only ``enabled=True`` hosts should be passed; this method does not
        filter.  The ``[kvm_hosts]`` group header is always emitted.

        For ``embedded`` hosts, the SSH key material is decrypted and
        written to a temp file by ``AnsibleService.write_inventory`` — this
        method only produces the INI text with the key path placeholder
        ``{key_path}`` replaced by the caller.  To avoid leaking key
        material into the INI text itself, ``embedded`` keys are handled by
        ``AnsibleService.write_inventory``, which calls
        ``get_decrypted_key_value`` per host.
        """
        lines = ["[kvm_hosts]"]
        for host in hosts:
            # For path-type hosts the key path goes directly into the INI.
            # For embedded-type hosts, AnsibleService.write_inventory will
            # write a temp key file and substitute the path before passing
            # the inventory to Ansible.  We use a sentinel here so
            # write_inventory can locate and replace it.
            if host.ssh_key_type == "path":
                key_ref = host.ssh_key_value
            else:
                key_ref = f"__embedded_key_{host.name}__"

            lines.append(
                f"{host.name}"
                f"  ansible_host={host.kvm_host}"
                f"  ansible_user={host.ssh_user}"
                f"  ansible_ssh_private_key_file={key_ref}"
            )
        return "\n".join(lines) + "\n"

    def get_decrypted_key_value(self, host: Host) -> str:
        """Return the plaintext SSH key value for *host*.

        For ``path`` hosts: returns the path string unchanged.
        For ``embedded`` hosts: decrypts and returns the PEM content.
        """
        if host.ssh_key_type == "path":
            return host.ssh_key_value
        from crypto import decrypt_key
        return decrypt_key(host.ssh_key_value, self._settings.ssh_decryption_key)


# ---------------------------------------------------------------------------
# INI parser (module-level, no I/O)
# ---------------------------------------------------------------------------

def _parse_ini(ini_text: str) -> list[dict]:
    """Parse an Ansible INI inventory block into a list of host dicts.

    Returns a list of ``{"name", "kvm_host", "ssh_user", **extra_vars}``
    dicts.  Lines that are blank, comments, or group headers are skipped.
    Entries missing ``ansible_host`` or ``ansible_user`` are also skipped
    with a warning.
    """
    results = []
    for line in ini_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("["):
            continue

        parts = stripped.split()
        name = parts[0]

        host_vars: dict[str, str] = {}
        for part in parts[1:]:
            if "=" in part:
                k, _, v = part.partition("=")
                host_vars[k] = v

        kvm_host = host_vars.pop("ansible_host", None)
        ssh_user = host_vars.pop("ansible_user", None)

        if not kvm_host or not ssh_user:
            logger.warning(
                "seed_from_ini: skipping '%s' — missing ansible_host or ansible_user",
                name,
            )
            continue

        results.append({"name": name, "kvm_host": kvm_host, "ssh_user": ssh_user, **host_vars})

    return results