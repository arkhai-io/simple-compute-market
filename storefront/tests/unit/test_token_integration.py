"""Integration tests: verify TokenRegistry migration from core to service.clients.token."""
import pytest


def test_erc20_token_metadata_resolves_from_service():
    """ERC20TokenMetadata in pydantic_models is the same class as in service.clients.token."""
    from market_storefront.schema.pydantic_models import ERC20TokenMetadata as CoreMeta
    from service.clients.token import ERC20TokenMetadata as ServiceMeta
    assert CoreMeta is ServiceMeta


def test_core_token_registry_module_removed():
    """The old core token_registry module must not exist."""
    with pytest.raises(ModuleNotFoundError):
        import market_storefront.utils.token_registry  # noqa: F401
