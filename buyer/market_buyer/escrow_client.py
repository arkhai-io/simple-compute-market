"""Buyer-side on-chain escrow creation via alkahest-py.

Two responsibilities, kept separate so future steps can swap out
either without disturbing the other:

1. ``make_buyer_payment_escrow_terms_fn`` — given env config (chain,
   token, expiration window), returns a builder that produces an
   ``EscrowTerms`` (the canonical negotiated artifact). Today, every
   negotiation outcome materializes as a single buyer-made
   ``ERC20EscrowObligation`` escrow with the listing/proposal-level
   arbiter ``demands`` encoded into the escrow demand bytes. Future steps
   replace the inlined arbiter encoding with an arbiter codec
   lookup; the builder's call signature stays stable.

2. ``make_create_escrow_fn`` — given chain creds, returns a thin
   submit hook ``Callable[[list[EscrowTerms]], list[str]]``. Each
   entry with ``maker == "buyer"`` is created on-chain in order; the
   returned uids match input order. Today supports ERC20 escrows
   only; readers extract the literal fields from
   ``obligation_data`` so adding new escrow kinds later just means
   wiring a per-contract SDK dispatcher in this function (step 6).

Both functions defer alkahest-py imports until they're actually
called, so importing this module (e.g. from tests that mock the
hooks) doesn't require a chain config.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from service.schemas import EscrowProposal, EscrowTerms


logger = logging.getLogger(__name__)


BuildEscrowTermsFn = Callable[
    [EscrowProposal, str | None, int, int], list[EscrowTerms],
]
"""``(proposal, legacy_recipient_fallback, agreed_amount, duration_seconds) -> list[EscrowTerms]``.

Materializes the seller-confirmed proposal (echoed back in the
negotiation response) into the canonical EscrowTerms list. The list
shape is forward-looking for multi-escrow designs (payment + seller
penalty deposit, etc.); today the list is always length 1 with
``maker == "buyer"``.
"""


CreateEscrowFn = Callable[[list[EscrowTerms]], list[str]]
"""Submit hook: ``list[EscrowTerms] -> list[escrow_uid]``.

Creates each buyer-made escrow on-chain in input order. Returned uids
match the order of input entries with ``maker == "buyer"``; if the
input list contains seller-made entries, those are skipped (the seller
has its own submit hook for them).
"""


def make_buyer_payment_escrow_terms_fn(
    *,
    chain_name: str,
    addr_config_path: Optional[str],
) -> BuildEscrowTermsFn:
    """Build a ``(proposal, legacy_recipient_fallback, agreed_amount, duration_seconds)
    -> [EscrowTerms]`` closure.

    The closure delegates to the canonical
    ``service.clients.alkahest.build_payment_obligation_data`` helper —
    same one the seller's verifier calls — so both sides produce
    identical obligation_data for the same negotiated inputs. The
    proposal's ``(chain_name, escrow_address)`` identifies the escrow
    contract via the reverse address lookup; ``fields["token"]``
    supplies the token; ``fields["arbiter"]`` (when present) overrides
    the default ``recipient_arbiter``. The closure's chain config is
    purely local plumbing (how to talk to the chain), not negotiated.

    ``agreed_amount`` is the absolute payment total in base units of the
    payment token — the negotiated artifact, already multiplied out from
    any per-hour rate. ``duration_seconds`` is carried into
    ``AgreementContext`` for codecs that bind the lease window into
    their demand.
    """
    def _build(
        proposal: EscrowProposal,
        seller_wallet_address: str,
        agreed_amount: int,
        duration_seconds: int,
    ) -> list[EscrowTerms]:
        # Late imports — alkahest is heavyweight; tests that mock this
        # builder shouldn't pay for it.
        from service.clients.alkahest import (
            address_to_slot,
            build_payment_obligation_data,
            get_escrow_codec_for,
        )
        from service.schemas import (
            accepted_demands,
            accepted_recipient_address,
            accepted_token_address,
        )

        # ERC20-only dispatch gate. Resolve the codec at build time so we
        # fail fast with a clear NotImplementedError when the proposal
        # references a non-ERC20 escrow contract. Phase 5 of the
        # generic-escrow templates rollout: other obligation kinds land
        # in later phases.
        codec = get_escrow_codec_for(
            proposal.chain_name, proposal.escrow_address,
            config_path=addr_config_path,
        )
        if codec.kind != "erc20_escrow_obligation_nontierable":
            raise NotImplementedError(
                f"Buyer dispatch not implemented for escrow kind "
                f"{codec.kind!r} at address {proposal.escrow_address!r} "
                f"(chain {proposal.chain_name!r}); ERC20 non-tierable only."
            )

        token = accepted_token_address(proposal)
        if not isinstance(token, str) or not token:
            raise ValueError(
                "EscrowProposal token missing or non-string — checked "
                "literal_fields['token']; cannot build buyer-side "
                "obligation_data"
            )
        demands = accepted_demands(proposal)
        recipient = accepted_recipient_address(proposal) or seller_wallet_address
        if not demands and (not isinstance(recipient, str) or not recipient):
            raise ValueError(
                "EscrowProposal demands missing and no legacy recipient fallback "
                "available; cannot build buyer-side "
                "obligation_data"
            )
        arbiter_kind = "recipient_arbiter"
        proposal_literal = proposal.literal_fields or {}
        proposal_arbiter = proposal_literal.get("arbiter")
        if isinstance(proposal_arbiter, str) and proposal_arbiter:
            arbiter_slot = address_to_slot(
                proposal.chain_name, proposal_arbiter,
                config_path=addr_config_path,
            )
            if arbiter_slot:
                arbiter_kind = arbiter_slot

        obligation_data = build_payment_obligation_data(
            demands=demands or None,
            recipient=recipient,
            agreed_amount=int(agreed_amount),
            duration_seconds=duration_seconds,
            token_contract_address=token,
            chain_name=chain_name,
            addr_config_path=addr_config_path,
            arbiter_kind=arbiter_kind,
        )

        terms = EscrowTerms(
            maker="buyer",
            escrow_contract=proposal.escrow_address,
            obligation_data=obligation_data,
            expiration_unix=proposal.expiration_unix,
        )
        return [terms]

    return _build


def make_create_escrow_fn(
    *,
    private_key: str,
    rpc_url: str,
    chain_name: str,
    addr_config_path: Optional[str],
) -> CreateEscrowFn:
    """Build the ``list[EscrowTerms] -> list[escrow_uid]`` submit hook.

    The hook is intentionally thin: it just submits each buyer-made
    ``EscrowTerms`` to its on-chain contract. All policy lives in
    ``EscrowTerms`` — the hook reads obligation_data fields by key,
    splits them into the SDK's expected shape, and submits.

    Today only the ERC20 non-tierable escrow contract is implemented;
    seeing any other ``escrow_contract`` address raises
    ``NotImplementedError``. Step 6 adds a per-contract dispatcher.
    """
    def _create(escrows: list[EscrowTerms]) -> list[str]:
        # Late imports for the same reason as the builder.
        from alkahest_py import AlkahestClient
        from service.clients.alkahest import (
            get_alkahest_network,
            get_escrow_kind_codec_by_address,
            prewarm_alkahest_address_config_cache,
            resolve_alkahest_address_config,
        )

        buyer_escrows = [e for e in escrows if e.maker == "buyer"]
        if not buyer_escrows:
            return []

        prewarm_alkahest_address_config_cache(addr_config_path)
        alkahest_network = get_alkahest_network(chain_name)
        address_config = resolve_alkahest_address_config(
            alkahest_network, config_path=addr_config_path,
        )

        client = AlkahestClient(
            private_key=private_key,
            rpc_url=rpc_url,
            address_config=address_config,
        )

        async def _do_one(escrow: EscrowTerms) -> str:
            # Codec lookup is the dispatch gate — an EscrowTerms whose
            # escrow_contract doesn't match a registered codec raises
            # at this point (rather than being silently misrouted).
            codec = get_escrow_kind_codec_by_address(
                escrow.escrow_contract, chain_name, config_path=addr_config_path,
            )
            logger.info(
                "[CLI_ESCROW] Creating escrow kind=%s contract=%s amount=%s exp=%s",
                codec.kind, escrow.escrow_contract,
                escrow.obligation_data.get("amount"), escrow.expiration_unix,
            )
            return await codec.create_obligation(
                client, escrow.obligation_data, escrow.expiration_unix,
            )

        async def _do_all() -> list[str]:
            return [await _do_one(e) for e in buyer_escrows]

        return _run_sync(_do_all())

    return _create


def _run_sync(coro):
    """Run an async coroutine from sync code, handling both with- and
    without-a-running-event-loop cases."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # If we're already inside a loop (e.g. a Jupyter notebook), schedule
    # and wait. This path is rare from the CLI but cheap to support.
    return loop.run_until_complete(coro)
