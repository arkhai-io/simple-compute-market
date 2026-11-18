"""The one rule every reader of a time value applies."""

from __future__ import annotations

import pytest

from injected_time import MAX_INSTANT, InvalidTime, check_instant, parse_time, read_time, time_document


@pytest.mark.parametrize("raw", [
    '{"now": true}',
    '{"now": false}',
    '{"now": 1794821400.5}',
    '{"now": 1794821400.0}',
    '{"now": "1794821400"}',
    '{"now": null}',
    '{"now": -1}',
    '{"now": 253402300800}',
    '{}',
    '{"now": 1794821400, "source": "injected"}',
    '{"now": 1794821400, "now": 1794822300}',
    '[1794821400]',
    '1794821400',
    '{"now": 1794821400',
    '',
    b'{"now": \xff}',
    '{"now": 1794821400}'.encode("utf-16"),
    '{"now": 1794821400}'.encode("utf-32"),
])
def test_every_invalid_document_is_refused_as_invalid_time(raw: str | bytes) -> None:
    with pytest.raises(InvalidTime) as refused:
        parse_time(raw)

    assert refused.value.code == "invalid_time"


@pytest.mark.parametrize("instant", [0, MAX_INSTANT, 1794821400])
def test_each_bound_and_an_instant_between_them_is_read(instant: int) -> None:
    assert parse_time(f'{{"now": {instant}}}') == instant
    assert parse_time(f'{{"now": {instant}}}'.encode()) == instant


def test_the_last_instant_is_the_last_second_of_the_year_9999() -> None:
    assert MAX_INSTANT == 253402300799


def test_a_refusal_names_what_is_wrong() -> None:
    with pytest.raises(InvalidTime, match="source"):
        parse_time('{"now": 1794821400, "source": "injected"}')
    with pytest.raises(InvalidTime, match='carries "now"'):
        parse_time("{}")
    with pytest.raises(InvalidTime, match="253402300800"):
        parse_time('{"now": 253402300800}')


def test_a_parsed_document_is_read_by_the_same_rule() -> None:
    assert read_time({"now": 1794821400}) == 1794821400
    with pytest.raises(InvalidTime):
        read_time({"now": True})
    with pytest.raises(InvalidTime):
        read_time(None)


def test_a_bare_instant_is_checked_by_the_same_rule() -> None:
    assert check_instant(0) == 0
    for value in (True, 1.0, "1", -1, MAX_INSTANT + 1, None):
        with pytest.raises(InvalidTime):
            check_instant(value)


def test_the_document_written_for_an_instant_reads_back_as_it() -> None:
    assert time_document(1794821400) == {"now": 1794821400}
    assert read_time(time_document(1794821400)) == 1794821400
    with pytest.raises(InvalidTime):
        time_document(-1)
