from __future__ import annotations

import io
import json

from frp_grant_admission.config import ListenAddress, parse_config
from frp_grant_admission.decision_log import DecisionLog
from frp_grant_admission.reasons import Reason
from frp_grant_admission.request import Decision, decide_request
from tests.frps_request import new_proxy
from tests.rfc8032 import TEST_1_THUMBPRINT
from tests.vector_builder import CONFIGURATION, EXP, NOW, PORT, claims, forged, header

CONFIG = parse_config(CONFIGURATION)


def lines(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_an_admission_is_one_line_naming_the_proxy_and_the_verified_grant() -> None:
    stream = io.StringIO()
    request = new_proxy()

    DecisionLog(stream).decision(decide_request(request, CONFIG, NOW), NOW)

    assert lines(stream) == [
        {
            "ts": "2027-01-01T00:00:00Z",
            "event": "admit",
            "proxy": "host-1.guest-17",
            "type": "tcp",
            "remote_port": PORT,
            "issuer": "issuer-a",
            "kid": TEST_1_THUMBPRINT,
            "sub": "host-1",
            "jti": "grant-0001",
            "exp": EXP,
            "verified": True,
        }
    ]
    assert request["content"]["metas"]["grant"] not in stream.getvalue()


def test_a_forged_grant_is_logged_unverified_and_never_written() -> None:
    stream = io.StringIO()
    grant = forged(header(), claims())

    DecisionLog(stream).decision(decide_request(new_proxy(metas={"grant": grant}), CONFIG, NOW), NOW)

    (line,) = lines(stream)
    assert line["event"] == "refuse"
    assert line["reason"] == "signature_invalid"
    assert line["kid"] == TEST_1_THUMBPRINT
    assert line["verified"] is False
    for segment in grant.split("."):
        assert segment not in stream.getvalue()


def test_a_refusal_before_the_grant_names_what_the_request_sent_and_nothing_else() -> None:
    stream = io.StringIO()
    request = new_proxy(proxy_type="stcp", user={"user": "h", "metas": {"token": "secret"}})

    DecisionLog(stream).decision(decide_request(request, CONFIG, NOW), NOW)

    assert lines(stream) == [
        {
            "ts": "2027-01-01T00:00:00Z",
            "event": "refuse",
            "reason": "proxy_type_not_allowed",
            "proxy": "host-1.guest-17",
            "type": "stcp",
            "remote_port": PORT,
            "verified": False,
        }
    ]
    assert "secret" not in stream.getvalue()


def test_a_line_cannot_be_forged_by_a_proxy_name() -> None:
    stream = io.StringIO()
    name = 'x"}\n{"event":"admit'

    DecisionLog(stream).decision(Decision(Reason.GROUP_NOT_ALLOWED, proxy=name), NOW)

    assert len(stream.getvalue().splitlines()) == 1
    assert lines(stream)[0]["proxy"] == name


def test_a_number_json_cannot_carry_is_logged_as_text() -> None:
    stream = io.StringIO()
    request = new_proxy(proxy_name=float("nan"), remote_port=float("inf"))

    DecisionLog(stream).decision(decide_request(request, CONFIG, NOW), NOW)

    (line,) = lines(stream)
    assert "NaN" not in stream.getvalue()
    assert (line["proxy"], line["remote_port"]) == ("nan", "inf")


def test_a_value_nested_too_deeply_to_walk_still_gets_its_line() -> None:
    stream = io.StringIO()
    nested: object = []
    for _ in range(5000):
        nested = [nested]

    DecisionLog(stream).decision(Decision(Reason.PORT_INVALID, proxy=nested, remote_port=0), NOW)

    (line,) = lines(stream)
    assert line["proxy"] == "<nested too deeply to log>"
    assert line["remote_port"] == 0


def test_a_load_lists_each_issuer_its_range_and_its_keys() -> None:
    stream = io.StringIO()

    DecisionLog(stream).config_loaded(CONFIG, "startup", NOW)

    (line,) = lines(stream)
    assert line["event"] == "config_loaded"
    assert line["trigger"] == "startup"
    assert line["listen"] == "127.0.0.1:7300"
    assert [(i["name"], i["ports"], len(i["keys"])) for i in line["issuers"]] == [
        ("issuer-a", {"start": 6100, "end": 6199}, 2),
        ("issuer-b", {"start": 6200, "end": 6249}, 1),
    ]
    assert TEST_1_THUMBPRINT in line["issuers"][0]["keys"]
    assert "listen_at_restart" not in line


def test_a_reload_naming_another_listen_address_says_it_waits_for_a_restart() -> None:
    stream = io.StringIO()

    DecisionLog(stream).config_loaded(CONFIG, "reload", NOW, bound=ListenAddress("127.0.0.1", 7299))

    (line,) = lines(stream)
    assert line["listen"] == "127.0.0.1:7299"
    assert line["listen_at_restart"] == "127.0.0.1:7300"


def test_a_refused_load_lists_every_problem() -> None:
    stream = io.StringIO()

    DecisionLog(stream).config_refused(("first", "second"), "reload", NOW)

    (line,) = lines(stream)
    assert line["event"] == "config_refused"
    assert line["problems"] == ["first", "second"]
    assert line["kept"] == "the running configuration"
