# Tasks — repair E2E fixture drift

## 1. Survey

- [ ] 1.1 Reproduce both fixture errors against the running stack and record
      the exact construction sites, rather than working from the job log:
      `e2e-tests/tests/e2e/roles/scenarios/vms/conftest.py`'s
      `provisioning_client`, and `e2e-tests/tests/e2e/roles/buyer_cli.py`'s
      `ProfileStore(...)` near line 378.
- [ ] 1.2 Sweep every e2e fixture that constructs a library client or model for
      the same class of drift, instead of fixing only the two that surfaced.
      88 errors came from 2 causes, so a third would be invisible behind them
      until the first two are fixed. Check at minimum `SyncStorefrontClient`,
      `SyncRegistryClient`, `SyncProvisioningClient`, `SiteCapacityClient`, and
      every `market_identity` model the suite builds directly.
- [ ] 1.3 For each construction site, compare against the installed wheel's
      signature — not the source tree. The suite runs against
      `.dist`-resolved wheels, and that is the shape that will actually bind.

## 2. Settle the caller question

- [ ] 2.1 **Decide whether the suite drives provisioning as the admin principal
      or the storefront principal**, and record the reasoning. They are
      different callers with different authorisation, and the retired shared
      admin key made the distinction invisible. Blocking for 3.1.
- [ ] 2.2 Determine whether `SELLER.ADMIN_API_KEY` retains any consumer once
      the provisioning fixture stops using it. If the storefront's `/admin/*`
      routes still gate on it, `storefront_admin_client` keeps it; if nothing
      uses it, remove the setting and its compose plumbing rather than leaving
      a retired-model artefact.

## 3. Repair

- [ ] 3.1 Rebuild `provisioning_client` on the current signature — a signer for
      the principal chosen in 2.1, plus an `expected_authorities` set pinning
      the provisioning service's own principal (`0xf39fd6e5…`,
      `PROVISIONING_IDENTITY__IDENTIFIER`). Correct the docstring, which still
      asserts "there is no per-agent identity".
- [ ] 3.2 Build the buyer-CLI `ProfileStore` through the model's own
      initial-state classmethod rather than passing `revision=0` literally, so
      the initial revision stays owned by the model.
- [ ] 3.3 Apply the same repair to any further sites 1.2 found.

## 4. Validation

- [ ] 4.1 Run the full e2e suite against the stack. Record the result as
      passed / failed / errored counts, and confirm **zero errors** — an error
      means a fixture is still wrong, which is this change's scope; a failure
      means the suite ran, which is not.
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

**Not started.** Written from a diagnosis of the first e2e run to reach pytest;
no code changed. Task 2.1 is blocking for 3.1.
