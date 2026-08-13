# Design

## Grounding

Audited against `origin/dev` at `e91767a3b074b20168bbcb87a8418d8287e5f8a6`.

### The unfulfillable response

`negotiate_controller.py` returns 409 with `error`, `reason`, `listing_id`, and
a `hint`. `error` is the constant `offer_unfulfillable`. `reason` is
`OfferUnfulfillableError`'s message, raised at four sites in
`market_storefront/utils/sync_negotiation.py`:

| Site | Message | Stability |
|---|---|---|
| 243 | `f"resource_shape_not_negotiable: {mismatched}"` | prefix only |
| 560 | `f"listing_not_open (status={listing_status!r})"` | prefix only |
| 599 | `"no_floor_price"` | exact |
| 606 | `decision.reason or "rejected"` | depends on the policy |

The policy channel at 606 is where `no_matching_inventory` arrives —
`has_matching_inventory_guard` in `arkhai_vms/negotiation/policies.py` returns
`NegotiationDecision(action="reject", reason="no_matching_inventory")` when no
inventory row matches every required attribute. The same channel carries
`compute_duration_invalid:duration_seconds must be > 0` and
`missing_amount: buyer's escrow proposal has no fields.amount`, both
interpolated, and falls back to the bare string `rejected` when a policy rejects
without a reason.

Three consequences for the contract:

1. `no_matching_inventory` is exact today and stable only because one policy
   emits it as a literal. It is not a protocol constant.
2. Two reasons cannot be matched by equality at all.
3. A policy reject with no reason is indistinguishable from any other, because
   `rejected` carries no information.

The apicredits storefront raises from the same shape in its own
`sync_negotiation.py`, so this is a repository-wide pattern rather than a VM
quirk.

### The hold posture

`capacity.hold_ttl_seconds` defaults to `0`. `domains/vms/storefront/storefront.bob.toml`
sets `900` and says why in a comment: the local profile has no untrusted buyers,
and holding capacity is what keeps the two-phase reserve path under e2e
coverage, while production places no pre-settlement hold.

The dev cluster runs `ACTIVE_PROFILES=production,provisioning-secrets,mock`.

So a contention scenario has two correct answers depending on where it runs, and
which one is correct is not derivable from the product revision. This is not a
configuration detail the harness can normalise away: it changes which code path
a losing buyer takes.

### Seller topology

`storefront.alice.toml` documents the constraint in the repository:

> Shares Bob's provisioning service for now. The multi-registry test stops at
> negotiation start so we never hit settle/lease/watchdog — if Alice later needs
> to settle, this needs its own provisioning instance (the provisioning
> service's `PROVISIONING_STOREFRONT_URL` callback points at bob-storefront, not
> alice-storefront).

Both storefronts poll one provisioning service for capacity — the read path is
many-to-one. The fulfillment callback is 1:1. A second seller can be discovered,
can negotiate, and cannot fulfil.

## Decisions

### A refusal expectation carries a match mode, not a string

A scenario declares `status`, `error`, and a `reason` expectation that is one of
`exact`, `prefix`, or `any`. `exact` is permitted only for reasons the product
emits verbatim; the schema enumerates which those are, and validation refuses
`exact` against a known-interpolated prefix.

Rejected: matching on `error` alone. It collapses five distinct refusals into
one, and the contention scenarios exist precisely to distinguish "lost the race"
from "listing was closed" and "shape was not negotiable."

Rejected: regular expressions. They would express the interpolated cases, but
they invite scenarios that assert on the interpolated *content* — a mismatched
attribute list, a listing status repr — which is exactly the incidental detail a
deterministic contract should exclude. Prefix matching gets the discrimination
without the temptation.

Rejected: waiting for the product to close the vocabulary first. That is the
better end state and it is a product change with its own consumers; blocking the
contract on it would stall this work behind an unproposed change. The contract
is written so that closing the vocabulary later is a narrowing — `exact` becomes
permissible for more reasons — not a rewrite.

### A scenario declares the hold posture it assumes

`capacity_hold: held` or `capacity_hold: none`, required. Validation refuses a
scenario without it. Evaluating a result against a target whose posture differs
from the declaration is a contract violation, reported as an inadmissible
result, not as a failed expectation.

The distinction matters: an inadmissible result says the run was not the run the
scenario describes. A failed expectation says the product misbehaved. Recording
the first as the second would manufacture a defect out of a configuration
mismatch, and that is the most likely way this harness produces a false finding
in its first month.

Rejected: inferring the posture from the target at evaluation time. It removes
the declaration and with it the review: a scenario reviewed for one posture would
silently evaluate correctly under the other, and the reviewer would never have
seen which one they approved.

Rejected: one scenario per posture, doubling the set. The expectations differ in
one dimension; a declared field is the smaller and more reviewable
representation.

### A buyer must prove discovery before the barrier

Each buyer in a contention scenario carries a discovery receipt: it observed its
assigned listing, through the market it was assigned, before the arrival barrier
released. A result missing a receipt for any buyer is inadmissible.

The reason is in the fan-in client: reads across registries log per-registry
failures and continue, so a buyer whose registry was unreachable sees a smaller
union and finds nothing. Its failure is not scarcity, but at the point of
evaluation it looks like one.

Rejected: treating an empty discovery as an implicit environment failure. It is
the right classification and it cannot be made reliably after the fact — an
empty result and a suppressed registry error are the same observation from the
evaluator's side. The receipt moves the evidence to where it can still be
gathered.

### The finite set omits what the product cannot represent

Declared: a single-buyer qualification row, a controller-driven reference row,
the buyer-contention rows over one physical GPU, a fan-in completeness row, and
the fan-out multi-market contention rows.

Not declared: seller-process contention. A scenario asserting a global fence
across two storefronts would assert something the topology cannot exhibit.

Rejected: declaring those rows disabled. A disabled fixture is a claim that it
would pass if enabled, and this one would not — it would put a permanently red
row in the contract and invite someone to make it pass by changing the product
to suit the harness.

### "Seller service" is reinterpreted as the market a resource is listed on

The plan's contention rows require "several distinct seller services and
listings over one physical GPU" behind one global fence. Read as seller
*processes*, that is not buildable: one storefront serves one site, and the
provisioning callback binds to one storefront, so a second storefront can
negotiate and can never fulfil. That constraint is settled architecture, not an
omission.

Product authority approved reinterpreting "seller service" as the market a
resource is listed on — the storefront-to-registry layer — on the grounds that
it is what carries the anti-vendor-lock product claim. Approved 2026-08-13.

Registry and storefront are N:N in both directions: a registry indexes listings
from many storefronts, and a storefront publishes to many registries. The e2e
topology exercises both at once — registry A carries two sellers while one of
them fans out to A and B.

**This is a reinterpretation, not a clarification.** The original phrasing meant
seller processes; the archival fixtures encode it, naming scenarios
`b<buyers>-s<sellers>-g<gpus>`. Under the new reading `s` would silently change
referent, and a reader would take seller scaling as covered when it is not. The
declared fixtures therefore name the axis `m` for markets and leave `s` unused,
so the two readings cannot be confused by a filename.

**What the substitution no longer proves.** Not several independent sellers
competing for one resource. Not cross-storefront arbitration. Not per-seller
fulfillment isolation. A multi-market result must not be reported as evidence
about any of them.

### Two multi-market shapes, and only one is contention

They prove different things and collapsing them would let a discovery result be
read as evidence about the fence.

**Fan-out contention.** One storefront, one physical GPU, one listing broadcast
to N registries, buyers arriving through different registries on a common
barrier. Exactly one success; a declared refusal signature for the rest; and the
sold capacity withdrawn from every registry that carried it. This is a
contention row.

**Fan-in completeness.** One registry, N storefronts, separate resources. The
buyer's discovery union contains every listing and keeps them distinct. No
contention — the sellers are not competing for anything — so it belongs with the
qualification rows and declares no scarcity.

The withdrawal assertion in the fan-out row is the point of the row, not a
tidiness check. The fan-out client succeeds if at least one registry accepts a
publish, and raises on delete only if every registry fails — so a sold resource
that fails to withdraw from one market stays listed there while the call reports
success. That is a double-sell path in the claim being tested. Whether
reconciliation already closes it is the first thing the row should establish.

### Expected outcome cardinality depends on fairness policy, not only on hold posture

A contention row declares exactly one success and typed scarcity for the rest.
That cardinality is not a property of contention alone. It is what the product's
scheduling policy decides to do when several demands arrive for one scarce
resource, and "exactly one wins" is one possible policy rather than a law.

The product's fairness work is design-gated, and its inputs changed: negotiable
shapes and negotiation-time holds altered what contention means. So the scenario
contract is declaring an expected cardinality against a policy that has not been
settled, in the same way it would have been declaring an expected refusal
against a hold posture that had not been settled.

The hold posture got a declared field because a scenario is unevaluable without
it. Fairness is different in one respect and the same in another: different
because a scenario does not currently choose a fairness policy, the deployment
does; the same because a change to it makes a previously-correct expectation
wrong without anything in the scenario changing.

**Not resolved here, and not a blocker.** Fairness policy changing what "one
success and N scarcities" means is a reason to design the two together, not a
prerequisite to satisfy first. Recorded so that whoever settles the fairness
policy knows this contract depends on it, and so that a contention row failing
after a fairness change is recognised as a contract that needs revisiting rather
than a product defect.

## Open questions

### Should the product close the reason vocabulary?

A closed set of reason codes, with interpolated detail moved to a separate
field, would let scenarios assert exactly and would help the buyer CLI and the
e2e suite equally. It is a product change with consumers outside the harness and
belongs to whoever owns the negotiation protocol specification. Recorded here
because this contract is shaped around its absence.
