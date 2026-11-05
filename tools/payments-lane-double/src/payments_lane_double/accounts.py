"""The double's account directory: who may call it, under which token, and its policy.

Everything here is read from the committed fixture file, whose values are public
development values. The directory is the double's whole notion of an account: a
mandate naming an account outside it is refused as the service refuses an unknown
account, and an account with no token can never authenticate.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from market_arkhai_payments.models import AccountId
from market_identity import Ed25519Signer, Identity


class FixtureError(ValueError):
    """A fixture file the double cannot serve from."""


@dataclass(frozen=True)
class Account:
    role: str
    account: str
    token: str | None
    funding: int


@dataclass(frozen=True)
class AccountDirectory:
    asset: str
    fee_bps: int
    receipt_seed: bytes
    receipt_identity: Identity
    accounts: tuple[Account, ...]

    def account_for_token(self, token: str) -> str | None:
        for entry in self.accounts:
            if entry.token is not None and entry.token == token:
                return entry.account
        return None

    def knows(self, account: str) -> bool:
        return any(entry.account == account for entry in self.accounts)

    def role(self, role: str) -> Account:
        for entry in self.accounts:
            if entry.role == role:
                return entry
        raise KeyError(role)

    def signer(self) -> Ed25519Signer:
        return Ed25519Signer(self.receipt_seed)


def load_accounts(path: Path) -> AccountDirectory:
    """Read and check the account fixture file."""

    with path.open("rb") as handle:
        document = tomllib.load(handle)
    return parse_accounts(document)


def parse_accounts(document: Mapping[str, Any]) -> AccountDirectory:
    try:
        asset = _text(document, "asset")
        fee_bps = document["fee_bps"]
        if type(fee_bps) is not int or not 0 <= fee_bps <= 10_000:
            raise FixtureError("fee_bps must be an integer from 0 to 10000")
        seed = bytes.fromhex(_text(document, "receipt_seed"))
        if len(seed) != 32:
            raise FixtureError("receipt_seed must be 32 bytes of hex")
        signer = Ed25519Signer(seed)
        stated = Identity.model_validate(document["receipt_identity"])
        # The stated identity is what lanes pin; a seed edited without it would
        # sign receipts every lane refuses.
        if stated != signer.identity:
            raise FixtureError("receipt_identity is not the identity of receipt_seed")
        accounts = tuple(_account(role, value) for role, value in document["accounts"].items())
    except KeyError as missing:
        raise FixtureError(f"account fixture is missing {missing.args[0]!r}") from None
    accounts_seen = [entry.account for entry in accounts]
    if len(set(accounts_seen)) != len(accounts_seen):
        raise FixtureError("an account appears twice in the account fixture")
    tokens = [entry.token for entry in accounts if entry.token is not None]
    if len(set(tokens)) != len(tokens):
        raise FixtureError("a bearer token is shared by two accounts")
    return AccountDirectory(asset=asset, fee_bps=fee_bps, receipt_seed=seed,
                            receipt_identity=stated, accounts=accounts)


def _account(role: str, value: Mapping[str, Any]) -> Account:
    account = AccountId.model_validate(_text(value, "account")).root
    token = value.get("token")
    if token is not None and (not isinstance(token, str) or not token
                              or any(character.isspace() for character in token)):
        raise FixtureError(f"{role}'s token must be nonempty text without whitespace")
    funding_text = value.get("funding", "0")
    if not isinstance(funding_text, str) or not funding_text.isdigit():
        raise FixtureError(f"{role}'s funding must be a decimal string of minor units")
    return Account(role=role, account=account, token=token, funding=int(funding_text))


def _text(document: Mapping[str, Any], key: str) -> str:
    value = document[key]
    if not isinstance(value, str) or not value:
        raise FixtureError(f"{key} must be nonempty text")
    return value
