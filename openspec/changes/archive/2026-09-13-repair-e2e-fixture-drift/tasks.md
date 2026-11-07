# Tasks — repair E2E fixture drift

## 1. Survey

- [ ] 1.1 Reproduce both fixture errors against the running stack and record
      the exact construction sites, rather than working from the job log:
      `e2e-tests/tests/e2e/roles/scenarios/vms/conftest.py`'s
      `provisioning_client`, and `e2e-tests/tests/e2e/roles/buyer_cli.py`'s
      `ProfileStore(...)` near line 378.
- [x] 1.2 Sweep every e2e fixture that constructs a library client or model for
      the same class of drift, instead of fixing only the two that surfaced.
      **Four further sites found, all masked behind the two that surfaced.**
      The two reported causes are not the whole drift:

      | Site | Current call | Installed signature |
      |---|---|---|
      | `vms/conftest.py` `storefront_client` | `private_key=` | `TypeError: unexpected keyword argument 'private_key'` |
      | `vms/conftest.py` `storefront_admin_client` | `private_key=`, `admin_key=` | same |
      | `vms/conftest.py` `registry_client` | `SyncRegistryClient(base_url=...)` | `TypeError: missing 4 required keyword-only arguments: 'signer', 'caller_role', 'expected_registries', 'registry_authority'` |
      | `vms/conftest.py` `provisioning_test_client` | `X-Admin-Key` only | constructs, then rejected: `/test/*` operations are in `ADMIN_PROVISIONING_OPERATIONS` and go through `ProvisioningAuthMiddleware` |

      `test_multi_registry.py` (`alice_admin_client`, and the two inline
      `SyncStorefrontClient` constructions in stages 06a/06b) and
      `tests/smoke/test_provisioning_smoke.py` / `test_storefront_smoke.py`
      carry the same shapes. The smoke modules are deselected in the e2e run,
      so they are invisible there and will fail identically once selected.

      `tests/e2e/roles/scenarios/vms/hosted/network.py` is already correct and
      is the in-repo reference for all of these: it builds a signer, a
      `TrustedIdentitySet`, and an explicit `caller_role` per client.
- [x] 1.3 For each construction site, compare against the installed wheel's
      signature — not the source tree. The suite runs against
      `.dist`-resolved wheels, and that is the shape that will actually bind.
      Signatures confirmed by introspection and by executing each construction
      site's exact call, rather than by reading the definitions.

## 2. Settle the caller question

- [x] 2.1 **Decide whether the suite drives provisioning as the admin principal
      or the storefront principal.** Settled as the **admin** principal, and
      the code decides it rather than a preference: `SyncProvisioningClient`
      fixes `caller_role` to `admin` in its base `__init__` with no parameter
      to override, and `ProvisioningAuthMiddleware` resolves
      `active_principals(asserted_role)` and verifies the request principal
      against that set. A storefront credential would construct and then be
      refused with 403. Recorded in the fixture docstring.
- [x] 2.2 Determine whether `SELLER.ADMIN_API_KEY` retains any consumer once
      the provisioning fixture stops using it. **It retains none.** The
      storefront's `/admin/*` routes moved to signed marketplace v2 identity
      with administrator trust pins resolved from
      `Identity.administrators.*` (`storefront.bob.toml`,
      `storefront.alice.toml`); `SyncStorefrontClient` no longer accepts an
      `admin_key` argument at all. The only remaining readers are the three
      fixtures listed in 1.2, each of which is itself drifted. Removal is
      therefore correct but is gated on repairing those fixtures, so it is
      deferred to 3.3 rather than done piecemeal here. Note this is a
      *different* setting from the registry bearer tokens
      (`VMS_REGISTRY_ADMIN_API_KEY`), which `SyncRegistryClient` still accepts
      as `api_key` and which stay.

## 3. Repair

- [x] 3.1 Rebuild `provisioning_client` on the current signature — a signer for
      the admin principal settled in 2.1, plus an `expected_authorities` set
      pinning the provisioning service's own principal
      (`PROVISIONING_IDENTITY__IDENTIFIER`). Docstring corrected; it no longer
      asserts "there is no per-agent identity" and now records which principal
      the suite drives and why the choice is forced.

      The credential had no home in the suite's settings: the config exposed
      `SELLER.PRIVATE_KEY` and `SELLER.ADMIN_API_KEY`, and no credential for
      the admin principal existed anywhere in the repository — the
      `dev-env/identities/` provenance table has no row for it. Added
      `provisioning.admin_scheme` / `admin_credential` and
      `provisioning.authority_scheme` / `authority_identifier` across
      `settings.toml`, `config/config.yml`, and `config/config-docker.yml`.
      No compose plumbing was needed: the service side already pins all three
      principals, and only the suite lacked the private half.
- [x] 3.2 Build the buyer-CLI `ProfileStore` through the model's own
      initial-state classmethod rather than passing `revision=0` literally, so
      the initial revision stays owned by the model.

      **The classmethod alone is not sufficient, and the original instruction
      would have produced a second broken fixture.** `ProfileRepository.replace`
      rejects a candidate whose revision does not advance past
      `expected_revision`, and `ProfileStore.empty()` returns revision 0
      against `expected_revision=0`. Constructing from `empty()` and populating
      it — like hard-coding `revision=0` — fails with
      `ProfileRevisionConflict: candidate revision must advance beyond current`.
      Verified by running all four candidates against the installed package.
      The working repair is `add_profile(ProfileStore.empty(), profile,
      select=True)`, which routes through `_next_store` and so keeps both the
      initial revision and its increment owned by the model.
- [ ] 3.3 Apply the same repair to the further sites 1.2 found. **Not done in
      this round, deliberately.** Unlike 3.1 and 3.2, these are not mechanical:
      `SyncStorefrontClient` binds exactly one `caller_role` per instance and
      refuses any operation belonging to another role, and the storefront now
      distinguishes four roles (`admin`, `buyer`, `seller`, `service`). The
      existing `storefront_admin_client` is used for both seller-owned routes
      and `/admin/*`, which are now different roles, so it has to become two
      clients and each caller has to be reassigned. That is a decision about
      what the suite asserts, not a signature translation, and it needs the
      same explicit settling 2.1 got. Carrying it as the next round of this
      change rather than guessing:
      - [ ] 3.3a Settle the role split for `storefront_admin_client` and
            reassign its callers. The mapping is now established by reading
            each method's asserted role, and `storefront_admin_client` spans
            three of them, so one client cannot serve it:

            | Required role | Methods called on the fixture |
            |---|---|
            | `admin` | `admin_import_resources`, `admin_reserve_capacity`, `admin_release_reservations`, `admin_release_one_reservation`, `admin_interrupt_deal`, `admin_resume`, `resume_listing`, `force_accept_negotiation`, `evaluate_settle`, `get_listing`, `get_negotiation`, `get_events` |
            | `seller` | `create_listing` |
            | `service` | `get_system_status` |

            `get_health`, `negotiate_new`, and `evaluate_negotiate` are
            unauthenticated and need no role. `storefront_client` is
            straightforward: `settle` and `get_settle_status` are `buyer`.

            The `service` row is the open decision and is recorded as a
            question in `design.md`: the storefront's only pinned service peer
            is the provisioning service, so a `service`-role client would have
            to sign as the provisioning identity, and `get_system_status` is
            asserted in roughly ten tests, so it cannot simply be dropped.
      - [ ] 3.3b Rebuild `storefront_client`, `storefront_admin_client`,
            `registry_client`, and `test_multi_registry.py`'s clients on the
            current signatures, following `hosted/network.py`.
      - [ ] 3.3c Re-sign `ProvisioningTestClient` for `/test/*`, which is
            behind the same authenticated route contract as the rest of the API.
      - [ ] 3.3d Apply the same to the smoke modules, and correct their
            module docstrings, which still assert the retired shared-key model.
      - [ ] 3.3e Remove `SELLER.ADMIN_API_KEY` and its plumbing once the
            fixtures above stop reading it (2.2).

## 4. Validation

- [ ] 4.1 Run the full e2e suite against the stack. Record the result as
      passed / failed / errored counts, and confirm **zero errors** — an error
      means a fixture is still wrong, which is this change's scope; a failure
      means the suite ran, which is not.

      **Zero errors is not the expected outcome of this round**, and that is
      not a regression. The 1.2 sites were masked: with `provisioning_client`
      repaired, `storefront_client`, `storefront_admin_client`, and
      `registry_client` now raise during setup where previously the
      provisioning fixture raised first. The check to apply this round is that
      the error *causes* have changed — the two reported constructors are gone
      and no error names `admin_key`, `private_key`, or a missing `revision`.
      Counting errors would hide that, which is the failure mode this branch
      has already recorded once.
- [x] 4.1a **Round 1 result: 1 failed, 12 passed, 1 skipped, 263 deselected,
      87 errors** (from 0 failed / 88 errors). Compared by cause, not count:

      | Cause | Before | After |
      |---|---|---|
      | `SyncProvisioningClient(admin_key=...)` | 87 | **0** |
      | `ProfileStore` missing `revision` | 1 | **0** |
      | `SyncStorefrontClient(private_key=...)` | 0 (masked) | 87 |

      Both repaired causes are gone and neither was replaced by a variant.
      The 87 remaining errors are the single masked cause predicted by 1.2.

      `provisioning_client` is confirmed working against the live service, not
      merely constructing: the host-registration fixture drove
      `GET /api/v1/hosts/kvm1` → 404 then `POST /api/v1/hosts/` → **201
      Created**. A 201 means the admin-signed request was authenticated and
      authorised and the signed response passed authority verification, which
      settles 2.1 empirically as well as by reading the code.

      The buyer-CLI repair is confirmed the same way: `test_credits_full_deal`
      now proceeds through fixture setup and invokes the real `market` binary,
      which is why it moved from an error to a failure.

- [ ] 4.2 Classify every remaining failure: a real finding with an issue
      raised, or a genuine pass. Do not fix the findings here.
      - [x] 4.2a `test_credits_full_deal` — **not yet classifiable, and the
            suite's own reporter is why.**
            `assert_market_run_succeeded` is reached only when the CLI exits
            non-zero, so `market credits buy` did fail; but it then calls
            `read_events()`, which resolves `run_id`, which waits ten seconds
            for a run-log that will never appear and raises. The raise replaces
            the prepared message — including the return code — with
            `market did not produce a run-log ... within 10s`. A failure
            reporter that fails while reporting yields the same blindness as a
            check that passes while the thing it checks is broken.
            Repaired by giving `MarketRun` a no-wait, no-raise
            `events_or_empty()` for the failure path and having the reporter
            use it, so the return code survives. Re-run to classify; the
            underlying CLI failure is a finding to raise, not to fix here.
- [ ] 4.3 Confirm the 12 currently-passing tests still pass. A fixture repair
      that changes their behaviour has changed what they exercise.
- [ ] 4.4 Run `make test` to confirm the fixture changes did not disturb the
      unit and integration suites.

## 4a. Work completed beyond the original plan

Recorded as final state; the reasoning behind each is in `design.md`.

- [x] 4a.1 **Diagnosability.** `assert_market_run_succeeded` could not report
      its own failures: it read run events on the failure path, which resolved
      a run id, which waited ten seconds for a log that would never appear and
      raised — discarding the return code it was about to print. `MarketRun`
      gained a no-wait `events_or_empty()` for that path.
- [x] 4a.2 **Wait removal.** `_discover_run_id` sampled the run directory every
      100ms for ten seconds, but every `BuyerCli.run(...)` call site is
      blocking, so the process had already exited and the wait raced a file
      that could not appear. Replaced with `_resolve_run_id`, a single
      observation. `wait_for_event` now checks the terminal condition first, so
      a process that died early reports its exit code instead of a timeout.
      The one remaining bounded sample applies only while the CLI is still
      running.
- [ ] 4a.3 **Deferred: a seam for the streaming case.** `RunLog.start`
      generates its run id internally and nothing lets a caller supply or
      observe it, so a test tailing a *live* run still has no transition to
      synchronize on for the log's first appearance. `TESTING.md` says to add
      the seam rather than sleep, but the candidates change `core/buyer`,
      outside this change's boundary. Carried to whatever change owns it.

- [x] 4b **Administrator role correction** (production). `admin_system_status`
      is an administrator operation readable by a configured service peer;
      both middlewares already dispatched on the asserted role for that path.
      Corrected the client to assert whichever role it holds, added the
      administrator contract, and kept the service-peer branch. Storefront
      administrators are now principals distinct from their sellers
      (`storefront.bob.toml`, `storefront.alice.toml`).

- [x] 4c **Fixtures rebuilt per role.** One client per role across the vms
      scenarios, the multi-registry scenario, and the smoke modules;
      `ProvisioningTestClient` signs through the shared provisioning route
      contract and verifies responses; `SELLER.admin_api_key` removed. Alice's
      storefront is configured rather than silently skipped.

- [x] 4d **Payload shapes.** `create_listing` no longer accepts
      `agent_wallet_address`, requires `capacity_source`, and requires the
      resource to declare `offering_mode`. `capacity_source_for` derives
      provenance from the listing resource rather than restating it, because
      the storefront compares the two field by field.

## 4e. Result

**0 errors, 38 passed, 11 failed, 52 skipped, 263 deselected** (from 88 errors,
12 passed). `make test` green; `make check-comment-hygiene` clean.

Validation evidence: storefront unit + integration 1106 passed with 4
pre-existing failures reproduced on pristine code; provisioning compute service
867 passed; `kit/identity` 163 passed; `core/storefront-client` 30 passed;
`test_admin_api.py` 45 passed, and against pristine production code exactly the
seven relocated status tests fail, confirming they exercise the correction
rather than pass alongside it. E2e collection clean at 127 tests. Not run here:
nothing — every suite named in section 4 of this plan was executed.

- [x] 4.1 Zero errors reached: every fixture constructs and authenticates.
- [x] 4.2 **Every remaining failure classified.** Two findings, neither a
      fixture, both latent since mid-August and deliberately not repaired here:

      | Finding | Tests | Diagnosis |
      |---|---|---|
      | `alkahest.address_config_invalid` | 10 | `storefront.bob.toml` sets `address_config_path = "/app/src/market_storefront/data/alkahest_anvil_addresses.json"`. The file is committed and parses; the path is a source-layout leftover. The image installs `market_storefront` as a wheel into `/app/.venv`, so no `/app/src` tree exists at runtime. Resolving through `importlib.resources` would stop layout and config from having to agree. Accounts for 3 preflight assertions and, via suppressed settlement composition, 7 listing-create `400`s |
      | `market credits buy` exits `rc=2` | 1 | No run-log written, so the CLI failed before its first event; `rc=2` indicates an argument error, so the command's interface has moved away from what the scenario passes |

## 5. Closeout

- [x] 5.1 **Comment hygiene.** `make check-comment-hygiene` clean. Direct read
      also removed retired-model diagnostics that named `X-Admin-Key` and
      `admin_api_key` in failure messages and docstrings — mechanically legal,
      but they would have sent a reader after a key that no longer exists.
- [x] 5.2 **Import placement.** Identity imports this change added to module
      functions and smoke fixtures were hoisted to module level: the smoke
      modules already import their clients at module level, and the vms
      conftest already imports `src.provisioning_test_client`, which now
      depends on `market_identity` at module level, so nothing was deferred by
      keeping them local. Verified by collection (127 tests), not syntax alone.
      Client imports in fixture bodies were left in place deliberately.
- [x] 5.3 **Documentation compliance.** No-permanent-change disposition holds,
      re-checked rather than assumed. `storefront-publication/spec.md` already
      requires roles be authorized "selected by route" without enumerating
      per-route roles, and already requires administrator subjects be complete
      principals distinct from the subjects they act for — so both the role
      correction and the seller/administrator separation are conformance to the
      documented contract, not new contract. `site-capacity/spec.md`'s
      cross-reference to `test_admin_api.py` as evidence for the
      `/api/v1/system/status` contract remains valid; that file still covers it.
- [x] 5.4 **Narrative compression.** Round-by-round debugging narrative moved
      to `design.md` and the task record reduced to final behavior, validation
      evidence, and deferred work.
- [x] 5.5 **Roadmap currency.** Nothing owed: `ROADMAP.md` has no goal for the
      local end-to-end stack, so there is no current-state description this
      change makes stale. Recorded as a deliberate disposition.
- [x] 5.6 **Campaign index currency.** Row updated to archived with its true
      outcome and the archive link; dependency graph updated. The four
      inherited questions and the two findings are recorded there as unowned,
      with no link to a successor directory that does not yet exist.
- [x] 5.7 **Promotion.** Record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| *(none)* — see the disposition table below | — |

Every material decision classified, per the completion checklist:

| Decision | Disposition |
|---|---|
| `admin_system_status` is an administrator operation also readable by a configured service peer | **Permanent, already documented.** `storefront-publication/spec.md` authorizes roles selected by route without enumerating them; this is conformance, and the dual-role dispatch it relies on predates the change |
| A storefront administrator is a principal distinct from its seller | **Permanent, already documented.** The same spec requires administrator subjects be complete principals distinct from the subjects they act for; development configuration now matches |
| One e2e client per role, named for the role | **Temporary.** A property of this suite, not of any boundary; belongs in the fixtures and their docstrings |
| The e2e suite drives provisioning as the admin principal | **Temporary.** Forced by the client, which fixes its own caller role; recorded in the fixture docstring |
| Repair-then-classify rather than repair-and-chase | **Temporary.** A scoping decision for this change |
| `capacity_source` derived from the listing resource rather than restated | **Temporary.** A fixture-construction choice; the storefront's field-by-field comparison is the durable fact and is already in its own spec |
| Waiting on a process that has exited is never correct | **Superseded by existing documentation.** `TESTING.md` already forbids clock-based synchronization; this change brought two call sites into line rather than establishing anything new |

## Inherited open questions

Carried from [`provide-e2e-development-identities`](../archive/2026-09-12-provide-e2e-development-identities/),
which deferred them deliberately. None blocked startup.

- [ ] 6.1 `storefront.credits.toml` pins `ed25519 My6-jSfLcyOzpAHBwTtd1kvMwOEOzaHCtdEaA3eaheU`
      as the `default` capacity site's expected authority, but that site is the
      provisioning service, which signs eip191. No private half exists in the
      repository. Either the pin is stale or that site is meant to run an
      uncommitted ed25519 identity — a topology decision for the domain owner.
- [ ] 6.2 The same table declares `expected_authorities` but no authority
      **URL**, so `capacity.sites.default` is a table where the loader expects
      a string. Whether the API-credits storefront should have a capacity site
      at all is the prior question.
- [ ] 6.3 `compose.apicredits.yml` has the `include`-plus-override shape that
      broke the root stack and will fail identically when used.
- [ ] 6.4 `kit/config`'s shared loader TOML-parses environment values, so any
      `0x`-prefixed value bound for an identity field arrives as an integer.
      Worked around per-value with Dynaconf's `@str`; a durable fix changes a
      loader every service shares.

## Implementation status

**Complete.** The fixtures are correct, the suite reports results rather than
setup errors, and both remaining failures are classified findings with issues
to raise. The drift was wider than the proposal assumed — six construction
sites and three payload shapes, four of them masked behind the first fixture to
raise — and the repair reached production once, to correct a misfiled route
role; that correction is recorded in 4b and in `design.md`.

Two items leave with the change rather than in it: the streaming run-id seam
(4a.3) and the four inherited questions below.
