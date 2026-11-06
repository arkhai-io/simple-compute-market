"""Whether a capacity declaration in a Resource Pool has a host to deliver through.

A pool names the provider identity that delivers what its declarations sell.
Some providers deliver through a host, so a declaration in their pools that
names none cannot be delivered, and the layers that admit or place capacity
refuse it. Each layer rechecks, as each rechecks a pool's deliverable offering
modes, so none relies on another having refused first.

The requirement is plain data keyed by provider identity and supplied by the
composition that knows its providers, so a layer applying it imports no
provider.

Naming a host is not enough to deliver through it. Where a declaration's pool
is backed and its provider needs a host, the declaration has a usable host only
when it names a host that is registered and enabled; a declaration without one
is neither admitted, placed, nor projected enabled, since a listing whose
delivery has no usable host is the same as a listing with no host. Which hosts
take new delivery is the host registry's fact, so the composition that owns
hosts supplies a ``DeliverableHosts`` report, and each layer reads it in the
transaction that makes its decision, so the decision is judged against the host
state that transaction sees rather than against a copy read before it began.
The layers learn only host identifiers, never connection details. The
rule does not apply in an unbacked pool, which delivers nothing through a host,
nor where the provider needs no host. See
openspec/specs/site-capacity/spec.md#requirement-admission-applies-the-pool-providers-host-requirement.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from sqlalchemy.orm import Session

#: Provider identity -> whether declarations in that provider's pools must
#: name a host.
HostRequirement = Mapping[str, bool]


class DeliverableHosts(Protocol):
    """The hosts taking new delivery, as the composition owning hosts reports them."""

    def deliverable_host_ids(self, db: Session) -> frozenset[str]:
        """The identifiers of registered, enabled hosts, read in ``db``.

        Read in the caller's session, so the caller judges its decision against
        the host state its own transaction sees.
        """
        ...


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


def declaration_has_usable_host(
    host_id: str | None,
    provider: str | None,
    backed: bool,
    host_requirement: HostRequirement | None,
    deliverable: frozenset[str] | None,
) -> bool:
    """Whether a declaration naming ``host_id`` has a host to deliver through.

    True when no rule applies: no requirement is supplied, the pool is
    unbacked, or ``pool_needs_host`` says its provider needs none. Otherwise
    the declaration must name a host and, when ``deliverable`` is supplied,
    that host must be in it. With a requirement but no ``deliverable`` report,
    any named host is usable: a composition that supplies no report has given
    nothing to judge a host by.
    """
    if host_requirement is None or not backed:
        return True
    if not pool_needs_host(provider, host_requirement):
        return True
    if not host_id:
        return False
    if deliverable is None:
        return True
    return host_id in deliverable
