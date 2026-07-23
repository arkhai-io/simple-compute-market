from compute_provisioning.app import (
    DEFAULT_COMPUTE_PROVISIONING_DESCRIPTION,
    ComputeProvisioningAppConfig,
    ComputeProvisioningMiddlewareMount,
    ComputeProvisioningRouterMount,
)


def test_provisioning_app_config_carries_shell_metadata():
    config = ComputeProvisioningAppConfig(
        title="Provisioning Service",
        version="0.2.0",
        description=DEFAULT_COMPUTE_PROVISIONING_DESCRIPTION,
        openapi_tags=[{"name": "system"}],
    )

    assert config.title == "Provisioning Service"
    assert config.version == "0.2.0"
    assert config.description == DEFAULT_COMPUTE_PROVISIONING_DESCRIPTION
    assert config.openapi_tags == [{"name": "system"}]


def test_mount_configs_default_to_empty_kwargs_and_prefix():
    assert ComputeProvisioningMiddlewareMount(object).kwargs == {}
    assert ComputeProvisioningRouterMount(object()).prefix == ""
