"""Unambiguous encoding of operator-chosen identifier components.

Identifiers an operator chooses (a site's or a pool's, for example) are strings
with no character restrictions, so joining them with a delimiter is not
collision-free:
``("a", "b:c")`` and ``("a:b", "c")`` would join identically. Every component is
therefore written as its decimal length, a colon, and exactly that many
characters, which fixes each boundary regardless of content and makes a joined
key injective.

Stored listing derivation keys depend on this exact byte form; changing it
changes every stored key.
"""

from __future__ import annotations


def length_prefixed(value: str) -> str:
    """Encode one component as ``<len>:<value>``."""
    return f"{len(value)}:{value}"


def length_prefixed_join(*components: str) -> str:
    """Encode each component and join them with ``:``."""
    return ":".join(length_prefixed(component) for component in components)


__all__ = ["length_prefixed", "length_prefixed_join"]
