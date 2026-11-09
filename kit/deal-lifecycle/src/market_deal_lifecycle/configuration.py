"""Role-owned dispute preferences and identity-bound credentials."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from typing import Annotated, Literal

from pydantic import (
    BaseModel, ConfigDict, Field, JsonValue, SecretStr, field_validator, model_validator,
)

from .terms import AuthorityRequirements, DisputeAuthority, NonnegativeSeconds


class AuthorityIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    interface: Annotated[str, Field(min_length=1)]
    origin: str
    account: Annotated[str, Field(min_length=1)]
    record_key: Annotated[str, Field(min_length=1)]

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return self.interface, self.origin, self.account, self.record_key


class AuthorityAdvertisement(BaseModel):
    """The advertised compatibility and minima used without a network fetch.

    Additional published policy is retained as JSON, not interpreted by the
    neutral layer. Interface adapters own its meaning.
    """

    model_config = ConfigDict(extra="allow", frozen=True, strict=True)
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)

    mechanisms: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)
    minimum_dispute_window_seconds: NonnegativeSeconds
    minimum_case_hold_seconds: NonnegativeSeconds | None = None


class DisputeEntry(DisputeAuthority):
    advertisement: AuthorityAdvertisement
    not_offered: bool = False
    not_accepted: bool = False

    @property
    def authority(self) -> DisputeAuthority:
        return DisputeAuthority.model_validate(
            self.model_dump(include={"interface", "origin", "account", "record_key", "params"})
        )

    @property
    def requirements(self) -> AuthorityRequirements:
        return AuthorityRequirements(
            self.authority,
            frozenset(self.advertisement.mechanisms),
            self.advertisement.minimum_dispute_window_seconds,
            self.advertisement.minimum_case_hold_seconds,
        )


class DisputeCredential(AuthorityIdentity):
    """One credential bound to an authority's whole identity, in exactly one form.

    ``api_key`` is the token itself, a secret setting a service states in its
    secret overlay; ``api_key_env`` names the environment variable holding it.
    ``ca_bundle_path`` names a PEM bundle the authority's mediation client alone
    verifies it under; absent, the client uses the default trust store.
    """

    # A validation error never shows the entry's input, which may hold the token.
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, hide_input_in_errors=True,
    )

    # Marked secret, as every credential setting is.
    api_key: SecretStr | None = Field(default=None, json_schema_extra={"secret": True})
    api_key_env: Annotated[str, Field(pattern=r"^[A-Z_][A-Z0-9_]*$")] | None = None
    ca_bundle_path: str | None = None

    @field_validator("ca_bundle_path")
    @classmethod
    def _refuse_empty_bundle(cls, value: str | None) -> str | None:
        # An empty path names no bundle, so it is refused where the configuration
        # is read rather than when a client is first built for a deal.
        if value is not None and not value.strip():
            raise ValueError("ca_bundle_path must name a file")
        return value

    @field_validator("api_key")
    @classmethod
    def _refuse_unusable_key(cls, value: SecretStr | None) -> SecretStr | None:
        # The rules a mediation credential applies to its token, so a stated key
        # that resolves is one a client can send. The message never quotes it.
        token = value.get_secret_value() if value is not None else None
        if token is not None and (
            not token or token != token.strip() or "\r" in token or "\n" in token
        ):
            raise ValueError("api_key must be nonempty, unpadded and on one line")
        return value

    @model_validator(mode="after")
    def _one_form(self) -> DisputeCredential:
        if self.api_key is not None and self.api_key_env is not None:
            raise ValueError("api_key and api_key_env are mutually exclusive")
        if self.api_key is None and self.api_key_env is None:
            raise ValueError("a dispute credential requires api_key or api_key_env")
        return self

    def resolve(self, environment: Mapping[str, str] | None = None) -> SecretStr:
        """The token, from whichever form the entry states.

        Raises ``ValueError`` naming the variable when it is unset or empty, which
        a role reads as holding no usable credential for the authority.
        """
        if self.api_key is not None:
            return self.api_key
        source = os.environ if environment is None else environment
        value = source.get(self.api_key_env) if self.api_key_env is not None else None
        if not value:
            raise ValueError(f"dispute credential requires environment variable {self.api_key_env}")
        return SecretStr(value)


class DisputeConfig(BaseModel):
    """Preferences and credentials; a credential is resolved only when it is used."""

    # A credential entry may hold its token, so no validation error shows input.
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, hide_input_in_errors=True,
    )

    entries: list[DisputeEntry] = Field(default_factory=list)
    credentials: list[DisputeCredential] = Field(default_factory=list)
    use_registry_dispute_authorities: bool = False

    def authorities(
        self,
        recommendations: Iterable[DisputeEntry | Mapping] = (),
        *,
        role: Literal["buyer", "seller"],
    ) -> tuple[DisputeEntry, ...]:
        entries = list(self.entries)
        if self.use_registry_dispute_authorities:
            entries.extend(
                item if isinstance(item, DisputeEntry) else DisputeEntry.model_validate(dict(item))
                for item in recommendations
            )
        seen = set()
        resolved = []
        for entry in entries:
            # A local veto must not be undone by a registry copy of the same
            # identity, and a registry cannot replace locally accepted params.
            if entry.identity in seen:
                continue
            seen.add(entry.identity)
            excluded = entry.not_offered if role == "seller" else entry.not_accepted
            if excluded:
                continue
            resolved.append(entry)
        return tuple(resolved)

    def credential_for(self, authority: DisputeAuthority | AuthorityIdentity) -> DisputeCredential | None:
        matches = [item for item in self.credentials if item.identity == authority.identity]
        if len(matches) > 1:
            raise ValueError("duplicate DisputeCredential bindings for authority identity")
        return matches[0] if matches else None


def dispute_config(document: Mapping, *, role: Literal["buyer", "seller"]) -> DisputeConfig:
    """Read root TOML entries, including case-insensitive settings mappings."""
    root = {str(key).lower(): value for key, value in document.items()}
    return DisputeConfig.model_validate({
        "entries": root.get("dispute", []),
        "credentials": root.get("disputecredential", []),
        "use_registry_dispute_authorities": root.get(
            "use_registry_dispute_authorities", role == "seller"
        ),
    })


def authorities_by_registry(
    config: DisputeConfig,
    recommendations: Mapping[str, Iterable[DisputeEntry | Mapping]],
    *,
    role: Literal["buyer", "seller"],
    report: Callable[[str], None],
) -> dict[str, tuple[DisputeEntry, ...]]:
    """Compose each registry independently; local preferences always win.

    The empty key holds local-only policy for work with no source registry.
    Credentials are resolved separately, never in this public projection.
    """
    resolved = {"": config.authorities(role=role)}
    for url, entries in recommendations.items():
        resolved[url.rstrip("/")] = config.authorities(entries, role=role)
    targets = recommendations or {"": ()}
    for url in targets:
        if not resolved[url.rstrip("/")]:
            report(f"{url}: {NO_DISPUTE_AUTHORITIES}" if url else NO_DISPUTE_AUTHORITIES)
    return resolved


NO_DISPUTE_AUTHORITIES = (
    "No dispute authority is available: configure [[Dispute]] or set "
    "use_registry_dispute_authorities = true to use the registry's recommendations; "
    "no hosted options can be offered or accepted."
)

