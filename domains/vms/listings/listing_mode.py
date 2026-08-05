"""VM-domain interpretation of the domain-neutral `listing_mode` hint.

`kit/resource-pools.hints` owns the key name and generic read; this module
owns what the VM domain accepts and what it structurally defaults to when
the tag is absent or unrecognized -- per this change's "Keep hints
advisory and domain-owned" decision, no other package encodes VM's
specific values.
"""

from __future__ import annotations

from typing import Any, Literal, Mapping

from market_resource_pools.hints import raw_listing_mode

VmListingMode = Literal["fungible", "specific_resource"]

_DEFAULT_VM_LISTING_MODE: VmListingMode = "fungible"
_VM_LISTING_MODES: tuple[VmListingMode, ...] = ("fungible", "specific_resource")


def resolve_vm_listing_mode(
    policy_tags: Mapping[str, Any],
) -> tuple[VmListingMode, str | None]:
    """Resolve a pool's `listing_mode` for VM publication.

    Returns ``(mode, explanation)``. ``explanation`` is ``None`` unless the
    raw tag was present but unrecognized, in which case the structural
    default is used and the explanation is meant to be surfaced on an
    operator-visible status surface (never fails projection ingestion or
    blocks publication).
    """
    raw = raw_listing_mode(policy_tags)
    if raw is None:
        return _DEFAULT_VM_LISTING_MODE, None
    if raw in _VM_LISTING_MODES:
        return raw, None  # type: ignore[return-value]
    return (
        _DEFAULT_VM_LISTING_MODE,
        f"unrecognized listing_mode {raw!r}, using {_DEFAULT_VM_LISTING_MODE!r}",
    )
