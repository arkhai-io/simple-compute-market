"""Schema-scoped registry resolution.

With several registries configured, a schema plugin's discovery verbs
must only query registries whose ``/filter-spec`` declares the plugin's
schema id. The matching is lenient by design: only an *explicit
mismatch* drops a registry — undeclared identity (pre-identity
deployments) and spec-fetch failures keep the registry in the list, so
existing single-registry setups behave exactly as before.
"""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest

from core_buyer import registry_config
from core_buyer.registry_config import (
    registry_schema_id,
    resolve_indexer_urls_for_schema,
)


class _SpecResponse(io.BytesIO):
    """Minimal context-manager body for a mocked urlopen."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _spec(schema: dict | None) -> _SpecResponse:
    body: dict = {"version": 1, "etag": "e", "listing_shape": {}, "filters": []}
    if schema is not None:
        body["schema"] = schema
    return _SpecResponse(json.dumps(body).encode("utf-8"))


@pytest.fixture(autouse=True)
def _fresh_cache():
    registry_config.reset_schema_id_cache()
    yield
    registry_config.reset_schema_id_cache()


def test_declared_id_is_parsed():
    with patch(
        "urllib.request.urlopen",
        return_value=_spec({"id": "vms.compute", "version": 1}),
    ):
        assert registry_schema_id("http://r:8080/") == "vms.compute"


def test_undeclared_and_failed_fetches_read_as_none():
    with patch("urllib.request.urlopen", return_value=_spec(None)):
        assert registry_schema_id("http://undeclared:8080") is None
    with patch("urllib.request.urlopen", side_effect=OSError("refused")):
        assert registry_schema_id("http://down:8080") is None


def test_schema_id_is_cached_per_url():
    with patch(
        "urllib.request.urlopen",
        return_value=_spec({"id": "vms.compute"}),
    ) as urlopen:
        registry_schema_id("http://r:8080")
        registry_schema_id("http://r:8080/")  # same registry, trailing slash
    assert urlopen.call_count == 1


def test_only_explicit_mismatch_drops_a_registry(capsys):
    responses = {
        "http://vms:8080/filter-spec": _spec({"id": "vms.compute"}),
        "http://tokens:8080/filter-spec": _spec({"id": "tokens.api"}),
        "http://legacy:8080/filter-spec": _spec(None),
    }

    def fake_urlopen(req, timeout=None):
        url = req.full_url
        if url not in responses:
            raise OSError("refused")
        return responses[url]

    with patch("urllib.request.urlopen", side_effect=fake_urlopen), \
         patch.object(registry_config, "resolve_indexer_auth", return_value={}):
        kept = resolve_indexer_urls_for_schema(
            "vms.compute",
            override="http://vms:8080,http://tokens:8080,http://legacy:8080,http://down:8080",
        )

    assert kept == ["http://vms:8080", "http://legacy:8080", "http://down:8080"]
    # The drop is visible, not silent — a buyer staring at "no matches"
    # can see why a configured registry wasn't asked.
    err = capsys.readouterr().err
    assert "tokens:8080" in err and "tokens.api" in err


def test_auth_token_rides_the_spec_fetch():
    seen_headers: list[dict] = []

    def fake_urlopen(req, timeout=None):
        seen_headers.append(dict(req.header_items()))
        return _spec({"id": "vms.compute"})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen), \
         patch.object(
             registry_config, "resolve_indexer_auth",
             return_value={"http://r:8080": "tok-1"},
         ):
        resolve_indexer_urls_for_schema(
            "vms.compute", override="http://r:8080,http://other:8080",
        )

    assert any(
        v == "Bearer tok-1"
        for h in seen_headers
        for k, v in h.items()
        if k.lower() == "authorization"
    )


def test_singleton_registry_list_is_returned_without_fetching():
    """One configured registry → nothing to choose among → no spec fetch."""
    with patch("urllib.request.urlopen") as urlopen, \
         patch.object(registry_config, "resolve_indexer_auth", return_value={}):
        kept = resolve_indexer_urls_for_schema(
            "vms.compute", override="http://only:8080",
        )
    assert kept == ["http://only:8080"]
    urlopen.assert_not_called()
