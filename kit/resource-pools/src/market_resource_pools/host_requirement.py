"""Whether a capacity declaration in a Resource Pool must name a host.

A pool names the provider identity that delivers what its declarations sell.
Some providers deliver through a host, so a declaration in their pools that
names none cannot be delivered, and the layers that admit or place capacity
refuse it. Each layer rechecks, as each rechecks a pool's deliverable offering
modes, so none relies on another having refused first.

The requirement is plain data keyed by provider identity and supplied by the
composition that knows its providers, so a layer applying it imports no
provider. See openspec/specs/site-capacity/spec.md.
"""

from __future__ import annotations

from collections.abc import Mapping

#: Provider identity -> whether declarations in that provider's pools must
#: name a host.
HostRequirement = Mapping[str, bool]


def pool_needs_host(
    provider: str | None,
    host_requirement: HostRequirement | None,
) -> bool:
    """Whether a declaration in a pool naming ``provider`` must name a host.

    With no requirement supplied, nothing is required: a composition that
    delivers nothing through hosts (a quota authority, for example) has no
    requirement to supply. Once a requirement is supplied, a provider it does
    not name needs a host, because an undeclared provider is the case a guess
    would get wrong silently. A value that is not a ``bool`` is refused rather
    than coerced, for the same reason.
    """
    if host_requirement is None:
        return False
    if not isinstance(provider, str) or provider not in host_requirement:
        return True
    needs_host = host_requirement[provider]
    if not isinstance(needs_host, bool):
        raise TypeError(
            f"host requirement for provider {provider!r} is not a bool"
        )
    return needs_host
