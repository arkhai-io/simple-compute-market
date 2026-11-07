from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from frp_grant_admission.cli import main, run_serve
from frp_grant_admission.decision_log import DecisionLog
from tests.rfc8032 import TEST_1_THUMBPRINT

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "config.toml"

INVALID = """\
listen = "0.0.0.0:7300"

[[issuers]]
name = "a"
audience = "relay-1"
ports = { start = 6100, end = 6199 }
keys = []

[[issuers]]
name = "b"
audience = "relay-1"
ports = { start = 6150, end = 6249 }
keys = [ { public_key = "not base64" } ]
"""


def test_check_prints_each_issuer_its_range_and_its_keys_thumbprints(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["check", str(EXAMPLE)]) == 0

    out = capsys.readouterr().out
    assert "listen 127.0.0.1:7300" in out
    assert "issuer issuer-a: audience relay-1, ports 6100-6199" in out
    assert "issuer issuer-b: audience relay-1, ports 6200-6249" in out
    assert f"  key {TEST_1_THUMBPRINT}" in out


def test_check_names_every_problem_of_a_file_that_does_not_load(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "config.toml"
    path.write_text(INVALID)

    assert main(["check", str(path)]) != 0

    err = capsys.readouterr().err
    assert "listen: '0.0.0.0:7300' is not an IPv4 address in 127.0.0.0/8" in err
    assert "issuers[0] ('a'): has no keys" in err
    assert "keys[0]: public_key is not the base64" in err
    assert "port ranges 6100-6199 and 6150-6249 overlap" in err


def test_check_names_a_file_that_cannot_be_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check", str(tmp_path / "absent.toml")]) != 0
    assert "cannot read" in capsys.readouterr().err


def test_serve_refuses_to_start_on_a_file_that_does_not_load(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(INVALID)
    stream = io.StringIO()

    assert run_serve(str(path), DecisionLog(stream)) == 1

    (line,) = [json.loads(text) for text in stream.getvalue().splitlines()]
    assert line["event"] == "config_refused"
    assert line["trigger"] == "startup"
    assert len(line["problems"]) == 4


def test_serve_requires_a_configuration(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        main(["serve"])

    assert exited.value.code != 0
