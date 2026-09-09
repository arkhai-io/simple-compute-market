## Why

`contact-exchange-settlement` requires that contact payloads "MUST be deletable
as part of the deal lifecycle without disturbing the settled obligation record,"
and carries a scenario for an operator removing a revealed introduction "at the
end of its retention window."

None of that is implemented. There is no deletion method, no purge path, and no
retention-window setting anywhere in the mechanism kit or in the storefront that
composes it. The retention window exists only as a phrase in a specification, and
an operator honouring it today does so with hand-written SQL against a table
holding both parties' personal contact details.

That is tolerable at one composing storefront and stops being tolerable as more
compose the mechanism, which is why this is a prerequisite of
`compose-contact-exchange-across-compute` rather than a follow-on. Multiplying the
number of deployments holding contact data before the deletion path exists
multiplies exposure against an obligation currently satisfied only in principle.

A retention window nobody was told about is also not a retention policy. Both
parties hand over contact details at reveal; neither is told how long they are
kept.

## What Changes

- Add a retention window as storefront configuration, with an explicit operator
  default rather than an implicit unbounded one.
- Add a deletion path that removes both contact payloads for one introduction
  while leaving the settled obligation record and the deal's terminal state
  intact.
- Run the deletion: a sweep over introductions past their window, plus an
  operator-invoked path for a single introduction on request.
- Disclose the effective window to both parties at reveal, through the same
  projection that carries the reveal itself.
- Record deletion as idempotent and safe against an already-deleted
  introduction, so a retried sweep converges rather than failing.

## Capabilities

### Modified Capabilities

- `contact-exchange-settlement`: the retention obligation gains an
  implementation contract — a configured window, an idempotent deletion path
  preserving the obligation record, and disclosure of the window to both parties.

### New Capabilities

None.

## Non-Goals

- Do not delete, alter, or re-key the settled obligation record. The deal
  remains, its terminal state remains, and `obligation_ref` remains resolvable;
  only the payloads go.
- Do not add a deletion path for deals whose introduction was never started.
  Those persist no contact data by construction and there is nothing to remove.
- Do not build per-deal contact aliasing. Related and useful, but a different
  concern; see `design.md`.
- Do not change the reveal surface's authentication, idempotency, or delivery
  dispatch.

## Impact

- Affected code: the contact-exchange mechanism kit's persistence contract, the
  composing storefront's introduction persistence, and storefront configuration.
- Affected specification: `openspec/specs/contact-exchange-settlement/spec.md`.
- Affected operators: a deployment gains a retention setting. An operator wanting
  the current behaviour must say so explicitly, which is the point.

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

- The retention window is configured with an explicit operator default and is
  disclosed to both parties at reveal —
  `openspec/specs/contact-exchange-settlement/spec.md`.
- Deletion is idempotent, removes both payloads, and preserves the settled
  obligation record — `openspec/specs/contact-exchange-settlement/spec.md`.
- Storefront deletion does not reach copies already delivered to configured sinks
  — `openspec/specs/contact-exchange-settlement/spec.md`.
