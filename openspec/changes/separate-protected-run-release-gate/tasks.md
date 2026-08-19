## 1. Separate the gates

- [x] 1.1 Split `require_release_identity` into an attested constructor that
      keeps every current check — including observed-equals-trusted commit — and
      a development constructor that builds the same `ReleaseIdentity` from
      observed local values. Both return one type; neither returns partial
      identity.
- [x] 1.2 Leave the safety gates (`require_test_secret`,
      `require_connected_account`, `require_ready_account`,
      `require_loopback_webhook`, `verify_loopback_webhook_endpoint`)
      unconditional, and prove by test that they run in both modes.
- [x] 1.3 `driver.run()` takes `--release-mode attested|local`, defaulting to
      `attested`, and runs one body under both. A protected invocation whose
      provenance binding fails still fails closed rather than downgrading.
- [x] 1.4 `StripeTestEvidence` records `release_mode`, derived from what was
      proven rather than from the flag, with the schema identity bumped so an
      unaware consumer fails instead of misreading.
- [x] 1.5 Evidence: unit tests for the mode split — a development run records a
      development mode; no argument combination yields an attested record without
      binding; a failed protected binding raises; safety gates fire in both
      modes; a live credential is refused in a development run.
- [x] 1.6 Closeout: hygiene clean; one refinement recorded in design.md -- the
      generated Compose environment is allowlist-complete by construction, so a
      locally rendered one carries every key and leaves the coordinates it
      cannot source empty, which the record reads as the local sentinel.
      Evidence schema bumped to v4 in both the dataclass and the JSON schema,
      where an attested document is held to every original constraint through a
      conditional branch. Suite: e2e-tests unit 90.

## 2. Make the stack startable locally

- [x] 2.1 Split `prepare-hosted-compose` so the attested path keeps
      `gh attestation verify` unchanged and a local path renders the same compose
      environment from locally available inputs, sharing the rendering.
- [x] 2.2 A `hosted-stripe-test-local` target that requires every safety
      precondition and none of the provenance ones, and passes
      `--release-mode local`.
- [x] 2.3 Evidence: the attested target's preconditions are unchanged (assert on
      the target's own requirements), and the local target refuses to run without
      the safety inputs.
- [x] 2.4 Closeout: hygiene clean. Verified end to end against the real staged
      v0.2.1 release -- `make prepare-hosted-compose-local` renders a complete
      environment, the gates reader accepts all 30 keys, the producer binds to
      the exact ghcr digest from the trust manifest, and the run records as
      local with a `local` consumer coordinate. Suites: scripts 20, e2e unit 90.

## 3. Replace the broker for local runs

- [ ] 3.1 Document the broker response payload as the seam: the keys the workflow
      consumes today, recorded where a future implementer will find them.
- [ ] 3.2 A local assembler producing that payload from operator-supplied
      provider credentials plus generated ephemeral identity credentials, writing
      the authority environment file the driver expects. Never writes provider
      credentials into the repository.
- [ ] 3.3 Evidence: the assembled payload satisfies the same consumption the
      workflow performs; generated identities are well-formed and ephemeral;
      provider credentials are absent from every emitted artifact.
- [ ] 3.4 Closeout.

## 4. Prove it on the blocked failure

- [ ] 4.1 Run the body locally against the real Stripe test account for one card
      lane and record what the `payer_profile_unavailable` stage actually raises
      — the diagnostic `add-bare-metal-hosted-settlement` has been unable to
      obtain. Disclose the result there rather than resolving that change's
      blocked task from a development run.
- [ ] 4.2 Permanent docs: record in `docs/development/TESTING.md` how to run the
      body locally, and that development evidence never qualifies.
- [ ] 4.3 Closeout: hygiene clean, strict validation, ROADMAP updated if the
      hosted-settlement gap rows change shape.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Safety prerequisites hold in every mode; provenance prerequisites classify the evidence rather than gate execution | `openspec/specs/deployment-state/spec.md` (promote at synchronization) |
| Release mode is derived from what was proven and recorded in the evidence, so no invocation can claim unearned attestation | `openspec/specs/deployment-state/spec.md` (promote at synchronization) |
| A development run requires no attested artifact, broker, or self-hosted runner, and local assembly matches the broker's payload shape | `openspec/specs/deployment-state/spec.md` (promote at synchronization) |
| How to run the hosted body locally, and that its evidence never qualifies | `docs/development/TESTING.md` |
