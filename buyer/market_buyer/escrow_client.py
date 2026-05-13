"""Buyer-side on-chain escrow creation via alkahest-py.

Two responsibilities, kept separate so future steps can swap out
either without disturbing the other:

1. ``make_buyer_payment_escrow_terms_fn`` — given env config (chain,
   token, expiration window), returns a builder that produces an
   ``EscrowTerms`` (the canonical negotiated artifact). Today, every
   negotiation outcome materializes as a single buyer-made
   ``ERC20EscrowObligation`` escrow with ``RecipientArbiter`` + the
   seller's wallet address as the demand recipient. Future steps
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
import time
from typing import Any, Callable, Optional

from service.schemas import EscrowTerms


logger = logging.getLogger(__name__)


BuildEscrowTermsFn = Callable[[str, int, int], list[EscrowTerms]]
"""``(seller_wallet, agreed_price, duration_seconds) -> list[EscrowTerms]``.

Returns the canonical escrow specs for a finalized negotiation. The list
shape (rather than a single EscrowTerms) is forward-looking for
multi-escrow designs (payment + seller penalty deposit, etc.). Today
the list is always length 1 with ``maker == "buyer"``.
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
    token_contract_address: str,
    expiration_seconds: int = 3600,
) -> BuildEscrowTermsFn:
    """Build a ``(seller_wallet, agreed_price, duration_seconds) -> [EscrowTerms]``
    closure.

    The closure resolves the per-chain ``RecipientArbiter`` and
    ``ERC20EscrowObligation`` addresses on first call (cached by the
    service.clients.alkahest layer), encodes the seller wallet as the
    arbiter's demand, computes the total payment as
    ``agreed_price * duration_seconds / 3600``, and stamps an absolute
    expiration ``now + expiration_seconds``.

    The amount formula and arbiter choice are today's hard-coded
    policy. Step 5 (arbiter codec) and step 6 (escrow SDK wrapper)
    will move these into pluggable codecs keyed by arbiter / escrow
    contract address; the closure's external signature stays the same.
    """
    def _build(
        seller_wallet_address: str, agreed_price: int, duration_seconds: int,
    ) -> list[EscrowTerms]:
        # Late imports — alkahest is heavyweight; tests that mock this
        # builder shouldn't pay for it.
        from service.clients.alkahest import (
            build_payment_obligation_data,
            get_erc20_escrow_obligation_nontierable,
        )

        # Canonical obligation_data — same helper the seller's verifier
        # calls, so both sides see identical expected values for the same
        # negotiated inputs.
        obligation_data = build_payment_obligation_data(
            seller_wallet=seller_wallet_address,
            agreed_price=agreed_price,
            duration_seconds=duration_seconds,
            token_contract_address=token_contract_address,
            chain_name=chain_name,
            addr_config_path=addr_config_path,
        )
        escrow_contract = get_erc20_escrow_obligation_nontierable(
            chain_name, config_path=addr_config_path,
        )
        expiration_unix = int(time.time()) + int(expiration_seconds)

        terms = EscrowTerms(
            maker="buyer",
            escrow_contract=escrow_contract,
            obligation_data=obligation_data,
            expiration_unix=expiration_unix,
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
