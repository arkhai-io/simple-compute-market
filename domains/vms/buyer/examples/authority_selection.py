"""First use of authority admission through the production VM buyer policy."""

from copy import deepcopy

from arkhai_vms_buyer.settlement_composition import resolve_buyer_settlement_policy
from market_core.schemas import SettlementOption, derive_settlement_option_id
from market_identity import Ed25519Signer

# Deterministic public development signer; never use it on a public network.
signer = Ed25519Signer(bytes(range(32)))


def authority(name):
    return {
        "interface": "arkhai.mediation.v1", "origin": f"https://{name}.example",
        "account": "11111111-1111-4111-8111-111111111111",
        "record_key": "ed25519:" + signer.identity.identifier, "params": {},
        "advertisement": {"mechanisms": ["arkhai.payments.v1"],
                          "minimum_dispute_window_seconds": 60, "minimum_case_hold_seconds": None},
    }


def option(entry):
    body = {
        "price": {"asset": "USD/6", "rates": [{"field": "amount", "per": "hour", "value": "100"}]},
        "settlement": {"schema": "arkhai.payments.v1", "payee_account": "22222222-2222-4222-8222-222222222222",
                       "window": "P7D", "deposit_agreement": False},
        "lifecycle": {"adjudication": {"version": 1,
            "dispute": {key: entry[key] for key in ("interface", "origin", "account", "record_key", "params")},
            "dispute_window_seconds": 120, "case_hold_max_seconds": None}, "delivery_deadline_seconds": 60},
    }
    return SettlementOption(option_id=derive_settlement_option_id(**body), **body)


def policy(entries):
    return resolve_buyer_settlement_policy({
        "Dispute": entries,
        "Settlement": {"schema_version": 1, "priority": ["arkhai.payments.v1"], "arkhai_payments": {
            "enabled": True, "service_url": "https://payments.example",
            "service_identity": signer.identity.model_dump(mode="json"), "fee_bps": 250,
        }},
    })


first, second = authority("first"), authority("second")
first_option, second_option = option(first), option(second)
listing = {"settlement_options": [second_option, first_option]}
selected = policy([first, second]).select(listing, expiration_unix=2_000_000_000)
assert selected.option == first_option
assert policy([second, first]).select(listing, expiration_unix=2_000_000_000).option == second_option
assert policy([first]).select({"settlement_options": [second_option]}, expiration_unix=2_000_000_000) is None
assert policy([]).select(listing, expiration_unix=2_000_000_000) is None
for field, value in (("origin", "https://unaccepted.example"), ("record_key", "unaccepted-key"),
                     ("params", {"procedure": "unaccepted"})):
    changed = deepcopy(first)
    changed[field] = value
    assert policy([first]).select({"settlement_options": [option(changed)]}, expiration_unix=2_000_000_000) is None
unsupported = deepcopy(first)
unsupported["interface"] = "unsupported.dispute.v1"
assert policy([unsupported]).select({"settlement_options": [option(unsupported)]}, expiration_unix=2_000_000_000) is None
incompatible = deepcopy(first)
incompatible["advertisement"]["mechanisms"] = ["other.payment.v1"]
assert policy([incompatible]).select({"settlement_options": [first_option]}, expiration_unix=2_000_000_000) is None
missing_deadline = first_option.model_dump(mode="json")
missing_deadline.pop("option_id")
missing_deadline["lifecycle"].pop("delivery_deadline_seconds")
missing_deadline = SettlementOption(option_id=derive_settlement_option_id(**missing_deadline), **missing_deadline)
assert policy([first]).select({"settlement_options": [missing_deadline]}, expiration_unix=2_000_000_000) is None
print("production VM selection: ordered authority preference, exact origin/key/params, no-authority, unsupported-interface, advertised-mechanism and compute deadline admission passed")
