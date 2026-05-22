"""Unit tests for service.registry_url — URL normalization + auth lookup."""
from __future__ import annotations

import pytest

from service.registry_url import (
    lookup_registry_auth,
    normalize_auth_map,
    normalize_registry_url,
)


class TestNormalizeRegistryUrl:
    def test_lowercases_scheme(self):
        assert normalize_registry_url("HTTP://example.com:8080") == "http://example.com:8080"

    def test_lowercases_host(self):
        assert normalize_registry_url("http://Example.COM:8080") == "http://example.com:8080"

    def test_strips_trailing_slash_on_empty_path(self):
        assert normalize_registry_url("http://example.com:8080/") == "http://example.com:8080"

    def test_preserves_non_root_path(self):
        # Paths beyond root are real and must survive — operator might be
        # pointing at a sub-mounted indexer (e.g. /registry/).
        assert normalize_registry_url("http://example.com/registry/") == "http://example.com/registry/"

    def test_preserves_port(self):
        # Port is authoritative; the auth lookup must distinguish two
        # registries on the same host but different ports.
        assert normalize_registry_url("http://example.com:8081") != normalize_registry_url("http://example.com:8080")

    def test_preserves_query_and_fragment(self):
        assert normalize_registry_url("https://h.com?x=1#y") == "https://h.com?x=1#y"

    def test_empty_string_passthrough(self):
        assert normalize_registry_url("") == ""

    def test_strips_whitespace(self):
        assert normalize_registry_url("  http://example.com  ") == "http://example.com"


class TestNormalizeAuthMap:
    def test_returns_empty_for_none(self):
        assert normalize_auth_map(None) == {}

    def test_returns_empty_for_empty(self):
        assert normalize_auth_map({}) == {}

    def test_normalizes_every_key(self):
        result = normalize_auth_map({
            "HTTP://A.com:8080/": "tok1",
            "http://b.com:8080": "tok2",
        })
        assert result == {
            "http://a.com:8080": "tok1",
            "http://b.com:8080": "tok2",
        }

    def test_collapsed_keys_last_wins(self):
        # Two keys that normalize to the same canonical form — operator
        # config bug, but last-write-wins is the predictable behaviour.
        result = normalize_auth_map({
            "http://example.com:8080/": "first",
            "HTTP://Example.com:8080": "second",
        })
        assert result == {"http://example.com:8080": "second"}

    def test_skips_non_string_keys(self):
        # Defensive against TOML deserializers that hand us int keys.
        result = normalize_auth_map({"http://example.com": "ok", 123: "skip"})  # type: ignore[dict-item]
        assert result == {"http://example.com": "ok"}


class TestLookupRegistryAuth:
    def test_returns_none_for_no_auth_map(self):
        assert lookup_registry_auth(None, "http://example.com") is None
        assert lookup_registry_auth({}, "http://example.com") is None

    def test_returns_token_for_exact_match(self):
        auth = {"http://example.com:8080": "tok"}
        assert lookup_registry_auth(auth, "http://example.com:8080") == "tok"

    def test_returns_token_despite_case_mismatch(self):
        auth = {"http://example.com:8080": "tok"}
        assert lookup_registry_auth(auth, "HTTP://Example.COM:8080") == "tok"

    def test_returns_token_despite_trailing_slash(self):
        auth = {"http://example.com:8080/": "tok"}
        assert lookup_registry_auth(auth, "http://example.com:8080") == "tok"

    def test_returns_token_despite_trailing_slash_other_direction(self):
        auth = {"http://example.com:8080": "tok"}
        assert lookup_registry_auth(auth, "http://example.com:8080/") == "tok"

    def test_returns_none_for_unmatched_url(self):
        auth = {"http://example.com:8080": "tok"}
        assert lookup_registry_auth(auth, "http://other.com:8080") is None

    def test_returns_none_for_empty_token(self):
        # An entry with an empty value collapses to no-auth; treat the
        # same as missing.
        auth = {"http://example.com": ""}
        assert lookup_registry_auth(auth, "http://example.com") is None

    def test_distinguishes_ports(self):
        # Two registries on the same host but different ports must NOT
        # share an auth token by accident.
        auth = {"http://example.com:8080": "tok-a"}
        assert lookup_registry_auth(auth, "http://example.com:8081") is None
