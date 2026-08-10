"""The API-credit domain's negotiation policies, offered per role.

Seller-side guards and the buyer-side key responder are different sets. A
storefront that could resolve ``answer_key_challenge`` would be able to name a
policy it must never run, which is precisely the question a per-role catalogue
exists to answer, so the offer is keyed by the requesting role.

The generic escrow vocabulary these chains interleave with is offered by the
policy kit and is not restated here. This domain offers only build-time
policies; the mechanisms a role may add are the role's to authorize.
"""

from __future__ import annotations

from collections.abc import Mapping

from market_policy import (
    InlineSource,
    NegotiationMiddleware,
    NegotiationPolicyRequest,
    NegotiationPolicySource,
    PolicyRole,
)

from domains.apicredits.negotiation.buyer_policies import answer_key_challenge
from domains.apicredits.negotiation.policies import (
    api_credits_round_zero_guard,
    credit_quota_guard,
    key_owned_by_buyer_wallet,
)

__all__ = [
    "API_CREDITS_BUYER_POLICIES",
    "API_CREDITS_DEFAULT_SELLER_CHAIN",
    "API_CREDITS_SELLER_POLICIES",
    "api_credits_policy_sources",
]

#: Seller-side guards this domain implements.
API_CREDITS_SELLER_POLICIES: Mapping[str, NegotiationMiddleware] = {
    "api_credits_round_zero_guard": api_credits_round_zero_guard,
    "credit_quota_guard": credit_quota_guard,
    "key_owned_by_buyer_wallet": key_owned_by_buyer_wallet,
}

#: Buyer-side responders this domain implements.
API_CREDITS_BUYER_POLICIES: Mapping[str, NegotiationMiddleware] = {
    "answer_key_challenge": answer_key_challenge,
}

#: Default seller chain: this domain's guards interleaved with the kit's, in
#: the order the domain requires, terminating in a kit price policy.
API_CREDITS_DEFAULT_SELLER_CHAIN = (
    "api_credits_round_zero_guard",  # arkhai-apicredits-domain
    "buyer_counter_guard",  # market_policy
    "credit_quota_guard",  # arkhai-apicredits-domain
    "key_owned_by_buyer_wallet",  # arkhai-apicredits-domain
    "escrow_shape_guard",  # market_policy
    "listed_price",  # market_policy — terminal
)

_BY_ROLE: Mapping[PolicyRole, Mapping[str, NegotiationMiddleware]] = {
    PolicyRole.STOREFRONT: API_CREDITS_SELLER_POLICIES,
    PolicyRole.BUYER: API_CREDITS_BUYER_POLICIES,
}


def api_credits_policy_sources(
    request: NegotiationPolicyRequest,
) -> tuple[NegotiationPolicySource, ...]:
    """The policies this domain offers to the requesting role."""
    return (
        InlineSource(
            _BY_ROLE[request.role],
            label=f"arkhai-apicredits-domain[{request.role.value}]",
        ),
    )
