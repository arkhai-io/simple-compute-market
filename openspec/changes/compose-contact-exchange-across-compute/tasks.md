# Tasks — compose contact exchange across the compute family

Depends on `contact-payload-retention` having landed. Do not begin Section 2
before it has.

## 1. Survey and placement

- [ ] 1.1 Separate the bare-metal introduction composition into domain-neutral
      parts (accepted-state interpretation, `obligation_ref` re-derivation, the
      obligation drive sequence) and domain-supplied parts (persistence client,
      configured values). Record the split before moving anything.
- [ ] 1.2 **Decision gate:** decide where the promoted glue lives, and record the
      reasoning in `design.md`. It is an open question there. The constraints are
      the mechanism kit's asserted package boundary and the composition seam that
      owns kit-side storefront runtime; do not place it by default.
- [ ] 1.3 **Decision gate:** decide which compute-family domains this change
      composes, and record the reasoning. Also open in `design.md`.

## 2. Promote

- [ ] 2.1 Move the domain-neutral bodies to the chosen home with persistence
      injected through the existing callback contract.
- [ ] 2.2 Promote the bodies unchanged. A promotion that also alters a check is
      unreviewable, and these checks are security checks — the `obligation_ref`
      re-derivation is what prevents a reveal against an obligation the accepted
      plan does not contain.
- [ ] 2.3 Leave the bare-metal storefront holding only its persistence client and
      configured values.
- [ ] 2.4 Confirm the mechanism kit's package-boundary test still passes and that
      the kit acquired no persistence, framework, or delivery dependency.
- [ ] 2.5 Run the bare-metal introduction coverage unchanged against the promoted
      implementation before composing any further domain.

## 3. Compose

- [ ] 3.1 Register the mechanism in each domain chosen in 1.3, supplying
      persistence and configured values only.
- [ ] 3.2 Add each domain's introduction persistence, matching the shape the
      promoted contract expects.
- [ ] 3.3 Confirm composition is independent of whether a listing is
      capacity-backed, in both directions: a backed listing may settle by
      introduction, and an unbacked listing is not required to.

## 3b. Per-origin contact resolution

- [ ] 3b.1 Make the seller's contact payload resolvable from a listing's origin
      rather than a single storefront-wide configuration value. The origin site is
      already on the durable listing binding and copied to the negotiation thread, so
      no new lookup is needed at acceptance.
- [ ] 3b.2 Resolve a single-origin deployment to the value it configures today, so
      existing operators see no change.
- [ ] 3b.3 Refuse acceptance when a listing's origin has no configured payload,
      rather than falling back to another origin's. Revealing the wrong seller's
      contact details is a disclosure failure, not a degraded result.
- [ ] 3b.4 **Integration.** Two origins configured behind one storefront: a deal on
      each listing reveals that origin's payload, and neither reveals the other's.
- [ ] 3b.5 **Integration.** An origin with no configured payload refuses at
      acceptance rather than revealing a fallback.

## 4. Delivery

- [ ] 4.1 Wire delivery dispatch in each newly composing domain, seller-side off
      the reveal's critical path and buyer-side inline.
- [ ] 4.2 Confirm delivery remains non-authoritative and that re-delivery reads
      the durable reveal rather than reconstructing one.

## 5. Specification

- [ ] 5.1 State in `openspec/specs/contact-exchange-settlement/spec.md` that
      accepted-state interpretation and the obligation drive sequence have one
      implementation, and that a composing domain supplies persistence and values
      rather than lifecycle logic.
- [ ] 5.2 Add a scenario covering the `obligation_ref` mismatch refusal, so the
      promoted security check is normative rather than incidental.
- [ ] 5.3 Update `openspec/specs/introduction-delivery/spec.md` for availability
      across composing domains, and for delivery reaching the seller at the listing's
      origin.
- [ ] 5.4 State in `openspec/specs/contact-exchange-settlement/spec.md` that the
      seller's contact payload is resolved from a listing's origin, with a scenario
      for two origins behind one storefront and one for an origin with no configured
      payload.

## 6. Validation

- [ ] 6.1 Mechanism-kit boundary and unit suites.
- [ ] 6.2 Per-domain introduction reveal coverage, including retry convergence and
      the mismatch refusal.
- [ ] 6.3 An end-to-end deal settling by introduction in a newly composing domain,
      including delivery.

## 7. Closeout

- [ ] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. The local rationale to keep at the promoted glue is why the
      re-derivation check exists, not which domain it came from.
- [ ] 7.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where no genuine circular
      import or documented lazy-load reason exists. Verify against the real test
      suite; a promotion is exactly where a latent circular import surfaces.
- [ ] 7.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table.
- [ ] 7.4 **Narrative compression.** Shorten completed-task notes to final
      behaviour, the two decision-gate outcomes, and any remaining open work.
- [ ] 7.5 **Roadmap currency.** Update Goal 6's open-gap row in
      `docs/development/ROADMAP.md`: cross-domain contact-exchange composition is
      owned by this change rather than unowned.
- [ ] 7.6 **Campaign index currency.** Update this change's row and its campaign's
      dependency graph in `openspec/changes/README.md`.
- [ ] 7.7 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Accepted-state interpretation and the obligation drive sequence have one implementation | `openspec/specs/contact-exchange-settlement/spec.md` |
| A composing domain supplies persistence and configured values, not lifecycle logic | `openspec/specs/contact-exchange-settlement/spec.md` |
| Delivery is available across composing domains and remains non-authoritative | `openspec/specs/introduction-delivery/spec.md` |
| The seller's contact payload is resolved per listing origin, not per storefront | `openspec/specs/contact-exchange-settlement/spec.md` |
