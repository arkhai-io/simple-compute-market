## 1. The consumer stops naming a hosted release

- [x] 1.1 Open up `StripeSettlementConfig` in `kit/hosted-settlement`: the API version and schema version become validated values rather than types admitting one release, and the configured capability set must be a superset of the marketplace's own required floor rather than equal to it.
- [x] 1.2 Make all three required-when-enabled, each with its own named blocker when absent, on the same terms as `expected_manifest_digest`.
- [x] 1.3 Remove the three pins from `e2e-tests/config/hosted-storefront.toml`, `e2e-tests/config/hosted-buyer.toml`, and `config.stripe-fiat-ed25519.toml`, leaving the comment that says the run supplies them.
- [x] 1.4 Give `EphemeralMarketplaceConfig` and `EphemeralBuyerConfig` the bound contract, and render the three pins from it with the same counted-substitution refusal the existing settings use. Integer and list settings need their own replacement helpers; `_SAFE_CONFIG_VALUE` must admit the rendered forms without loosening for anything else.
- [x] 1.5 Pass `release.hosted_contract` into both renderers at their construction sites in `e2e-tests/src/hosted_real_stripe/driver.py`.
- [x] 1.6 Prove it: a config stating a 0.3.0 contract parses and is ready; an enabled config missing any pin is unready with the blocker that names it; a rendered config states the bound release's own coordinates; a renderer whose count is wrong refuses to render.

## 2. The build derives what follows from the release it binds

- [x] 2.1 Derive the client wheel, OpenAPI, conformance, and migration artifact filenames in `Makefile` from the version the bound trust config states, leaving `HOSTED_RELEASE_TRUST` naming one release explicitly.
- [x] 2.2 Do the same in `domains/vms/storefront/Makefile` and `kit/hosted-settlement/Makefile`.
- [x] 2.3 Prove it: the build's hosted artifact names follow a trust config naming a version other than 0.2.1, with no edit to a Makefile.

## 3. The pinned client moves to the release that declares the capability

- [x] 3.1 Copy the bound release's `arkhai_hosted_settlement_client-0.3.0-py3-none-any.whl` into the wheelhouse the marketplace resolves from.
- [x] 3.2 Move the pin to `==0.3.0` in `kit/hosted-settlement/pyproject.toml`, `domains/bare_metal/storefront/pyproject.toml`, and `domains/bare_metal/buyer/pyproject.toml`, and refresh every `uv.lock` that resolves it.
- [x] 3.3 Update the wheelhouse review test that asserts the pinned client version.
- [x] 3.4 Prove it: the storefront and buyer packages install and their existing hosted unit suites pass against the new client.

## 4. The payer submits its own verification

- [x] 4.1 Add `verify_setup` to `HostedPayerFacade`, carrying exactly one form of evidence — deposited minor-unit amounts or descriptor code — against one setup under one opaque binding, through the pinned client's own request model. Refuse both-or-neither before any hosted call.
- [x] 4.2 Carry verification-pending readiness through `payer_setup_projection`, and make buyer compatibility treat a setup awaiting payer verification as not-yet-ready rather than revoked or unavailable.
- [x] 4.3 Add the payer CLI command, emitting the same projection the other setup commands emit.
- [x] 4.4 Report the operation as an unavailable prerequisite naming the capability where the bound release does not declare direct payer instrument setup, before any hosted mutation.
- [x] 4.5 Prove it at the kit boundary: one evidence form admits, both or neither refuses before any call, the projection carries readiness and no evidence, and an undeclaring release reports the capability as the missing prerequisite.

## 5. The saved-instrument lane sets up without a browser

- [x] 5.1 Declare direct payer instrument setup as a prerequisite of a bank-funded `saved_instrument` lane in the per-scenario capability map, so an undeclaring release refuses through the existing prerequisite path.
- [x] 5.2 Let `start_setup` carry the optional opaque instrument token the released request model declares, transient on the same terms as an action URL, and confirm it reaches no projection.
- [x] 5.2a Let `_validate_payer_fixture` admit a setup awaiting payer verification, instead of requiring every saved-instrument setup to return a browser action URL.
- [x] 5.3 Add the lifecycle bridge surface that submits the verification and returns the refreshed fixture, alongside `complete_payer_setup`.
- [x] 5.4 Take the direct path in the driver's saved-instrument stage when the bound release declares the capability, and the existing browser path when it does not.
- [x] 5.5 Report a profile the bound release offers no setup for as an unavailable prerequisite, and confirm the interactive path for a non-declaring release is byte-for-byte what it is today.
- [x] 5.6 Prove it: a bank-funded saved-instrument lane against a declaring release needs no browser and records no submitted evidence; against a non-declaring release the interactive path and its evidence are unchanged.

## 6. End to end against a locally built 0.3.0 authority

- [x] 6.1 Run a `saved_instrument` bank-funded lane against the locally built 0.3.0 producer, through binding, rendering, migration, readiness, direct setup, and funding authorization. Record what was reached.

      Reached, against a producer built here and real Stripe test mode. The
      compose environment rendered `0.3.0`, schema `6`, and all eighteen
      capabilities from the producer's own artifacts. The authority migrated to
      schema 6 and served a readiness response stating `api_version: 0.3.0` —
      stated by the running service, which is what `report-the-contract-served`
      changed on the producer side.

      The marketplace consumer then reached ready against that live authority
      with a configuration carrying the bound release's own contract, and the
      same consumer bound to 0.2.1 against the same authority reported
      `hosted.api_mismatch` and `hosted.schema_mismatch`. That pair is the whole
      point: before this change the second case could not be reported at all,
      because the client could not parse the response, and the first could not
      be configured, because the version was a type.

      The lane itself: `start_setup` carrying an instrument token for Stripe's
      documented test bank returned `verification_pending` with no action;
      `verify_setup` with the deposits that bank always makes returned `ready`;
      the instrument listed as a ready `us_bank_account`. No browser was
      launched and no browser action was issued. The projections carried the
      opaque setup reference and readiness and nothing else.

      Not reached: the scenario body past the payer fixture. Driving negotiation
      and funding needs the marketplace and storefront containers, a connected
      account bound into the stack, and webhook forwarding, none of which this
      change touches. What it does touch was exercised end to end.

- [x] 6.2 Confirm the protected lane still refuses: with no signed 0.3.0 manifest it fails closed exactly as before, and the refusal names the missing release rather than the new capability.

      It refuses, and never gets near the capability. An attested render is
      refused for want of a marketplace manifest before any hosted input is
      read; supplied one, it is refused because the marketplace manifest digest
      does not match its trusted identity. Naming the locally built producer in
      attested mode changes none of that. No attested environment was rendered
      in any of the four attempts, and no refusal mentioned
      `payer-direct-instrument-setup.v1`, because provenance is settled before
      contract is considered.

## 7. Record the decisions that outlive the change

- [x] 7.1 Promote the source-of-expectation decision into `openspec/specs/settlement-configuration/spec.md` by way of this change's delta, and note in `openspec/specs/deployment-state/architecture.md` that the consumer half now reads its asserted contract from the bound release on the same terms as the producer half.
- [x] 7.2 Document the browserless bank-funded setup path and the 0.3.0 client requirement in `docs/development/TESTING.md`.
