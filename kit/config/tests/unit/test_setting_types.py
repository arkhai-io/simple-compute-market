"""The shared setting types: a usable duration and a site authority's origin."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from market_config import (
    MAX_SECONDS,
    PositiveSeconds,
    SiteAuthorityUrl,
    positive_seconds,
    site_authority_url,
)

SECONDS = TypeAdapter(PositiveSeconds)
ORIGIN = TypeAdapter(SiteAuthorityUrl)


@pytest.mark.parametrize(
    ("stated", "seconds"), [(5, 5.0), (0.25, 0.25), ("30", 30.0), (" 2.5 ", 2.5)]
)
def test_a_positive_number_of_seconds_is_read_as_a_float(stated, seconds):
    assert positive_seconds(stated) == seconds
    assert SECONDS.validate_python(stated) == seconds


@pytest.mark.parametrize(
    "stated",
    [
        True,
        False,
        0,
        -1,
        -0.5,
        float("nan"),
        float("inf"),
        float("-inf"),
        "nan",
        "inf",
        "soon",
        "",
        None,
        [5],
        10**400,
    ],
)
def test_a_value_that_is_not_a_positive_finite_number_is_refused(stated):
    with pytest.raises(ValueError):
        positive_seconds(stated)
    with pytest.raises(ValidationError):
        SECONDS.validate_python(stated)


def test_a_boolean_is_refused_by_name():
    with pytest.raises(ValueError, match="not a boolean"):
        positive_seconds(True)


def test_the_longest_duration_can_be_applied_to_any_instant_in_use():
    """The longest accepted duration subtracted from now, as a watchdog takes
    "now minus the timeout", stays after year 1, and added to an instant in
    the year 8000 stays before 9999. A value just above it is refused."""
    longest = positive_seconds(MAX_SECONDS)
    now = datetime.now(timezone.utc)

    assert (now - timedelta(seconds=longest)).year >= 1
    assert (datetime(8000, 1, 1) + timedelta(seconds=longest)).year < 9999
    with pytest.raises(ValueError, match="inside datetime's range"):
        positive_seconds(math.nextafter(MAX_SECONDS, math.inf))


@pytest.mark.parametrize("stated", [1e11, 1e14, 1e300, "1e14", MAX_SECONDS + 1])
def test_a_duration_that_would_leave_datetimes_range_is_refused(stated):
    """1e11 seconds builds a timedelta, but subtracted from now it overflows."""
    with pytest.raises(ValueError, match="inside datetime's range"):
        positive_seconds(stated)


@pytest.mark.parametrize("stated", [1e-7, 5e-7, 5e-324])
def test_a_duration_that_rounds_to_no_time_is_refused(stated):
    """Positive, but below half a microsecond a timedelta holds zero."""
    assert timedelta(seconds=stated) == timedelta(0)
    with pytest.raises(ValueError, match="at least a microsecond"):
        positive_seconds(stated)


def test_a_microsecond_is_accepted():
    assert positive_seconds(1e-6) == 1e-6


def test_a_refusal_names_no_value():
    with pytest.raises(ValueError) as refused:
        positive_seconds("123456789-secret")
    assert "123456789" not in str(refused.value)


def test_the_duration_schema_states_its_bounds():
    class Settings(BaseModel):
        interval: PositiveSeconds

    schema = Settings.model_json_schema(mode="validation")["properties"]["interval"]

    assert {key: schema[key] for key in ("type", "exclusiveMinimum", "maximum")} == {
        "type": "number",
        "exclusiveMinimum": 0,
        "maximum": MAX_SECONDS,
    }


@pytest.mark.parametrize(
    ("stated", "origin"),
    [
        ("http://site-a:8081", "http://site-a:8081"),
        ("https://site.example.test", "https://site.example.test"),
        ("  https://site.example.test/  ", "https://site.example.test"),
        ("HTTP://Site-A:8081/", "http://site-a:8081"),
        ("http://site-a:80", "http://site-a"),
        ("https://bücher.example", "https://xn--bcher-kva.example"),
        ("http://[::1]:8081", "http://[::1]:8081"),
        ("http://10.0.0.7:8081", "http://10.0.0.7:8081"),
    ],
)
def test_an_origin_is_accepted_as_the_url_standard_normalizes_it(stated, origin):
    assert site_authority_url(stated) == origin
    assert ORIGIN.validate_python(stated) == origin


@pytest.mark.parametrize("stated", ["http://@a", "http://:@a"])
def test_empty_credentials_are_dropped_by_the_parser(stated):
    assert site_authority_url(stated) == "http://a"


@pytest.mark.parametrize("stated", ["http://-", "http://site-a;x", "http://%41"])
def test_a_host_the_standard_accepts_is_accepted_whether_or_not_it_exists(stated):
    """The parser decides syntax, not existence: such a host fails as
    unreachable at the first poll."""
    assert site_authority_url(stated).startswith("http://")


@pytest.mark.parametrize(
    ("stated", "reason"),
    [
        (8081, "must be a string"),
        (None, "must be a string"),
        ("", "not a valid URL"),
        ("http://", "not a valid URL"),
        ("site-a:8081", "scheme is http or https"),
        ("ftp://site-a", "scheme is http or https"),
        ("https://user:pass@site.example.test", "without credentials"),
        ("https://token@site.example.test", "without credentials"),
        ("https://site.example.test?x=1", "without a query or fragment"),
        ("https://site.example.test/?", "without a query or fragment"),
        ("https://site.example.test#top", "without a query or fragment"),
        ("https://site.example.test#", "without a query or fragment"),
        ("https://site.example.test/v1", "without a path"),
        ("https://site.example.test//", "without a path"),
        ("https://site.example.test:bad", "not a valid URL"),
        ("https://site.example.test:70000", "not a valid URL"),
        ("http://site a", "not a valid URL"),
        ("http://si\tte-a", "without control characters"),
        ("http://site\n-a", "without control characters"),
        ("http://site\x00-a", "without control characters"),
        ("http://site-a\x7f", "without control characters"),
        ("https://site.example.test\n", "without control characters"),
        ("https://site.example.test\r\n", "without control characters"),
        ("\thttps://site.example.test", "without control characters"),
        (" https://site.example.test\t ", "without control characters"),
        ("http://[::1", "not a valid URL"),
    ],
)
def test_a_url_that_is_not_an_http_origin_is_refused(stated, reason):
    with pytest.raises(ValueError, match=reason):
        site_authority_url(stated)
    with pytest.raises(ValidationError):
        ORIGIN.validate_python(stated)


@pytest.mark.parametrize(
    "stated",
    [
        "https://operator:hunter2@site.example.test",
        "https://operator:hunter2\uff20site.example.test",
        "https://hunter2.example.test:hunter2",
        "http://hunter 2.example.test",
        "http://hunter2\t.example.test",
        "\thttps://hunter2.example.test",
        "https://hunter2.example.test\r\n",
    ],
)
def test_an_origin_refusal_carries_no_value_even_in_its_context(stated):
    """A parse error's message can quote the value, so the refusal is raised
    with no exception context at all, not only with its cause suppressed."""
    with pytest.raises(ValueError) as refused:
        site_authority_url(stated)
    assert "hunter2" not in str(refused.value)
    assert refused.value.__context__ is None
    assert refused.value.__cause__ is None


def test_a_duration_refusal_carries_no_context():
    with pytest.raises(ValueError) as refused:
        positive_seconds("123456789-secret")
    assert refused.value.__context__ is None


def test_the_origin_schema_is_a_string():
    class Settings(BaseModel):
        sites: dict[str, SiteAuthorityUrl]

    schema = Settings.model_json_schema(mode="validation")["properties"]["sites"]

    assert schema["additionalProperties"] == {"type": "string"}
