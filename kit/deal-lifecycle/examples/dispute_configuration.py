"""Run the public, library-only dispute configuration surface without services."""

from market_deal_lifecycle.configuration import (
    DisputeCredential,
    DisputeEntry,
    dispute_config,
    authorities_by_registry,
)

# Reserved example origin and public fixture identities, never production trust.
authority = {
    "interface": "example.dispute.v1",
    "origin": "https://dispute.example",
    "account": "acct_example",
    "record_key": "example-public-key",
    "params": {},
    "advertisement": {
        "mechanisms": ["example.payment.v1"],
        "minimum_dispute_window_seconds": 60,
        "minimum_case_hold_seconds": None,
    },
}
entry = DisputeEntry.model_validate(authority)
# TOML has no null literal; omission expresses an unbounded case hold.
toml_authority = authority | {
    "advertisement": {key: value for key, value in authority["advertisement"].items()
                      if key != "minimum_case_hold_seconds"}
}
assert DisputeEntry.model_validate(toml_authority).advertisement.minimum_case_hold_seconds is None
buyer = dispute_config({}, role="buyer")
seller = dispute_config({}, role="seller")
assert buyer.authorities([entry], role="buyer") == ()
assert seller.authorities([entry], role="seller") == (entry,)
opted_in = dispute_config({"use_registry_dispute_authorities": True}, role="buyer")
assert opted_in.authorities([entry], role="buyer") == (entry,)
local = dispute_config({"Dispute": [authority | {"not_accepted": True}],
                        "use_registry_dispute_authorities": True}, role="buyer")
assert not local.authorities([entry], role="buyer")
credential = DisputeCredential.model_validate(
    {key: authority[key] for key in ("interface", "origin", "account", "record_key")}
    | {"api_key_env": "EXAMPLE_DISPUTE_API_KEY"}
)
bound = buyer.model_copy(update={"credentials": [credential]})
assert bound.credential_for(entry.authority) == credential
assert bound.credential_for(entry.authority.model_copy(update={"record_key": "other"})) is None
resolved = credential.resolve({"EXAMPLE_DISPUTE_API_KEY": "example-only-secret"})
assert resolved.get_secret_value() == "example-only-secret"
assert "example-only-secret" not in bound.model_dump_json()
assert "example-only-secret" not in entry.authority.model_dump_json()
assert "example-only-secret" not in str(resolved)
reports = []
registries = authorities_by_registry(
    opted_in, {"https://registry.example": [entry], "https://other.example": []},
    role="buyer", report=reports.append,
)
assert registries["https://registry.example"] == (entry,)
assert registries["https://other.example"] == ()
assert "[[Dispute]]" in reports[0] and "use_registry_dispute_authorities" in reports[0]
print("per-registry resolution and empty-list diagnostics: OK")
print("buyer default: no authorities; seller default: registry recommendation")
print("buyer opt-in, local veto, exact credential identity, and secret isolation: OK")
print(entry.authority.model_dump_json())
