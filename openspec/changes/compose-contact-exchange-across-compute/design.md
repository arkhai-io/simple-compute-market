# Design — compose contact exchange across the compute family

## Context

Settlement by introduction already exists and works: rateless options, a
scalar-declining registration, one non-financial obligation, a durable
authenticated reveal, and a loose-listing discovery profile, composed end to end
on bare metal. The mechanism kit is domain-neutral by assertion — a
package-boundary test pins its permitted imports and explicitly excludes web
frameworks, HTTP clients, the Alkahest carriers, and Stripe.

The obstacle to a second domain is not the mechanism. It is that the glue binding
the mechanism to a domain's accepted state currently lives in one domain and is
mostly not about that domain.

## Goals / Non-Goals

**Goals.** One implementation of accepted-state interpretation. A second and third
composing domain. Delivery available wherever the mechanism composes.

**Non-Goals.** No change to the mechanism's registration, option shape, reveal
surface, or configuration. No persistence dependency in the mechanism kit. No
coupling to whether a listing is capacity-backed.

## Decisions

### Promote the glue rather than copy it

The bare-metal glue reads a negotiation thread, requires its terminal state to be
success, validates a settlement plan carrying exactly one obligation, checks the
obligation's mechanism, re-derives `obligation_ref` from the agreement and the
canonical obligation content and compares it against the requested one, then
drives register, materialize, bind, check, and collect.

Every one of those steps is a statement about the mechanism's own invariants, not
about bare metal. The `obligation_ref` re-derivation in particular is a security
check — it is what stops a caller from requesting a reveal against an obligation
that is not the one the plan accepted — and a security check with several
implementations is a security check with several behaviours.

Copying it into each domain was the alternative and is rejected on the
established rule that an extracted concern leaves no domain-local copy, and that
domains retain only the values and hooks that instantiate a kit mechanism.

### Persistence stays injected

The mechanism kit imports no persistence and its boundary test enforces that. The
promoted glue needs persistence, so it either lands somewhere that may hold a
persistence dependency, or it takes persistence through the callback contract the
reveal service already uses.

The second is preferred and is largely how the current glue is already shaped:
the reveal service takes prepare, authorize, persist, load, and complete
callbacks, and the domain supplies them. Promoting the *bodies* of prepare and
complete while leaving persistence injected keeps the kit boundary intact and
leaves the domain supplying values rather than logic.

Where the promoted bodies live is genuinely open — the mechanism kit cannot hold
them if they need persistence types, and a storefront-side kit is the obvious
alternative but should follow the composition seam that owns kit-side storefront
runtime rather than inventing a parallel home.

### Delivery follows composition

A reveal that only sits behind an authenticated read is a worse product than one
that reaches its owner, and the delivery contract already exists: a
mechanism-neutral event, a sink protocol, discovery, and protocol-thin built-ins,
with dispatch injected so the mechanism kit gained no delivery dependency.

Delivery remains non-authoritative. That property is load-bearing and worth
restating in every domain that gains it: best-effort delivery is safe precisely
because the durable, re-readable reveal is what the parties can always fall back
to, and re-delivery reads the durable reveal rather than reconstructing one, so a
re-send cannot invent contact data that was never exchanged.

### Composition is independent of backing

A capacity-backed listing may settle by introduction — a seller with real,
admittable inventory may still prefer to agree terms directly. An unbacked listing
may settle by another mechanism, which is exactly the anticipated next version of
that market.

Keeping the two independent is what makes both features composable rather than a
single special case, and it is why this change and `unbacked-listing-publication`
have no dependency in either direction. It is also why no pool-level or listing-level
field may name a settlement mechanism.

### One contact per origin

`ContactSettlementConfig.contact_payload` is a single value bound from storefront
configuration at acceptance. That is coherent at one seller per storefront and stops
being coherent the moment one storefront publishes for several seller sites — which
is exactly the shape the 1:N site-to-storefront work introduces, and which Goal 7's
own system coverage exercises with two seller sites behind one storefront.

A storefront-wide payload in that deployment does not degrade gracefully. It reveals
one seller's contact details for another seller's listing: a correctness failure that
discloses the wrong party's personal information, not a missing feature.

So the payload is resolved from the listing's origin. The origin site is already on
the durable listing binding and copied to the negotiation thread, so the input is
present at acceptance without a new lookup. A deployment with one origin resolves to
the value it configures today, which is what keeps this from being a breaking change
for existing operators.

The alternative was a release contract restricting introductions to one seller per
storefront. Rejected: it would make Goal 7's stated value — discovery and a
trustworthy introduction across sellers — untrue for the multi-seller case the goal
exists to serve, and the restriction would have to be enforced somewhere rather than
merely documented.

Making the payload resolvable is also the hook per-deal aliasing would need. That is
noted rather than built here; choosing an alias per deal is a separate decision from
knowing which seller's contact to reveal.

### Retention first

This change is gated on `contact-payload-retention` rather than coordinating with
it. The mechanism's specification requires payloads to be deletable as part of the
deal lifecycle; nothing implements deletion. Composing more widely before that
exists multiplies the number of deployments holding personal contact details
against an obligation satisfied only in principle, and the multiplication is the
whole point of this change.

## Risks / Trade-offs

- **[Promotion changes behaviour subtly]** → The glue's checks are security checks
  and a promotion that relaxes one would be hard to see. Mitigated by promoting
  the bodies unchanged first and composing a second domain only after the
  bare-metal path passes its existing coverage against the promoted
  implementation.
- **[The promoted home is wrong]** → Named as an open question rather than
  guessed. Landing it in the wrong place is recoverable; landing it in the
  mechanism kit and acquiring a persistence dependency there is much less so,
  because the boundary test is what currently makes the kit's neutrality
  checkable.
- **[Delivery multiplies configured sinks]** → Each composing domain's operator
  configures their own sinks, and each sink is a place a contact payload comes to
  rest outside the storefront's retention control. This is the reason retention
  disclosure is scoped to storefront retention rather than stated absolutely.

## Open questions

- **Where does the promoted glue live?** Constrained by the mechanism kit's
  package boundary and by the composition seam that owns kit-side storefront
  runtime. Deferred; no task places it.
- **Which compute-family domains compose it in this change?** Composing all of
  them at once maximises the duplication avoided and the blast radius; composing
  one proves the promotion with less. Deferred to planning rather than decided
  here.

## Migration Plan

1. Promote the glue with persistence injected; bare metal composes the promoted
   implementation and its existing coverage passes unchanged.
2. Compose the next domain.
3. Extend delivery to it.

Purely additive for existing deals: accepted plans, obligation records, and
revealed introductions are untouched, and the reveal surface's wire shape does not
change.
