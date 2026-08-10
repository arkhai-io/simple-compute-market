"""The VM domain's negotiation policies, offered per role.

The domain owns two seller-side guards and, when a chain asks for it, a
reinforcement-learning strategy. It offers no buyer-side policies. The generic
escrow vocabulary its chains interleave with is offered by the policy kit and
is not restated here.

The RL strategy is a separate source because loading it pulls in the strategy
module and its model-checkpoint handling. A storefront that never negotiates with
RL should not pay for that, so the domain offers the source only when the
composing role's configuration names one of its aliases. That decision belongs
here: the domain knows which of its own policies are expensive.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from market_policy import (
    InlineSource,
    NegotiationMiddleware,
    NegotiationPolicyRequest,
    NegotiationPolicySource,
    PolicyRole,
)

from domains.vms.negotiation.policies import (
    has_matching_inventory_guard,
    round_zero_opening_guard,
)

__all__ = [
    "RL_POLICY_NAMES",
    "VM_DEFAULT_SELLER_CHAIN",
    "VM_SELLER_POLICIES",
    "TorchStrategySource",
    "vm_policy_sources",
]

#: Seller-side guards this domain implements.
VM_SELLER_POLICIES: Mapping[str, NegotiationMiddleware] = {
    "round_zero_opening_guard": round_zero_opening_guard,
    "has_matching_inventory_guard": has_matching_inventory_guard,
}

#: Chain names served by the torch strategy. Naming any of these is what makes
#: loading the strategy worthwhile.
RL_POLICY_NAMES = frozenset({"rl", "erc20_rl", "native_token_rl", "erc1155_rl"})

#: Default seller chain: this domain's guards interleaved with the kit's, in
#: the order the domain requires, terminating in a kit price policy.
VM_DEFAULT_SELLER_CHAIN = (
    "round_zero_opening_guard",  # VM domain
    "buyer_counter_guard",  # market_policy
    "has_matching_inventory_guard",  # VM domain
    "escrow_shape_guard",  # market_policy
    "bisection",  # market_policy — terminal
)


@dataclass(frozen=True)
class TorchStrategySource:
    """The reinforcement-learning strategy, under each escrow-kind alias.

    Loading imports :mod:`domains.vms.negotiation.rl.torch_arkhai_strategy` and
    its checkpoint-loading machinery, so this source is offered only when a chain
    names one of :data:`RL_POLICY_NAMES`.

    Torch itself is imported lazily inside the strategy's own forward passes, not
    at module import, so composing this source does not by itself pull torch into
    the process — the first RL negotiation round does. What composition avoids is
    the strategy module and its dependency graph.

    It fails rather than degrading: a chain that asks for RL and receives a silent
    substitute negotiates under a strategy the operator did not choose.
    """

    def describe(self) -> str:
        return "vm-torch-strategy"

    def load(self) -> Mapping[str, NegotiationMiddleware]:
        from domains.vms.negotiation.rl.torch_arkhai_strategy import rl_middleware

        return {name: rl_middleware for name in sorted(RL_POLICY_NAMES)}


def vm_policy_sources(
    request: NegotiationPolicyRequest,
) -> tuple[NegotiationPolicySource, ...]:
    """The policies this domain offers to the requesting role."""
    if request.role is not PolicyRole.STOREFRONT:
        return ()
    sources: list[NegotiationPolicySource] = [
        InlineSource(VM_SELLER_POLICIES, label="vm-domain[storefront]"),
    ]
    if request.wants_any(RL_POLICY_NAMES):
        sources.append(TorchStrategySource())
    return tuple(sources)
