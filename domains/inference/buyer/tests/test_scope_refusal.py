"""A completed inference settlement shows the delivered key, the base URL, and the model name."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from arkhai_api_buying.stages import SettlementResume
from rich.console import Console

from arkhai_inference_buyer.cli import CONTRIBUTIONS


def test_a_completed_purchase_shows_the_key_the_base_url_and_the_model_name():
    credentials = {"key_id": "ik_existing", "base_url": "http://inference-gateway:8105/v1", "balance": 400}
    connection = json.dumps({
        "kind": "inference.v1", "service_name": "llama-3.1-8b", "base_url": credentials["base_url"],
        "key_id": "ik_existing", "quantity": 100,
    })
    output = io.StringIO()
    resume = SettlementResume(
        contributions=CONTRIBUTIONS,
        run_id="run-topup-1",
        deal=SimpleNamespace(),
        identity=SimpleNamespace(),
        settlement_config=lambda: None,
        options={},
        poll_interval=0.0,
        settlement_timeout=1.0,
        console=Console(file=output, width=200),
        credential_store=MagicMock(name="credential_store"),
    )
    final = {
        "status": "ready", "fulfillment_uid": "f-1",
        "connection_details": connection, "tenant_credentials": credentials,
    }

    log = MagicMock(name="log", run_id="run-topup-1", secrets=frozenset())

    assert resume.finish(
        log, final, reference=("Escrow UID", "0x" + "ee" * 32), end_fields={}, unready_border="yellow",
    ) is final

    rows = [line.strip("│ ").split() for line in output.getvalue().splitlines()]
    assert ["Key", "ID", "ik_existing"] in rows
    assert ["Base", "URL", "http://inference-gateway:8105/v1"] in rows
    assert ["Model", "llama-3.1-8b"] in rows
    log.end.assert_called_once_with("ready", fulfillment_uid="f-1")
