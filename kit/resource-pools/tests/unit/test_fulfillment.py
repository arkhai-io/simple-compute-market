import pytest
from market_resource_pools import ProviderNotFoundError, ProviderRegistry, FulfillmentValidationIssue, FulfillmentValidationResult

def test_validation_result_validity():
    assert FulfillmentValidationResult().valid
    assert not FulfillmentValidationResult((FulfillmentValidationIssue('bad','bad'),)).valid

def test_registry_missing_provider():
    with pytest.raises(ProviderNotFoundError):
        ProviderRegistry({}).require('missing')
