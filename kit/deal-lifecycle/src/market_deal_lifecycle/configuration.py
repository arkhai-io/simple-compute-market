"""Role-owned dispute preferences and identity-bound credential references."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr

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
    api_key_env: Annotated[str, Field(pattern=r"^[A-Z_][A-Z0-9_]*$")]

    def resolve(self, environment: Mapping[str, str] | None = None) -> SecretStr:
        value = (os.environ if environment is None else environment).get(self.api_key_env)
        if not value:
            raise ValueError(f"dispute credential requires environment variable {self.api_key_env}")
        return SecretStr(value)


class DisputeConfig(BaseModel):
    """Configuration contains references only; no resolved credential is stored."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

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

