## 1. Separate the producer's contract from its provenance

- [x] 1.1 In `scripts/prepare-hosted-compose.py`, split the hosted `HOSTED_SETTLEMENT_VERIFIED_*`
      keys into a provenance group and a contract group, mirroring the existing
      `_LOCAL_MARKETPLACE_COORDINATES` treatment of the consumer half. No behavior change yet:
      the attested path must render a byte-identical environment.
- [x] 1.2 Add a regression test pinning the attested environment's exact key set and values for
      a fixed input, so every later task is checked against it.

## 2. Read the asserted contract from the bound release

- [ ] 2.1 Render the contract group (release version, API version, schema version, funding
      profiles, capabilities) from the bound release's conformance artifact rather than from
      the signed manifest's duplicated fields, keeping the attested output identical.
- [ ] 2.2 In `e2e-tests/src/hosted_real_stripe/gates.py`, replace the `"0.2.1"`, `"5"`,
      `_FUNDING_PROFILES`, and `_CAPABILITIES` literal expectations in `_require_hosted_half`
      with a comparison against the coordinates the run bound. Keep the disagreement failure
      closed and before Compose creates any service.
- [ ] 2.3 Cover the "newer hosted release is bound" and "composed authority does not serve the
      bound contract" scenarios. Verify the harness admits a 0.3.0-shaped conformance artifact
      with no source edit, and refuses a mismatched environment.

## 3. Accept a locally built producer

- [ ] 3.1 Add `--local-hosted-image` to `prepare-hosted-compose.py` and a `--hosted-conformance`
      input naming the generated artifacts. Render provenance keys empty and the contract keys
      from those artifacts.
- [ ] 3.2 Fail closed when a local hosted image is named without readable contract artifacts,
      reporting the missing artifacts rather than falling back to another release's coordinates.
- [ ] 3.3 Give `gates.py::_require_hosted_half` the matching local branch: accept a bare image
      reference, expect empty provenance, and assert the contract exactly as an attested run does.
- [ ] 3.4 Confirm no safety assertion acquired a mode parameter — test-mode-only credential,
      live-object refusal, loopback-only webhook delivery, connected-account readiness, and
      browser availability stay on an unbranched path (design D4).

## 4. Compute the release mode from what was bound

- [ ] 4.1 Derive the recorded release mode from the bound halves rather than from a flag, so a
      local producer alone makes the run a development run.
- [ ] 4.2 Cover all four combinations of released/local producer and consumer: each admits, and
      only attested/attested records an attested mode.
- [ ] 4.3 Verify no flag, argument, or environment variable can record a run with any local half
      as attested.

## 5. Build and run a local producer

- [ ] 5.1 Add `HOSTED_LOCAL_HOSTED_IMAGE` and a Makefile target that builds the producer image
      and artifacts from a sibling hosted-settlement-service checkout.
- [ ] 5.2 Stop `prepare-hosted-compose-local` and `hosted-stripe-test-local` from requiring the
      six `HOSTED_PRODUCTION_*` identities when a local producer is named; keep requiring them
      when one is not.
- [ ] 5.3 Derive the released-producer identities from the committed trust manifest so the
      released-producer local run stops requiring six hand-copied digests. Five are in
      `manifests/hosted-settlement-*-trust.json`; the workflow run id is the remaining input.

## 6. Prove it end to end

- [ ] 6.1 Run one existing lane against a locally built producer at the currently released
      version and confirm it behaves as it does against the published image, and that its
      evidence records `release_mode: local`.
- [ ] 6.2 Build hosted-settlement-service 0.3.0 locally, bind it, and run a `saved_instrument`
      lane. This is the first scenario with no published image behind it and no browser in it.
      Record what it reaches. A development run qualifies no lane in the protected matrix.
- [ ] 6.3 Confirm an attested run is unchanged: same rendered environment, same assertions, same
      fail-closed behavior, byte-for-byte evidence shape.

## 7. Record what was decided

- [ ] 7.1 Document the producer-local recipe in `docs/development/TESTING.md` beside the existing
      consumer-local one, including the two-checkout prerequisite and that a local producer never
      qualifies evidence.
- [ ] 7.2 Promote the accepted provenance/contract split to
      `openspec/specs/deployment-state/architecture.md`, which currently explains the protected
      boundary without naming that distinction.
- [ ] 7.3 External: a protected run of the matrix remains blocked on the protected environment and
      is unaffected by this change. Recorded, not simulated.
