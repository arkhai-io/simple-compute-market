## Why

`contact-exchange-settlement` requires that contact payloads "MUST be deletable
as part of the deal lifecycle without disturbing the settled obligation record,"
and carries a scenario for an operator removing a revealed introduction "at the
end of its retention window."

Almost none of that is implemented, and it is worth being exact about which part,
because the imprecise version overstates the work. The deletion *primitive*
exists: `delete_introduction(conn, obligation_ref)` lives in the mechanism kit's
persistence module, is exported, and is unit-tested for the idempotency this
change wants. The `contact_introductions` table also already carries `created_at`.

What does not exist is anything that calls either. `delete_introduction` has no
production caller, `created_at` is never read, and there is no retention window
setting, no sweep, no operator path, and no disclosure. So the retention window
exists as a phrase in a specification and a column nobody queries, and an operator
honouring it today does so with hand-written SQL against a table holding both
parties' personal contact details.

That is tolerable at one composing storefront and stops being tolerable as more
compose the mechanism, which is why this is a prerequisite of
`compose-contact-exchange-across-compute` rather than a follow-on. Multiplying the
number of deployments holding contact data before the deletion path exists
multiplies exposure against an obligation currently satisfied only in principle.

A retention window nobody was told about is also not much of a policy. Both
parties hand over contact details — the buyer supplies theirs with the start
request itself — and neither is told how long they are kept, nor can find out
before committing them.

## What Changes

- Add a retention window as storefront configuration, defaulting to 30 days, with
  an unset value meaning indefinite retention. The window is an aggregate policy
  over the storefront's dataset, not a per-deal term.
- Add a caller for the existing deletion primitive: an operator-invoked path for a
  single introduction, and a scheduled sweep over introductions past the window.
  Both invoke the same underlying operation, so there is one deletion
  implementation and a manual cycle cannot diverge from the unattended one.
- Read the window live at sweep time. Setting a finite window is the operator's
  consent to delete existing rows past it; unsetting it stops deletion.
- Disclose the effective window at reveal, through the projection that already
  carries the reveal.
- Make the window queryable from the storefront before a buyer negotiates, on the
  storefront's existing public readiness projection, so a party can decline a
  storefront whose retention they find unacceptable rather than learning it after
  handing over their contact details.
- Record deletion as idempotent and safe against an already-deleted introduction,
  so a retried sweep converges rather than failing, and confirm the authenticated
  read returns a clean already-deleted outcome.

## Capabilities

### Modified Capabilities

- `contact-exchange-settlement`: the retention obligation gains an
  implementation contract — a configured window with a stated default, an
  idempotent deletion path preserving the obligation record, both invocation
  paths sharing one handler, and disclosure of the window both at reveal and
  before a buyer commits contact data.

### New Capabilities

None.

## Non-Goals

- Do not delete, alter, or re-key the settled obligation record. The deal
  remains, its terminal state remains, and `obligation_ref` remains resolvable;
  only the payloads go.
- Do not add a deletion path for deals whose introduction was never started.
  Those persist no contact data by construction and there is nothing to remove.
- Do not record the window per row and enforce the recorded value. Retention is
  an aggregate policy over a dataset the storefront owns and pays for, not a term
  agreed with a counterparty; see `design.md`.
- Do not publish the window into the registry, on the listing shape, or on the
  settlement option's published parameters. Every listing a storefront publishes
  would carry the same value for a minority use case, and buyer-side filtering on
  storefront configuration wants a storefront metadata surface that does not
  exist. Noted in `design.md` as the eventual home.
- Do not add a publisher-level metadata surface to the registry. It is the right
  scope for storefront-scoped policy and is a separate change with its own
  publish-payload, indexer, and read-surface work.
- Do not build per-deal contact aliasing. Related and useful, but a different
  concern; see `design.md`.
- Do not change the reveal surface's authentication, idempotency, or delivery
  dispatch.
- Do not claim the disclosed window covers copies already delivered to configured
  sinks, and do not present it as a commitment. It states current storefront
  policy, which the operator may change or override at any time.

## Impact

- Affected code: the composing storefront's introduction persistence and
  configuration, a storefront admin route, a storefront background sweep, and the
  storefront's public readiness projection. The mechanism kit's persistence module
  already carries the deletion primitive and needs a select-by-age query beside
  it.
- Affected specification: `openspec/specs/contact-exchange-settlement/spec.md`.
- Affected operators: a deployment gains a retention setting that defaults to 30
  days. Nothing is released yet, so no deployment holds historical payloads that a
  first run would delete.
- Not affected: the registry schema, the listing shape, the settlement option's
  published parameters, or any filter specification.

## Dependencies and Related Changes

- **Prerequisite for `compose-contact-exchange-across-compute`.**
- Coordinate with `openspec/specs/introduction-delivery/spec.md`: delivery hands
  each side a copy of the reveal, so a payload deleted from the storefront may
  still exist at a configured sink. Disclosure must not imply otherwise.
- Discharges half of the recorded open gap for contact-payload retention
  automation in `docs/development/ROADMAP.md`.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — no change expected; retention is
      mechanism behaviour rather than repository-wide architecture.
- [x] Existing subsystem specification —
      `openspec/specs/contact-exchange-settlement/spec.md`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The retention window is storefront configuration with a stated default,
  applied as an aggregate policy read live rather than pinned per deal —
  `openspec/specs/contact-exchange-settlement/spec.md`.
- Deletion is idempotent, removes both payloads, and preserves the settled
  obligation record — `openspec/specs/contact-exchange-settlement/spec.md`.
- The scheduled sweep and the operator-invoked path share one deletion handler —
  `openspec/specs/contact-exchange-settlement/spec.md`.
- The window is queryable from the storefront before a buyer commits contact
  data, and is disclosed again at reveal —
  `openspec/specs/contact-exchange-settlement/spec.md`.
- Storefront deletion does not reach copies already delivered to configured sinks,
  and the disclosed window states current policy rather than a commitment —
  `openspec/specs/contact-exchange-settlement/spec.md`.
