## 1. The consumer stops naming a hosted release

- [ ] 1.1 Replace `expected_api_version`, `expected_schema_version`, and `required_capabilities` in `e2e-tests/config/hosted-storefront.toml` and `e2e-tests/config/hosted-buyer.toml` with non-activating placeholders and the comment the manifest-digest placeholder already carries; the capability placeholder names one capability no release declares, never an empty list.
- [ ] 1.2 Give `EphemeralMarketplaceConfig` and `EphemeralBuyerConfig` the bound contract, and render the three pins from it with the same counted-substitution refusal the existing settings use. Integer and list settings need their own replacement helpers; `_SAFE_CONFIG_VALUE` must admit the rendered forms without loosening for anything else.
- [ ] 1.3 Pass `release.hosted_contract` into both renderers at their construction sites in `e2e-tests/src/hosted_real_stripe/driver.py`.
- [ ] 1.4 Prove it: a rendered config states the bound release's own API version, schema version, and capabilities; a committed template satisfies no real release; a renderer whose substitution count is wrong refuses to render.

## 2. The build derives what follows from the release it binds

- [ ] 2.1 Derive the client wheel, OpenAPI, conformance, and migration artifact filenames in `Makefile` from the version the bound trust config states, leaving `HOSTED_RELEASE_TRUST` naming one release explicitly.
- [ ] 2.2 Do the same in `domains/vms/storefront/Makefile` and `kit/hosted-settlement/Makefile`.
- [ ] 2.3 Prove it: the build's hosted artifact names follow a trust config naming a version other than 0.2.1, with no edit to a Makefile.

## 3. The pinned client moves to the release that declares the capability

- [ ] 3.1 Copy the bound release's `arkhai_hosted_settlement_client-0.3.0-py3-none-any.whl` into the wheelhouse the marketplace resolves from.
- [ ] 3.2 Move the pin to `==0.3.0` in `kit/hosted-settlement/pyproject.toml`, `domains/bare_metal/storefront/pyproject.toml`, and `domains/bare_metal/buyer/pyproject.toml`, and refresh every `uv.lock` that resolves it.
- [ ] 3.3 Update the wheelhouse review test that asserts the pinned client version.
- [ ] 3.4 Prove it: the storefront and buyer packages install and their existing hosted unit suites pass against the new client.

## 4. The payer submits its own verification

- [ ] 4.1 Add `verify_setup` to `HostedPayerFacade`, carrying exactly one form of evidence — deposited minor-unit amounts or descriptor code — against one setup under one opaque binding, through the pinned client's own request model. Refuse both-or-neither before any hosted call.
- [ ] 4.2 Carry verification-pending readiness through `payer_setup_projection`, and make buyer compatibility treat a setup awaiting payer verification as not-yet-ready rather than revoked or unavailable.
- [ ] 4.3 Add the payer CLI command, emitting the same projection the other setup commands emit.
- [ ] 4.4 Report the operation as an unavailable prerequisite naming the capability where the bound release does not declare direct payer instrument setup, before any hosted mutation.
- [ ] 4.5 Prove it at the kit boundary: one evidence form admits, both or neither refuses before any call, the projection carries readiness and no evidence, and an undeclaring release reports the capability as the missing prerequisite.

## 5. The saved-instrument lane sets up without a browser

- [ ] 5.1 Declare direct payer instrument setup as a prerequisite of a bank-funded `saved_instrument` lane in the per-scenario capability map, so an undeclaring release refuses through the existing prerequisite path.
- [ ] 5.2 Let `_validate_payer_fixture` admit a setup awaiting payer verification, instead of requiring every saved-instrument setup to return a browser action URL.
- [ ] 5.3 Add the lifecycle bridge surface that submits the verification and returns the refreshed fixture, alongside `complete_payer_setup`.
- [ ] 5.4 Take the direct path in the driver's saved-instrument stage when the bound release declares the capability, and the existing browser path when it does not.
- [ ] 5.5 Give `us_bank_transfer.v1` a saved-instrument path, and confirm the interactive path for a non-declaring release is byte-for-byte what it is today.
- [ ] 5.6 Prove it: a bank-funded saved-instrument lane against a declaring release needs no browser and records no submitted evidence; against a non-declaring release the interactive path and its evidence are unchanged.

## 6. End to end against a locally built 0.3.0 authority

- [ ] 6.1 Run a `saved_instrument` bank-funded lane against the locally built 0.3.0 producer, through binding, rendering, migration, readiness, direct setup, and funding authorization. Record what was reached.
- [ ] 6.2 Confirm the protected lane still refuses: with no signed 0.3.0 manifest it fails closed exactly as before, and the refusal names the missing release rather than the new capability.

## 7. Record the decisions that outlive the change

- [ ] 7.1 Promote the source-of-expectation decision into `openspec/specs/settlement-configuration/spec.md` by way of this change's delta, and note in `openspec/specs/deployment-state/architecture.md` that the consumer half now reads its asserted contract from the bound release on the same terms as the producer half.
- [ ] 7.2 Document the browserless bank-funded setup path and the 0.3.0 client requirement in `docs/development/TESTING.md`.
