# Tasks

One commit. The seam proof and the fixtures that exercise it are the same
review: a seam asserted without a foreign adapter is an assertion, and fixtures
without the purity tests do not establish the property either.

Baseline: `origin/dev` at `e91767a3b074b20168bbcb87a8418d8287e5f8a6`. Re-pin
before starting.

Sequenced after `add-harness-buyer-action-slice`. The seam is proved generic by
contrast with a working concrete adapter, and there is nothing to contrast with
until one exists.

Nothing here executes a future-domain fixture, and nothing adds an adapter for
bare metal or API credits. If a task appears to need either, the plan premise is
wrong — pause for design review.

## 1. Generic seam proof

- [ ] 1.1 Add one arbitrarily-named fake adapter under
  `tools/issue-discovery/tests/`, carrying an opaque namespaced payload. The
  name must be one the core has never seen; do not name it after a plausible
  future domain, which would invite someone to grow it into one.
- [ ] 1.2 Round-trip its payload through the runtime and back unchanged, and
  assert the runtime did not interpret it.
- [ ] 1.3 Add the adapter with no edit to the generic runtime. If an edit turns
  out to be required, stop — that is the property failing, and the finding is
  more valuable than the workaround.
- [ ] 1.4 Add an import-purity test: the generic runtime imports no concrete
  domain module.
- [ ] 1.5 Add an identity-purity test: no domain identity appears in a generic
  code path, including in a conditional, a lookup table, or a log line.

## 2. Version and capability failures

- [ ] 2.1 Fail an adapter declaring an unsupported contract version, naming the
  version it declared and the versions supported.
- [ ] 2.2 Fail an adapter declaring a capability the runtime does not know,
  naming the capability.
- [ ] 2.3 Read declared capabilities from the product's own
  `DomainCapability` vocabulary rather than maintaining a parallel list. A
  second list drifts, and the drift is silent.

## 3. Disabled fixtures for the product's other domains

- [ ] 3.1 Add fixtures for `bare_metal` and `apicredits` using their real
  `DomainIdentity` values and the capabilities those domains actually declare.
  Do not invent plausible identities — a fixture with a wrong-but-plausible
  identity stays green when the real one changes, losing exactly the
  compatibility signal wanted.
- [ ] 3.2 Validate and dry-plan both. Neither has an adapter.
- [ ] 3.3 Assert zero effect on attempted execution: no process started, no file
  written, no connection opened, no state changed. Assert on the absence of
  effects, not on a raised exception — an implementation that acts and then
  fails raises the same exception as one that refuses up front.

## 4. Bounded fixture for a domain that does not exist

- [ ] 4.1 Add exactly one, for one purpose: proving the seam accepts a namespace
  the core has never seen.
- [ ] 4.2 Cap it in the schema — an identity, a namespace, and an opaque
  payload. No capability declarations, no actor roles, no expected outcomes, no
  oracles. A fixture carrying any of those fails validation.
- [ ] 4.3 Add a test that the elaborate version is refused. The cap is a control
  only if something enforces it; as a review comment it is an instruction.

## 5. Feature-onboarding proof

- [ ] 5.1 Run the intake workflow against the fake adapter and record what it
  required. If it required an undocumented step, the step is the finding.
- [ ] 5.2 Simulate a deprecated or renamed product target and assert the failure
  names the target, the domain, and the fixture that referenced it — not a
  generic resolution error. A harness that fails vaguely against product change
  trains its operators to ignore it.
- [ ] 5.3 Run the existing harness suite plus the VM fixtures, and demonstrate
  that no generic-core edit was required by any of the above.

## 6. Documentation

- [ ] 6.1 Record in `docs/development/TESTING.md` what adding a domain to the
  harness costs — an adapter, an oracle, redaction and cleanup rules, focused
  tests — and what the generic runtime may not contain.
- [ ] 6.2 State plainly that this is an ordinary testing seam and not a plugin
  platform: no discovery, no registry, no lifecycle hooks, no third-party
  contract. An adapter is a module the configuration names.
- [ ] 6.3 Record the feature-onboarding workflow in
  `docs/development/ISSUE_DISCOVERY.md`.
- [ ] 6.4 Verify every path cited by both documents resolves on the branch.

## 7. Closeout

- [ ] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
  match; read touched files for what the target cannot catch.
- [ ] 7.2 **Import placement.** Migrate local imports added here to module level
  where safe, verifying each against the real suite.
- [ ] 7.3 **Documentation compliance.** Re-check accepted decisions against
  `openspec/README.md`'s placement rules, and confirm every citation resolves.
- [ ] 7.4 **Narrative compression.** Reduce task notes to final behaviour,
  validation evidence, unresolved work, and promotion destinations. The
  speculation-cap reasoning belongs in `design.md`.
- [ ] 7.5 **Roadmap currency.** `docs/development/ROADMAP.md` owes nothing: the
  harness is not a market capability. Recorded as a deliberate disposition.
- [ ] 7.6 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location | State |
|---|---|---|
| Adding a domain costs an adapter, an oracle, redaction and cleanup rules, and focused tests — and no generic-runtime edit | `docs/development/TESTING.md` | Pending |
| The generic runtime treats domain payloads as opaque and contains no concrete-domain branch or identity | `docs/development/TESTING.md` | Pending |
| This is a testing seam, not a plugin platform | `docs/development/TESTING.md` | Pending |
| The feature-onboarding workflow, and that an incompatible product change fails naming the target | `docs/development/ISSUE_DISCOVERY.md` | Pending |
| `The harness runtime is domain-agnostic`, `Prepared domains validate without executing`, and `Incompatible product change fails explicitly` | `openspec/specs/test-compatibility/spec.md` | At archival |
