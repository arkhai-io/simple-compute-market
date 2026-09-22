import pytest
from market_fulfillment import (
    FulfillmentValidationIssue,
    FulfillmentValidationResult,
    ProviderNotFoundError,
    ProviderRegistry,
    provider_needs_host,
)

def test_validation_result_validity():
    assert FulfillmentValidationResult().valid
    assert not FulfillmentValidationResult((FulfillmentValidationIssue('bad','bad'),)).valid

def test_registry_missing_provider():
    with pytest.raises(ProviderNotFoundError):
        ProviderRegistry({}).require('missing')


class _Declared:
    needs_host = True


class _Undeclared:
    pass


class _NotABool:
    needs_host = "yes"


def test_a_declared_host_need_is_read_from_the_class():
    assert provider_needs_host(_Declared()) is True


@pytest.mark.parametrize("provider", [_Undeclared(), _NotABool()])
def test_a_provider_that_does_not_declare_its_host_need_is_refused(provider):
    with pytest.raises(TypeError):
        provider_needs_host(provider)
