"""Real registry, shared account authority and shipped market client."""

from datetime import timedelta
import json
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from e2e_harness.settings import settings
import httpx
import injected_time
from market_core.rfq import RfqAccountRequest, RfqAudience, RfqOperation, RfqTarget, ShareContact
from market_identity import Ed25519Signer, Identity
import pytest
from registry_client.rfq_account import RfqAccountError, SyncRfqAccountClient

from tests.e2e.roles.buyer_cli import create_profiled_buyer_cli
from tests.e2e.roles.helpers.rfq_account_adapter import AccountAuthority, BrowserSessionTransport, serve_account_authority

# Matches the development profile's pin. Never use on a public network.
_SIGNER = Ed25519Signer(sha256(b"SCM development-only RFQ account authority").digest())


def _command(buyer, *arguments, contact=None, accept=True, error=None):
    input_text = None if contact is None else f"{contact}\n{'y' if accept else 'n'}\n"
    result = buyer.run(["rfq", *map(str, arguments)], timeout=35, input_text=input_text)
    if error is not None:
        assert result.returncode and error in result.stderr(), result.stderr()
        return None
    assert result.returncode == 0, result.stderr()
    return json.loads(result.stdout())


def _configured_buyer(binary, base: Path, token: str | None, *, origin: str, url: str, audience: RfqAudience):
    return create_profiled_buyer_cli(
        binary=binary, base=base, domain_identity="vms",
        marketplace_scheme=str(settings.BUYER.get("marketplace_scheme", "eip191")),
        marketplace_credential=str(settings.BUYER.MARKETPLACE_CREDENTIAL),
        registries=[url],
        registry_authorities={
            url: {"authority": audience.name, "identities": [audience.principal.model_dump(mode="json")]},
        },
        toml_sections=("[rfq]", f"account_origin = {json.dumps(origin)}", ""),
        credential_environment={"ARKHAI_RFQ_ACCOUNT_TOKEN": token or ""},
    )


@pytest.mark.e2e_buyer_rfq_introductions
def test_buyer_introduces_two_respondents_through_shipped_cli(buyer_cli_binary, tmp_path):
    url = str(settings.REGISTRY.API_URL).rstrip("/")
    pin = Identity(
        scheme=str(settings.REGISTRY.get("authority_scheme", "eip191")),
        identifier=str(settings.REGISTRY.IDENTIFIER),
    )
    audience = RfqAudience(name=str(settings.REGISTRY.AUTHORITY_ID), principal=pin.model_dump(mode="json"))
    authority = AccountAuthority(
        signer=_SIGNER, namespace="development", registries=[(audience, url)],
    )

    now = injected_time.now_datetime()
    base = {
        "shape": {"gpu_model": "B300", "gpu_count": 8},
        "node_count": 100, "regions": [f"rfq-introductions-{uuid4().hex}"],
        "start_earliest": (now.date() + timedelta(days=30)).isoformat(),
        "start_latest": (now.date() + timedelta(days=37)).isoformat(),
        "term": {"value": 6, "unit": "month"},
        "respond_by": (now + timedelta(days=14)).isoformat(timespec="seconds"),
    }
    requirements = tmp_path / "requirements.json"
    requirements.write_text(json.dumps(base))
    partial = tmp_path / "partial.json"
    partial.write_text(json.dumps({"offered_node_count": 40}))

    with serve_account_authority(authority) as origin:
        buyer_subject = uuid4().hex

        def participant(name, subject=None):
            account = authority.issue(subject or uuid4().hex, can_share_contact=True)
            return _configured_buyer(buyer_cli_binary, tmp_path / name, account.token, origin=origin, url=url, audience=audience)

        buyer = participant("buyer", buyer_subject)
        alice, bob, outsider = (participant(name) for name in ("alice", "bob", "outsider"))
        created = _command(buyer, "create", "compute", "--inputs", requirements)
        rfq_id = created["resource_id"]
        intro_ids = []
        try:
            visitor = _configured_buyer(buyer_cli_binary, tmp_path / "visitor", None, origin=origin, url=url, audience=audience)
            public_request = _command(visitor, "show", rfq_id)
            assert public_request["requirements"] == base
            assert "buyer_reference" not in public_request
            _command(alice, "respond", rfq_id, "--offer", partial, contact="alice@example.test",
                     accept=False, error="Contact sharing cancelled.")
            assert _command(buyer, "responses", rfq_id)["responses"] == []

            first = _command(alice, "respond", rfq_id, "--offer", partial, contact="alice@example.test")
            bob_view = _command(bob, "show", rfq_id)
            bob_request = RfqAccountRequest(
                registry=audience, request_id=uuid4().hex, inputs={
                    "version": bob_view["version"],
                    "terms_revision": bob_view["terms_revision"],
                    "counterparty": bob_view["buyer_reference"],
                    "consent_to_share": True,
                    "contact": {"email": "bob@example.test"},
                },
            )
            bob_input = tmp_path / "bob-response.json"
            wrong_party = bob_request.model_copy(update={
                "request_id": uuid4().hex,
                "inputs": bob_request.inputs | {"counterparty": "wrong-buyer"},
            })
            bob_input.write_text(wrong_party.model_dump_json())
            _command(bob, "respond", rfq_id, "--inputs", bob_input, error="rfq_counterparty_changed")
            bob_input.write_text(bob_request.model_dump_json())
            second = _command(bob, "respond", rfq_id, "--inputs", bob_input)
            first_id, second_id = first["resource_id"], second["resource_id"]
            rows = _command(buyer, "responses", rfq_id)["responses"]
            assert len(rows) == 2
            assert next(row for row in rows if row["response_id"] == first_id)["offered_quantity"] == 40
            assert all("contact" not in row for row in rows)

            current = _command(buyer, "show-response", rfq_id, first_id)
            select_target = RfqTarget(RfqOperation.SELECT, rfq_id, first_id)
            selection_id = uuid4().hex
            authority.drop_next_acknowledgement(select_target.path)
            one = _command(
                buyer, "select", rfq_id, first_id, "--request-id", selection_id, contact="buyer@example.test",
            )
            first_intro = one["introduction_id"]
            intro_ids.append(first_intro)
            own_read = uuid4().hex
            assert _command(
                buyer, "show-introduction", first_intro, "--request-id", own_read,
            )["contact"] == {"email": "alice@example.test"}
            assert _command(alice, "show-introduction", first_intro)["contact"] == {"email": "buyer@example.test"}
            _command(outsider, "show-introduction", first_intro, error="rfq_introduction_not_found")
            session = authority.issue(buyer_subject, can_share_contact=True, browser=True)
            selection = ShareContact(
                version=current["version"], terms_revision=current["terms_revision"],
                counterparty=current["respondent_reference"], consent_to_share=True,
                contact={"email": "buyer@example.test"},
            )
            replay_request = RfqAccountRequest(
                registry=audience, request_id=selection_id, inputs=selection.model_dump(mode="json"),
            )
            # Verify the adapter refuses a browser write without a CSRF proof.
            with httpx.Client(base_url=origin, cookies={"rfq_session": session.token}) as browser:
                replay_body = replay_request.model_dump(mode="json")
                unprotected = browser.post(select_target.path, json=replay_body)
                assert unprotected.status_code == 403
            with SyncRfqAccountClient(
                origin, credential=session.token, registry=audience, transport=BrowserSessionTransport(session),
            ) as browser:
                replay = browser.select(rfq_id, first_id, selection, request_id=selection_id)
                changed = selection.model_copy(update={"contact": {"email": "different@example.test"}})
                with pytest.raises(RfqAccountError, match="rfq_request_id_reused"):
                    browser.select(rfq_id, first_id, changed, request_id=selection_id)
                shared = browser.read_introduction(first_intro)
            assert replay.model_dump(mode="json", exclude_none=True) == one
            assert shared.model_dump(mode="json", exclude_none=True) == _command(
                buyer, "show-introduction", first_intro,
            )

            second_view = _command(buyer, "show-response", rfq_id, second_id)
            stale_action = RfqAccountRequest(
                registry=audience, request_id=uuid4().hex, inputs={
                    "version": second_view["version"],
                    "terms_revision": second_view["terms_revision"],
                    "counterparty": second_view["respondent_reference"],
                    "consent_to_share": True,
                    "contact": {"email": "buyer@example.test"},
                },
            )
            stale_file = tmp_path / "stale-selection.json"
            stale_file.write_text(stale_action.model_dump_json())
            replacement = tmp_path / "amended.json"
            replacement.write_text(json.dumps(base | {"node_count": 80}))
            edited = _command(buyer, "edit", rfq_id, "--inputs", replacement, "--version", 1)
            assert edited["terms_revision"] == 2
            _command(buyer, "select", rfq_id, second_id, contact="buyer@example.test", error="stale_rfq_terms")
            for _ in range(2):
                refused = buyer.run(["rfq", "select", rfq_id, second_id, "--inputs", str(stale_file)], timeout=35)
                assert refused.returncode != 0
                error_line = refused.stderr().splitlines()[-1]
                error = json.loads(error_line)
                assert error == {
                    "code": "stale_rfq_version", "request_id": stale_action.request_id,
                }, error
            renewed = _command(bob, "reconfirm", rfq_id, second_id, contact="bob@example.test")
            two = _command(buyer, "select", rfq_id, renewed["resource_id"], contact="buyer@example.test")
            second_intro = two["introduction_id"]
            intro_ids.append(second_intro)
            assert first_intro != second_intro
            assert _command(buyer, "show-introduction", second_intro)["contact"] == {"email": "bob@example.test"}
            assert _command(bob, "show-introduction", second_intro)["contact"] == {"email": "buyer@example.test"}
            _command(alice, "show-introduction", second_intro, error="rfq_introduction_not_found")

            _command(alice, "end-introduction", first_intro, "--version", 1)
            intro_ids.remove(first_intro)
            _command(buyer, "show-introduction", first_intro, "--request-id", own_read, error="rfq_contact_ended")
            assert _command(buyer, "show-introduction", second_intro)["contact"] == {"email": "bob@example.test"}
        finally:
            for introduction in intro_ids:
                _command(buyer, "end-introduction", introduction, "--version", 1)
            latest = _command(buyer, "show", rfq_id)
            _command(buyer, "close", rfq_id, "--version", latest["version"])
