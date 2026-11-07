"""The credits storefront's two authority pins name the same service.

`storefront.credits.toml` pins the credits service's principal twice, on
purpose:

- `[capacity.sites.default.expected_authorities]` — the capacity poller's,
  owned by `market_capacity_publication`.
- `[credits.expected_authorities]` — the issuance and key-administration
  client's.

They are separate because they are separate privilege surfaces and the
capacity key is a dynaconf *list*, which merges rather than replaces: a
deployment appending a capacity authority must not silently widen what the
credits boundary accepts. The cost of that separation is that one
identifier is written twice in one file and could drift. This is what
stops the drift being silent.

Deliberately not a runtime coupling. The assertion holds only while both
keys are present, so a deployment that legitimately points capacity
somewhere else, or drops capacity publication entirely, is not broken by
it -- it just stops being checked here.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

_TOML = (
    Path(__file__).resolve().parents[1]
    / "storefront"
    / "storefront.credits.toml"
)


@pytest.fixture(scope="module")
def settings() -> dict:
    return tomllib.loads(_TOML.read_text(encoding="utf-8"))


def _identities(section: dict | None) -> list[dict]:
    if not section:
        return []
    return list(section.get("identities") or [])


def test_the_credits_client_has_an_authority_pinned(settings):
    """Without this the client silently stays on the shared secret.

    `credits_expected_authorities()` returns None when the key is absent,
    which leaves signing off. That is the right behaviour for a
    mid-flip deployment and the wrong one for this file, which configures
    the compose stack the e2e runs against -- where the service's own
    signing credential is selected and every route requires a signature.
    """
    pinned = _identities(settings.get("credits", {}).get("expected_authorities"))
    assert pinned, (
        "[credits.expected_authorities].identities is unset, so the "
        "storefront would not verify credits-service responses"
    )
    for entry in pinned:
        assert entry.get("scheme"), entry
        assert entry.get("identifier"), entry


def test_both_pins_name_the_same_authority(settings):
    """The duplication is accepted; divergence is not."""
    capacity = _identities(
        settings.get("capacity", {})
        .get("sites", {})
        .get("default", {})
        .get("expected_authorities")
    )
    credits = _identities(
        settings.get("credits", {}).get("expected_authorities")
    )
    if not capacity or not credits:
        pytest.skip("only one of the two authority pins is configured")

    def key(entries: list[dict]) -> set[tuple[str, str]]:
        return {(str(e["scheme"]), str(e["identifier"])) for e in entries}

    assert key(capacity) == key(credits), (
        "[capacity.sites.default.expected_authorities] and "
        "[credits.expected_authorities] point at the same credits service "
        "but pin different principals; one of them is stale"
    )


def test_the_pinned_authority_is_the_committed_dev_identity(settings):
    """The pin matches the private half the compose stack mounts.

    A rotation that updated the seed and not this file would otherwise
    surface as every credits call failing response verification against a
    live service -- the same class of error the comment above the capacity
    pin records having happened once already.
    """
    market_identity = pytest.importorskip("market_identity")
    seed_path = (
        Path(__file__).resolve().parents[3]
        / "dev-env"
        / "identities"
        / "api-credits-service.ed25519"
    )
    if not seed_path.exists():
        pytest.skip("dev identities are not present in this checkout")
    signer = market_identity.create_signer(
        "ed25519", seed_path.read_text(encoding="utf-8").strip()
    )
    pinned = {
        str(e["identifier"])
        for e in _identities(
            settings.get("credits", {}).get("expected_authorities")
        )
    }
    assert signer.identity.identifier in pinned, (
        f"[credits.expected_authorities] does not include "
        f"{signer.identity.identifier!r}, the public half of "
        f"{seed_path.name}"
    )
