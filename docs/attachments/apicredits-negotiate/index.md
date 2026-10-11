# API-credit standalone negotiation

Repair of final inventory finding B1. Tested implementation: `29280e22`
on `fix-apicredits-negotiate`, based on campaign `ba706fb3`.

`market credits negotiate` now selects through the declared buyer table.
The selected entry owns payer preparation or constrained Alkahest selection,
price prerequisites and proposal construction. Payment rate metadata reaches
the scalar policy's opening shape without inventing an escrow. Interrupted
rounds retain their selection, provision terms and per-credit scaled prices;
the CLI restores the quantity multiplier for core's absolute resume bounds.

## Prepared target and replay

Checkout-owned installed wheels and the real Typer command/core signed buyer
client. Registry I/O and seller HTTP are controlled boundaries, not deployed
services. Personas are deterministic synthetic Ed25519 signers. Fixtures use
fresh temporary XDG config/state, no wallet/chain configuration for payment,
and no external credentials or inherited deployment selectors. Alkahest
fixtures supply an address-only wallet and controlled chain metadata.

From the repository root:

```sh
make dist && make -C domains/apicredits/buyer reinit &&
(cd domains/apicredits/buyer &&
 uv run --no-sync pytest tests/test_negotiate_cli.py -q -s)
```

This command opens the CLI surface, prints each negotiation and checks the
signed request/response, recorded accepted state and interrupted-run replay.
The same entry was run successfully. Temporary state is fixture-owned;
no servers, containers, browser pages or external resources were started.

## Observations

| Claim | Action and observed result | Evidence |
|---|---|---|
| Payment-only negotiation is wallet-free | Four credits at explicit rate 2 produced opening/accepted amount 8; advertised rate 100 produced 400. Selected payer account, exact Agreement bytes and settlement data survived in the run. | `test_payment_only_cli_is_wallet_free_and_preserves_accepted_state` |
| Interrupted negotiation keeps its mechanism and bounds | Lost continuation after a counter, disabled fresh payment admission, then invoked `--from`. It called the existing `neg-1` thread, accepted amount 8 and retained the same proposal. | `test_payment_cli_resume_uses_recorded_selection_without_fresh_admission` |
| Alkahest opening behavior is retained | Explicit rate 2 with decimals 2 produced per-credit 200/total 800; derived base-unit rate 100 stayed 100/total 400. The existing chain/token/escrow proposal shape was retained. | `test_alkahest_cli_keeps_explicit_scaling_and_derived_base_units` |
| Selected Alkahest still requires an EVM address | Missing address returned exit 2 before any seller request. | `test_selected_alkahest_refuses_missing_wallet_before_seller_request` |

All named evidence is in
`domains/apicredits/buyer/tests/test_negotiate_cli.py`. Six new CLI cases passed;
the entire buyer suite passed **23 cases** (17 existing + 6 new). Wheel build,
reinit, Ruff F checks, comment hygiene and strict change/API-credit-spec
validation passed. Three existing Pydantic schema-shadowing warnings remain.

The controlled seller acceptance supplies opaque mandate data; this is
negotiation/accepted-state evidence, not payment approval, live ledger,
on-chain settlement or credit issuance qualification.

## Permanent documentation

- `openspec/specs/api-credits/spec.md`: standalone table dispatch and resume scenarios.
- `openspec/specs/api-credits/architecture.md`: stage-owned selection/pricing/opening and recovery.
- `openspec/specs/buyer-orchestration/architecture.md`: shared standalone stage ownership.
- `openspec/specs/market-composition/architecture.md`: removed only the repaired B1 limitation; B2 remains for its owner.
- API-credit delta spec matches the permanent contract. Joined inventory and task 8.2 closeout remain parent-owned.

## Adjacent repairs

`4e189c8b` decodes registry publisher pins as JSON on fresh negotiation.
`e43d72a8` does the same on source-pinned trust refresh. Both fix strict tuple
decoding of the registry's JSON arrays; fresh negotiation and `--from` above
exercise them through the production command.
