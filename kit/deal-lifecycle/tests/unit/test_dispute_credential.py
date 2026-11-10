"""A dispute credential's two forms, its validation, and its one resolution."""

from __future__ import annotations

import tomllib

import pytest
from pydantic import ValidationError

from market_deal_lifecycle.configuration import DisputeCredential, dispute_config

# Reserved example identity and public test-only tokens that authenticate to
# nothing; never use them on a public network.
IDENTITY = {
    "interface": "example.dispute.v1",
    "origin": "https://dispute.example",
    "account": "acct_example",
    "record_key": "example-public-key",
}
TOKEN = "dispute-credential-canary"
# Short enough that pydantic would print it whole in an error's input.
SHORT_TOKEN = "tok"
VARIABLE = "EXAMPLE_DISPUTE_API_KEY"


def credential(**form: object) -> DisputeCredential:
    return DisputeCredential.model_validate(IDENTITY | form)


def test_a_stated_key_resolves_to_itself_whatever_the_environment_holds():
    stated = credential(api_key=TOKEN)
    assert stated.resolve({VARIABLE: "unread"}).get_secret_value() == TOKEN
    assert stated.resolve({}).get_secret_value() == TOKEN


def test_a_named_variable_resolves_to_its_value():
    named = credential(api_key_env=VARIABLE)
    assert named.resolve({VARIABLE: TOKEN}).get_secret_value() == TOKEN


@pytest.mark.parametrize("environment", [{}, {VARIABLE: ""}], ids=["unset", "empty"])
def test_an_unusable_variable_raises_value_error_naming_it(environment):
    with pytest.raises(ValueError, match=VARIABLE):
        credential(api_key_env=VARIABLE).resolve(environment)


def test_both_forms_are_refused_naming_both():
    with pytest.raises(ValidationError) as refused:
        credential(api_key=SHORT_TOKEN, api_key_env=VARIABLE)
    message = str(refused.value)
    assert "api_key and api_key_env are mutually exclusive" in message
    assert SHORT_TOKEN not in message


def test_neither_form_is_refused():
    with pytest.raises(ValidationError, match="requires api_key or api_key_env"):
        credential()


@pytest.mark.parametrize(
    "key", ["", " tok", "tok ", "t\nk", "t\r\nk"],
    ids=["empty", "leading-space", "trailing-space", "lf", "crlf"],
)
def test_an_unusable_key_is_refused_at_validation_without_showing_it(key):
    with pytest.raises(ValidationError, match="api_key must be nonempty") as refused:
        credential(api_key=key)
    if key.strip():
        assert key.strip() not in str(refused.value)


def test_a_configuration_error_never_shows_a_stated_token():
    with pytest.raises(ValidationError) as refused:
        dispute_config(
            {"DisputeCredential": [IDENTITY | {"api_key": SHORT_TOKEN, "api_key_env": VARIABLE}]},
            role="seller",
        )
    assert SHORT_TOKEN not in str(refused.value)


def test_a_malformed_variable_name_is_still_refused():
    with pytest.raises(ValidationError):
        credential(api_key_env="lower_case")


def test_the_token_never_appears_in_a_repr_or_a_dump():
    stated = credential(api_key=TOKEN)
    assert TOKEN not in repr(stated)
    assert TOKEN not in stated.model_dump_json()
    assert TOKEN not in repr(stated.resolve())
    assert DisputeCredential.model_fields["api_key"].json_schema_extra == {"secret": True}


def test_a_credential_names_no_ca_bundle_unless_it_states_one():
    assert credential(api_key=TOKEN).ca_bundle_path is None
    assert credential(api_key=TOKEN, ca_bundle_path="/run/lane-ca.pem").ca_bundle_path == "/run/lane-ca.pem"


@pytest.mark.parametrize("path", ["", "  "], ids=["empty", "blank"])
def test_an_empty_ca_bundle_path_is_refused_rather_than_read_as_the_default_store(path):
    with pytest.raises(ValidationError, match="ca_bundle_path must name a file"):
        credential(api_key=TOKEN, ca_bundle_path=path)


def test_the_credential_an_authority_resolves_to_carries_its_ca_bundle():
    document = tomllib.loads(
        f"""
        [[DisputeCredential]]
        interface = "{IDENTITY['interface']}"
        origin = "{IDENTITY['origin']}"
        account = "{IDENTITY['account']}"
        record_key = "{IDENTITY['record_key']}"
        api_key = "{TOKEN}"
        ca_bundle_path = "/run/lane-ca.pem"
        """
    )
    config = dispute_config(document, role="seller")
    resolved = config.credential_for(credential(api_key_env=VARIABLE))
    assert resolved is not None
    assert resolved.ca_bundle_path == "/run/lane-ca.pem"


def test_an_api_key_entry_loads_from_toml_text():
    document = tomllib.loads(
        f"""
        [[DisputeCredential]]
        interface = "{IDENTITY['interface']}"
        origin = "{IDENTITY['origin']}"
        account = "{IDENTITY['account']}"
        record_key = "{IDENTITY['record_key']}"
        api_key = "{TOKEN}"
        """
    )
    config = dispute_config(document, role="seller")
    [loaded] = config.credentials
    assert loaded.resolve({}).get_secret_value() == TOKEN
    assert TOKEN not in config.model_dump_json()
