# Implementation review — unbacked-bare-metal-listings

## Summary

This revision adds implementation round 2, Sections 11–13 (decisions 20–22):

- **Section 11:** the VM storefront chart and both the VM and API-credit storefronts start without waiting on their dependencies; the preflights' settings are retired and refused. It also carries task 11.9, one `kit/alkahest` derivation of release conditions, which settles 122 F2.
- **Section 12:** each chart's Helm test pod carries no workload selector label.
- **Section 13:** end-to-end scenarios hold shared services for the whole module, through one helper per pause kind. The provisioning service's pause routes now report whether the worker is at its gate.

It also closes round 1 with `1df44f4`, which fixes `132-implementation`'s F1 (the Helm served list and the validation tooling's marker variables).

**What I read.**

- The triage records `132-implementation.triage.md`, `131-validation.triage.md`, and `134-validation.triage.md`; the validation record `134-validation.md`, which is of `9aa024e` and passed; and the owner's note `138-implementation-owner.md` ("No notes").
- `9aa024e..8ac5657`: `1df44f4`, then `09cf669` (Section 11), `f88a8f9` (12), `ad1a1b6` (13), and `8ac5657` (a repair of 11–13).
- The current `tasks.md` Sections 11–13 with their notes, decisions 19–22 in `design.md`, and the `deployment-state` and `test-compatibility` deltas, checked against `openspec/specs/deployment-state/spec.md`.

**Base.** The local `dev` ref is stale, so I measured from the merge base with `origin/dev` (`968a4a9`).

**Checks.** `make check-comment-hygiene` passes. `make check-architecture` was refused in this session again, so it is unrun here.

**Validation.** No validation record exists for any round-2 commit.

## Assessment

Round 2 is careful and mostly sound.

- **Startup.** The init containers and in-process preflights are gone, with the retired settings refused in every way an operator could still state them: the configuration file and environment, `config set`, and the values schema, in two spellings each.
- **Section 11 tests.** VM's degraded start is proven on the started application through `StorefrontClient`, over the composition seams rather than module patches (closing 122 F4 and 85 F3's VM residue). The repair commit added real recovery evidence for the registry, the site, and the credits service.
- **11.9.** It unifies the release-condition derivation as 122 F2 asked.
- **Section 12.** The Helm label work is complete across all six charts, with a topology render test.
- **Section 13.**
  - The hold mechanism replaces every direct pause.
  - Holds resume in a `finally` that also covers a hold that never reached its gate.
  - A `--setup-plan` check over the real fixture graph proves each module's cleanup runs while its holds still stand. That is an unusually strong guard on a property that is easy to break silently.

What most needs attention is that each of the round's two promises still has one gap.

- **"Start without waiting" (D20).** It is kept everywhere but one place. Every storefront still constructs its Alkahest clients synchronously during startup, and over a websocket URL that construction connects without a bound. Round 1 bounded exactly that for the probe, but not for startup (F1).
- **"Hold until the loop is at its gate" (D22).** The provisioning workers' new `at_gate` can read true while a woken timer cycle is about to pass the gate. The cause is a single `if` before the wait, and synchronous routes that touch an `asyncio.Event` from a worker thread (F2).

Two recorded open items need a decision before promotion, and I state a position on each:

- D20's sentence on a failed cycle contradicts the code and the corrected delta (F3);
- the uv lock churn committed with Section 13 (F4).

The remaining findings are minor.

## Questions

### direction — If you were implementing this change, what would you have done differently?

**Alkahest clients at startup.** I would not construct them during startup at all. The probe now owns construction: bounded, one thread per chain, a late result adopted (round 1's 122 F1). A storefront could therefore start with an empty client map and let the probe's first step, which runs as its timer starts, build every client.

- **Cost:** an HTTP chain's client arrives one step later. Construction over HTTP makes no call, so that is milliseconds.
- **Gain:** startup touches no chain, which is exactly D20's rule (F1).

**Gate counter.** I would also have placed it so the check and the increment cannot be separated: make the routes `async def`, and use `while not set: await wait()` (F2).

**Recorded triage questions.** I agree with the recorded resolutions of the release order (cleanup not autouse, listed after the holds) and the live read-back of holds. On the two still open:

- **D20's wording:** change the design, not the code. A registry outage is reported by the registry check and by `registry_not_converged` per listing, and a completed cycle is the right state, since the cycle did what it could (F3).
- **The locks:** relock with the pinned uv before merge (F4).

### testing — Is the validation strategy sound?

**Section 11.**

- **VM `test_degraded_startup.py` — application integration.** It runs the real app and its full lifespan, read through `StorefrontClient`. The registry, site, and provisioning service are refused at a closed port, and the chain is reached only through `VmCompositionSeams`.
- **VM `test_publication_loop.py` and `test_negotiate_controller.py` — application integration.** Registry recovery and site recovery, in the same process.
- **API credits `test_lifecycle_status.py` — application integration over the routes, without the lifespan** (recorded). `_startup_tasks` runs directly. The seed waits, then completes once the ledger answers. Status is never checked for reporting the credits service as degraded (F5).
- **Unit:** the retired-setting refusals, in two spellings each, and the startup refusals.
- **Chart render:** no `wait-for-` container, a `startupProbe`, and no `initialDelaySeconds`.

**Section 12 — chart render.** `test_no_test_pod_carries_a_workload_selector` ties the test pods it reads to the charts' `templates/tests/`. It reads Deployment selectors only, not Service selectors, and it does not pin which charts must contribute a test pod (F6).

**Section 13.**

- **Unit tests of each worker's gate state** (`test_lease_lifecycle.py`, `test_fulfillment_convergence_gate.py`), event-driven with no sleeps. They cover the steady states, not the wake race (F2).
- **Application integration of the routes** through `ProvisioningClients` (`test_system_api.py`).
- **Unit tests of the e2e helpers:** `test_hold_helpers.py`, `test_scenario_holds.py`, and `test_scenario_cleanup_order.py`. The last runs `pytest --setup-plan`, which executes no fixture body and so needs no service.
- **The source check** catches typed-client calls, references, and literal route strings. It misses an import alias, a `getattr` by string, and a route built from a constant prefix, so the 13.5 note's "flags any reference" overstates it (F6).
- **`_until_held`'s half-second poll** is bounded, injectable, and recorded as declined. I accept that.

**Validation.** There is none for round 2. `134-validation.md` validated `9aa024e`, before any of Sections 11–13. Unrun:

- the three lanes on the new startup and the reordered cleanup;
- `make helm-topology-up` / `helm-topology-check` (the maintainer's, 11.8 and 13.7), which is the only evidence for the `test-compatibility` scenario "The Helm deal test passes".

The repair commit records that no uninterrupted `make test` has run on it.

### documentation — Does the code and documentation comply with AGENTS.md, ARCHITECTURE.md, and openspec/README.md?

**Mostly.**

- Comment hygiene passes. The added comments state current invariants: why no init container waits, why the cleanup fixtures are not autouse, and the module-hold rule.
- The `deployment-state` MODIFIED block is the permanent requirement word for word, less the one sentence that permitted a wait (checked against `openspec/specs/deployment-state/spec.md:306-354`).
- D19 now names `escrow_release_conditions`.
- The remaining unresolved citation, `e2e-tests/tests/e2e/roles/helpers/introduction_stages.py`, is in task 22.1's own plan and resolves when Section 22 lands. That is not a stale permanent reference.

**Stale or inaccurate text:**

- D20's failed-cycle sentence (F3).
- Two comments this round left behind: the API-credit server's list of startup refusals, and the bare-metal modules' references to autouse fixtures the lane does not have (F7).

**Commit message.** The repair commit `8ac5657` departs from the repository's conventions:

- a `fix(scenarios):` subject;
- no trailers;
- a reference to an outside item label ("M1/M2");
- workflow narration addressed to a named person (F7).

**Another change's design.** `openspec/changes/apicredits-end-to-end-lane/design.md:19-20` still describes `credits.fail_on_unreachable`, which this round removes. Archive cleanup's return of dependents to design is the mechanism that catches this, so I raise no finding. It is worth naming in that cleanup's notes.

### architecture — Is the code organized by ARCHITECTURE.md's layers?

Yes.

- **11.9** puts one domain-neutral rule in `kit/alkahest` (`escrow_release_conditions`), with VM, API credits, and bare metal composing it.
- **The new wire model** sits in the thin contracts package (`WorkerPauseResponse`), with the typed client returning it. The worker state comes from the family kit (`compute_provisioning`'s lease lifecycle) and the service (the convergence watchdog). The routes compose them.
- **The e2e hold helpers** sit in the roles' helpers. The lane conftests compose them into fixtures, and no scenario reaches past them.
- **Charts** own their test labels. The storefronts own their startup refusals.

No edge crosses a layer. The round adds no dependency beyond the provisioning version floors, which are consistent: contracts 0.10.0, client 0.8.0, `compute_provisioning` 0.20.0, and the service 0.18.0, each one bump over `origin/dev`.

### consistency — Does the implementation do what the design and delta specs say, and only that?

Mostly; F1, F2, and F3 are the exceptions. By earlier finding and record:

**`132-implementation`:**

- **F1 — resolved** in `1df44f4`. `PIPELINE_MARKER_VARIABLES` reads `E2E_APICREDITS_MODULE`. `HELM_SCENARIOS` gains `e2e_alkahest_trusted_oracle`, which passed on Helm in `134-validation.md`. The all-scenarios run keeps the served list (`scripts/validate_slice.py:63-71`, `:327-331`). The Section 3 note's reason is corrected.

**`122-implementation`:**

- **F2 — resolved by 11.9.** `escrow_release_conditions` (`kit/alkahest/src/market_alkahest/release_conditions.py:132-160`) is called by all three storefronts. `publication_release_conditions` and `demands_for_published_escrows` are gone.
- **F4 — resolved by 11.5's** started-application VM test over `VmCompositionSeams`.
- **F1, F3, F5, F6 — resolved in round 1, as previously reviewed.**

**`85-implementation`:** every finding was resolved or disposed by round 1's triages. 85 F3's VM residue is now closed by 11.5.

**Validation records:**

- **`131-validation` and `134-validation` observations — disposed in their triages.** The tooling observations (the raw Helm status, the vanished evidence directory, the aggregate-status wait) are recorded with no action in this change.
- **`134-validation` V-findings:** none.

**New in round 2:** F1, F2, and F3 are departures from D20, D22, and their deltas. The delta's VM degraded-start scenario now matches the code (`specs/deployment-state/spec.md:13-22`).

## Findings

### F1 — Every storefront still builds its Alkahest clients synchronously at startup, unbounded for a websocket chain

- **Lens:** consistency
- **Basis:** specification
- **Severity:** should
- **Evidence:**
  - `domains/vms/storefront/src/market_storefront/server.py:352`;
  - `domains/apicredits/storefront/src/apicredits_storefront/server.py:212`;
  - `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/runtime.py:905-906`;
  - `kit/storefront/src/market_storefront_kit/alkahest_clients.py:61-70` (a websocket client connects while it is built);
  - delta `specs/deployment-state/spec.md:5-9` ("a service MUST NOT wait for one … in its own startup");
  - `design.md:889-892`;
  - `kit/alkahest/src/market_alkahest/chain_probe.py:276-354` (the probe's bounded construction).

Before the app answers `/health`, each storefront calls `build_alkahest_clients`, which constructs every chain's client in the startup thread. Over an HTTP `rpc_url` that makes no call. Over `ws://` or `wss://` it connects, and an endpoint that accepts TCP but never completes the upgrade holds startup indefinitely. That outlives the new `startupProbe`'s 60-second budget and restarts the pod in a loop.

Bare metal's release values use a websocket URL (`helm/bare-metal-release-values.yaml:132`). Round 1 bounded exactly this hang for the probe (122 F1) but left the startup path, so the round's central rule — a service does not wait on a dependency in its own startup — holds for every dependency but this one.

**Suggested action:** Start each storefront with an empty client map and let the probe's first step construct the clients through its bounded, one-per-chain construction. Alternatively, run the startup build through the same bounded construction. Add a degraded-start case with a constructor that never returns.

### F2 — A provisioning worker can answer `at_gate: true` while a woken timer cycle is about to run

- **Lens:** consistency
- **Basis:** specification
- **Severity:** should
- **Evidence:**
  - `provisioning/compute/src/compute_provisioning/lease_lifecycle.py:282-289` and `provisioning/compute/service/src/compute_provisioning_service/services/fulfillment_convergence.py:161-166` and `:175-180` (`if not is_set(): await wait()`, then the counter's increment);
  - `provisioning/compute/service/src/compute_provisioning_service/controllers/system_controller.py:159`, `:172`, `:182`, `:195` (synchronous routes, which FastAPI runs on a threadpool thread);
  - `provisioning/compute/contracts/src/compute_provisioning_contracts/system.py:83-94`;
  - delta `specs/test-compatibility/spec.md:8-10` ("MUST wait until each held loop reports itself paused at its gate").

`asyncio.Event.wait()` returns once its waiter has been woken, even if `clear()` ran after the `set()` that woke it. So a resume (the previous module's `finally`) followed by a pause (the next module's hold) can be answered `paused=True, at_gate=True` before the woken timer task has incremented its counter. That task then passes the single `if` and runs a cycle inside the hold.

The routes being synchronous widens this window. `set()` and `clear()` run off the event loop's thread, so the waiter's wake is applied whenever the loop next runs, concurrently with the pause thread reading the counter. The hold is the round's mechanism for "no timer cycle races a stage", and the unit tests cover only steady states.

**Suggested action:**

- Make the four pause and resume routes `async def`, so the event and the counter are touched on the loop's thread.
- Change both gates to `while not self._resume_event.is_set(): await self._resume_event.wait()`.
- Add a unit case of resume, then pause, before the woken cycle runs, asserting the cycle does not run and `at_gate` holds.

### F3 — D20 still says an unreachable registry shows as a failed cycle, which the code and the corrected delta contradict

- **Lens:** documentation
- **Basis:** evidence
- **Severity:** should
- **Evidence:**
  - `openspec/changes/unbacked-bare-metal-listings/design.md:871-874`;
  - `domains/vms/storefront/tests/integration/test_publication_loop.py:855-905` (the cycle completes with `fail` / `registry_not_converged`, and status is `degraded`);
  - `specs/deployment-state/spec.md:17-22`;
  - `tasks.md:2433-2436` ("Open for triage … Neither side is changed").

The recorded handling leaves both sides as they are. But closeout promotes D20 to `DEPLOYMENT_AND_CONFIG.md` and `ARCHITECTURE.md` (23.9), which would carry a statement the code does not meet. The code's behaviour is the better one: the cycle did all it could, and the outage is reported by the registry check and by each listing's `registry_not_converged`. The delta already says so.

**Suggested action:** Rewrite `design.md:873-874` to what the delta and the test show — the registry check reports the registry unreachable, the storefront reports itself degraded, each unpublished listing records `registry_not_converged`, and the next cycle publishes once the registry answers — and close the triage item.

### F4 — Section 13 committed eleven locks rewritten by a different uv, against the round's own handoff

- **Lens:** direction
- **Basis:** judgement
- **Severity:** should
- **Evidence:**
  - `ad1a1b6`'s locks, for example `domains/vms/storefront/uv.lock` (about 1,490 changed lines, of which only the provisioning contracts and client version lines are real changes) and `domains/bare_metal/storefront/uv.lock`;
  - `tasks.md:2347-2355` ("a later session should not commit this churn with a section");
  - `tasks.md:2411-2415`;
  - `tasks.md:2650-2656`.

The genuine change in these locks is four internal version bumps. The rest is a uv version's churn: platform markers repeated on every dependency, and wheels for platforms outside each project's declared `environments`. The repair notes that every committed lock still passes `make check-locks` under the pinned uv, so CI is unaffected. But the next `make lock` on the pinned uv will probably rewrite them back, and the change would merge about two thousand lines of noise into `dev`.

The decision is recorded as "the owner's".

**Suggested action:** Relock the eleven projects with the pinned uv (0.11.17) before merge, so history carries only the version bumps, and note in Section 13 that it was done.

### F5 — Nothing shows the API-credit storefront reporting an unreachable credits service as degraded

- **Lens:** testing
- **Basis:** specification
- **Severity:** minor
- **Evidence:**
  - `domains/apicredits/storefront/tests/integration/test_lifecycle_status.py:369-408` (asserts only that the URL does not appear in status);
  - `domains/apicredits/storefront/src/apicredits_storefront/services/system_service.py:34-53`;
  - delta `specs/deployment-state/spec.md:8-9` ("report the dependency as degraded in its status").

The code reports `checks["credits_service"] == "unreachable"` and `status: degraded`. VM's equivalent test asserts that; the API-credit one does not.

**Suggested action:** Assert `status.checks["credits_service"] == "unreachable"` and `status.status == "degraded"` in `test_startup_does_not_wait_for_an_unreachable_credits_service`.

### F6 — Two Section 12–13 checks are narrower than their notes claim

- **Lens:** testing
- **Basis:** evidence
- **Severity:** minor
- **Evidence:**
  - `e2e-tests/tests/unit/test_scenario_holds.py:73-78` and `:119`, against `tasks.md:2626-2634` ("flags any reference to a pause operation or hold helper");
  - `helm/tests/test_release_topology.py:424-472`.

**The source check** matches only names and attributes, and route strings that appear whole. It misses three forms:

- `from …compute_deal import storefront_loops_held as hold`;
- `getattr(client, "admin_pause_lifecycle_loops")()`;
- a route built from a constant prefix, as the provisioning client builds its own.

None is in the tree today.

**The topology test** reads Deployment selectors only. A Service, PodDisruptionBudget, or NetworkPolicy selecting by instance alone would match a test pod unseen; every one today also requires `name`. The test also does not pin which charts must contribute a test pod.

**Suggested action:**

- Narrow the 13.5 note, or extend the check to imported aliases and to string constants naming a pause operation.
- Have the topology test also read Service selectors and assert each release's expected set of test pods.

### F7 — Stale comments, and a nonconforming commit message, from this round

- **Lens:** documentation
- **Basis:** guidance
- **Severity:** minor
- **Evidence:**
  - `domains/apicredits/storefront/src/apicredits_storefront/server.py:191-194` (lists the startup refusals without the removed settings or the unset `[credits].service_url`, both refused since 11.4);
  - `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_mock_deal.py:86-87`, `test_bare_metal_publication.py:42-43`, and `test_bare_metal_introduction.py:40-41` ("but the lane's autouse ones"; the bare-metal lane has none);
  - `git log -1 8ac5657`;
  - `AGENTS.md`, "Public repository discipline".

**Comments.** Both are text the round touched, and closeout part 1 only confirms comments. A reader of the server's comment would miss two refusals.

**Commit message.** `8ac5657` has:

- a `fix(scenarios):` subject, where every other commit of the change names it and its section;
- no trailers;
- an outside item label ("M1/M2") no reader of this repository can resolve;
- workflow narration addressed to a named person, rather than a description of the change.

It is already pushed, so it is permanent unless the branch is rewritten.

**Suggested action:**

- Update the two comments.
- For the commit, describe the change in the merge commit's message, and keep outside labels and review routing out of future commit messages.

## Readiness

Round 2 should not advance to round 3 until:

- F1 and F2 are fixed — each is a gap in the one promise its section exists to keep;
- F3 is decided;
- F4 is decided, preferably by relocking.

F5–F7 can be taken in the same fix commit.

No round-2 commit has been validated. Before advancing, the round's head needs:

- a validation run covering all three pipeline lanes on the changed startup and the reordered holds and cleanup;
- the local suites, as one uninterrupted `make test`, which the repair notes has not yet run;
- the maintainer's Helm topology run (11.8 and 13.7), which is the only evidence for "The Helm deal test passes" and for no init container on the VM storefront in a live release.

<!-- reviewer-session: claude:c66b9641-ebc7-4b54-8f87-d5f36fe524fd -->
<!-- reviewer: claude claude-opus-5-5 high -->
<!-- reviewer-unavailable: codex gpt-6-sol: codex is not installed -->
<!-- reviewed-commit: 8ac56577379a50686e6cd6e45fb7c2f2ddeca215 -->
