# Tasks — repair-storefront-alkahest-configuration

## Implementation status

**Implemented, unverified against the stack.** All three gaps are closed and
each fix is verified against the real packages at unit level. The e2e run that
confirms settlement becomes ready has not happened yet.

## 1. Supply the EVM credential

- [x] 1.1 Add `STOREFRONT_WALLET__PRIVATE_KEY` for `bob-storefront` and
      `alice-storefront` to `compose.local-identities.yml`, `@str`-marked.
      Anvil 2 for Bob and Anvil 4 for Alice, each derived and checked against
      the `Wallet.address` its own storefront config declares.
- [x] 1.2 Record at the call site why the name differs from the `AGENT_PRIV_KEY`
      the adjacent env files supply, so the next reader does not "fix" it back.

## 2. Make the address configuration reachable

- [x] 2.1 Bind-mount `alkahest_anvil_addresses.json` to
      `/app/alkahest_anvil_addresses.json` for both VM storefronts in
      `domains/vms/compose.yml`, matching the API-credits convention.
- [x] 2.2 Point `Settlement.alkahest.address_config_path` at the mount in
      `storefront.bob.toml` and `storefront.alice.toml`.
- [x] 2.3 Add `Chains.anvil.alkahest_address_config_path`, which client
      construction reads separately from the readiness preflight, and note
      that the two reads are independent.

## 3. Validation

- [x] 3.1 `build_alkahest_clients` reproduces the production symptom with no
      credential and proceeds past address-config resolution with one, failing
      only on DNS for the compose-internal RPC host.
- [x] 3.2 `alkahest_preflight` carries `alkahest.address_config_invalid` for
      the current path and not for the mounted one.
- [ ] 3.3 `make -C e2e-tests test-e2e`: confirm `checks.alkahest` reports
      `anvil`, that no `[SETTLEMENT] option suppressed` line names
      `alkahest.v1`, and that the seven listing-create refusals are gone.
      Compare failure *causes*, not counts — the escrow phases have never run,
      so new failures downstream of a now-publishing listing are the expected
      result and are findings for classification, not regressions.
- [ ] 3.4 `make test` stays green. No production Python changed, so nothing is
      expected here; run it rather than assume.

## 3g. Restore the pause/advance lifecycle controls (production)

The August green run (commit `a1128a4c`) showed seven admin routes that no
longer exist. Two were relocated and survive; the rest were deleted with no
record in `openspec/` or `docs/`. The e2e stages that used them were deleted
in the same window, which is why nothing failed.

- [x] 3g.1 **Corrected an earlier claim.** I reported that the settlement
      worker had no sweep entry point, having found `jobs.py`'s per-settlement
      `run_once` and stopped. `servicing.py`'s
      `SettlementServicingWorker.run_once(limit) -> int` is the direct
      equivalent of the old `ClaimsEngine.tick()`. The sweep/loop split
      survived the settlement-neutrality redesign intact.
- [x] 3g.2 **What was actually lost was the pause, and it had inverted.** The
      old `ClaimsEngine.run(interval, paused=...)` took a predicate and held
      the loop at its cycle boundary. Today `admin_pause` sets one
      `_GLOBALLY_PAUSED` flag whose only consumers are the negotiation runtime
      and the status read: **no loop consults it**. So pause used to stop
      reconciliation and leave trading open, and now stops trading and leaves
      reconciliation running — the opposite control, not a weaker one.
- [x] 3g.3 Added `core_storefront/loop_lifecycle.py`: a pause gate plus
      per-loop state, kept deliberately separate from the trading pause
      because a scenario needs deterministic reconciliation *and* a deal to
      agree. Gated `fulfillment_resume` and `site_projection_poller` directly;
      gave `run_negotiation_watchdog` and `SettlementServicingWorker.run` an
      injected `paused` predicate, restoring the shape the claims engine had,
      and wired the storefront's gate into the worker at startup.
      Verified: a gated loop reports `running`, is held at `paused` across a
      pause, and resumes on release.
- [x] 3g.4 Restored `POST /api/v1/admin/capacity/projections/refresh` and
      added three `lifecycle/{loop}/run-cycle` advances (`claims`,
      `fulfillment-resume`, `site-projections`), each over the operation its
      timer already invokes, with admin route contracts and client methods on
      both variants.
- [x] 3g.5 `pause_storefront`, `advance_storefront`, `site_capacity_admin_client`
      and the 307-line `host_registry.py` restored in the e2e fixtures.
      Storefront suites: **1107 passed**, with the 4 failures that reproduce on
      pristine code. E2e collection clean at 127.

- [ ] 3g.6 **Deferred, with reasons.**
      - `capacity-events/run-cycle`: the per-event drain has no callable unit —
        it is inline in the kit's `poll_events` loop. August had the same
        problem and called a full reconcile instead, which its own docstring
        admits runs a *superset* of the subscriber's work. Extracting a
        one-cycle drain is new design, not restoration.
      - Per-loop state is logged but not returned: `AdminPauseResponse.loops`
        and `HealthResponse.loops` were both dropped, so reporting it typed
        means changing the server model and the client's. Until then
        `pause_storefront` can only assert the aggregate, and a scenario cannot
        verify that the specific loop it depends on reached its gate.
      - The ~11 deleted scenario stages are not yet restored; they consume the
        controls above.

## 4. Closeout

- [ ] 4.1 **Comment hygiene.** `make check-comment-hygiene`.
- [ ] 4.2 **Import placement.** No Python changed; record that disposition.
- [ ] 4.3 **Documentation compliance.** Confirm the no-permanent-change
      disposition still holds once the stack result is known.
- [ ] 4.4 **Narrative compression.** Reduce these notes to final state.
- [ ] 4.5 **Roadmap currency.** Expected to own nothing; record either way.
- [ ] 4.6 **Campaign index currency.** Move the alkahest item out of the
      campaign's unowned table into this change's row, and reconcile on
      archival.
- [ ] 4.7 **Promotion.** Complete the design-promotion record.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| *(none expected — configuration only; the conventions relied on are already demonstrated elsewhere in the repository)* | — |

## Deferred, carried out of this change

- [ ] 5.1 Converge compose configuration onto a single source shared with the
      tests, and reconcile it with the Helm charts, which express the same
      deployment more coherently. Accepted as follow-up during this change and
      deliberately not attempted here.
- [ ] 5.2 Stop the shared Dynaconf loader TOML-parsing environment values bound
      for string fields, so `0x`-prefixed credentials do not need `@str` per
      value. Second occurrence of the workaround; also carried as an inherited
      question from `provide-e2e-development-identities`.
- [ ] 5.3 Delete or rewrite `domains/vms/storefront/.env.{bob,alice}.docker`,
      which carry configuration for a layout that no longer exists, including a
      stale `ALKAHEST_ADDRESS_CONFIG_PATH`. Left in place because the compose
      files still reference them.
