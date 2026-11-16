# Spot-deals replay onto `dev`

Base: `dev` after the open-ended-terms change (PR #351) merged. The four commits of
sections 1–3 (PR #354) were rebased onto it, to `a701e6803`. Section 4 with its
permanent tests, the shared runway rule and refusal classes (the 8 commits of PR
#370), and compute buyers' selection of spot and on-demand options (the 5 commits of
PR #372, task 2.7) had been stacked on the pre-rebase branch; they were
cherry-picked onto `a701e6803` in order, authorship kept, to `dab8d06b8`. There is
no merge commit.

Conflicts and their resolution:

- `domains/vms/storefront/pyproject.toml` and its lock: the lifecycle client moves to
  runtime dependencies for `deals preempt`; `dev`'s newer dev-dependency pins are
  kept and the client's redundant dev entry dropped. `make dist` then
  `make check-locks`: every lock current.
- `kit/settlement-runtime/src/market_settlement_runtime/horizon.py`: `dev`'s
  `parse_utc`, `bound_seconds` and `check_accepted_horizon` are kept beside the
  incoming `minimum_rate_duration_seconds`, whose use in `resolve_horizon` merged
  cleanly with the whole-second start and its floor.
- Both buyers' `settlement_composition.py`: the per-term `waivers` signature is kept
  with task 2.7's `approvable_terms(context)` return.
- `domains/bare_metal/buyer/tests/test_buyer_composition.py`: `dev`'s deadline-waiver
  test is kept; the recurring-option test moves to `test_recurring_options.py`.

Suites after the replay, before round 1's triage: deal-lifecycle 82,
deal-lifecycle-buyer 22, deal-lifecycle-client 2, deal-lifecycle-contracts 37,
deal-servicing 70, settlement-runtime 302, bare-metal storefront 631 and VM
storefront 1785 (1 skipped) passed. The payments kit (287 passed, 5 failed, 9 typing
errors), the bare-metal buyer (66 passed, 2 failed) and the VM buyer's
`test_recurring_option_selection.py` (failed at collection) were red, every failure
the servicing declaration's earlier shape or the open-ended-terms change's once-only
guards. Round 1's triage reconciled them; its evidence is in the change's task
notes ("Round 1 triage fixes").

First use:

```sh
make dist
make -C kit/arkhai-payments first-use-rate
```

The committed [prepared target](../spot-deals-sections-1-3/index.md#scope-and-prepared-first-use)
owns in-process state, deterministic development payer/payee accounts, fixture
signing and an injected clock. It uses no secrets, server, container or persistent
external state and does not qualify live payment or mediation.
