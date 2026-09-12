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
            reassign its callers.
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
- [ ] 4.2 Classify every remaining failure: a real finding with an issue
      raised, or a genuine pass. Do not fix the findings here.
- [ ] 4.3 Confirm the 12 currently-passing tests still pass. A fixture repair
      that changes their behaviour has changed what they exercise.
- [ ] 4.4 Run `make test` to confirm the fixture changes did not disturb the
      unit and integration suites.

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
verified against the installed packages; task 2.1 is settled from the code and
no longer blocks 3.1.

The survey found that the drift is wider than the proposal assumed: four
further sites carry the same class of error and were invisible because the
`provisioning_client` fixture raised first. Two of them need a decision about
which role the suite asserts, not a signature translation, so they are carried
as 3.3a–3.3e rather than guessed at. The proposal's "Impact" line — that a
repair turns 88 errors into 88 results — holds only once 3.3 lands; this round
moves the error causes rather than eliminating them.
