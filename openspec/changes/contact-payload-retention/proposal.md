## Why

`contact-exchange-settlement` requires that contact payloads "MUST be deletable
as part of the deal lifecycle without disturbing the settled obligation record,"
and carries a scenario for an operator removing a revealed introduction "at the
end of its retention window."

None of that is implemented, and what does exist is unsafe to call.
`delete_introduction(conn, obligation_ref)` lives in the mechanism kit's
persistence module, is exported, and is unit-tested for repeat-call convergence,
but it removes the whole `contact_introductions` row. The reveal route service
treats a missing row as an introduction that was never started, so after that
delete:

- an authenticated read answers 409 "introduction has not been started" rather than
  a deleted outcome;
- a buyer's repeat start with a fresh request id persists a new contact pair and
  announces the introduction to the seller a second time, so the buyer can reverse
  a deletion and the seller cannot tell;
- operator re-delivery reports the deal as never revealed.

The primitive has no production caller, `created_at` is never read, and there is no
retention window, no sweep, no operator path, and no disclosure. An operator
honouring the requirement today does so with hand-written SQL against a table
holding both parties' personal contact details — and, through the defect above,
undoes nothing a buyer cannot redo.

Only bare metal composes `contact-exchange.v1` today. This is a prerequisite of
`compose-contact-exchange-across-compute` rather than a follow-on because that
change composes the mechanism into VM, and multiplying the deployments holding
contact data before the deletion path exists multiplies exposure against an
obligation satisfied only in principle.

A retention window nobody was told about is also not much of a policy. Both
parties hand over contact details — the buyer supplies theirs with the start
request itself — and neither is told how long they are kept, nor can find out
before committing them.

## What Changes

- Replace whole-row deletion with redaction in place: the row stays as a tombstone
  recording when its payloads were deleted, both contact payloads are emptied, and
  the agreed introduction context is kept. Database triggers make the active part of
  the table append-only — the only permitted update is the one-way redaction, and an
  unredacted row cannot be deleted — so removing a payload can leave no hole a later
  start could refill.
- After redaction, a read answers a stable deleted outcome; a start converges the
  obligation but persists nothing and delivers nothing; re-delivery refuses; and the
  one projection every reveal surface uses refuses to render a redacted record.
- Add a retention window to the mechanism's typed seller configuration,
  `retention_seconds`, defaulting to 30 days, with the literal `indefinite` meaning
  no deletion. The window is an aggregate policy over the storefront's dataset read
  from the running configuration, not a per-deal term.
- Add one deletion operation in the kit with two callers: a scheduled sweep over
  introductions whose reveal is older than the window, and an operator-invoked
  deletion of one introduction. Both reach it through a framework-free kit admin
  service, which also previews what the next sweep would delete.
- Disclose the effective window as one machine-readable kit object, on the
  storefront's public readiness projection before a buyer commits contact data, and
  again in the reveal projection. Both state current policy scoped to the
  storefront's introduction record.
- Compose all of it into the bare-metal storefront: the sweep loop registered with
  the kit loop controller, its step and preview, the admin deletion route, and the
  readiness field.
- Prove reveal, disclosure, operator deletion, expiry, and sweep end to end with the
  first introduction scenario on the bare-metal lane.
- Require normatively that every storefront composing the mechanism runs the sweep
  and serves both disclosures, so a later composing domain cannot omit them.

Everything not specific to bare metal lands in `kit/contact-exchange`. A compute-family
storefront serving several domains is the long-term direction, and VM inherits the
kit parts when `compose-contact-exchange-across-compute` composes the mechanism there.

## Capabilities

### Modified Capabilities

- `contact-exchange-settlement`: the retention obligation gains an implementation
  contract — redaction leaving a tombstone, a configured window with a stated default
  read as an aggregate policy, one deletion operation behind both invocation paths,
  outcomes for every surface after deletion, disclosure before commitment and at
  reveal, and a requirement that every composing storefront runs it.
- `introduction-delivery`: neither the reveal nor an operator's re-delivery delivers
  an introduction whose payloads have been deleted.

### New Capabilities

None.

## Non-Goals

- Do not delete, alter, or re-key the settled obligation record. The deal remains,
  its terminal state remains, and `obligation_ref` remains resolvable; only the
  payloads go.
- Do not remove tombstones. A tombstone is what stops a deleted introduction being
  revealed again; removing one safely is anticipated cleanup with a stated
  precondition, recorded in `design.md` and unowned.
- Do not add a deletion path for deals whose introduction was never started. Those
  persist no contact data by construction and there is nothing to remove.
- Do not record the window per row and enforce the recorded value. Retention is an
  aggregate policy over a dataset the storefront owns and pays for, not a term
  agreed with a counterparty; see `design.md`.
- Do not publish the window into the registry, on the listing shape, or on the
  settlement option's published parameters, and do not add a publisher-level
  registry metadata surface. See `design.md` for the eventual home.
- Do not build per-deal contact aliasing.
- Do not compose retention into VM. VM does not compose the mechanism; it inherits
  retention with it.
- Do not change the reveal surface's authentication, idempotency, or wire shape
  beyond adding the disclosure object and the deleted outcome.
- Do not bound or redact the responses the storefront records for exact retry.
  Every reveal response is recorded there with the counterparty's contact and kept
  indefinitely; how long recorded outcomes are kept and what they may hold needs one
  answer for every authenticated response, not an exception for this mechanism. It
  is recorded as unowned work, and the disclosure does not claim to cover it.
- Do not claim the disclosed window covers copies held outside the introduction
  record, and do not present it as a commitment.

## Impact

- `kit/contact-exchange`: persistence (redaction, tombstone column, triggers,
  select-expired query), the retention configuration field, the deletion operation,
  sweep cycle and loop runner, the admin service, the disclosure model, and the route
  service's behaviour after deletion.
- `domains/bare_metal/storefront`: introduction persistence wrappers, the readiness
  response, the admin deletion route, sweep loop registration, and re-delivery.
- `domains/bare_metal/buyer`: surfacing the deleted outcome.
- `e2e-tests` and the bare-metal lane's development configuration: the introduction
  scenario and the contact-exchange settlement configuration it needs.
- Affected specifications: `openspec/specs/contact-exchange-settlement/spec.md`,
  `openspec/specs/introduction-delivery/spec.md`.
- Affected operators: a bare-metal deployment composing contact exchange gains a
  retention setting that defaults to 30 days. Nothing is released, so no deployment
  holds historical payloads that a first sweep would delete.
- Not affected: the registry schema, the listing shape, the settlement option's
  published parameters, or any filter specification.

## Dependencies and Related Changes

- **Depends on `kit-owned-storefront-loop-lifecycle`**, whose controller the
  retention sweep registers with and whose step the end-to-end scenario uses.
- **Prerequisite for `compose-contact-exchange-across-compute`**, which composes the
  kit parts into VM and owns VM's wiring of them.
- **Gives `unbacked-bare-metal-listings` an introduction scenario to build on** for
  its own evidence that unbacked discovery reaches a usable introduction.
- Coordinate with `openspec/specs/introduction-delivery/spec.md`: delivery hands
  each side a copy of the reveal, so a payload deleted from the storefront may still
  exist at a configured sink. Disclosure must not imply otherwise.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — its settlement-configuration paragraph
      names the deletion operation and the retention boundary; it is updated to the
      operation's current name and to redaction leaving a tombstone.
- [x] Existing subsystem specification —
      `openspec/specs/contact-exchange-settlement/spec.md` and
      `openspec/specs/introduction-delivery/spec.md`.
- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md` — the retention setting, its
      default, and `indefinite`.
- [x] `docs/development/TESTING.md` — the loop table's bare-metal row gains the
      retention sweep.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Deletion redacts in place and leaves a tombstone; the table's active part is
  append-only; every surface's outcome after deletion —
  `openspec/specs/contact-exchange-settlement/spec.md`.
- The retention window is mechanism configuration with a stated default, applied as
  an aggregate policy read from the running configuration —
  `openspec/specs/contact-exchange-settlement/spec.md`.
- The scheduled sweep and the operator-invoked path share one deletion operation —
  `openspec/specs/contact-exchange-settlement/spec.md`.
- The window is disclosed before a buyer commits contact data and again at reveal,
  as current policy scoped to the introduction record —
  `openspec/specs/contact-exchange-settlement/spec.md`.
- Every storefront composing the mechanism runs the sweep and serves both
  disclosures — `openspec/specs/contact-exchange-settlement/spec.md`.
- A deleted introduction is never delivered —
  `openspec/specs/introduction-delivery/spec.md`.
