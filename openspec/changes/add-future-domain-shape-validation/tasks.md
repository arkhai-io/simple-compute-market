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
- [ ] 6.5 **Comment hygiene and import placement, before the pre-closeout review.** Run
  `make check-comment-hygiene` and read the comments this change added for any that
  narrate the review or migration that introduced them; move each import the change
  added to module level unless a verified circular import or a recorded lazy-load
  reason keeps it local. Closeout only confirms both.

## 7. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 7.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read
  the comments this change added for any that narrate the review or migration that
  introduced them. Do not edit code here: anything to rewrite returns the change to
  implementation.
- [ ] 7.2 **Import placement — confirm.** Check the imports this change added for any
  still local without a recorded reason. One that should move returns the change to
  implementation.
- [ ] 7.3 **Documentation compliance.** Re-check this change's accepted decisions
  against `openspec/README.md`'s placement rules, and the permanent documents
  against the code they describe.
- [ ] 7.4 **Narrative compression.** Compress completed-task notes to final behavior,
  material validation evidence, unresolved or deferred work, and
  permanent-documentation destinations, moving durable rationale into `design.md`
  first. The speculation-cap reasoning belongs in `design.md`.
- [ ] 7.5 **Roadmap currency.** Update the affected goal's current state and gap
  mapping in `docs/development/ROADMAP.md`, or record that no goal is affected.
  Expected disposition: `docs/development/ROADMAP.md` owes nothing, since the harness
  is not a market capability; record it as a deliberate disposition.
- [ ] 7.6 **Campaign index currency.** Update this change's row, and its campaign's
  dependency graph, in `openspec/changes/README.md`, or record that both are
  unchanged. Other rows' `Depends on` are left alone: archive cleanup releases
  dependents after the closeout gate.
- [ ] 7.7 **Packaging.** Run `make check-packaging` and resolve every failure it
  reports (a failure needing a code or lock change returns the change to
  implementation).
- [ ] 7.8 **End-to-end pipeline.** Record the passing run the latest validation names,
  its result, and the scenarios that exercise this change, or an explicit blocker
  naming its cause and the change that owns it, with the validations it gates
  treated as unrun.
- [ ] 7.9 **Promotion.** Write the permanent documents this change owes —
  `docs/development/TESTING.md` and `docs/development/ISSUE_DISCOVERY.md` (drafted in
  section 6) — and complete the design-promotion record below. A `spec.md` the deltas
  cover — here `openspec/specs/test-compatibility/spec.md` — is written by the archive
  in 7.11, not by hand; the record names it all the same.
- [ ] 7.10 **Documentation citations.** After promotion, run
  `make check-doc-citations CHANGE=add-future-domain-shape-validation` and resolve
  every match, then `openspec validate add-future-domain-shape-validation --strict`.
- [ ] 7.11 **Archival.** Last, once every other part is checked: `openspec archive
  add-future-domain-shape-validation -y` merges the deltas into `openspec/specs/` and
  moves the change under `openspec/changes/archive/`; point the index row at the
  archived directory, and run `openspec validate --specs --strict`.

## Design promotion record

| Accepted decision | Permanent location | State |
|---|---|---|
| Adding a domain costs an adapter, an oracle, redaction and cleanup rules, and focused tests — and no generic-runtime edit | `docs/development/TESTING.md` | Pending |
| The generic runtime treats domain payloads as opaque and contains no concrete-domain branch or identity | `docs/development/TESTING.md` | Pending |
| This is a testing seam, not a plugin platform | `docs/development/TESTING.md` | Pending |
| The feature-onboarding workflow, and that an incompatible product change fails naming the target | `docs/development/ISSUE_DISCOVERY.md` | Pending |
| `The harness runtime is domain-agnostic`, `Prepared domains validate without executing`, and `Incompatible product change fails explicitly` | `openspec/specs/test-compatibility/spec.md` | At archival |
