# Design: rotate-registry-account-principals

## Context

`kit/identity` provides dual-proof rotation: one canonical intent naming the current and
replacement principals, the stable subject, the authority, a nonce, the overlap and an expiry,
signed by both principals
([marketplace identity](../../specs/marketplace-identity/spec.md)). The registry applies it to
publishers, whose stable subject owns their listings
([registry discovery](../../specs/registry-discovery/spec.md), "Publisher principal rotation").
`add-persistent-buyer-profiles` gives buyer profiles a primary principal, its history, and
`market profile rotate`.

`add-buyer-compute-rfqs` makes a principal own its RFQs and responses directly (its D1), and
the review of pull request #401 on 2026-11-27 settled that stable ownership across key changes
comes after the MVP, here: with keys held by the buyer account service, a key changes rarely.

## Decisions

### D1 — A registry-local account subject

The registry gives any participant that signs its own requests a stable account subject, to
which its principals bind; RFQs and responses are owned by it. It is local to one registry: a
participant active at two registries rotates at each.

### D2 — Rotation reuses the publisher scheme

An account subject moves to a new principal only by the two-proof rotation the registry applies
to publishers, from `kit/identity`'s primitives, with the same overlap, retirement, and
operator disablement of a compromised principal.

### D3 — The buyer CLI applies rotations

A buyer profile's rotation is applied at each registry where the profile holds an account, from
the buyer CLI.

### D4 — Existing RFQs move to account subjects

RFQs and responses owned by a principal move to that principal's account subject when the
subject is first created.

## Open Questions

### Q1 — Sharing the publisher's subject

Whether the account subject generalizes the publisher subject, so that a seller who also posts
RFQs has one subject, or stands beside it.

### Q2 — When a subject is created

On a principal's first write, or by an explicit enrolment.

### Q3 — Which registries the CLI rotates at

How the CLI knows the registries where a profile holds an account.

## Verification

Integration tests prove ownership surviving a rotation, refusal by a retired principal, and the
migration of principal-owned RFQs.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1–D2, D4 | `openspec/specs/registry-discovery/spec.md`; the `buyer-compute-rfqs` capability's specification |
| D3 | `openspec/specs/marketplace-identity/spec.md`; `docs/buyer-quickstart.md` |
| Goal 9 | `docs/development/ROADMAP.md`, Goal 9 |
