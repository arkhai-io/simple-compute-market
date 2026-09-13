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

## 3r. The Alice stages, handed over

- [x] 3r.1 **Declared, not deleted.** `test_06b` and `test_06c` skip with the
      reason at the call site: provisioning's storefront principal is a single
      identity, so Alice is never a trusted caller and never loads capacity.

      Only these two. The scenario's subject -- registry isolation, Alice's
      absence from registry-B, fan-in across two storefronts, resilience to a
      dead registry -- does not touch provisioning and keeps running. `00g`
      reads system status and `02b` imports a storefront-local CSV, so both are
      expected to pass; neither has been *observed* passing, because the whole
      scenario was skipped until this week, so the successor change widens the
      skip set on evidence rather than on my expectation.

- [x] 3r.2 **Not a regression, and worth being precise about why.** The Aug 15
      green run skipped every Alice stage, and the skip was incidental:
      `ALICE.*` was absent from configuration and `_require_setting` skips on an
      empty value. This change configured Alice while repairing the identity
      plumbing, which turned silent absences into real runs. The auth work made
      a pre-existing limitation visible; it did not cause it.

      The configuration stays. Reverting it would restore the silence that let
      this scenario go unexercised for months.

- [x] 3r.3 Handed to `repair-multi-storefront-scenario`, which owns letting
      provisioning trust more than one storefront principal. ROADMAP Goal 1's
      open-gap table names the gap and that change as its owner -- the goal
      already argues that consolidating physical authority is what makes a
      storefront replaceable by another front-end over the same hardware, so
      the fact that it cannot yet serve two belongs in its current state rather
      than only in a skip string.

## 3t. Prior-head run: 11 failed, 75 passed, 28 skipped

From 10/72/32. Four fewer skips and three more passes; the claims-name fix is
not in this head.

- [x] 3t.1 **The pause could never be observed: loop intervals were lost.**
      Four failures reported loops `pausing` -- mid-cycle when the bounded wait
      expired. `storefront.bob.toml` and `storefront.alice.toml` used to carry
      `negotiation_watchdog_interval`, `claims_sweep_interval` and
      `fulfillment_resume_sweep_interval` at 2 seconds, with a comment saying
      exactly why: a pause is observed only when a loop next reaches its gate,
      and the shipped defaults (60s watchdog, 30s sweeps) exceed the pause's
      own 5s wait, so every loop reports `pausing` forever. All three settings
      were gone from both files; `poll_interval = 1` survived.

      Restored with that reasoning. This is the same class as every other
      config loss this session, and it is why the restored pause stages could
      not pass however correct the gate was.

- [x] 3t.2 **A malformed log call, not a product defect.**
      `TypeError: not enough arguments for format string` in
      `test_full_deal_buyer_cli.py`: three placeholders, two arguments -- a
      stray `listing_resource=%s` the equivalent call in `test_full_deal.py`
      does not have. Swept every e2e module for lazy-log
      placeholder/argument mismatches; this was the only one, and it is now
      zero.

- [ ] 3t.3 **`500` on admin reservations, located.** The generic
      `"Storefront administrator request failed"` is the admin middleware
      wrapping a downstream error -- it does log the cause, and the traceback
      runs through `service_peer_auth.py:312`, the line after that
      middleware's claim test. `POST /api/v1/admin/portfolio/reservations` is
      not a callback and not the status read, so the middleware should pass it
      straight through; it is failing inside the branch that decides. Reading
      the body is the first thing past that point, and the outer frames show an
      `EndOfStream` on the request stream, which suggests the body is being
      consumed twice on this path. Needs the full frame list to confirm.

- [ ] 3t.4 **`409` on settle: "accepted provision terms have no SSH public
      key".** The scenario passes `ssh_public_key` to `settle`, but the key has
      to be in the *accepted* provision terms, which come from the negotiation.
      So `negotiate_new`'s `provision_terms` is missing it -- payload drift on
      the same axis as `capacity_source` and `offering_mode`.

- [ ] 3t.5 Unchanged: `market negotiate` exits 2, `market credits buy` exits 2,
      `market buy` exits 0 with no run-log.

## 3y. The buyer CLI had no settlement mechanism enabled

- [x] 3y.1 **`market negotiate` exited 2 on "listing has no installed,
      enabled, compatible settlement option".** Three conditions, and the
      failing one was `enabled`: the fixture's generated buyer config carried
      no `[Settlement]` section at all, and `AlkahestSettlementConfig.enabled`
      defaults to `false`, so every advertised option was incompatible.

      A mechanism the buyer has *installed* is not one it will *use*. That is
      the point of `unify-settlement-mechanism-configuration` (2026-08-12):
      the buyer's own configuration decides what is selectable. August's
      config had no `[Settlement]` either and was green, so this is drift from
      that change rather than a fixture mistake.

- [x] 3y.2 Added `[Settlement]` with `schema_version`, `priority`, and
      `[Settlement.alkahest] enabled = true`, modelled on the storefront's own
      working section rather than assembled from the field list. Note the
      section is capitalised -- lowercase `[settlement]` is explicitly refused
      as legacy, with a migration command named, so a near-miss here fails
      loudly rather than silently disabling the mechanism.

      `address_config_path` is set on the mechanism section as well as the
      chain entry: alkahest resolves contract addresses through the mechanism
      section, and the chain entry does not serve that lookup.

- [x] 3y.3 Verified against the buyer's own resolver rather than by shape.
      With the section, `ordered_registrations()` yields `['alkahest']`;
      with no `[Settlement]`, it yields `[]` -- reproducing the reported
      failure exactly. E2e collection 140; pyflakes clean apart from one
      pre-existing unused local.

- [ ] 3y.4 `market credits buy` exits 2 and `market buy` exits 0 with no
      run-log. The credits scenario drives a different storefront and its own
      buyer profile, so whether it needs the same section is not assumed --
      the next run's error text decides.

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
