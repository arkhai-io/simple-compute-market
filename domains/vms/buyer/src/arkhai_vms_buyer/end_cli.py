"""The VM buyer's canonical ``end`` verb, registered from the buyer half."""

from __future__ import annotations

from market_deal_lifecycle_buyer import EndTarget, register_end_command
from rich.console import Console

from . import common
from .deal_helpers import (
    accepted_settlement_mechanism, load_deal_context,
    make_deal_publisher_trust_resolver, open_run_log,
)
from .settlement_composition import buyer_stage, resolve_buyer_settlement_policy
from .settlement_stages import BuyerResumeContext


def end_context(run_id, *, poll_interval, identity):
    identity = identity or common.resolve_recovery_buyer_identity(run_id)
    deal = load_deal_context(run_id, signer=identity.signer)
    stage = buyer_stage(accepted_settlement_mechanism(deal))
    log = open_run_log(run_id, signer=identity.signer, profile_id=identity.profile_id)
    context = BuyerResumeContext(
        run_id=run_id, deal=deal, log=log, signer=identity.signer,
        resolve_seller_principals=make_deal_publisher_trust_resolver(run_id, deal, identity.signer),
        resolve_policy=resolve_buyer_settlement_policy, resolve_address_book=common.chain_address_book,
        poll_interval=poll_interval, timeout=60, console=Console(),
    )

    return deal, log, stage.lifecycle(context)


def end_target(run_id: str, _config: str | None = None) -> EndTarget:
    """The run's deal, its lifecycle, and its run log for the ``end`` verb.

    The VM buyer reads no ``--config``. The resume context's poll interval paces
    settlement polling, which an end does not do.
    """
    deal, log, lifecycle = end_context(run_id, poll_interval=1, identity=None)
    return EndTarget(
        negotiation_id=deal.negotiation_id, lifecycle=lifecycle,
        record=lambda name, fields: log.event(name, **fields),
    )


def register(app):
    register_end_command(app, end_target)
