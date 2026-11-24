"""The terminal previews the authorized RFQ recipient before any mutation."""

import json
from types import SimpleNamespace

from market_core.rfq import (
    RfqAudience, RfqDetail, RfqInput, RfqInputContract, RfqMutationReceipt, RfqOperation, RfqTarget,
)
from market_identity import Ed25519Signer
import pytest
from typer.testing import CliRunner

from core_buyer import rfq_cli

# Deterministic test signer. Never use on a public network.
_PIN = Ed25519Signer(bytes([30]) * 32).identity
_AUDIENCE = RfqAudience(name="registry-test", principal=_PIN.model_dump(mode="json"))


@pytest.fixture
def captures(monkeypatch):
    exchanged = []

    class Account:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def read_detail(self, rfq_id):
            return self.exchange(RfqTarget(RfqOperation.READ, rfq_id), RfqInput())

        def exchange(self, target, inputs, *, request_id=None):
            exchanged.append((target, inputs, request_id))
            if target.operation == RfqOperation.READ:
                return RfqDetail(
                    rfq_id=target.rfq_id, kind="compute", registry=_AUDIENCE,
                    state="open", version=7, terms_revision=3,
                    requirements={"metadata": {"deposit": "30% upfront"}},
                    buyer_reference="intended-buyer",
                )
            return RfqMutationReceipt(resource_id="new-response", state="pending", version=1)

    monkeypatch.setattr(rfq_cli, "_configured_client", lambda *args, **kwargs: (Account(), _AUDIENCE))

    def mock_validator(body):
        return body

    contract = RfqInputContract("compute", mock_validator, mock_validator, mock_validator)
    app = rfq_cli.build_rfq_app([SimpleNamespace(buyer=SimpleNamespace(rfq_inputs=(contract,)))])
    return app, exchanged


@pytest.mark.parametrize("answer", ("n", "y"))
def test_terminal_previews_exact_contact_and_sends_only_after_confirmation(captures, tmp_path, answer):
    app, exchanged = captures
    contact = {"email": "seller@example.test", "handle": "seller-alias"}
    contact_file = tmp_path / "chosen-contact.json"
    contact_file.write_text(json.dumps(contact))

    result = CliRunner().invoke(
        app, ["respond", "test-rfq", "--request-id", "consent-id", "--contact-file", str(contact_file)],
        input=f"{answer}\n",
    )
    assert "registry-test" in result.stderr and _PIN.identifier in result.stderr
    assert "intended-buyer" in result.stderr
    assert "terms revision 3, record version 7" in result.stderr
    assert '"deposit": "30% upfront"' in result.stderr
    assert json.dumps(contact) in result.stderr
    assert "Share this contact" in result.stderr
    if answer == "n":
        assert result.exit_code == 1
        assert [entry[0].operation for entry in exchanged] == [RfqOperation.READ]
        assert result.stdout.strip() == "n"
    else:
        assert result.exit_code == 0, result.exception
        _, submission = exchanged
        target, inputs, request_id = submission
        assert target.operation == RfqOperation.RESPOND
        assert inputs.counterparty == "intended-buyer" and inputs.version == 7 and inputs.terms_revision == 3
        assert inputs.contact == contact and inputs.consent_to_share is True
        assert request_id == "consent-id"
        assert "contact" not in json.loads(result.stdout.splitlines()[-1])



def write_action(folder, *, registry=None, consent=True):
    path = folder / "action.json"
    path.write_text(json.dumps({
        "registry": registry or _AUDIENCE.model_dump(mode="json"),
        "request_id": "agent-consent-id",
        "inputs": {
            "version": 7,
            "terms_revision": 3,
            "counterparty": "intended-party",
            "consent_to_share": consent,
            "contact": {"email": "synthetic-party@example.test"},
        },
    }))
    return path


@pytest.mark.parametrize(("arguments", "operation"), [
    (["respond", "test-rfq"], RfqOperation.RESPOND),
    (["reconfirm", "test-rfq", "test-response"], RfqOperation.RECONFIRM),
    (["select", "test-rfq", "test-response"], RfqOperation.SELECT),
])
def test_noninteractive_action_preserves_explicit_preconditions(captures, tmp_path, arguments, operation):
    app, exchanged = captures

    result = CliRunner().invoke(app, [*arguments, "--inputs", str(write_action(tmp_path))])

    assert result.exit_code == 0, result.output
    assert not result.stderr
    [(target, payload, request_id)] = exchanged
    assert target.operation == operation
    assert target.rfq_id == "test-rfq"
    assert target.response_id == (arguments[2] if len(arguments) == 3 else None)
    assert request_id == "agent-consent-id"
    assert payload.version == 7 and payload.terms_revision == 3
    assert payload.counterparty == "intended-party"
    assert payload.consent_to_share is True
    assert payload.contact == {"email": "synthetic-party@example.test"}
    assert "contact" not in json.loads(result.stdout)


@pytest.mark.parametrize(("registry", "consent", "code"), [
    (None, 1, "rfq_invalid_action_inputs"),
    (_AUDIENCE.model_dump(mode="json") | {"name": "wrong-registry"}, True, "rfq_action_registry_mismatch"),
])
def test_noninteractive_action_refuses_invalid_input_before_exchange(captures, tmp_path, registry, consent, code):
    app, exchanged = captures
    action = write_action(tmp_path, registry=registry, consent=consent)

    result = CliRunner().invoke(app, ["select", "test-rfq", "test-response", "--inputs", str(action)])

    assert result.exit_code == 1
    assert json.loads(result.stderr) == {"code": code, "request_id": "agent-consent-id"}
    assert not exchanged


def test_noninteractive_sharing_refuses_invalid_target_without_dispatch(captures, tmp_path):
    app, exchanged = captures
    result = CliRunner().invoke(
        app, ["select", "wrong/path", "test-response", "--inputs", str(write_action(tmp_path))],
    )

    assert result.exit_code == 1
    assert json.loads(result.stderr) == {"code": "rfq_invalid_target"}
    assert not exchanged


def test_noninteractive_commands_report_input_errors_without_dispatch(captures, tmp_path):
    app, exchanged = captures
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[")
    cases = (
        (["create", "compute", "--inputs", str(invalid)], "rfq_invalid_input_file"),
        (["search", "unknown"], "rfq_kind_not_installed"),
        (["close", "rfq-test", "--version", "0"], "rfq_invalid_inputs"),
    )
    for arguments, code in cases:
        result = CliRunner().invoke(app, arguments)
        assert result.exit_code == 1
        assert json.loads(result.stderr) == {"code": code}
    assert not exchanged
