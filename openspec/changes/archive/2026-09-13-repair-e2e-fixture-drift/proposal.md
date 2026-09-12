## Why

The end-to-end suite now reaches pytest for the first time since mid-August and
reports **12 passed, 1 skipped, 88 errors**. Every one of the 88 is a fixture
error, from two places where the suite still calls a library the way that
library used to be shaped:

- `SyncProvisioningClient.__init__() got an unexpected keyword argument
  'admin_key'`. The fixture passes a shared admin key; the client now takes a
  `signer` and an `expected_authorities` set. Its docstring still states the
  retired model outright — "there is no per-agent identity" — which is no
  longer true of the provisioning service.
- `ValidationError: 1 validation error for ProfileStore — revision Field
  required`. `ProfileStore` gained a required `revision` for optimistic
  concurrency; the buyer-CLI fixture constructs one without it while already
  passing `expected_revision=0` to the repository.

Neither is a test that fails on its own merits. Both are constructors that
raise before any assertion runs, so 88 tests report an error rather than a
result and the suite's output says nothing about the system it was written to
exercise.

The drift accumulated because these code paths had no working stack to run
against: `docker compose up` was broken from mid-August until
[`provide-e2e-development-identities`](../archive/2026-09-12-provide-e2e-development-identities/)
repaired it, so library signatures changed without their e2e callers being
updated and nothing reported it.

## What Changes

- Rebuild the `provisioning_client` fixture on the client's current shape: an
  identity signer plus the trust pin for the provisioning service's principal,
  replacing the shared-admin-key construction, and correct the docstring that
  still asserts the retired model.
- Supply `revision` where the buyer-CLI fixture builds a `ProfileStore`, using
  the `revision=0` initial state the model already provides a constructor for
  rather than hard-coding it.
- Re-run the suite and classify what remains. A fixture repair changes 88
  errors into 88 results, and those results are unknown today — some will pass
  and some will be real findings about the system.

## Non-Goals

- Do not change library signatures to match the fixtures. The libraries moved
  deliberately — provisioning gained per-caller identity, `ProfileStore` gained
  optimistic concurrency — and the suite is what is stale.
- Do not fix whatever the repaired suite then reveals in the same change.
  Classify it and raise it; a repair that also chases its own findings never
  reaches a reviewable boundary.
- Do not reduce assertions to make tests pass. A test that errors is
  uninformative; a test weakened until it passes is worse.

## Impact

- Affected code: `e2e-tests/` fixtures only. No production source, no
  distribution, no persisted state, no permanent specification.
- Affected validation: the e2e suite's result becomes meaningful for the first
  time since mid-August. That is the point of the change and also its risk —
  the suite may report real defects that were invisible while it could not run.

## Inherited open questions

Deferred by the archived identities change, recorded here so they are not lost.
Neither of the first two blocked startup — `credits-storefront` came up healthy
— so whatever reads that table does not read it at startup.

- `storefront.credits.toml` pins `ed25519 My6-jSfLcyOzpAHBwTtd1kvMwOEOzaHCtdEaA3eaheU`
  as the `default` capacity site's expected authority, but that site is the
  provisioning service, which signs eip191. No private half exists in the
  repository, so it cannot be satisfied by supplying a credential.
- The same table declares `expected_authorities` but no authority **URL**, so
  `capacity.sites.default` is a table where the loader expects a URL string.
- `compose.apicredits.yml` still has the `include`-plus-override shape that
  broke the root stack, and will fail the same way when used.
- `kit/config`'s shared loader TOML-parses environment values, so any
  `0x`-prefixed value bound for an identity field arrives as an integer.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [ ] Existing subsystem specification
- [ ] New subsystem specification
- [x] No permanent documentation change

`docs/development/TESTING.md` already defines the levels and the fixture
architecture this restores; nothing about the boundary changes. The change
brings callers back into step with contracts that are already documented where
they belong.
