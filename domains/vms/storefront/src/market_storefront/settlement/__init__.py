"""VM-domain settlement helpers."""

from market_storefront.settlement.compute_lease import (
    encode_compute_lease,
    token_resource_from_accepted_escrow,
)
from market_storefront.settlement.fulfillment import (
    FulfillmentReconciliationUnavailable,
    find_compute_fulfillments,
    reconcile_or_submit_compute_fulfillment,
    submit_compute_fulfillment,
)

# Buyer-side escrow creation/selection (make_buyer_payment_escrow_terms_fn,
# make_create_escrow_fn, select_escrow_entry) moved to
# core_buyer.{escrow_client,escrow_selection}: they are buyer-role
# machinery, and concept modules import no core packages.
__all__ = [
    "FulfillmentReconciliationUnavailable",
    "encode_compute_lease",
    "find_compute_fulfillments",
    "reconcile_or_submit_compute_fulfillment",
    "submit_compute_fulfillment",
    "token_resource_from_accepted_escrow",
]
