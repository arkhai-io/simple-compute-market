"""Integration tests: verify TokenRegistry migration from core to service.clients.token."""
import pytest


def test_erc20_token_metadata_resolves_from_service():
    """ERC20TokenMetadata in pydantic_models is the same class as in service.clients.token."""
    from core.agent.app.schema.pydantic_models import ERC20TokenMetadata as CoreMeta
    from service.clients.token import ERC20TokenMetadata as ServiceMeta
    assert CoreMeta is ServiceMeta


def test_action_executor_token_registry_from_service():
    """action_executor.TOKEN_REGISTRY is the same object as service.clients.token.TOKEN_REGISTRY."""
    import core.agent.app.utils.action_executor as ae
    from service.clients.token import TOKEN_REGISTRY as service_reg
    assert ae.TOKEN_REGISTRY is service_reg


def test_core_token_registry_module_removed():
    """The old core token_registry module must not exist."""
    with pytest.raises(ModuleNotFoundError):
        import core.agent.app.utils.token_registry  # noqa: F401
