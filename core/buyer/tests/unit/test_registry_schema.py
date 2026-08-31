"""Schema-scoped discovery through signed, authority-pinned registry clients."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from market_identity import Ed25519Signer, TrustedIdentitySet

from core_buyer import registry_config
from core_buyer.registry_config import (
    registry_schema_id,
    resolve_indexer_urls_for_schema,
)


class _FakeRegistryClient:
    calls: list[dict] = []
    schemas: dict[str, str | None] = {}
    failures: set[str] = set()

    def __init__(self, base_url: str, **kwargs) -> None:
        self.base_url = base_url
        self.calls.append({"base_url": base_url, **kwargs})

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def get_filter_spec(self):
        if self.base_url in self.failures:
            raise OSError("refused")
        return SimpleNamespace(schema_id=self.schemas.get(self.base_url))


@pytest.fixture(autouse=True)
def _fresh_cache():
    registry_config.reset_schema_id_cache()
    _FakeRegistryClient.calls = []
    _FakeRegistryClient.schemas = {}
    _FakeRegistryClient.failures = set()
    yield
    registry_config.reset_schema_id_cache()


def _signer(seed: int) -> Ed25519Signer:
    return Ed25519Signer(bytes([seed]) * 32)


def _authority(name: str, signer: Ed25519Signer) -> registry_config.RegistryAuthority:
    return registry_config.RegistryAuthority(
        authority=name,
        principals=TrustedIdentitySet(identities=(signer.identity,)),
    )


def _authorities(urls: list[str]) -> dict:
    return {
        url: _authority(f"registry-{index}", _signer(index + 10))
        for index, url in enumerate(urls)
    }


def test_declared_id_is_read_with_buyer_signer_and_authority_pin():
    buyer = _signer(1)
    authority = _authority("registry-r", _signer(2))
    _FakeRegistryClient.schemas["http://r:8080"] = "vms.compute"

    with patch.object(registry_config, "SyncRegistryClient", _FakeRegistryClient):
        assert registry_schema_id(
            "http://r:8080/",
            signer=buyer,
            registry_authority=authority,
        ) == "vms.compute"

    call = _FakeRegistryClient.calls[0]
    assert call["signer"] is buyer
    assert call["caller_role"] == "buyer"
    assert call["expected_registries"] == authority.principals
    assert call["registry_authority"] == authority.authority


def test_undeclared_and_failed_signed_fetches_read_as_none():
    buyer = _signer(3)
    authority = _authority("registry", _signer(4))
    _FakeRegistryClient.failures.add("http://down:8080")
    with patch.object(registry_config, "SyncRegistryClient", _FakeRegistryClient):
        assert registry_schema_id(
            "http://undeclared:8080",
            signer=buyer,
            registry_authority=authority,
        ) is None
        assert registry_schema_id(
            "http://down:8080",
            signer=buyer,
            registry_authority=authority,
        ) is None


def test_schema_id_cache_is_bound_to_url_and_authority():
    buyer = _signer(5)
    first = _authority("registry", _signer(6))
    second = _authority("registry", _signer(7))
    _FakeRegistryClient.schemas["http://r:8080"] = "vms.compute"
    with patch.object(registry_config, "SyncRegistryClient", _FakeRegistryClient):
        registry_schema_id(
            "http://r:8080",
            signer=buyer,
            registry_authority=first,
        )
        registry_schema_id(
            "http://r:8080/",
            signer=buyer,
            registry_authority=first,
        )
        registry_schema_id(
            "http://r:8080",
            signer=buyer,
            registry_authority=second,
        )
    assert len(_FakeRegistryClient.calls) == 2


def test_only_explicit_mismatch_drops_a_registry(capsys):
    urls = [
        "http://vms:8080",
        "http://tokens:8080",
        "http://legacy:8080",
        "http://down:8080",
    ]
    buyer = _signer(8)
    authorities = _authorities(urls)
    _FakeRegistryClient.schemas = {
        "http://vms:8080": "vms.compute",
        "http://tokens:8080": "tokens.api",
        "http://legacy:8080": None,
    }
    _FakeRegistryClient.failures.add("http://down:8080")

    with (
        patch.object(registry_config, "SyncRegistryClient", _FakeRegistryClient),
        patch.object(registry_config, "resolve_registry_api_keys", return_value={}),
    ):
        kept = resolve_indexer_urls_for_schema(
            "vms.compute",
            signer=buyer,
            registry_authorities=authorities,
            override=",".join(urls),
        )

    assert kept == ["http://vms:8080", "http://legacy:8080", "http://down:8080"]
    err = capsys.readouterr().err
    assert "tokens:8080" in err and "tokens.api" in err


def test_api_key_is_additional_to_signed_identity():
    urls = ["http://r:8080", "http://other:8080"]
    buyer = _signer(20)
    authorities = _authorities(urls)
    with (
        patch.object(registry_config, "SyncRegistryClient", _FakeRegistryClient),
        patch.object(
            registry_config,
            "resolve_registry_api_keys",
            return_value={"http://r:8080": "tok-1"},
        ),
    ):
        resolve_indexer_urls_for_schema(
            "vms.compute",
            signer=buyer,
            registry_authorities=authorities,
            override=",".join(urls),
        )

    first = _FakeRegistryClient.calls[0]
    assert first["api_key"] == "tok-1"
    assert first["signer"] is buyer
    assert first["expected_registries"] == authorities["http://r:8080"].principals
    assert first["registry_authority"] == "registry-0"


def test_singleton_registry_list_is_returned_without_fetching():
    urls = ["http://only:8080"]
    with patch.object(registry_config, "SyncRegistryClient", _FakeRegistryClient):
        kept = resolve_indexer_urls_for_schema(
            "vms.compute",
            signer=_signer(30),
            registry_authorities=_authorities(urls),
            override=urls[0],
        )
    assert kept == urls
    assert not _FakeRegistryClient.calls


def test_schema_resolution_rejects_missing_authority_pin():
    with pytest.raises(RuntimeError, match="exactly match"):
        resolve_indexer_urls_for_schema(
            "vms.compute",
            signer=_signer(31),
            registry_authorities={},
            override="http://one:8080,http://two:8080",
        )


def test_registry_authority_config_is_structured_and_exact() -> None:
    registry = _signer(40)
    configured = {
        "http://registry/": {
            "authority": "registry-production",
            "identities": [registry.identity.model_dump(mode="json")],
        },
    }
    with (
        patch(
            "market_config.config_loader.load_user_config",
            return_value={},
        ),
        patch(
            "market_config.config_loader.get_dotted",
            return_value=configured,
        ),
    ):
        assert registry_config.resolve_registry_authorities(
            ["http://registry"]
        ) == {
            "http://registry": _authority("registry-production", registry),
        }


def test_registry_authority_config_rejects_unknown_or_malformed_pins() -> None:
    with (
        patch(
            "market_config.config_loader.load_user_config",
            return_value={},
        ),
        patch(
            "market_config.config_loader.get_dotted",
            return_value={
                "http://registry": {
                    "authority": "registry-production",
                    "identities": [
                        {
                            "scheme": "ed25519",
                            "identifier": "not-a-public-key",
                        }
                    ],
                }
            },
        ),
        pytest.raises(RuntimeError, match="invalid authority"),
    ):
        registry_config.resolve_registry_authorities(["http://registry"])

    extra = {
        "authority": "other",
        "identities": [_signer(41).identity.model_dump(mode="json")],
    }
    with (
        patch(
            "market_config.config_loader.load_user_config",
            return_value={},
        ),
        patch(
            "market_config.config_loader.get_dotted",
            return_value={"http://other": extra},
        ),
        pytest.raises(RuntimeError, match="exactly match"),
    ):
        registry_config.resolve_registry_authorities(["http://registry"])
