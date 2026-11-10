"""The double's identity and callers, read from its committed fixture file.

The fixture's values are public development values. The record key the fixture
states is checked against its seed, since lanes pin the stated key: a seed edited
without it would sign records every lane refuses. Only the accounts the fixture
names can call the double, each under its own token.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import ValidationError as SchemaValidationError
from market_arkhai_mediation.contract import INTERFACE, validate
from market_identity import Ed25519Signer


class FixtureError(ValueError):
    """A fixture file the double cannot serve from."""


@dataclass(frozen=True)
class AuthorityFixture:
    interface: str
    origin: str
    #: The authority's payments account, which extends, reverses and lifts.
    account: str
    params: dict[str, Any]
    record_seed: bytes
    record_key: str
    advertisement: dict[str, Any]
    #: The authority account's bearer token at the payments double.
    payments_token: str
    #: The bearer token of the control routes.
    control_token: str
    #: Each caller's bearer token and the payments account it acts as.
    tokens: Mapping[str, str]

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return self.interface, self.origin, self.account, self.record_key

    def signer(self) -> Ed25519Signer:
        return Ed25519Signer(self.record_seed)

    def account_for_token(self, token: str) -> str | None:
        return self.tokens.get(token)


def record_key_of(seed: bytes) -> str:
    """The record key an Ed25519 seed yields, as the contract spells one."""

    return "ed25519:" + Ed25519Signer(seed).identity.identifier


def load_authority(path: Path) -> AuthorityFixture:
    """Read and check the authority fixture file."""

    with path.open("rb") as handle:
        return parse_authority(tomllib.load(handle))


def parse_authority(document: Mapping[str, Any]) -> AuthorityFixture:
    try:
        interface = _text(document, "interface")
        if interface != INTERFACE:
            raise FixtureError(f"interface must be {INTERFACE}")
        seed = _seed(document, "record_seed")
        record_key = _text(document, "record_key")
        if record_key != record_key_of(seed):
            raise FixtureError("record_key is not the key of record_seed")
        authority = {"interface": interface, "origin": _text(document, "origin"),
                     "account": _text(document, "account"), "record_key": record_key,
                     "params": dict(document["params"])}
        validate("DisputeAuthority", authority)
        payments_token = _token(document, "payments_token")
        control_token = _token(document, "control_token")
        tokens: dict[str, str] = {}
        for role, entry in document["accounts"].items():
            account, token = _text(entry, "account"), _token(entry, f"accounts.{role}.token")
            validate("AccountId", account)
            if token in tokens:
                raise FixtureError("a bearer token is shared by two accounts")
            tokens[token] = account
    except KeyError as missing:
        raise FixtureError(f"authority fixture is missing {missing.args[0]!r}") from None
    except SchemaValidationError as error:
        raise FixtureError(f"authority fixture does not fit the contract: {error.message}") from None
    if len(set(tokens.values())) != len(tokens):
        raise FixtureError("an account appears twice in the authority fixture")
    # The control token must never also name a caller, or a caller holding it
    # would act at the API as that party.
    if control_token in tokens:
        raise FixtureError("control_token is also a caller's bearer token")
    return AuthorityFixture(
        interface=interface, origin=authority["origin"], account=authority["account"],
        params=authority["params"], record_seed=seed, record_key=record_key,
        advertisement=dict(document["advertisement"]), payments_token=payments_token,
        control_token=control_token, tokens=tokens,
    )


def _seed(document: Mapping[str, Any], key: str) -> bytes:
    try:
        seed = bytes.fromhex(_text(document, key))
    except ValueError:
        raise FixtureError(f"{key} must be 32 bytes of hex") from None
    if len(seed) != 32:
        raise FixtureError(f"{key} must be 32 bytes of hex")
    return seed


def _token(document: Mapping[str, Any], key: str) -> str:
    value = document[key.rsplit(".", 1)[-1]]
    if not isinstance(value, str) or not value or any(
            character.isspace() for character in value):
        raise FixtureError(f"{key} must be nonempty text without whitespace")
    return value


def _text(document: Mapping[str, Any], key: str) -> str:
    value = document[key]
    if not isinstance(value, str) or not value:
        raise FixtureError(f"{key} must be nonempty text")
    return value
