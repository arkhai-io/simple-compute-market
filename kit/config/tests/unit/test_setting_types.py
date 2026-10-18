"""The shared setting types: a usable duration and a site authority's origin."""

from __future__ import annotations

import math
from datetime import timedelta

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


def test_every_accepted_duration_builds_a_timedelta():
    """The bound itself is refused: it rounds up to a float timedelta cannot
    hold. The largest float below it is accepted and builds one."""
    largest = math.nextafter(MAX_SECONDS, 0)

    assert timedelta(seconds=positive_seconds(largest))
    with pytest.raises(OverflowError):
        timedelta(seconds=MAX_SECONDS)


@pytest.mark.parametrize("stated", [MAX_SECONDS, 1e14, 1e300, "1e14"])
def test_a_duration_timedelta_cannot_hold_is_refused(stated):
    with pytest.raises(ValueError, match="longest duration a timedelta holds"):
        positive_seconds(stated)


def test_a_refusal_names_no_value():
    with pytest.raises(ValueError) as refused:
        positive_seconds("123456789-secret")
    assert "123456789" not in str(refused.value)


def test_the_duration_schema_states_its_bounds():
    class Settings(BaseModel):
        interval: PositiveSeconds

    schema = Settings.model_json_schema(mode="validation")["properties"]["interval"]

    assert {key: schema[key] for key in ("type", "exclusiveMinimum", "exclusiveMaximum")} == {
        "type": "number",
        "exclusiveMinimum": 0,
        "exclusiveMaximum": MAX_SECONDS,
    }


@pytest.mark.parametrize(
    ("stated", "origin"),
    [
        ("http://site-a:8081", "http://site-a:8081"),
        ("https://site.example.test", "https://site.example.test"),
        ("  https://site.example.test/  ", "https://site.example.test"),
        ("HTTP://site-a", "HTTP://site-a"),
        ("http://[::1]:8081", "http://[::1]:8081"),
    ],
)
def test_an_origin_is_accepted_without_its_trailing_slash(stated, origin):
    assert site_authority_url(stated) == origin
    assert ORIGIN.validate_python(stated) == origin


@pytest.mark.parametrize(
    ("stated", "reason"),
    [
        (8081, "must be a string"),
        (None, "must be a string"),
        ("", "scheme is http or https"),
        ("site-a:8081", "scheme is http or https"),
        ("ftp://site-a", "scheme is http or https"),
        ("http://", "naming a host"),
        ("http://:8081", "naming a host"),
        ("https://user:pass@site.example.test", "without credentials"),
        ("https://token@site.example.test", "without credentials"),
        ("https://site.example.test?x=1", "without a query or fragment"),
        ("https://site.example.test/?", "without a query or fragment"),
        ("https://site.example.test#top", "without a query or fragment"),
        ("https://site.example.test/v1", "without a path"),
        ("https://site.example.test//", "without a path"),
        ("https://site.example.test:bad", "numeric port"),
        ("https://site.example.test:70000", "numeric port"),
        ("http://[::1", r"must be an HTTP\(S\) origin$"),
        ("https://user:secret\uff20site.example.test", r"must be an HTTP\(S\) origin$"),
    ],
)
def test_a_url_that_is_not_an_http_origin_is_refused(stated, reason):
    with pytest.raises(ValueError, match=reason):
        site_authority_url(stated)
    with pytest.raises(ValidationError):
        ORIGIN.validate_python(stated)


def test_an_origin_refusal_names_no_value():
    with pytest.raises(ValueError) as refused:
        site_authority_url("https://operator:hunter2@site.example.test")
    assert "hunter2" not in str(refused.value)


def test_the_origin_schema_is_a_string():
    class Settings(BaseModel):
        sites: dict[str, SiteAuthorityUrl]

    schema = Settings.model_json_schema(mode="validation")["properties"]["sites"]

    assert schema["additionalProperties"] == {"type": "string"}
