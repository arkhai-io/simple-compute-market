"""Probe the selected bare-metal Alkahest gate with terminal journal state.

This is an isolated stage-library diagnostic, not a chain or hardware drive.
"""

import asyncio
from types import SimpleNamespace

from arkhai_bare_metal_storefront.settlement_composition import SELLER_STAGES


class Journal:
    async def get_status(self, negotiation):
        return SimpleNamespace(obligations=[SimpleNamespace(
            mechanism_ref="stale-ref", materialization_state="materialized",
            obligation_ref="stale-obligation", fulfillment_ref=None,
            reclaim_state="succeeded", mechanism_status="reclaimed",
        )])


async def main():
    service = SimpleNamespace(settlement_runtime=Journal())
    record = {"negotiation_id": "audit-neg", "settlement_ref": "stale-ref",
              "evidence": {"source": {"obligation_ref": "stale-obligation"}}}
    try:
        await SELLER_STAGES["alkahest.v1"].revalidate(service, {}, record)
        print("reclaimed_journal_authorized_by_revalidation=True")
    except Exception as error:
        print("refused=", type(error).__name__, str(error))


if __name__ == "__main__":
    asyncio.run(main())
