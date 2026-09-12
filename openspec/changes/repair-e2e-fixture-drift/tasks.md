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

## 4a. Diagnosability and wait removal

Added this round: repairing the fixtures exposed that the buyer-CLI helper
could not report its own failures, and that it synchronized by sampling the
clock rather than on an observable transition.

- [x] 4a.1 **Remove the run-id discovery wait.** `_discover_run_id` sampled the
      run directory every 100ms for ten seconds and then raised. Every
      `BuyerCli.run(...)` call site uses `subprocess.run`, so the process has
      already exited before the lookup — the wait was racing a file that could
      never appear, and the raise discarded the return code the reporter was
      about to print. Replaced with `_resolve_run_id`, a single filesystem
      observation: the run directory is fixture-owned and per-run, so this
      invocation's log is the one id not already present.
- [x] 4a.2 **Never sample against an exited process.** `wait_for_event` polled
      until a deadline and only checked process state as a side path, so a CLI
      that died early still cost the full timeout and reported
      "did not see event" instead of the exit code. It now checks the
      terminal condition first: once `exited` is true the run-log is final, and
      the assertion names the return code and stream tails. The remaining
      bounded 200ms sample applies only while the process is genuinely still
      running, which is the streaming case below.
- [ ] 4a.3 **Seam for the streaming case.** `RunLog.start` generates its run-id
      internally via `_new_run_id()` and nothing lets a caller supply or
      observe it before work begins, so a test that tails a *live* run still
      has no transition to synchronize on for the log's first appearance. The
      methodology's own instruction applies — where no seam exists, adding it
      is the correct fix rather than a sleep — but the candidates
      (a `--run-id` input, or emitting the run-id deterministically before the
      first event) change `core/buyer`, which is outside this change's
      "`e2e-tests/` fixtures only" impact statement. Raise it rather than
      widening this change unilaterally.

## 4b. Administrator role correction

- [x] 4b.1 `admin_system_status` asserted `service` while binding an operation
      named for the administrator, and its sibling read on the same prefix
      (`GET /api/v1/system/events`) was already an administrator contract. The
      route was misfiled in `service_peer_auth`, whose other entries are all
      provisioning POST callbacks carrying a capacity reservation. Corrected in
      the client (both async and sync) and moved to `admin_identity`.
      Verified directly against the resolvers: `GET /api/v1/system/status` now
      returns `("admin_system_status", "system/status")` from the admin
      contract and `None` from the service-peer callback, while all five
      fulfillment callbacks still resolve to the service peer with their
      site and reservation intact.
- [x] 4b.2 Seller split from administrator. `storefront.bob.toml` principal
      `0x3c44cddd…` / operator `0x976ea740…`; `storefront.alice.toml`
      principal `0x15d34aaf…` / operator `0x14dc7996…`. Administrators are
      pinned only in these two files, so no compose change was needed.
- [x] 4b.3 Storefront integration tests updated: `test_admin_api.py` gains an
      `admin_client` fixture and the seven `get_system_status` assertions move
      to it. `service_client` stays for the provisioning callbacks, which are
      genuinely service-to-service.

      Test evidence in this environment: storefront-client suite 30 passed
      (includes `test_admin_auth`, `test_auth_headers`); storefront unit
      `test_admin_auth` + `test_identity_dispatch` +
      `test_service_peer_identity` 32 passed; e2e collection clean
      (`test_multi_registry` 20 collected, smoke 16 collected); all eight
      rebuilt clients construct against the committed dev credentials; and a
      seller-role client is refused `get_system_status` with
      `this operation requires caller_role='admin', not 'seller'`.

      Two limits worth recording. `test_admin_api.py` itself cannot be
      executed here: it imports `market_storefront.server`, which needs the
      separately released `hosted_settlement_client` wheel, so the change to
      it is verified by the resolver tests above rather than by running it.
      And `tests/unit/test_config_loader.py` has two failures
      (`test_structured_settlement_publication_defaults_are_validated`,
      `test_structured_publication_defaults_reject_partial_or_secret_input`)
      which reproduce identically on pristine code and are unrelated to this
      change.

## 5. Closeout

- [ ] 5.1 **Comment hygiene.** `make check-comment-hygiene`.
- [ ] 5.2 **Import placement.** Note that e2e fixtures import inside the
      fixture body deliberately, and preserve that placement.
- [ ] 5.3 **Documentation compliance.** Confirm the no-permanent-change
      disposition still holds; `TESTING.md` already defines this architecture.
- [ ] 5.4 **Narrative compression.** Reduce task notes to final state.
- [ ] 5.5 **Roadmap currency.** Expected to own nothing; record the
      disposition either way.
- [ ] 5.6 **Campaign index currency.** Update this change's row, and reconcile
      the inherited open questions — they move on to whatever raises them.
- [ ] 5.7 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| *(none expected — this change restores callers to contracts already documented in `docs/development/TESTING.md`)* | — |

Classified as **temporary** and deliberately not promoted:

| Decision | Disposition |
|---|---|
| Which principal the e2e suite drives provisioning as | Belongs in the fixture's own docstring, not a specification: it is a property of this suite, not of the provisioning boundary |
| Repair-then-classify rather than repair-and-chase | A scoping decision for this change |

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

**Partially implemented.** Both reported fixture errors are repaired and
confirmed against the running stack: the provisioning fixture performs
authenticated admin writes (`201 Created`), and the buyer-CLI fixture reaches
the real `market` binary. Task 2.1 is settled from the code and by observed
authorisation, and no longer blocks 3.1.

Round 2 repairs the failure reporter that was hiding the one new result. The
87 remaining errors are all the single masked `SyncStorefrontClient` cause and
are gated on the role decision in 3.3a.

The survey found that the drift is wider than the proposal assumed: four
further sites carry the same class of error and were invisible because the
`provisioning_client` fixture raised first. Two of them need a decision about
which role the suite asserts, not a signature translation, so they are carried
as 3.3a–3.3e rather than guessed at. The proposal's "Impact" line — that a
repair turns 88 errors into 88 results — holds only once 3.3 lands; this round
moves the error causes rather than eliminating them.
