"""Run the production bare-metal buyer commands against a served storefront.

The commands run through the core ``market`` application with the bare-metal
buyer installed, negotiate and settle over HTTP, and write and reload a real
run log, as a buyer runs them. What is doubled is replaced at the buyer CLI's
own factories, its one seam, and nowhere else: the registry client, serving the
one listing the test published; the buyer's profile, whose identity resolves to
the test's signer; and, where a test pays, the payments client behind the
buyer's approval.
"""

from __future__ import annotations

import json
import traceback
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from arkhai_bare_metal_buyer import cli as buyer_cli
from arkhai_bare_metal_buyer.plugin import domain as bare_metal_buyer
from core_buyer.cli import build_app
from market_arkhai_payments import PaymentApproval
from market_identity import Identity, Signer
from typer.testing import CliRunner


class ListingRegistry:
    """The buyer's registry client, serving the one listing it was given."""

    def __init__(self, listing: SimpleNamespace) -> None:
        self.listing = listing

    def __enter__(self) -> ListingRegistry:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def get_listing(self, listing_id: str) -> SimpleNamespace:
        assert listing_id == self.listing.listing_id
        return self.listing


def last_json_line(result: Any) -> dict:
    """The JSON a command printed last, once it is shown to have succeeded."""
    assert result.exit_code == 0, result.output + "".join(
        traceback.format_exception(result.exception) if result.exception else ()
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


class BuyerCommands:
    """One buyer's ``market bare-metal`` commands, over its own config and run logs.

    ``settings`` is appended to the ``[bare_metal]`` table and may open its
    subtables. ``delivered``, when given, is the file the buyer's own delivery
    sink writes each delivered introduction to.
    """

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        *,
        signer: Signer,
        registry_principal: Identity,
        settings: str = "",
        delivered: Path | None = None,
    ) -> None:
        identity = SimpleNamespace(
            profile_id=str(uuid.uuid4()), principal=signer.identity, signer=signer
        )
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        monkeypatch.setattr(buyer_cli, "fresh_identity", lambda: identity)
        monkeypatch.setattr(buyer_cli, "recovery_identity", lambda run_id: identity)
        registry = registry_principal.model_dump(mode="json")
        delivery = (
            f'[Delivery]\nenabled = ["file"]\n[Delivery.file]\npath = "{delivered}"\n'
            if delivered is not None
            else ""
        )
        self.config = tmp_path / "buyer.toml"
        self.config.write_text(
            delivery + "[bare_metal]\n"
            # A development fixture on a reserved domain, never to be used on a
            # public network; the registry client is doubled, so nothing calls it.
            'registry_url = "https://registry.invalid"\n'
            'registry_authority = "registry-a"\n'
            f'registry_principals = [{{scheme = "{registry["scheme"]}", '
            f'identifier = "{registry["identifier"]}"}}]\n' + settings,
            encoding="utf-8",
        )
        self._monkeypatch = monkeypatch
        self._app = build_app(domains=[bare_metal_buyer])
        self._runner = CliRunner()

    def serve(self, listing: SimpleNamespace) -> None:
        """Serve ``listing`` from the buyer's registry client."""
        self._monkeypatch.setattr(
            buyer_cli, "registry_client", lambda config, identity: ListingRegistry(listing)
        )

    def pay_through(self, payments: Any) -> None:
        """Back the buyer's approval with ``payments``, as its configuration states it."""
        self._monkeypatch.setattr(
            buyer_cli,
            "payment_approval",
            lambda config: PaymentApproval(
                config.arkhai_payments, config.payer_account, client_for_owner=payments
            ),
        )

    def run(self, *arguments: str) -> dict:
        """Run ``market bare-metal <arguments>`` and return the JSON it printed last."""
        return last_json_line(
            self._runner.invoke(
                self._app, ["bare-metal", *arguments, "--config", str(self.config)]
            )
        )
