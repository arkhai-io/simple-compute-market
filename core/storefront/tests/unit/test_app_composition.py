import pytest

from core_storefront.app_composition import (
    DEFAULT_STOREFRONT_DESCRIPTION,
    StorefrontAppConfig,
    build_storefront_app,
    default_storefront_app_config,
)
from core_storefront.domain_registry import StorefrontDomainRegistry

from test_domain_registry import _registration


def test_default_storefront_app_config_sets_shared_shell_defaults():
    config = default_storefront_app_config(root_path="/seller")

    assert config == StorefrontAppConfig(
        title="Arkhai Storefront",
        description=DEFAULT_STOREFRONT_DESCRIPTION,
        version="1.0.0",
        root_path="/seller",
        swagger_ui_parameters={"persistAuthorization": True},
    )


def test_app_exposes_only_safe_registration_projection():
    pytest.importorskip("fastapi")
    vm = _registration("vm", "compute.v1", "vms")
    bare_metal = _registration(
        "bare_metal", "bare_metal.v1", "bare_metal"
    )
    registry = StorefrontDomainRegistry((vm, bare_metal))

    app = build_storefront_app(
        config=default_storefront_app_config(),
        registry=registry,
        runtime_resolver=registry.resolve_registration,
    )

    assert app.state.market_domains == registry.projection()
    assert not hasattr(app.state, "market_domain")
    assert not hasattr(app.state, "domain_registry")


def test_app_rejects_a_resolver_that_reconstructs_registration_objects():
    pytest.importorskip("fastapi")
    vm = _registration("vm", "compute.v1", "vms")
    registry = StorefrontDomainRegistry((vm,))

    def reconstructed(_binding):
        return _registration("vm", "compute.v1", "vms")

    with pytest.raises(RuntimeError, match="exact startup-owned registration"):
        build_storefront_app(
            config=default_storefront_app_config(),
            registry=registry,
            runtime_resolver=reconstructed,
        )
