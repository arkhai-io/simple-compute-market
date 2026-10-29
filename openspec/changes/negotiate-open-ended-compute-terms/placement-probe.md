# Terms-placement diagnostic

Run date: 2026-10-29. This is a structural probe against the current checkout, not
an acceptance test or a decision about term placement. All fixture identities are
obviously non-operational examples; no chain or external authority is contacted.

## Observation

- `core/src/market_core/schemas.py`'s actual `SettlementOption` retains both common
  objects inside option params across JSON round-trip, and changing notice changes
  the canonical option ID.
- Alkahest currently has no closed typed option-params model: its builder emits
  `{"accepted_escrow": ...}`; projections extract that key from a mapping. The probe
  executes the unchanged projection functions extracted from the source AST to avoid
  loading unrelated chain dependencies, and they still work with both common keys.
- `kit/alkahest/src/market_alkahest/schemas.py`'s actual `EscrowTerms` silently drops
  those unknown keys. That type represents obligation materialization, not option
  params. It is evidence against using that model to round-trip the shared terms,
  not evidence that the option carrier needs a sibling field.
- Source inspection of `kit/alkahest/src/market_alkahest/proposals.py` shows the
  splitter writes `service_terms.interruptible` with schema `vms.interruptible.v1`
  and `refund_authority: seller_declared`; it does not yet consume the shared terms.
- `kit/deal-lifecycle` and the revised mandate check are absent. The full same-codec,
  hosted/Alkahest, splitter and buyer-check experiment cannot pass or fail yet. An
  adapter must still refuse lifecycle promises its mechanism cannot enforce.

## Reproduce from repository root

The isolated UV environment needs Pydantic 2, no repository environment refresh.
The first diagnostic loader omitted registration in `sys.modules`, causing Pydantic
forward-reference resolution to fail; the command below corrects the loader and was
the successful run. That failure was in the probe, not a params rejection.

```sh
uv run --no-project --with 'pydantic>=2,<3' python - <<'PY'
import ast
import copy
import importlib.util
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result

core = module("core/src/market_core/schemas.py", "probe_core")
alk = module("kit/alkahest/src/market_alkahest/schemas.py", "probe_alk")
terms = {
    "early_termination": {
        "version": 1,
        "entitlements": {"payer": {"notice_seconds": 0, "settles_through": "stop+exposure"},
                         "payee": {"notice_seconds": 120, "settles_through": "stop"}},
        "exposure_seconds": 300, "max_term_seconds": 86400},
    "adjudication": {
        "version": 1,
        "dispute": {"interface": "arkhai.mediation.v1",
                    "origin": "https://mediation.example",
                    "account": "acct_example", "record_key": "ed25519:example",
                    "params": {"procedure": "optimistic"}},
        "dispute_window_seconds": 1209600, "case_hold_max_seconds": None}}
escrow = alk.AcceptedEscrow(chain_name="example", escrow_address="fixture",
                            literal_fields={}, rates=[]).model_dump(mode="json")
params = {"accepted_escrow": escrow, **terms}
payload = {"mechanism": "alkahest.v1", "asset": "fixture", "rates": [], "params": params}
option_id = core.derive_settlement_option_id(**payload)
option = core.SettlementOption(option_id=option_id, **payload)
roundtrip = core.SettlementOption.model_validate_json(option.model_dump_json())
assert roundtrip.params == params
print("option params roundtrip: PASS (both common objects retained)")
changed = copy.deepcopy(payload)
changed["params"]["early_termination"]["entitlements"]["payee"]["notice_seconds"] = 121
assert core.derive_settlement_option_id(**changed) != option_id
print("term-sensitive option identity: PASS")

# Execute only these unchanged source functions; avoid unrelated chain imports.
source = ast.parse(Path("kit/alkahest/src/market_alkahest/settlement_config.py").read_text())
names = {"_value", "_alkahest_escrow", "alkahest_chain_projection", "alkahest_escrow_kind_projection"}
tree = ast.Module(body=[n for n in source.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
scope = {"Mapping": Mapping, "Any": Any}
exec(compile(tree, "settlement_config.py selected functions", "exec"), scope)
assert scope["alkahest_chain_projection"](option) == "example"
assert scope["alkahest_escrow_kind_projection"](option) is None
print("existing Alkahest option projections with common keys: PASS")

typed = alk.EscrowTerms.model_validate({
    "maker": "buyer", "chain_name": "example", "escrow_contract": "fixture",
    "obligation_data": {}, "expiration_unix": 2000000000, **terms})
assert not set(terms).intersection(typed.model_dump())
print("EscrowTerms (obligation params, NOT option params) drops unknown common keys")
assert not Path("kit/deal-lifecycle").exists()
print("shared lifecycle codec / buyer mandate check: NOT RUN (design-stage codec absent)")
print("splitter service term: source inspection only; not an end-to-end placement verdict")

PY
```

Successful output:

```text
option params roundtrip: PASS (both common objects retained)
term-sensitive option identity: PASS
existing Alkahest option projections with common keys: PASS
EscrowTerms (obligation params, NOT option params) drops unknown common keys
shared lifecycle codec / buyer mandate check: NOT RUN (design-stage codec absent)
splitter service term: source inspection only; not an end-to-end placement verdict
```

## Required decision experiment

After the foundation codec exists, run the identical versioned early_termination
and adjudication objects through hosted and Alkahest option validation, option ID,
Agreement serialization, codec projection, splitter service terms and buyer
commitment checking. Check for silent key loss, unknown-key refusal and any codec
branch on mechanism/arbiter vocabulary. Separate structural carriage from supported
mechanism semantics: the old splitter is not thereby given a lifecycle adapter.
Present the full result to the owner before selecting inside-versus-beside params.
