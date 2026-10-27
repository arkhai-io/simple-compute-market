"""API credits binds the api family's purchase shape under ``api_credits.v1``."""

from arkhai_api.purchase import (
    provision_key_id,
    provision_key_mode,
    provision_quantity,
    provision_terms_model,
)

API_CREDITS_PROVISION_KIND = "api_credits.v1"

ApiCreditsProvisionTerms = provision_terms_model(API_CREDITS_PROVISION_KIND)
make_api_credits_provision_terms = ApiCreditsProvisionTerms.purchase

__all__ = [
    "API_CREDITS_PROVISION_KIND",
    "ApiCreditsProvisionTerms",
    "make_api_credits_provision_terms",
    "provision_key_id",
    "provision_key_mode",
    "provision_quantity",
]
