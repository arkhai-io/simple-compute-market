"""Disposable local-ledger diagnostic helpers; no production credentials."""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import httpx
from market_arkhai_payments import (
    ArkhaiPaymentsConfig,
    payments_client_for_owner,
)
from market_core.schemas import Agreement, SettlementOption, derive_settlement_option_id
from market_identity import Ed25519Signer

PAYER = "00000000-0000-4000-8000-000000000011"
PAYEE = "00000000-0000-4000-8000-000000000012"
DISPUTE = "00000000-0000-4000-8000-000000000013"
BUYER = Ed25519Signer(bytes([21]) * 32)
SELLER = Ed25519Signer(bytes([22]) * 32)
URL = os.environ.get("PAYMENTS_URL", "http://127.0.0.1:3180")
SEED_TX = "aa1b6ade7b07f1779e29cd0a9fe04ac427c55221dbb5d78c7c8feaf309c946af"


def config():
    response = httpx.get(URL + "/health", trust_env=False)
    response.raise_for_status()
    assert response.json()["status"] == "ok"
    settings = ArkhaiPaymentsConfig(
        enabled=True,
        service_url=URL,
        fee_bps=250,
        dispute_authority=DISPUTE,
        development_auth=True,
    )
    with payments_client_for_owner(settings, PAYER) as client:
        # Public pin from the checkout-owned seed transaction, not the tested mandate.
        identity = client.get_transaction(SEED_TX).snapshot.issuer
    return ArkhaiPaymentsConfig.model_validate(
        {**settings.model_dump(), "service_identity": identity.model_dump(mode="json")}
    )


def option():
    body = dict(
        mechanism="arkhai.payments.v1",
        asset="USD/2",
        rates=[],
        params=dict(
            payee_account=PAYEE, asset="USD/2", window="P7D", deposit_agreement=True
        ),
    )
    return SettlementOption(option_id=derive_settlement_option_id(**body), **body)


def agreement(negotiation_id, provision, duration=3600):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return Agreement(
        negotiation_id=negotiation_id,
        listing_id="listing-smoke",
        listing_hash="0" * 64,
        buyer=BUYER.identity.model_dump(mode="json"),
        seller=SELLER.identity.model_dump(mode="json"),
        settlement=option(),
        settlement_params={"payer_account": PAYER},
        amount=100,
        asset="USD/2",
        duration_seconds=duration,
        start_utc=now,
        accepted_at=now,
        provision_terms=provision,
    )


def effect(directory, identity):
    with sqlite3.connect(Path(directory) / "provider.db") as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS effects (id TEXT PRIMARY KEY)")
        conn.execute("INSERT OR IGNORE INTO effects VALUES (?)", (identity,))
        return conn.execute("SELECT COUNT(*) FROM effects").fetchone()[0]


def crash(message):
    print(message, flush=True)
    os._exit(75)
