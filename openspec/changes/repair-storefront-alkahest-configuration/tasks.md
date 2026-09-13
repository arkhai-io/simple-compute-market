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

## 3b. Drift the settling stack exposed

Publishing listings reached code that had never run. Three were mine.

- [x] 3b.1 `ProvisioningTestClient._verify` omitted `verify_response`'s
      required `max_skew`. Now carries `max_timestamp_skew=300`, mirroring the
      canonical client's own default rather than a new number.
- [x] 3b.2 `validate_publish_listing` is a seller operation but two tests still
      called it on the buyer-role client. The registry refused it and the
      refusal was not a signed v2 response, so the client reported
      `unsupported_version` wrapped as `502` — a confusing surface for a plain
      role error. Repointed to `registry_seller_client`, which existed but had
      no callers.
- [x] 3b.3 Four raw `httpx.get` reads of `/listings/{id}` sent no headers;
      that route authenticates and admits `buyer`, `seller`, or `service`, so
      it answered `401 context_mismatch`. Signed via a helper, verified against
      the registry's own `verify_request`. They stay raw because they assert on
      the status code — 200 against 404 is what distinguishes "published here"
      from "not published here", and the typed client raises instead of
      reporting it. The two private-registry reads keep their bearer token
      alongside the signature: both gates apply and neither substitutes for
      the other.

- [ ] 3b.4 **Findings, not repaired here.** Each is downstream of a listing
      that now publishes, so none was observable before this change:

      | Finding | Tests |
      |---|---|
      | `409 No available compute VM matched required attributes` on admin reservation | 2 |
      | `500 UNIQUE constraint failed: storefront_listing_bindings.derivation_key` on a second listing create | 1 |
      | `market credits buy` exits `rc=2` before writing a run-log (carried from the previous change) | 1 |

## 3c. Registry response-body authentication (production)

Round result: **9 failed, 50 passed, 42 skipped** from 10/47/44. All three
3b fixes landed — `max_skew` gone, the repoint took effect, and the signed
reads verify (`bob_in_a` and `alice_in_a` both true where both were 401).

- [x] 3c.1 **The registry verified proofs against a re-serialized model.**
      `validate_publish` hashed `ValidatePublishRequest.model_validate(body)
      .model_dump(mode="json")`, which materializes every defaulted field. A
      caller that omits an optional one — `demands`, here — signs a different
      document and is refused `401`. The refusal is unsigned, so the client
      cannot verify it and reports `unsupported_version` wrapped as `502`,
      naming nothing about the cause.

      Added `wire_body` and authenticated against the bytes received; the
      parsed model still serves validation. Only this route was affected:
      `publish_listing` and `update_listing` take `body: dict` and so already
      hashed what arrived.

- [x] 3c.2 **The test suite had encoded the defect.** `_ValidationAuth` signed
      `ValidatePublishRequest.model_validate(json.loads(request.content))
      .model_dump(mode="json")` — the same transformation the server applied —
      so the pair agreed while every real client failed. Corrected to sign the
      wire bytes, and added a guard asserting that a payload omitting optional
      fields authenticates.

      Evidence the corrected tests exercise the fix: against pristine
      production code **all 10 fail**; with the fix the registry integration
      suite is **112 passed**. Every one of those ten was previously green only
      because the test reproduced the server's serialization.

- [x] 3c.3 **Buyer CLI config carried no authority pins.** `market buy` exited
      1 with `Missing required [registry.authorities] identity pins`. The
      fixture wrote only `[registry] urls`. Now emits one pin per registry with
      `authority` and `identities`, the exact key set the loader requires, and
      rejects a mapping that does not cover every configured URL — the loader
      demands an exact match, so partial pins are an error rather than a
      narrower trust set.

- [x] 3c.4 **The private registry's bearer token was stale.** The test
      hardcoded `test-buyer-token`; the stack seeds its bootstrap key
      (`development-registry-bootstrap-key`). Sourced from configuration, and
      the module docstring that asserted the old token corrected.

- [ ] 3c.5 **Finding: the committed buyer config is stale the same way.**
      `dev-env/identities/buyer.config.toml` spells the pin key `principals`
      where the loader requires `identities`, so it would fail with
      "contains an invalid authority" rather than the missing-pins error.
      Not repaired here: it is not on the e2e path, and it belongs with the
      inherited API-credits pin questions.

## 3d. Remaining authenticated-read drift

Round result: **9 failed, 54 passed, 38 skipped** from 9/50/42. The registry
body-hash fix landed (`unsupported_version` gone) and `market buy` now reaches
`rc=0` instead of refusing to start.

- [x] 3d.1 **Swept the reads properly this time.** 3c fixed the sites the
      errors named; two more failed the moment the earlier ones passed. The
      first sweep matched call text containing "registry", so
      `httpx.get(f"{url}/listings/{listing_id}")` — where the host is behind a
      variable — was invisible. Re-swept on the request *path* instead, which
      is the property that determines whether a route authenticates.
- [x] 3d.2 Signing helper moved from `test_multi_registry` into the vms
      conftest so every module reads through one implementation, and applied
      to the two reads in `test_full_deal` and `test_full_deal_buyer_cli`.
- [x] 3d.3 **Fan-in enumeration goes through the canonical client.** The
      per-URL helper hand-built a `urllib` request with a query string.
      Discovery is authenticated and the proof binds the query, so signing it
      by hand would be a second canonicalization to keep in step with the
      registry's — the same shape of mismatch as 3c.1. Added `registry_b` pins
      to configuration so a client can be constructed per registry; an
      unpinned URL is refused rather than read unsigned, which the dead-registry
      resilience case already treats as a per-URL error.
- [x] 3d.4 `evaluate_negotiate` takes `buyer_principal: Identity`, not
      `buyer_address`. The evaluation asks what the strategy would do for a
      caller, and the caller is a marketplace principal rather than an EVM
      wallet.

- [ ] 3d.5 **Findings unchanged**, all downstream of a publishing listing:
      `409 No available compute VM` (2), `500 UNIQUE constraint failed:
      storefront_listing_bindings.derivation_key` (1), `market credits buy`
      `rc=2` (1). New this round: `market buy` exits **rc=0 without writing a
      run-log**, which the 4a reporter change makes legible — the command now
      starts and succeeds but produces no run evidence, so the run-log path or
      its trigger is the next thing to look at.

## 3e. Fan-in conversion and a misleading assertion

Round result: **8 failed, 55 passed, 38 skipped** from 9/54/38.

- [x] 3e.1 **The fan-in signing worked; my conversion did not.** The typed
      client returned results and I then called `model_dump` on them.
      `ListingListResponse.listings` holds `ListingSummary` dataclasses whose
      serializer is `to_dict`, so every URL failed with
      `'ListingSummary' object has no attribute 'model_dump'` — after the
      request had already succeeded. Replaced the defensive `getattr` chain
      with the two names the class actually has. This is the branch's own
      lesson landing on me: `ListingListResponse` is exactly the type that
      taught it, and I modelled it instead of reading it.
- [x] 3e.2 **An assertion that gave inverted guidance.** Stage 05a's
      evaluate-negotiate check now reaches a real decision (`200 OK`), and got
      `reject`. Its failure message was written for `accept` only: it reported
      "Strategy accepted at round 0", told the reader to *lower* the opening
      price, and printed neither the decision nor the reason. Following it
      would have moved the price the wrong way. Now reports the actual
      decision, reason, and both reference amounts, and separates the guidance
      for `accept` from `reject` while warning that a guard can decline for
      reasons unrelated to price.

      Deliberately not tuned `BUYER_INITIAL_PRICE`: the reason is not yet
      known, and choosing a price to make a red test green without it would be
      guessing at the scenario's intent.

- [ ] 3e.3 **Findings unchanged:** `409 No available compute VM` (2),
      `500 UNIQUE constraint failed: ...derivation_key` (1), `market credits
      buy` `rc=2` (1), and `market buy` exiting `rc=0` without a run-log (1).

## 3f. Buyer identity on the negotiation path

Round result: **8 failed, 57 passed, 36 skipped** from 8/55/38. Fan-in is
fixed; no per-URL registry errors remain.

- [x] 3f.1 **`buyer_address` is retired across the client.** No method accepts
      it, so all 14 call sites were latent `TypeError`s; only two had been
      reached. The replacement differs by method, which is why a blanket
      rename would have been wrong:
      - `negotiate_new` derives `buyer_principal` from the signer — the
        argument is simply gone.
      - `evaluate_negotiate` takes `buyer_principal: Identity`.
      - `settle` still needs the wallet, now as `buyer_evm_address`.
      - `get_settle_status` and `wait_for_settlement` never needed it.
- [x] 3f.2 **Corrected an error from 3d.** The two multi-registry buyer clients
      were built without a signer on the belief that `negotiate_new` is
      unauthenticated. It signs with `role="buyer"` and takes the buyer
      principal from the signer, so both now carry one.
- [x] 3f.3 **Checked the whole surface statically rather than per run.** Walked
      the AST of every e2e module and compared each storefront-client call
      against the installed signature: unknown keywords and missing required
      arguments. That found two sites in a module this round had not touched.
      **0 mismatches** remain suite-wide. Reacting to one `TypeError` per run
      is what turned this into five rounds; the signatures were readable all
      along.

- [x] 3f.4 **The 05a assertion earned its keep immediately.** It now reports
      `decision='reject' reason='no_matching_inventory'` — not a price problem.
      The message it replaced would have sent the reader to adjust
      `BUYER_INITIAL_PRICE`, which is why it was worth fixing before tuning
      anything.

- [ ] 3f.5 **Findings.** `no_matching_inventory` and the two
      `409 No available compute VM` reservation failures are plausibly one
      cause — the seeded inventory not matching the demanded resource
      attributes — and should be investigated together rather than as three.
      Also open: `500 UNIQUE ...derivation_key` (1), `market credits buy`
      `rc=2` (1), `market buy` `rc=0` with no run-log (1).

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

## 3h. Restore the deleted scenario stages

- [x] 3h.1 Eleven stages restored from commit `a1128a4c`, 514 lines: four
      `pauses_the_storefront_loops`, five
      `registers_executor_host_and_syncs_projection`,
      `test_09bb_claims_cycle_registers_the_seller_claim`, and
      `test_10a_expire_lease_and_arm_teardown_gate`. Seven arrived as whole
      classes that had been removed; placement was computed by comparing class
      order against the August file rather than guessed, because pytest runs
      stages in file order and a capacity declaration after the listing it
      backs is useless.
- [x] 3h.2 Collection rises 127 → 140, with all 11 stages selected.
- [x] 3h.3 **Signature check over the restored code**, extended this round to
      flag calls to methods that do not exist at all — the earlier version
      skipped them, which is why it reported clean while three were broken.

- [ ] 3h.4 **Six pre-existing mismatches surfaced by the stronger check.**
      Verified present in the checkpoint before this restoration, so not
      introduced here:

      | Site | Problem |
      |---|---|
      | `test_compute_dynamic_listings.py` ×4 | reaches into `storefront_admin_client._post` and `._admin_headers` — private helpers, and `_admin_headers` belongs to the retired shared-key model |
      | `test_full_deal.py`, `test_full_deal_buyer_cli.py` | call `admin_release_one_reservation`, which the client no longer exposes |

      The private-helper reach-through is the more interesting one: a test that
      calls a client's internals bypasses exactly the signed-request
      construction the client exists to own, so it would keep working while the
      public path was broken. Both need a public route or a recorded reason,
      and the release call needs its replacement identified.

## 3i. Faults in the restored stages

Run: **14 failed, 61 passed, 39 skipped** from 8/57/36. The rise is the 13
restored stages running for the first time since August; 14 = the 8 carried
failures plus 6 new, all in the restored code.

- [x] 3i.1 **The capacity-admin client was signing as the wrong principal.**
      Five failures, one per executor stage:
      `SiteCapacityAdminClientError: Invalid marketplace authentication`.
      `SiteCapacityAdminClient` asserts the `seller` role, and provisioning
      binds that role to the storefront principal it serves
      (`PROVISIONING_STOREFRONT_IDENTITY__IDENTIFIER`, Anvil 2). The fixture
      signed as the provisioning administrator, which is trusted for `admin`
      and refused here.

      The August fixture passed a shared admin key, under which the caller's
      identity did not matter; it does now. Declaring sellable capacity is a
      seller's act, so the corrected principal agrees with what the call means
      rather than merely satisfying the check. Verified the signer derives to
      exactly the identifier provisioning pins.

- [x] 3i.2 **Two constants and a helper were left behind by the restoration.**
      `DYNAMIC_POOL_ID`, and `E2E_LEASE_EXPIRY_BACKDATE` with
      `_expired_lease_end()`. Inserting stage bodies moved the code that used
      module-level names without the names themselves — the restoration was
      scoped to functions and classes, and nothing checked what they referenced.

      Swept the modules with pyflakes rather than fixing the one name the run
      reported: that found the other two before they cost a round. Added to the
      pre-handoff checks alongside the signature comparison, for the same
      reason — a `NameError` in a stage that has not run yet is invisible to
      both collection and the AST signature check.

- [ ] 3i.3 Findings unchanged: `409 No available compute VM` (2),
      `offer_unfulfillable` (2), `no_matching_inventory` (1),
      `500 UNIQUE ...derivation_key` (1), `market credits buy` `rc=2` (1),
      `market buy` `rc=0` with no run-log (1). The inventory cluster should
      clear once the executor stages authenticate.

## 3j. Two pauses, and pools that declare what they deliver

Run: **7 failed, 69 passed, 38 skipped** from 14/61/39. Capacity declaration
worked: `no_matching_inventory` and the strategy's terminal `reject` are gone,
and the two reservation refusals moved from "no VM matched" to a mode
declaration — further down the same path.

- [x] 3j.1 **I conflated the two pause controls.** `negotiate/new` refused with
      `503 {"error":"paused","reason":"global"}` because I wired
      `set_loops_paused` into `admin_pause`, which also stops trading. August
      kept them separate and its docstring said why: *"a scenario needs
      deterministic reconciliation and a deal to agree."* A single control
      makes the second impossible.

      Restored `/lifecycle/pause` and `/lifecycle/resume` as loop-only
      controls with their own contracts and client methods; `/admin/pause`
      returns to trading only. My own gate module docstring claimed the two
      were "deliberately separate" while the controller wired them together —
      the test caught what the comment asserted.

      A gain from separating them: the loop-only response carries per-loop gate
      state, so `pause_storefront` again asserts that each loop reached its
      gate rather than that a pause was merely requested. That closes the
      weakening recorded in 3g.6.

- [x] 3j.2 **Pools must declare the offering modes they deliver.** Reservation
      refused with `offering mode 'vm' is not declared by matching pool(s)`.
      The August `register_e2e_pool` predates `pool-declared-offering-modes`
      (2026-09-04) and set only `listing_mode`. It now writes the
      `deliverable_modes` policy tag, and reconciles it on an existing pool the
      same way the listing mode already was. Verified against the server's own
      `pool_delivers_offering_mode` predicate, including that the old tag shape
      fails it.

- [ ] 3j.3 **Remaining.** Findings: `500 UNIQUE ...derivation_key` (1),
      `market credits buy` `rc=2` (1), `market buy` `rc=0` with no run-log (1).
      Out of scope: alice's `offer_unfulfillable` (1) — provisioning serves one
      storefront, so her capacity view cannot load; to be deprecated with that
      reason recorded. Expected to clear next run: the two reservation
      refusals (2).

## 3k. The lifecycle module I was reinventing

Run: **10 failed, 72 passed, 32 skipped** from 7/69/38. Six previously-skipped
stages now run, which is why passes and failures both rose.

- [x] 3k.1 **My pause assertion asserted what I had documented it could not.**
      `set_loops_paused` returned a snapshot, and my own docstring said so: *"a
      loop mid-cycle when the request arrives is still `running` ... a caller
      that needs the stronger property waits."* `pause_storefront` then
      asserted every loop was already `paused`. Two rounds running I wrote the
      correct reasoning in a comment and contradicted it in code.

- [x] 3k.2 **An eighth deleted module: `market_storefront/lifecycle.py`**, 350
      lines, which is the designed version of the gate I hand-rolled. It has
      what mine lacked: a per-loop acknowledgement event, `await_quiescence`
      with a bounded wait so pausing returns only once loops sit at their
      gates, `pausing` distinguished from `paused`, and a warning when a loop
      gates under an unregistered name. Its comments also record the exact
      trap I fell into: *"conflating the two made the second impossible to ask
      for."*

      Restored it and tombstoned my `core_storefront/loop_lifecycle.py`.
      `server._set_loops_paused` awaits quiescence before reporting.
      `CLAIMS_ENGINE` becomes `SETTLEMENT_SERVICING`, the same periodic sweep
      under the name the neutrality redesign gave it.

- [x] 3k.3 Restored `test_lifecycle_registry.py` and
      `test_lifecycle_client_parity.py`, also deleted. Storefront suite
      **1128 passed** (from 1107), with the 4 pre-existing failures.

- [ ] 3k.4 **`test_loop_gate_wiring.py` is held back, and is the next task.**
      Restoring it fails 10 tests, which is the correct answer: it asserts that
      *every* production loop acknowledges its gate, and my rewiring covers
      four of five. The capacity-events poller is ungated and registers one
      loop per site, which the test also checks. Not shipped only because
      landing a red suite is worse than landing a precise specification of the
      remaining wiring; it goes in next round with the wiring that satisfies
      it, and must not be weakened to fit.

- [ ] 3k.5 **New, needs diagnosis.** Reservations moved from `502` to
      `500` and a `settle/{escrow}` call now fails — both further along the
      capacity path than before, both first-time-reached. Findings unchanged:
      `500 UNIQUE ...derivation_key`, credits `rc=2`, `market buy` `rc=0`.
      Out of scope: alice `offer_unfulfillable`.

## 3l. Startup crash from the lifecycle rewiring

The run never reached pytest. Both VM storefronts exited (3) on
`TypeError: start_registered_loop() got an unexpected keyword argument
'logger'` — I substituted the function name at four call sites and left an
argument it does not take. Its logger parameter is `task_logger`, because it
forwards to `start_storefront_background_task` and needs to distinguish the
two.

- [x] 3l.1 Fixed the four registered-loop call sites. The two remaining
      `logger=` sites are correct: the capacity-events poller, still ungated
      and therefore still on `start_storefront_background_task`, and the
      startup-steps runner.
- [x] 3l.2 Checked every call in `startup.py` against the real signatures by
      AST rather than by eye: **0 mismatches**. The same technique that has
      been catching client drift applies to internal calls, and would have
      caught this before the run.
- [x] 3l.3 Storefront suite **1128 passed**, 4 pre-existing failures.

      Recorded because the lesson is specific: nothing in the unit suites
      exercises `startup.py`'s call sites, so a signature error there is
      invisible until a container starts. `test_loop_gate_wiring.py` — held
      back in 3k.4 — is what covers this, which makes landing it the priority
      rather than a follow-up.

- [x] 3l.4 `credits-storefront` logs `KeyError: 'X-Market-Identity-Scheme'`
      and a failed quota registration against the credits service, but the
      container reports **healthy** and did not fail the run. Pre-existing
      noise in the API-credits lane, adjacent to the inherited questions about
      that topology; recorded rather than chased.

## 3m. Second startup crash from the same edit

`TypeError: run_negotiation_watchdog() got an unexpected keyword argument
'task_logger'`. The 3l fix rewrote `logger=logger` by text within each
`start_registered_loop(...)` argument span — which contains a nested
`partial(run_negotiation_watchdog, ..., logger=logger)`. The outer call needed
the rename; the inner one did not.

- [x] 3m.1 Restored `logger=` on the watchdog partial. Its parameter is
      `logger`; only `start_registered_loop` uses `task_logger`, because it
      forwards to `start_storefront_background_task` and must distinguish them.
- [x] 3m.2 **The 3l check was too narrow and passed anyway.** It compared
      keywords for calls made by name, so a callee reached through
      `functools.partial` was invisible. Widened to resolve `partial`'s first
      argument and check against that signature: **0 mismatches** across
      `startup.py`, direct and partial.

      Two crashes from one edit, both surviving a check I had just written.
      The pattern is that a text substitution inside a call span is not scoped
      to that call — the span contains other calls — and a check derived from
      the same mental model as the edit shares its blind spot.

- [ ] 3m.3 **`test_loop_gate_wiring.py` needs harness adaptation, not
      weakening.** Attempted to land it; 10 tests fail on module internals
      rather than on the gate contract — it patches
      `fulfillment_resume_runtime.get_sqlite_client`, which no longer exists
      because the loop now takes an injected `sqlite_client`. The gate
      assertions are the ones worth keeping; the injection points have moved.
      Adapting the harness while preserving every assertion is the next task,
      and it is what would have caught both crashes above: nothing else in the
      suites exercises `startup.py`'s call sites.

## 3n. Gate the fifth loop, through the kit

- [x] 3n.1 **`poll_events` takes a gate factory, not a predicate.**
      `paused: Callable[[str], Callable[[], bool]] | None` receives a site id
      and returns that site's gate. The pollers run concurrently and each holds
      its own feed position, so one shared predicate could only hold every site
      together. `site_events_poller` in `core_storefront` consults it once per
      cycle before any request, so a cycle either runs completely or never
      starts — an interrupted cycle would replay or skip events.

      Per-site fan-out stays in the kit. Nothing about it is compute-specific,
      and moving it back to the storefront to satisfy a test would revert an
      architectural choice to make an assertion convenient.

- [x] 3n.2 **Declared gates.** `await_quiescence` waits on task handles, and
      the storefront holds no task per site now. `lifecycle.declare_and_gate`
      registers a gated name with no handle, so it acknowledges and is waited
      on; without it a site poller could still be mid-cycle while the pause
      reported every loop idle — optimistic in the one direction a pause exists
      to prevent. `loop_states` reports declared names too, since a name that
      is waited on and reports nothing is the least useful place to be silent.

- [x] 3n.3 All five loops are now gated and acknowledged: negotiation
      watchdog, settlement servicing, fulfillment resume, site projections, and
      capacity events (aggregate plus one declared gate per site).

- [x] 3n.4 Tests. Added two cases to `test_lifecycle_registry.py` covering a
      declared gate: that it is waited on and reports `paused`, and that
      declaring suppresses the unregistered-name warning. Updated
      `test_poller_loop_delegates_to_composed_kit_runtime`, which asserted the
      old delegation shape — now asserts the factory is passed and returns a
      per-site gate, by shape rather than identity.

      Storefront **1130 passed**, 4 pre-existing failures; `core/storefront`
      160 passed; `kit/capacity-publication` 8 passed.

- [ ] 3n.5 **`test_loop_gate_wiring.py` still not landed.** Its watchdog cases
      patch `market_storefront.negotiation_watchdog`, a module that no longer
      exists — the watchdog moved to `market_storefront_kit` and is driven by
      an injected predicate. Its per-site cases assert storefront-side
      registration, which is now the kit's. Adapting it means rewriting the
      harness against both seams while preserving every assertion; that is the
      next task and is worth doing, because nothing else exercises
      `startup.py`'s call sites and two startup crashes came from exactly there.

## 3o. The gate wiring test lands, and finds two defects

- [x] 3o.1 **Adapted, not weakened.** All ten cases kept. Two loop bodies moved
      to `kit/` since the test was written, so the watchdog and the settlement
      sweep are covered through the injected predicate — the same seam the
      original covered for the core-bodied loops, and the seam that was wrong.
      The per-site cases assert declared gate names instead of task handles,
      because the fan-out is the kit's now; the property is unchanged, that each
      site acknowledges for itself and one cannot answer for another. **10
      passed.**

- [x] 3o.2 **I was wrong to drop the startup-delay case.** I removed
      `test_negotiation_watchdog_gates_before_its_startup_delay_elapses` on the
      grounds that `STARTUP_SWEEP_DELAY_SECONDS` no longer exists. It does,
      renamed to `policy.initial_delay_seconds` — and it sits *before* the
      loop, so the watchdog was unobservable for its whole startup window. The
      original's docstring names the consequence exactly: "the first pause of an
      end-to-end run lands inside it."

      Moved the delay inside the loop, after the gate: it now holds the first
      sweep and not the acknowledgement. Case restored and passing.

      This is the second time I have declared a restored assertion obsolete and
      been wrong. Both times the subject had been renamed rather than removed.

- [x] 3o.3 **The fulfillment-resume loop no longer survived a failing sweep.**
      August wrapped the cycle — "a cycle that raises must not end the loop …
      would otherwise stop the resume worker for the life of the process with
      no further sweep and no recovery." The guard was lost when the loop was
      rewritten to take an injected client, before this change. Restored,
      including the `CancelledError` path so a cancelled loop still exits
      cleanly rather than being caught by the broad handler.

      Found only because the restored test asserts it. Nothing else did.

- [x] 3o.4 Suites: `domains/vms/storefront` **1140 passed**, 4 pre-existing
      failures; `core/storefront` 160; `kit/settlement-runtime` 90;
      `kit/capacity-publication` 8; `kit/storefront` 7 passed with its
      pre-existing `test_composition` failure.

      `startup.py`'s call sites are now exercised by tests, which is what both
      startup crashes needed.

## 3p. The six pre-existing mismatches

All six turned out to be one gap: no service-role client. Each was a scenario
standing in for the provisioning peer with no way to sign as it.

- [x] 3p.1 **Four private-helper reach-throughs.** Two dynamic-listing stages
      posted to `/api/v1/admin/fulfillment/events/{usage-started,
      capacity-released}` through `storefront_admin_client._post` with
      `._admin_headers()`. Those are service-peer callback routes, and
      `_admin_headers` belongs to the retired shared-key model.

      Reaching into a client's internals bypasses the signed-request
      construction the client exists to own, so the call would keep working
      while the public path was broken — the same shape as the registry test
      that encoded the body-hash bug. Now `notify_usage_started` and
      `notify_capacity_released` on a service-role client.

- [x] 3p.2 **`admin_release_one_reservation` has no admin replacement, and
      should not.** The surviving `admin_release_reservations` is fleet-wide;
      using it here would clear other scenarios' holds, which is the race the
      archived identities change recorded when it removed a fleet-wide
      teardown. The per-reservation production path is the peer callback, so
      both call sites now use `notify_capacity_released` with the
      `capacity_reservation_id` the reserve response already returns.

- [x] 3p.3 Added `storefront_service_client`, signing as the provisioning
      service's own principal (`provisioning.service_credential`, Anvil 0) with
      `caller_role="service"`. Verified the signer derives to exactly the
      identifier `storefront.bob.toml` pins as its service peer. Distinct from
      the provisioning admin credential: the two are trusted for different
      roles and are not interchangeable.

- [x] 3p.4 **The signature sweep is clean for the first time** — 0 mismatches
      across every e2e module, including calls to methods that do not exist,
      which the earlier version of the check skipped. Collection 140; pyflakes
      clean apart from one pre-existing unused local.

## 3q. The `500 UNIQUE ... derivation_key`, diagnosed

Two separate problems wearing one symptom.

- [x] 3q.1 **Test drift: two scenarios shared a publication source.** A
      listing's binding is keyed on site, offering mode, contract, and its
      source identity -- pool, resource, GPU count -- so two scenarios
      advertising one resource on one site derive the same key and the second
      create is refused.

      `test_full_deal.py` and `test_full_deal_buyer_cli.py` both used
      `compute-e2e-deal-001`. August's buyer-CLI scenario used
      `compute-e2e-deal-cli-001`; the distinct id was lost at some point, and
      the restored executor stage still declared capacity under the August name
      -- so that scenario also had capacity for a resource its listing never
      advertised. Restored throughout the file, including the seeded CSV row,
      whose `vm_host` now names this scenario's own executor rather than the
      shared `kvm1`.

      Demonstrated against the real function rather than inferred: identical
      resource ids produce identical keys, distinct ones do not. Audited every
      scenario -- no resource id is shared now.

- [ ] 3q.2 **Product finding: an `IntegrityError` escapes as a 500.**
      `upsert_listing_with_binding` is named for an upsert but does not upsert
      on this constraint, and `listings_controller` lets `sqlite3.IntegrityError`
      reach the client as
      `500 {"detail": "UNIQUE constraint failed: storefront_listing_bindings.derivation_key"}`.

      Two defects regardless of who caused the collision. A caller publishing a
      listing whose source is already bound is making a conflicting request,
      not triggering a server fault: it should be a `409` naming the colliding
      source and the listing that holds it. And a raw SQLite constraint string
      is not a contract -- it names a column, not the thing the caller did
      wrong, which is why this read as a mystery for several rounds.

      Not repaired here: it is storefront error handling with no fixture
      component, and the scope boundary applies. Raise as an issue with the
      trace and this diagnosis.

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

## 3s. The advance route still named the claims engine

Reported from the branch head, and correct: `test_full_deal.py` expected
`result["loop"] == "claims_engine"` while the controller returned
`"settlement_servicing"`. Confirmed against the snapshot -- one stale
reference, and the only one in the tree.

- [x] 3s.1 **Mine, from the restoration.** The stage was inserted verbatim from
      the August tree. I applied the `CLAIMS_ENGINE -> SETTLEMENT_SERVICING`
      substitution to the storefront unit tests I restored and not to the e2e
      stages, where the name appears as a string literal inside an assertion
      rather than as a constant.

- [x] 3s.2 **Fixed at the root, not at the assertion.** A loop's name was
      spelled in four places: the registration, the gate call, the route alias,
      and the response literal. `test_loop_gate_wiring.py` covers the first
      two; the last two were unguarded, and both had drifted -- the route was
      still `/lifecycle/claims/run-cycle`, which named an engine that no longer
      exists.

      - Route renamed to `/lifecycle/settlement-servicing/run-cycle`.
      - `ADVANCE_LOOP_NAMES` declares alias -> registered loop name, and every
        handler reports from it. No response literal remains. Declared rather
        than derived because `site-projections` does not transform into
        `site_projection_poller` by any rule -- inferring it was what made my
        first attempt at the test wrong.
      - The e2e stage advances `settlement-servicing` and asserts that name.

- [x] 3s.3 `test_lifecycle_advance_routes.py`: each advance route reports a
      name the registry knows and runs exactly one cycle; every route appears
      in the declaration; every declared value is a registered loop. Three of
      the five fail against the pre-fix controller, so they test the change.
      Storefront suite **1149 passed**, 4 pre-existing failures.

      One incidental find: `admin_controller` and `server` import each other,
      so importing the controller from a cold interpreter hits the cycle
      part-way. Every other test here imports through the app and never sees
      it. Noted at the import in the new test rather than restructured.

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

## 3u. Two loops reached their gate once and never again

Run: **10 failed, 76 passed, 28 skipped**. The restored intervals worked --
every loop now reports `paused` except two, and both are mine.

- [x] 3u.1 **The capacity aggregate gated once, then blocked forever.** It
      awaited `poll_events`, which gathers the site pollers and never returns.
      One gate call is enough to be *acknowledged* and not enough to ever
      *observe a pause*, so every pause reported it `pausing` until the bounded
      wait expired. It now runs the fan-out as a task and gates and idles,
      which is also what keeps a storefront with no site configured reporting a
      capacity loop at all. A completed fan-out is awaited rather than idled
      over, so its failure surfaces instead of being hidden behind a healthy
      aggregate.

      Its idle cadence is its own constant, not the poll interval: the loop
      does no work, so the only thing the interval controls is how soon a pause
      is seen, and tying that to polling made observation as slow as the
      slowest deployment's polling.

- [x] 3u.2 **The watchdog's startup delay stopped it cycling.** In 3o.2 I moved
      the delay inside the loop so the gate came first. That fixed
      acknowledgement and not observability: the loop gated once, then slept 30
      seconds, so a pause requested after that first call went unseen for the
      whole window. Now a monotonic deadline holds the *sweep* while the cycle,
      and therefore the gate, keeps its cadence -- which is what the August
      implementation did, and what I should have copied rather than
      approximated.

- [x] 3u.3 **The tests could not have caught either.** Both asserted a loop
      reached its gate *at least once*, which both loops did. They now assert
      the gate is reached more than once, and the capacity case runs past one
      aggregate cadence so the window can contain a second call.

      Two consequences of the loop no longer returning:
      `test_poller_loop_delegates_to_composed_kit_runtime` awaited it and hung
      the suite, and its patched minimal settings then broke the app build that
      the gate's first `server` import performs. Both fixed in the test --
      driven as a task, with `server` imported up front.

      `domains/vms/storefront` unit **1007 passed**, 1 pre-existing failure;
      `kit/storefront` 7 passed with its pre-existing `test_composition`
      failure; the lifecycle files 59 passed.

- [ ] 3u.4 Unchanged: admin reservations `500` (traced to
      `service_peer_auth.py:312`), settle `409` for provision terms carrying no
      SSH key, and the three buyer-CLI exits.

## 3v. The admin reserve `500`, and what `resource_id` means for a pool

Run: **6 failed, 80 passed**. The gate-cadence fix cleared the four pause
failures.

- [x] 3v.1 **The `500` is `KeyError: 'resource_id'`** at
      `admin_controller.py:1254` in `reserve_capacity`. My earlier
      double-body-read hypothesis was wrong: the `EndOfStream` frames are
      starlette unwinding *after* an inner exception, and the three middleware
      frames are the chain the request passes through rather than where it
      fails. The loudest thing in the trace was the least informative.

- [x] 3v.2 **Discovery: what `resource_id` means per cardinality mode.**
      Settled from `openspec/specs/storefront-publication/spec.md`:

      | Mode | Candidate identity | `resource_id` |
      |---|---|---|
      | `specific_resource` | one per enabled member, each naming a physical resource; derivation key is resource-keyed | the node |
      | `fungible` | one pooled candidate, sized to what a single member can satisfy | absent -- pool-keyed |

      `resource-pool-management/spec.md` corroborates the optionality
      directly: every durable reference to a pool keys on
      `(site_id, pool_id[, resource_id])`. There is no `resource_id`-as-shape
      anywhere; a fungible candidate's shape is structural -- pool, slice size,
      and projected attributes. A named compute shape would come from ROADMAP
      Goal 2, whose dimensions Goal 1 records as not yet expressible, so it is
      a plausible future design rather than a current one.

      A fungible *reservation* is the separate question: the ledger does choose
      a member at reserve time, and records it as `member_id` plus a backing
      resource. So the likely contract answer is
      `ReserveCapacityResponse.resource_id: str | None` -- which is how the
      controller already treats `pool_id` two lines above, under the comment
      that pools are the aggregator's concept and not the ledger's.

- [x] 3v.3 **Root cause not settled statically, and the failure now says so.**
      Traced the payload through ledger, HTTP, site client and aggregator.
      Both ledger builders (`_match_payload`,
      `_reservation_payload_for_reserve`) always include `resource_id`, the
      transport is a passthrough `dict` that would carry a `None` rather than
      drop a key, and the only `exclude_none` in the path is on the *request*
      body. So a genuinely absent key is unexplained, and changing the response
      type on that basis would paper over a payload that should be complete.

      Extracted `require_reservation_fields`, which refuses such a payload with
      a `502` naming the missing field, the authority, and the keys the payload
      *did* carry. Absent and null stay distinct: a null `resource_id` is the
      authority saying there is no single backing resource, an absent key is
      the two sides disagreeing about shape, and collapsing them would turn the
      contract question into a silent empty string.

      Five tests against the extracted function -- not a copy of the guard,
      which is what my first draft did and is the antipattern this suite has
      already been caught by twice.

- [x] 3v.4 The next run's failure text did name the shape, from the other
      end: the guard passed, the hold landed, and `ReserveCapacityResponse`
      refused to serialize a payload with no `resource_id`. So 3v.2's
      contract question is answered by retirement rather than by
      `str | None` -- the field is not optional, it is absent by design.
      Completed in 3z.

## 3w. The SSH key is a negotiated term

- [x] 3w.1 The scenarios sent `"ssh_public_key": ""` in `negotiate_new`'s
      `provision_terms` and the real key at `settle`. August did the same and
      was green, so the product moved the key from a settle-time input to a
      negotiated term: settle reads it from the accepted terms, refuses an
      empty one, then refuses a caller's key that differs. Both guards say why
      in the same words -- "current configuration will not reinterpret this
      run". Fixed at all four sites, with the reason at each.

      `buyer_config` was already in scope at every site, checked by AST rather
      than by eye.

## 3x. Retiring `resource_id` from the reservation response

- [x] 3x.1 **The 502 named the payload, and the answer was a route that strips
      the field.** `kit/site`'s reserve route removes `resource_id`,
      `capacity_bucket_id`, `backing_resource_id` and `vm_host` from every
      reservation response before returning it. I had read that line rounds ago
      as a dimension filter and not noticed it rewrites the response.

      So `ReserveCapacityResponse.resource_id` was unsatisfiable for *every*
      reservation, not only pooled ones -- and because the dataclass defaulted
      it to `""`, a caller could not tell a stripped field from an answer. This
      is the "dead physical-identity plumbing" ROADMAP Goal 1 lists under
      `pools-9-retire-local-physical-authority`: a response field surviving
      from before the boundary stripped it.

- [x] 3x.2 Retired rather than worked around. Removed from the response model
      and `from_dict`, removed from the controller's construction, and dropped
      from `_REQUIRED_RESERVATION_FIELDS` -- requiring a field the boundary
      strips reintroduces a failure no authority can avoid. An unexpected
      `resource_id` in a payload now lands in `extra`, so nothing is silently
      discarded.

- [x] 3x.3 Three e2e assertions rewritten against what the boundary reports.
      The re-reservation stages asserted the response echoed the resource they
      had pinned in the claim; the claim is what establishes the match, so they
      now assert a reservation came back at the requested size. The dynamic
      stage asserts `pool_id`, which the boundary does report. Asserting
      physical identity there was only ever possible while it leaked.

- [x] 3x.4 Tests: six against `require_reservation_fields`, including that
      `resource_id` is *not* required and that a fully stripped payload is
      accepted. Storefront unit **1013 passed**, 1 pre-existing failure;
      `core/storefront-client` 30 passed.

- [x] 3x.5 The next run settled all three, and none of them the way the
      counts suggested: same six failures, four different causes.
      `market negotiate` got past the settlement option and exited 1 on a
      strict-contract parse (3aa); `market credits buy` still exits 2, on the
      missing buyer `[Settlement]` after all (3ab); `market buy` now exits 4
      rather than 0, and is the one cause this round could not establish
      (3ac). The reservation `500` was this retirement landing incompletely
      (3z).

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

- [x] 3y.4 The credits scenario did need the same section, and not assuming
      it was still right: the error text was the deciding evidence and it
      arrived by a different route -- `credits buy` refuses earlier and in
      its own words, before any run-log exists. Carried in 3ab.

## 3z. The retirement landed in three of four places

- [x] 3z.1 **Both dynamic-listing stages still `500` on admin reserve, and
      the innermost frame names a different layer.** The `KeyError` is gone;
      what raises now is
      `ValidationError: 1 validation error for ReserveCapacityResponse /
      resource_id / Field required`, from the model's `__init__` inside the
      route.

      The reservation itself succeeded: the stage event
      `capacity_reserved_by_admin` records the hold with its
      `closed_listing_ids`, and the site authority returned 200. Only the
      response refused to serialize. So the failure moved from before the
      write to after it -- the route now performs its effect and then reports
      a 500, which is worse than the original for a caller that retries.

- [x] 3z.2 **Cause: the retirement was applied to the client dataclass, the
      controller's construction and the required-fields tuple, and not to the
      server's response model.** Four places hold this field's shape and 3x
      moved three of them. `capacity_admin_models.ReserveCapacityResponse`
      still declared `resource_id: str`, required.

      Removed, with the boundary's reason stated on the model the way the
      client dataclass already states it -- the next reader of either sees
      why the field is absent rather than missing.

- [x] 3z.3 **Why the existing tests did not catch it.** The five tests added
      in 3x.4 bind `require_reservation_fields`, which is the guard, and the
      guard was correct. Nothing constructed the response. That is the
      shape this suite has been caught by before from the other direction:
      a test that exercises one layer and reads as though it covered the
      contract.

      Added two tests that build `ReserveCapacityResponse` the way the
      controller builds it, from the same stripped payload the guard accepts,
      plus one asserting the field is absent from `model_fields`. The guard
      and the response now fail together or pass together.

## 3aa. `TrustedIdentitySet` refused its own decoded wire form

- [x] 3aa.1 **`market negotiate` now exits 1, ~200 lines further on.** 3y's
      `[Settlement]` section worked: the CLI selects the advertised option,
      resolves prices, and dies at
      `TrustedIdentitySet.model_validate(listing_dict.get("publisher_principals"))`
      with `identities / Input should be a valid tuple ... input_type=list`.

- [x] 3aa.2 **The contract accepts an array over the wire and refuses the
      same array once decoded.** `ContractModel` is `strict=True`, and
      strict validation's Python-mode conversion table refuses a `list` for a
      `tuple` field -- while its JSON-mode table accepts an array. Verified
      both directions against the installed pydantic rather than from the
      documentation: `model_validate_json` parses the payload,
      `model_validate` of the decoded dict does not. Nested `Identity` dicts
      are accepted either way, so list-versus-tuple was the whole of it.

      Every caller reading a listing's publisher principals is on the decoded
      path. Three of them -- `core_buyer.orchestration._seller_principals`,
      `core_buyer.deal_helpers._parse_publisher_trust` and
      `registry_client.models.from_dict` -- hand-roll the conversion, which
      is what kept the gap invisible until a fourth validated the decoded
      payload directly.

- [x] 3aa.3 **Fixed on the contract, once, following the convention this
      repository already uses for it.** `AlkahestSettlementConfig` is the
      same kind of model -- `extra="forbid"`, `frozen=True`, `strict=True`
      with tuple fields -- and carries `accept_toml_address_lists`, a
      `mode="before"` validator converting the array form to a tuple. The
      validator added to `identities` mirrors it.

      Deliberately not `Field(strict=False)`, which would also admit a set or
      a generator and let the caller decide the order of a contract whose
      docstring pins it as ordered. A `list` only; everything else still
      fails.

- [x] 3aa.4 Tests: the decoded form parses and equals the JSON-parsed form,
      and every constraint survives it -- uniqueness, the one-to-two bound,
      identifier validation, and a set still refused. Verified by executing
      the model, not by reading it.

## 3ab. The credits buyer had no settlement mechanism either

- [x] 3ab.1 **`market credits buy --new-key` exits 2 with no run-log, and
      the credits CLI refuses earlier than the VM one.** Its generated config
      carries `[wallet]` and `[chains.anvil]` and no `[Settlement]`, so
      `buy_cli` raises
      `no buyer settlement mechanism is enabled` before `RunLog.start` --
      which is exactly the reported symptom, rc 2 and no first event.

      3y.4 declined to assume this from the VM failure. The assumption would
      have been right and the caution was still correct: the two CLIs refuse
      at different points for the same missing section, and the credits one
      refuses without leaving evidence, so the guess could not have been
      confirmed from a run-log that does not exist.

- [x] 3ab.2 Added the section by mirroring the VM fixture's working one
      rather than assembling it from the field list, as in 3y.2:
      `priority = ["alkahest.v1"]`, `enabled = true`, and
      `address_config_path` on the mechanism section as well as the chain
      entry. The seeded credits listing is priced in an anvil ERC-20, so
      alkahest is the mechanism the seller advertises.

- [ ] 3ab.3 Unverified beyond this: the credits storefront's own config has
      no `[Settlement]` section, and its seller-side readiness raises
      `no enabled settlement mechanism is ready` when nothing is enabled. It
      reported healthy this run, but it also failed its demo seed (the
      carried-forward `X-Market-Identity-Scheme` quota-registration 401), so
      it never published and never exercised that path. If the next run
      discovers no credits listing, this is the first place to look -- and a
      missing seller section, not the buyer's.

## 3ac. `market buy` exits 4, and the cause is not established

- [x] 3ac.1 **What the run proves.** The buy discovers one match, prints
      `negotiate →`, and reports `exited / no_match_agreed_to_terms` with
      rc 4. No `/api/v1/negotiate/new` reaches bob-storefront at any point in
      the scenario's window -- the whole container log was read, not the tail
      -- so the buyer abandoned the negotiation locally, before contacting
      the seller. Progress from the previous run's rc 0, which produced no
      run-log at all.

- [x] 3ac.2 **What it rules out, and why the remainder does not add up.**
      Every local exit path in the negotiate hook returns before
      `negotiation_started` is emitted, and that event was emitted. An
      exit-at-opening decision, a `RuntimeError`, and an escaping exception
      each leave a visible trace -- `negotiate ←`, `negotiate ✗`, or a rich
      traceback with rc 1 -- and none appears. Stdout is complete: the
      assertion tails 2500 characters and the captured output is shorter.

      So the evidence and the source disagree. Rather than pick the most
      plausible frame and act on it -- the mistake this change has already
      paid for once -- this round buys evidence.

- [x] 3ac.3 **Product diagnostics, not test-only.** Three gaps, each real
      outside the suite:

      - The negotiate hook narrows its handler to `RuntimeError`, which is
        what the transport raises. Anything else left a negotiation with an
        opening and no outcome and no error -- a silence with three
        explanations. Now named in an event and an attempt record, then
        reraised unchanged.
      - A `negotiation_returned` event carrying scalars only, emitted before
        the outcome is serialized. The serialization can itself refuse a
        payload, and this separates "the seller declined" from "the buyer
        could not write down what happened".
      - `market buy` collected per-candidate attempts and dropped them,
        reporting one aggregate reason for a buy that agreed with nobody.
        The digest now reaches the run-log's terminal event and a
        `Candidates tried` panel on any non-ready outcome.

- [x] 3ac.4 The `B4` assertion prints the run-log's events on failure,
      through `events_or_empty` -- the non-blocking read added for callers
      reporting a failure they already have. Whitelisted fields: the full
      events carry proposals, accepted terms and tenant credentials, and an
      assertion message in CI output is not the place for those. Checked by
      running the selection over representative events.

- [x] 3ac.5 The digest decided it in one run:
      `CanonicalizationError: body is not canonicalizable JSON`, raised inside
      the negotiation and now named in the event stream, the attempt record
      and a `Candidates tried` panel. Not a seller refusal at all. Carried
      into 3ah, which is where it stops being an e2e repair.

## 3ad. Four fixes landed; four causes moved

- [x] 3ad.1 Same six tests, and every one of them a different failure:
      admin reserve returns `200` and the response now reports no `pool_id`
      (3af); settle passes the SSH term and fails reading the escrow from
      chain (3ae); both buyer CLIs reach the wire and fail to canonicalize an
      18-decimal amount (3ah); `credits buy` still exits 2, still without
      evidence (3ag). The count has not moved in three runs and the stack has
      moved every time -- read causes, not counts.

## 3ae. Settle handed the mechanism adapter to escrow verification

- [x] 3ae.1 **`400 Failed to read escrow ...:
      'AlkahestConditionalEscrowClient' object has no attribute 'erc20'`.**
      `create_client("alkahest.v1")` returns the conditional-escrow adapter --
      the mechanism's materialize/check surface -- while escrow verification
      reads an attestation through the alkahest client's own escrow codecs and
      needs the resolved chain client. `prepare_vm_settlement` passed the
      adapter.

      Three other callers get this right and pass the chain client: the admin
      dry-run (which is why stage `07b` verifies the same escrow
      successfully), the resume sweep, and the resume convergence path. The
      settle path is the one outlier, and the mismatch surfaces *after* the
      buyer has created and funded the escrow.

- [x] 3ae.2 Added `chain_client()` to the adapter and used it at the call
      site, rather than reaching into composition for a second copy of the
      client map. The adapter already resolves chains internally for
      materialize and status; this makes that resolution available to a caller
      holding the mechanism client.

- [x] 3ae.3 **The unit test passed `object()` into a mocked verifier**, so any
      client type satisfied it. Replaced with a stub that resolves a chain
      client the way the adapter does, and an assertion that the verifier
      received *that* object. Same shape of gap as 3z.3: a test that binds one
      layer and reads as though it covered the seam.

## 3af. The reservation response reports no pool membership

- [x] 3af.1 **Both dynamic stages now get `200` and assert on `pool_id`,
      which is `None`.** Flagged as the likely next failure when the response
      model was fixed, so this is the contract question from 3v.2 arriving in
      its final form rather than a regression.

- [x] 3af.2 The payload carries neither `pool_id` nor pool-bearing resource
      attributes: the boundary reports the hold and withholds the topology.
      But the storefront is not missing this fact -- it recorded it at
      publication time in `storefront_listing_bindings.pool_id`, which is the
      durable `(site_id, pool_id[, resource_id])` reference the specs require
      every pool reference to key on. Read it from there, after the ledger and
      the mirrored attributes, so an authority that does report membership
      still wins.

      This is what "pools are the aggregator's concept, not the ledger's"
      means in practice: asking the ledger to echo the aggregator's topology
      was the same mistake as asking it for physical identity.

- [ ] 3af.3 Unverified: whether the `specific_resource` listing's durable
      binding carries `pool_id` as well as `physical_resource_id`. The
      publication binding is keyed on pool, resource and GPU count, so it
      should; if it does not, the next run reports `None` again and the answer
      is that the binding is incomplete at publication, not that the response
      is wrong.

## 3ag. The credits refusal still has no evidence

- [x] 3ag.1 `credits buy` exits 2 with no run-log for the third consecutive
      run. The `[Settlement]` section from 3ab did not change the outcome, and
      the reason is unknown because the helper deliberately withheld process
      output as possibly carrying a transient domain credential -- correct
      instinct, wrong consequence: three rounds of guessing about a message
      the command printed every time.

- [x] 3ag.2 Masked rather than withheld. Credential-shaped runs -- long
      hexadecimal and long opaque base64url -- are replaced before the stderr
      tail is quoted. Checked against the refusals this command can emit: the
      config-key and mechanism-ID text survives masking intact, while wallet
      keys, issued secrets and ed25519 material do not. Deliberately
      over-masks: a reader loses nothing, and CI output keeps a key forever.

- [ ] 3ag.3 Candidate refusals the next run will discriminate between, in
      order of suspicion: the hosted-funding branch demanding
      `[Settlement.stripe]` when the resolved funding mode is not
      `interactive`; a missing-config refusal for registry URLs or wallet
      material; and price resolution returning nothing. Read the text first.

## 3ah. Uint256 amounts do not survive canonical JSON — outside this change

- [x] 3ah.1 **Both buyer CLIs now reach the wire and fail there.**
      `market negotiate` and `market buy` raise
      `CanonicalizationError: body is not canonicalizable JSON` while signing
      the round-0 body. The underlying error is
      `IntegerDomainError: 7000000000000000000000 exceeds safe integer domain
      for JSON floats`, reproduced directly against the installed `rfc8785`:
      a Python `int` above 2^53-1 has no canonical JSON number form.

      The amount is `7000 × 10^18`. Both CLIs scale explicit prices from
      display units to base units using the asset's on-chain `decimals`, and
      the dev-stack MockERC20 reports 18 -- while the fixture's listing
      advertises `decimals: 0` and prices in raw units, on the belief that
      display equals raw here. So the scaling is not spurious; it is the
      product converting a human price correctly and then being unable to
      sign it.

- [x] 3ah.2 **This is an unimplemented existing requirement, not a fixture
      defect.** `negotiation-protocol/spec.md`, "Uint256-safe negotiation
      values": canonical JSON wire representations MUST encode uint256-domain
      values as decimal-digit strings, persistence MUST round-trip values
      beyond JSON's safe-integer range, and amounts MUST NOT be interpreted
      through floating point. Its first scenario is literally an 18-decimal
      token amount.

      The convention is implemented in `market_core.schemas` -- int
      internally, decimal-digit string on serialization -- and advertised
      rates already travel as strings. It stops at the negotiation proposal:
      `EscrowProposal.fields` is an untyped `dict[str, Any]`, and the scalar
      policy writes `fields["amount"] = int(round(amount))` through float
      arithmetic. So the wire carries a JSON number where the spec requires a
      string, and the policy layer reasons in doubles where the spec forbids
      it.

      Consequence beyond the suite: no deal denominated in whole units of an
      18-decimal asset can be signed by either party. The cap is ~0.009 of
      such a token.

- [x] 3ah.3 **Raised for disposition, and the disposition was to implement it
      here.** The work spans proposal encoding, integer arithmetic through
      the policy chain, the seller's context boundary, the accepted echo, and
      the refusal path -- a requirement being implemented rather than a
      fileset repairing a fixture. Carried out in 3ai.

## 3ai. Uint256-safe negotiation values, implemented

- [x] 3ai.1 **What had actually changed, since "it worked a month ago" is the
      right question.** The requirement was implemented server-side and on
      the typed contracts; the buyer's proposal path kept the old shape.
      Already correct before this round: `_amount_to_db_text` /
      `_amount_from_db_text` storing amount columns as decimal text because
      SQLite INTEGER cannot hold an 18-decimal amount; `market_core.schemas`
      carrying uint256 fields as int internally and decimal-digit strings on
      serialization; `kit/alkahest`'s accepted-escrow builder writing
      `fields["amount"] = str(agreed_amount)`; `_seller_reference_amount`
      computing the seller's price through `Decimal` and returning an int.

      Three places kept the old shape, all on the same field:
      `_set_proposal_amount` wrote `int(round(amount))` as a JSON *number*,
      `_amount_from_proposal` returned a float and the bisection compared and
      averaged in floats, and `NegotiationContext.our_reference_amount` was
      typed `float` with the round hook casting its exact integer through
      `float()` one line after computing it. `EscrowProposal.fields` is
      `dict[str, Any]`, so no typed model ever saw the value and nothing
      complained.

      It survived because the two conditions never met until now: the
      API-driven scenarios negotiate raw amounts near 10 000, and the
      buyer-CLI scenarios only began scaling display prices into base units
      when the settlement-DSL work introduced `price × 10**decimals`. This
      session's earlier fixes are what carried a CLI negotiation as far as
      signing for the first time. `rfc8785` did not change; the first
      uint256-magnitude value to reach `canonical_body_hash` arrived three
      runs ago, and it arrived as a JSON number.

- [x] 3ai.2 **The contract, in one place.** `parse_wire_amount` and
      `format_wire_amount` in `kit/policy`. Absent stays distinct from
      malformed: `None` for no scalar (exact escrows negotiate none), and a
      refusal for a float, a negative, a boolean, or a non-digit string. A
      float is refused even when integral at today's magnitude -- accepting
      `7000.0` is accepting `7e21`, and the contract is the type rather than
      the current magnitude.

- [x] 3ai.3 **Integer arithmetic through the policies.** The `0.01` and `1.5`
      float bounds restated as cross-multiplied integer comparisons
      (`their × 100 ≤ our × 101`, `their × 2 ≤ our × 3`) and midpoints as
      floor division. Same bounds, exact at any magnitude. `_exact_amount`
      guards the context bounds and still admits an integral float, so
      existing callers spelling a small bound `10_000.0` keep working while a
      fractional one is refused.

- [x] 3ai.4 **Types made honest.** `NegotiationContext` amounts are `int`,
      and the four sites casting to `float()` -- the VM, API-credits and
      bare-metal seller round hooks, plus the system-service dry run -- pass
      integers.

- [x] 3ai.5 **Exact scaling in both directions.** `display_to_base_units`
      shifts the exponent with `Decimal.scaleb` and refuses a price finer
      than the asset's smallest unit rather than rounding money the caller
      did not name; `scaled_base_units` multiplies a per-unit rate by the
      unit count exactly and refuses a non-integral product. Wired into all
      four CLI scaling sites (VM buy and negotiate, API-credits buy and
      negotiate) and both the fresh and resume paths of the negotiation
      client.

- [x] 3ai.6 **One wire convention, not three.** The RL strategy's own
      `_proposal_with_amount` was a fourth amount writer, also emitting a
      JSON number into a body the seller signs; it now uses the shared
      formatter.

- [x] 3ai.7 **A refusal rather than a 404.** `NegotiationAmountError` maps to
      `400 invalid_proposal_amount` on both negotiate routes, ahead of the
      generic `ValueError → 404` that would otherwise report a malformed
      amount as a missing listing.

- [x] 3ai.8 **Verified by execution.** 22 tests binding the production
      helpers in `kit/policy` (round trip, refusals, opening counter,
      clamping, convergence, the floor-division midpoint observed on the
      maximize side where it is not clamped, and a malformed peer amount
      refused rather than read as absent) and 8 in `core/buyer` binding the
      seam: an 18-decimal display price becomes an exact base-unit integer,
      the policy's round-0 body carries it as a string, and
      `canonical_body_hash` produces a digest -- the assertion that was
      failing in the stack. Six existing assertions moved to the wire form.
      All 30 run green here.

- [x] 3ai.9 **The balance question had an answer in the repository.**
      `dev-env/generate_state.py` funds the buyer with
      `FUNDING = 1_000 * 10**18` -- one thousand whole tokens of an
      18-decimal MockERC20, transferred in `9 * 10**18` chunks. So the dev
      chain has always treated this asset as 18-decimal with whole-token
      balances, and the fixtures' `decimals: 0` was the only place claiming
      otherwise. It also settles the 7000-token bid: it was seven times the
      buyer's entire balance and would have failed at escrow creation.

## 3aj. The fixtures now price at the asset's real decimals

- [x] 3aj.1 **What was inconsistent.** The listings advertised
      `decimals: 0` with a comment reading "listing-display only; raw
      amounts are what land on-chain", and priced in units of 10 000. The
      contract reports 18 decimals, the funding script mints whole tokens,
      and the publication clause compiler scales a resource's `min_price` by
      `resolve_token(...).decimals` read from the chain -- so nothing except
      those four fixture files believed in 0.

      That belief is what made a display price and a base-unit amount look
      like the same number, which is why a CLI scenario could pass explicit
      prices for a year and only now produce an unsignable one.

- [x] 3aj.2 **The new shape, one asking rate expressed once per path.** Ten
      tokens per hour: `10 * 10**18` base units in the explicitly advertised
      accepted-escrow rates, and `10` in the resource-import CSV's
      `min_price`, which is a display amount the clause compiler scales. The
      two paths now agree rather than coinciding, which they previously did
      only because a scale of `10**0` is the identity.

      Buyer prices keep their relationship to it: opening 7 tokens (under
      the rate, so round 0 counters), ceiling 12 (over it, so the buyer
      accepts the seller's first counter at 8.5). API-driven scenarios carry
      base units, `7 * 10**18` and `12 * 10**18`; the CLI scenarios carry
      whole tokens on the flags and let the CLI scale them, which is the
      product behaviour under test.

- [x] 3aj.3 **All three amounts are past 2^53-1 by construction**, so the
      scenarios now exercise the uint256 wire path rather than staying below
      the range where the old `int` form happened to work. Checked
      arithmetically rather than by eye: opening < rate < ceiling, the first
      counter lands under the ceiling, and worst-case exposure is 1.2% of the
      funded balance -- eight concurrent scenario escrows against the shared
      buyer wallet still fit.

- [x] 3aj.4 **The response models had to move with them.** An amount
      above 2^53-1 in a bare `int` response field is as unsignable as one in
      a request: the seller canonicalizes its own response body. Added
      `Uint256Amount` / `OptionalUint256Amount` to `market_core.schemas`
      beside the existing parse/serialize helpers, and applied them to the
      fields the scenarios now push into that range: negotiation
      `agreed_amount` and `proposed_amount`, force-accept request and
      response `amount`, `agreed_price` on the settle verification request,
      evaluate-negotiate's `our_reference_amount`, `their_proposed_amount`
      and `decision_amount`, and a listing refund's `amount_raw`. Verified by
      canonicalizing each of the changed responses at 18-decimal magnitudes.

      `negotiate_new` in the storefront client already sent
      `str(initial_amount)`, and `ForceAcceptRequest.amount` accepts the
      decimal string by ordinary lax coercion, so no caller changes were
      needed alongside.

- [x] 3aj.5 One did, and it was not a model field: the stage-event stream.
      Carried in 3ak.3.

## 3ak. The repriced fixtures reached further and found four more seams

- [x] 3ak.1 **`market buy` negotiated, escrowed, settled and provisioned.**
      Round 0 countered at 8.5 tokens exactly as the fixture intends, the
      buyer escrowed `8500000000000000000`, settlement submitted, the
      provisioning job ran. It then failed publishing fulfillment evidence:
      `'AlkahestConditionalEscrowClient' object has no attribute
      'string_obligation'`.

      The same defect as the settle path, at the other end of the deal, on
      the line this change noticed and left alone one round ago: peer
      settlement publishes its evidence as a string obligation through the
      alkahest client's codecs, and it was handed the mechanism adapter.
      Fixed the same way, through `chain_client()`, with the chain taken from
      the projection context. Worth naming: this one surfaces *after* the VM
      exists and the buyer's money is committed.

- [x] 3ak.2 **The evaluate-negotiate stages fail in the test's own request
      body.** Those fixtures build the proposal dict themselves and carried
      `"amount": BUYER_INITIAL_PRICE` as an int, so the buyer signed nothing
      -- `IntegerDomainError` came out of the client's own canonicalization.
      The fixtures now send the decimal-digit form.

      Deliberately not fixed by having the client rewrite the amount inside a
      proposal it is handed: `negotiate_new` constructs that field and can
      own its form, but silently editing a caller's signed body is a
      different promise. The refusal is loud and names the value.

- [x] 3ak.3 **The multi-registry stage broke on a `500` from
      `/api/v1/system/events`, three stages away from its cause.** The
      negotiation logged `round_decided` with `our_amount`, `their_amount`
      and `decision_amount` as raw integers; the events route serves those
      payloads in a signed response, and the response could not be
      canonicalized.

      Fixed in `_public_value`, the single funnel every stage-event field
      already passes through, so it covers the VM, API-credits and
      bare-metal emitters and any nested payload rather than seven call
      sites. Deliberately magnitude-dependent: `round` and `gpu_count` are
      genuinely numbers and consumers read them as such, so only a value
      with no canonical number form changes shape, and it changes to the
      same decimal string the rest of the contract uses.

- [x] 3ak.4 **The fungible reservation now reports its pool; the
      resource-keyed one still did not, and the fixtures explain why.** The
      fungible scenario declares `attribute.pool_id` on its resources and
      passes `pool_id` on its offers. The dynamic scenario declared the pool
      only in its *capacity declaration* -- the provisioning side -- while
      its CSV and its offers named a resource and nothing else. So the
      listing carried no pool provenance, its durable binding recorded none,
      and the reservation had no membership to report. The storefront was
      right; the fixture was asserting something it had never been told.

      Declared it, matching the capacity declaration this scenario already
      makes: `attribute.pool_id` in the CSV and `pool_id` on the offer. A
      `specific_resource` candidate is still a member of its pool, which is
      what `(site_id, pool_id[, resource_id])` says.

- [x] 3ak.5 **`credits buy` exits 2 because `--service-name` does not
      exist.** One line of redacted stderr, after three rounds of
      hypotheses -- the CLI printed it every time and the helper was
      throwing it away. Service selection goes through the typed resource
      query, which the option's own help text uses as its example
      (`'service_name=weather ...'`). Both invocations now pass
      `--resource 'service_name="weather-api"'`.

      The masking change earned its place here: the refusal text survived
      redaction intact, which is exactly what it was built for.

- [x] 3ak.6 `service_name` is filterable: the query was accepted and the
      credits CLI moved on to its next refusal (3al.4). The option's help
      documents it, and the seeded listing is the only credits listing in the
      stack, so a rejected filter fails loudly on the query rather than
      silently matching nothing. If it is rejected, dropping the filter
      entirely is the fallback -- discovery is already schema-routed to that
      registry.

## 3al. Five failures, four of them further on

- [x] 3al.1 **`market buy` reaches ready.** B4 passes: negotiated, escrowed,
      settled, provisioned, evidence published. The chain-client fixes at
      both ends of settlement were the last of it. B5 is now the frontier
      (3al.5).

- [x] 3al.2 **I broke `test_01` of the dynamic-listings scenario.** Declaring
      `pool_id` on the offer made the listing resource carry pool *and*
      resource, while `capacity_source_for` copies one or the other -- so the
      declared source disagreed with the resource it was derived from and
      `listings/create` refused with `400 capacity source identity and
      gpu_count must match the listing_resource resource`.

      The helper's either/or predated any resource declaring both. It now
      copies both when both are present, which is what a `specific_resource`
      member is: pool-bound and resource-keyed. The route compares the two
      fields independently, so an either/or copy could only ever agree with
      an either/or resource.

- [x] 3al.3 **Force-accept sends the amount as a JSON number.** The response
      model was retyped last round; the client's request body was not, and
      `{"amount": int(amount)}` put `9500000000000000000` through
      canonicalization. Now the decimal string, which the route already
      parses. Same omission shape as the retirement that reached three of
      four places.

- [x] 3al.4 **The credits buyer pins no registry authorities.** With
      `--service-name` gone the CLI got further and refused with
      `Missing required [registry.authorities] identity pins`: a registry
      read is authenticated in both directions and the buyer will not
      discover through an index it cannot attribute. The VM fixture passes
      pins; the credits fixture never did.

      Pinned both registries, because the schema filter routing to the
      credits index is the thing this scenario exercises -- so the compute
      registry has to be pinned too, even though nothing here discovers
      through it. The credits registry's own principal now lives in the
      docker profile beside its URL, matching what compose pins, and the
      fixture skips with the missing URLs named rather than failing opaquely
      if either pin is absent.

- [ ] 3al.5 **B5: the listing stays `open` where the scenario expects
      `closed` while capacity is held.** First run to get here, so this
      expectation has never been observed either way in this change. Not
      investigated: whether closing is driven by a loop this scenario pauses,
      whether a one-GPU listing against a larger host is genuinely still
      satisfiable, or whether the expectation is stale. Read the seller's
      reconciliation for this listing before touching either side.

- [ ] 3al.6 **05b: the buyer refuses the seller's acceptance -- a design
      question, not a defect I should guess at.** `market negotiate` exits 3
      on "seller accept state omitted the buyer-selected settlement option".
      The negotiation itself is healthy: round 0 counters at 8.5 tokens and
      the buyer's convergence rule accepts.

      Why only this command: round 0 synthesizes an `expected_selection` from
      the advertised option whenever one is in the policy params, and
      `market negotiate` puts it there for alkahest while `market buy`'s
      orchestration sets it only for hosted settlement. So `buy` skips the
      echo check and completes the same deal against the same seller, while
      `negotiate` requires an echo the alkahest accept path does not produce.

      The question is which side is right: whether a peer (alkahest)
      acceptance is supposed to echo a settlement selection at all, or
      whether synthesizing an expectation from an advertised escrow option is
      the overreach. The spec sentence about exact option matching on
      acceptance is written about hosted options. Both fixes are one-liners
      and they mean opposite things, so this wants a decision rather than a
      patch.

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
