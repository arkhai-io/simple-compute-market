from core_storefront.provisioning_app import (
    DEFAULT_PROVISIONING_DESCRIPTION,
    ProvisioningAppConfig,
    ProvisioningMiddlewareMount,
    ProvisioningRouterMount,
)


def test_provisioning_app_config_carries_shell_metadata():
    config = ProvisioningAppConfig(
        title="Provisioning Service",
        version="0.2.0",
        description=DEFAULT_PROVISIONING_DESCRIPTION,
        openapi_tags=[{"name": "system"}],
    )

    assert config.title == "Provisioning Service"
    assert config.version == "0.2.0"
    assert config.description == DEFAULT_PROVISIONING_DESCRIPTION
    assert config.openapi_tags == [{"name": "system"}]


def test_mount_configs_default_to_empty_kwargs_and_prefix():
    assert ProvisioningMiddlewareMount(object).kwargs == {}
    assert ProvisioningRouterMount(object()).prefix == ""
