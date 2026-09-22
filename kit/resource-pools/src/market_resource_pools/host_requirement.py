"""Whether a Resource Pool's provider needs a host to deliver.

A pool names the fulfillment provider that executes its settlements. Some
providers connect to a host to deliver; a capacity declaration in such a pool
that names no host can be neither admitted nor placed, because nothing could
execute it. Site admission and settlement scheduling each recheck this, as they
recheck a pool's deliverable offering modes, so neither relies on the other
having refused first.

The requirement is supplied by the composition that registers the providers,
as plain data keyed by provider identity, so a layer applying it never imports
a provider. See openspec/specs/fulfillment/spec.md and
openspec/specs/site-capacity/spec.md.
"""

from __future__ import annotations

from collections.abc import Mapping

#: Provider identity -> whether that provider's delivery needs a host.
HostRequirement = Mapping[str, bool]


def pool_needs_host(
    provider: str | None,
    host_requirement: HostRequirement | None,
) -> bool:
    """Whether a declaration in a pool with ``provider`` must name a host.

    With no requirement supplied, nothing is required: a composition that
    registers no fulfillment provider (a quota authority, for example) never
    executes against a host. Once a requirement is supplied, a provider it does
    not name needs a host, because an undeclared provider is the case a guess
    would get wrong silently.
    """
    if host_requirement is None:
        return False
    if not isinstance(provider, str) or provider not in host_requirement:
        return True
    return bool(host_requirement[provider])
