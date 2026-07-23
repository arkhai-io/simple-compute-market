from core_storefront.app_composition import (
    DEFAULT_STOREFRONT_DESCRIPTION,
    StorefrontAppConfig,
    default_storefront_app_config,
)


def test_default_storefront_app_config_sets_shared_shell_defaults():
    config = default_storefront_app_config(root_path="/seller")

    assert config == StorefrontAppConfig(
        title="Arkhai Storefront",
        description=DEFAULT_STOREFRONT_DESCRIPTION,
        version="1.0.0",
        root_path="/seller",
        swagger_ui_parameters={"persistAuthorization": True},
    )
