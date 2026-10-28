"""Unit tests for AdminSettleService.

These tests isolate the service logic from HTTP, the chain, and real inventory.
All external calls (verify_escrow_against_plan, _build_provisioning_job_spec)
are patched so the tests verify:

  1. verify_escrow_dry_run — correct delegation and result mapping
  2. evaluate_settle_dry_run — correct delegation and result mapping

The integration tests in test_settle_controller.py cover the full HTTP path.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from market_site_client import SiteCapacityClientError


@pytest.fixture
def db():
    return AsyncMock()


@pytest.fixture(autouse=True)
def _stub_chains(monkeypatch):
    """Inject a synthetic [chains.anvil] entry, and its address book in the
    Alkahest section, so verify_escrow_dry_run's chain lookup resolves and the
    chain-aware code path can run.
    """
    from market_config.config_loader import ChainConfig
    from market_storefront.utils import config as agent_config
    from tests._settings_overrides import replaced_setting

    monkeypatch.setattr(
        agent_config,
        "CHAINS",
        {
            "anvil": ChainConfig(
                name="anvil",
                rpc_url="http://anvil:8545",
                chain_id=31337,
            ),
        },
        raising=False,
    )
    with replaced_setting(
        "settlement",
        {
            "schema_version": 1,
            "priority": ["alkahest.v1"],
            "alkahest": {
                "enabled": True,
                "address_books": {"anvil": "/fake/alkahest.json"},
            },
        },
    ):
        yield


@pytest.fixture
def svc(db):
    from market_storefront.services.admin_settle_service import AdminSettleService
    return AdminSettleService(
        sqlite_client=db,
        alkahest_clients={"anvil": MagicMock()},
    )


_LISTING_ID = "listing-abc"
_ESCROW_UID = "escrow-xyz"
_LISTING_ROW = {
    "listing_id": _LISTING_ID,
    "status": "open",
    "listing_resource": {"gpu_model": "H200", "gpu_count": 1, "region": "California, US"},
    "demand_resource": {"token": {"symbol": "MOCK", "contract_address": "0x01", "decimals": 0}, "amount": 5000},
}


# ---------------------------------------------------------------------------
# verify_escrow_dry_run
# ---------------------------------------------------------------------------

_NEGOTIATION_ID = "neg-accepted"
_ESCROW_ADDRESS = "0x" + "11" * 20
_PLAN = {"obligations": [{"mechanism": "alkahest.v1"}], "service_terms": {}}


def _accepted_thread(*, mechanism: str = "alkahest.v1", terminal: str = "success"):
    """An accepted Alkahest deal's thread: its Agreement, proposal, and plan."""
    return {
        "negotiation_id": _NEGOTIATION_ID,
        "terminal_state": terminal,
        "agreement_bytes": json.dumps({"settlement": {"mechanism": mechanism}}).encode(),
        "settlement_data": {
            "accepted_escrow_proposal": {
                "chain_name": "anvil",
                "escrow_address": _ESCROW_ADDRESS,
                "expiration_unix": 1_900_000_000,
            }
        },
        "settlement_plan": _PLAN,
    }


class TestVerifyEscrowDryRun:
    @pytest.mark.parametrize("thread", [None, _accepted_thread(terminal="")])
    async def test_raises_value_error_without_an_accepted_negotiation(
        self, svc, db, thread
    ):
        """No accepted negotiation → ValueError (controller maps to 404)."""
        db.load_negotiation_thread_row.return_value = thread
        with pytest.raises(ValueError, match="not found"):
            await svc.verify_escrow_dry_run(
                escrow_uid=_ESCROW_UID, negotiation_id=_NEGOTIATION_ID
            )

    async def test_returns_valid_true_when_verification_passes(self, svc, db):
        """Verification against the plan succeeds → valid=True, no reason."""
        db.load_negotiation_thread_row.return_value = _accepted_thread()
        with patch(
            "market_storefront.services.admin_settle_service.verify_escrow_against_plan",
            new=AsyncMock(),
        ) as mock_verify:
            result = await svc.verify_escrow_dry_run(
                escrow_uid=_ESCROW_UID, negotiation_id=_NEGOTIATION_ID
            )
        mock_verify.assert_awaited_once()
        assert result["valid"] is True
        assert result["escrow_uid"] == _ESCROW_UID
        assert "reason" not in result or result.get("reason") is None

    async def test_returns_valid_false_when_verification_fails(self, svc, db):
        """EscrowVerificationError → valid=False with reason string."""
        from market_storefront.utils.escrow_verification import EscrowVerificationError
        db.load_negotiation_thread_row.return_value = _accepted_thread()
        with patch(
            "market_storefront.services.admin_settle_service.verify_escrow_against_plan",
            new=AsyncMock(side_effect=EscrowVerificationError("token mismatch")),
        ):
            result = await svc.verify_escrow_dry_run(
                escrow_uid=_ESCROW_UID, negotiation_id=_NEGOTIATION_ID
            )
        assert result["valid"] is False
        assert result["escrow_uid"] == _ESCROW_UID
        assert "token mismatch" in result["reason"]

    async def test_a_deal_not_settled_by_alkahest_is_not_valid(self, svc, db):
        db.load_negotiation_thread_row.return_value = _accepted_thread(
            mechanism="arkhai.payments.v1"
        )
        with patch(
            "market_storefront.services.admin_settle_service.verify_escrow_against_plan",
            new=AsyncMock(),
        ) as mock_verify:
            result = await svc.verify_escrow_dry_run(
                escrow_uid=_ESCROW_UID, negotiation_id=_NEGOTIATION_ID
            )
        mock_verify.assert_not_awaited()
        assert result["valid"] is False
        assert "does not select Alkahest" in result["reason"]

    async def test_verifies_against_the_committed_plan_on_the_accepted_contract(
        self, svc, db
    ):
        """The plan the deal committed, on the chain and escrow contract its
        accepted proposal names, as settlement verifies it."""
        db.load_negotiation_thread_row.return_value = _accepted_thread()
        with patch(
            "market_storefront.services.admin_settle_service.verify_escrow_against_plan",
            new=AsyncMock(),
        ) as mock_verify:
            await svc.verify_escrow_dry_run(
                escrow_uid=_ESCROW_UID, negotiation_id=_NEGOTIATION_ID
            )
        call_kwargs = mock_verify.call_args.kwargs
        assert call_kwargs["escrow_uid"] == _ESCROW_UID
        assert call_kwargs["settlement_plan"] == _PLAN
        assert call_kwargs["chain_name"] == "anvil"
        assert call_kwargs["escrow_address"] == _ESCROW_ADDRESS
        assert call_kwargs["alkahest_address_config_path"] == "/fake/alkahest.json"
        assert "alkahest_client" in call_kwargs


# ---------------------------------------------------------------------------
# evaluate_settle_dry_run
# ---------------------------------------------------------------------------

class TestEvaluateSettleDryRun:
    async def test_raises_value_error_when_listing_not_found(self, svc, db):
        """Missing listing → ValueError (controller maps to 404)."""
        db.load_listing.return_value = None
        with pytest.raises(ValueError, match="not found"):
            await svc.evaluate_settle_dry_run(
                escrow_uid=_ESCROW_UID,
                listing_id=_LISTING_ID,
                ssh_public_key="ssh-ed25519 test",
                duration_seconds=3600,
            )

    async def test_returns_would_submit_false_when_no_host_found(self, svc, db):
        """_build_provisioning_job_spec returns None → would_submit=False with reason."""
        db.load_listing.return_value = _LISTING_ROW
        with patch(
            "market_storefront.services.admin_settle_service._build_provisioning_job_spec",
            new=AsyncMock(return_value=None),
        ):
            result = await svc.evaluate_settle_dry_run(
                escrow_uid=_ESCROW_UID,
                listing_id=_LISTING_ID,
                ssh_public_key="",
                duration_seconds=3600,
            )
        assert result["would_submit"] is False
        assert result["escrow_uid"] == _ESCROW_UID
        assert result["reason"]

    async def test_returns_would_submit_true_with_host_details(self, svc, db):
        """_build_provisioning_job_spec returns spec → would_submit=True with host_id."""
        db.load_listing.return_value = _LISTING_ROW
        fake_spec = {
            "resource_id": "r-1",
            "host_id": "host-1",
            "required_attributes": {"gpu_model": "H200"},
            "ssh_public_key": "ssh-ed25519 test",
            "duration_seconds": 3600,
        }
        with patch(
            "market_storefront.services.admin_settle_service._build_provisioning_job_spec",
            new=AsyncMock(return_value=fake_spec),
        ):
            result = await svc.evaluate_settle_dry_run(
                escrow_uid=_ESCROW_UID,
                listing_id=_LISTING_ID,
                ssh_public_key="ssh-ed25519 test",
                duration_seconds=3600,
            )
        assert result["would_submit"] is True
        assert result["escrow_uid"] == _ESCROW_UID
        assert result["host_id"] == "host-1"
        # A preview cannot know the guest's name, which provisioning derives
        # from the reservation settle commits.
        assert "vm_target" not in result
        assert result["required_attributes"] == {"gpu_model": "H200"}

    async def test_a_held_negotiation_previews_its_held_resource(self, svc, db):
        """Settle commits the acceptance hold, so the preview reports the held
        resource's host rather than probing for free capacity."""
        db.load_listing.return_value = {
            **_LISTING_ROW,
            "listing_resource": {
                **dict(_LISTING_ROW.get("listing_resource") or {}),
                "resource_id": "r-held",
                "offering_mode": "vm",
            },
        }
        # Shaped as the site returns a reservation from reserving: its
        # placement (resource and host) is withheld; it names its site.
        db.load_capacity_hold.return_value = {
            "capacity_reservation_id": "res-held",
            "payload": {"capacity_reservation_id": "res-held", "site": "default"},
        }
        site = MagicMock()
        site.get_reservation = AsyncMock(
            return_value={"capacity_reservation_id": "res-held", "host_id": "host-held"}
        )
        runtime = MagicMock()
        runtime.site_client.return_value = site
        probe = AsyncMock()
        with patch(
            "market_storefront.services.admin_settle_service.build_capacity_runtime",
            return_value=runtime,
        ), patch(
            "market_storefront.services.admin_settle_service._build_provisioning_job_spec",
            new=probe,
        ):
            result = await svc.evaluate_settle_dry_run(
                escrow_uid=_ESCROW_UID,
                listing_id=_LISTING_ID,
                ssh_public_key="ssh-ed25519 test",
                duration_seconds=3600,
                negotiation_id="neg-held",
            )
        runtime.site_client.assert_called_once_with("default")
        site.get_reservation.assert_awaited_once_with("res-held")
        db.load_capacity_hold.assert_awaited_once_with(negotiation_id="neg-held")
        probe.assert_not_awaited()
        assert result["would_submit"] is True
        assert result["host_id"] == "host-held"
        assert result["capacity_reservation_id"] == "res-held"

    async def test_a_hold_the_site_no_longer_has_previews_no_host(self, svc, db):
        db.load_listing.return_value = {
            **_LISTING_ROW,
            "listing_resource": {
                **dict(_LISTING_ROW.get("listing_resource") or {}),
                "resource_id": "r-held",
                "offering_mode": "vm",
            },
        }
        db.load_capacity_hold.return_value = {
            "capacity_reservation_id": "res-gone",
            "payload": {"capacity_reservation_id": "res-gone", "site": "default"},
        }
        site = MagicMock()
        site.get_reservation = AsyncMock(
            side_effect=SiteCapacityClientError("not found", status_code=404)
        )
        runtime = MagicMock()
        runtime.site_client.return_value = site
        with patch(
            "market_storefront.services.admin_settle_service.build_capacity_runtime",
            return_value=runtime,
        ):
            result = await svc.evaluate_settle_dry_run(
                escrow_uid=_ESCROW_UID,
                listing_id=_LISTING_ID,
                ssh_public_key="",
                duration_seconds=3600,
                negotiation_id="neg-gone",
            )
        assert result["capacity_reservation_id"] == "res-gone"
        assert result["host_id"] is None

    async def test_a_negotiation_without_a_hold_probes(self, svc, db):
        """With no hold, settle reserves fresh capacity, so the preview probes."""
        db.load_listing.return_value = _LISTING_ROW
        db.load_capacity_hold.return_value = None
        probe = AsyncMock(return_value=None)
        with patch(
            "market_storefront.services.admin_settle_service._build_provisioning_job_spec",
            new=probe,
        ):
            result = await svc.evaluate_settle_dry_run(
                escrow_uid=_ESCROW_UID,
                listing_id=_LISTING_ID,
                ssh_public_key="",
                duration_seconds=3600,
                negotiation_id="neg-free",
            )
        probe.assert_awaited_once()
        assert result["would_submit"] is False

    async def test_passes_correct_args_to_build_spec(self, svc, db):
        """_build_provisioning_job_spec is called with listing and caller-supplied ssh_public_key."""
        db.load_listing.return_value = _LISTING_ROW
        with patch(
            "market_storefront.services.admin_settle_service._build_provisioning_job_spec",
            new=AsyncMock(return_value=None),
        ) as mock_build:
            await svc.evaluate_settle_dry_run(
                escrow_uid=_ESCROW_UID,
                listing_id=_LISTING_ID,
                ssh_public_key="ssh-ed25519 mykey",
                duration_seconds=7200,
            )
        call_kwargs = mock_build.call_args.kwargs
        assert call_kwargs["order_dict"] is _LISTING_ROW
        assert call_kwargs["ssh_public_key"] == "ssh-ed25519 mykey"
        assert call_kwargs["duration_seconds"] == 7200
        assert call_kwargs["sqlite_client"] is db

    async def test_no_db_write_on_evaluate(self, svc, db):
        """evaluate_settle_dry_run must not call any DB write methods."""
        db.load_listing.return_value = _LISTING_ROW
        with patch(
            "market_storefront.services.admin_settle_service._build_provisioning_job_spec",
            new=AsyncMock(return_value=None),
        ):
            await svc.evaluate_settle_dry_run(
                escrow_uid=_ESCROW_UID,
                listing_id=_LISTING_ID,
                ssh_public_key="",
                duration_seconds=3600,
            )
        # Only load_listing (read) should have been called — no insert/update
        db.load_listing.assert_awaited_once_with(listing_id=_LISTING_ID)
        for method_name in [
            "insert_settlement_job",
            "update_settlement_job",
            "update_listing",
            "upsert_listing",
        ]:
            getattr(db, method_name).assert_not_called()
