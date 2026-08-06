## Why

POOLS-7 Section 11.2 fixed `most_available`'s claim-blindness bug (a
site with abundant capacity in the wrong pool could outrank a site that
actually matched a claim) by injecting an exact `ClaimMatcher` for
domains whose backing site needs full claim semantics. Landing that fix
surfaced three related, larger design questions that were deliberately
kept out of Section 11's scope (a schema-retirement change, not a new
capability), and their answers were designed during Section 11's review
but never implemented:

1. The VM claim's `resource_type: "compute.gpu"` conflates three
   different concepts (what the buyer is purchasing, what shape of
   resource they're requesting, and how the site internally represents
   inventory) under one field.
2. `dimensions` currently mixes quantitative fields (matched by
   sufficiency) with, in a rejected proposal, categorical fields
   (matched by equality) — the review correctly identified that this
   breaks the one clean invariant `dimensions` has today.
3. Claim-shaped vocabulary is inconsistent across the codebase:
   `required_attributes` (VM job-spec construction) holds an entire
   claim, not just attributes; `dimensions` sometimes means quantitative
   fields and sometimes appears as a section title for a different
   concept entirely; `capacity.probe(claim=...)` and a hypothetical
   `capacity.probe(requirement=...)` describe the same thing with
   different words in different places.

This change documents the accepted direction for all three and scopes
the work needed to implement it, without pretending it belongs inside
POOLS-7's already-closing Section 11.

## Origin

This proposal's design decisions were reached during POOLS-7 Section
11's code review (2026-07-30), recorded in that change's `design.md`
under "Section 11 code-review amendment and planning decisions" and
`tasks.md`'s note on 11.2. That record remains the discussion transcript;
this proposal is the durable, standalone specification of what to build
from it. Section 11 itself implements none of this — it only adds the
injection seam (`ClaimMatcher`, `dict_resource_satisfies_claim`) that
this change's structured requirement shape will eventually be translated
into, at the domain layer, before reaching that seam.

## What Changes

### 1. A structured, buyer-facing `requirements` shape

Replace the flat, ambiguous claim shape with an explicit, nested
requirement structure grouped by resource family:

```json
{
    "offering_type": "vm",
    "requirements": {
        "cpu": {"count": 8},
        "memory": {"gib": 32},
        "gpu": {"count": 1, "model": "A100"},
        "storage": {"gib": 200}
    }
}
```

Each leaf's matching semantics (quantitative sufficiency vs. categorical
equality) is defined by the domain-owned schema for that family, not
inferred generically by the matcher — `gpu.count` is quantitative,
`gpu.model` is categorical, and nothing in the wire shape itself has to
say so. The **generic matching contract underneath does not change**:
this structured shape is parsed, at the domain layer (mirroring where
`compute_capacity_claim_from_order` already lives today), into the
existing flat `dimensions`/`attributes`/`resource_type` split
`kit/site`'s `resource_satisfies_requirement` already implements
correctly. The matcher stays generic at the structural level; it never
needs to learn that `gpu.model` is different from `gpu.count`.

**Symmetric with the resource/inventory side (decided 2026-08-04, see
`design.md`):** a site's own resource capability description adopts the
same family-grouped shape, flattened into `dimensions`/`attributes` by
the same shared utility that flattens `requirements` — not a
requirement-only shape with the resource side left independently flat.
Investigated first, not assumed: the resource side has no flattening
step at all today (`dict_resource_satisfies_claim` reads a wire
snapshot's `attributes` unmodified), so this closes that gap rather
than only mirroring it cosmetically.

### 2. Separate `offering_type` from `resource_type`

Introduce `offering_type` (candidate names considered:
`offering_type`, `fulfillment_type`, `market_type` — `offering_type`
is preferred, see Alternatives) as the buyer-facing concept of *what is
being purchased* (`vm`, `bare-metal`, `pod`, `api_credits`), distinct
from `resource_type` (the existing site-inventory-adapter discriminator,
e.g. `compute.gpu`, that `kit/site`'s admission logic already checks).
`resource_type` keeps its current meaning and scope unchanged — POOLS-7
Section 11.2 already uses it correctly, at the site-inventory layer, and
nothing here requires touching that.

Whether `offering_type` needs to appear on the wire at all depends on
routing: today, every storefront only ever talks to site authorities
within its own domain (VM's storefront never reaches a bare-metal site),
so the domain boundary itself already establishes the type, and
`offering_type` may not need to be a real claim field until a shared,
cross-domain capacity endpoint exists. This change should confirm that
architecture is still true before deciding whether to add the field
now or defer it further.

### 3. Canonical requirement/claim vocabulary

Adopt consistent naming repository-wide:

| Term | Meaning |
|---|---|
| `ResourceRequirement` | The complete, structured buyer constraint set (see §1) |
| `CapacityClaim` | A request to `probe`/`reserve` capacity satisfying a `ResourceRequirement` |
| `CapacityReservation` | The authoritative hold or commitment (existing, unchanged) |
| `dimensions` | Quantitative-only, sufficiency-matched (existing, unchanged meaning) |
| `attributes` | Categorical-only, equality-matched (existing, unchanged meaning) |

This is a two-speed migration:

- **Free, no wire/schema change:** rename purely local variables (e.g.
  `vm_job_spec_service.py`'s `required_attributes` local, already
  renamed to `capacity_claim` in POOLS-7 Section 11.7.5) as they're
  touched.
- **Not free, real compatibility surface:** the serialized/persisted
  `"required_attributes"` dict key. Traced its full blast radius during
  Section 11: the admin API's request/response bodies
  (`admin_controller.py`, `admin_settle_service.py`),
  `fulfillment_resume_runtime.py`'s **durable resume context**
  (persisted across restarts, not just in-memory), and
  `core/storefront-client`'s external client library. Renaming the wire
  key needs the staged approach below, not a single-PR rename.

## Non-Goals

- Do not change `kit/site`'s admission semantics, `resource_satisfies_requirement`,
  or the `dimensions`/`attributes` split those already implement correctly.
- Do not touch `resource_type`'s existing meaning or its POOLS-7 Section
  11.2 usage.
- Do not require every domain to adopt `offering_type` if routing already
  makes it redundant — decide this explicitly during design, not by
  default inclusion.
- Do not rename the persisted `"required_attributes"` wire key without a
  compatibility plan covering every consumer named above.
- Do not touch API-credit issuance/rollback durability (idempotency,
  partial-failure recovery, compensation guarantees) — that is a
  separate, unrelated deferred item from POOLS-7 Section 11 review and
  belongs in its own change if picked up.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — new/updated vocabulary section
      if `ResourceRequirement`/`CapacityClaim` become repository-wide terms
- [ ] `openspec/specs/site-capacity/spec.md` — the matching contract, if
      the structured `requirements` shape becomes the wire-level claim
      format `probe`/`reserve` accept
- [ ] New subsystem specification — none anticipated; this is vocabulary
      and shape, not a new capability
- [ ] No permanent documentation change — not applicable, this change is
      documentation-and-vocabulary-shaped by nature

### Knowledge to promote (once designed and implemented)

- The `dimensions`/`attributes` split's invariant (quantitative vs.
  categorical) and why a structured `requirements` shape doesn't
  weaken it — `openspec/specs/site-capacity/architecture.md`
- `resource_type` vs. `offering_type`'s distinct scopes — `docs/development/ARCHITECTURE.md`'s
  vocabulary table, `openspec/specs/site-capacity/spec.md`

## Dependencies and Related Changes

- Builds on POOLS-7 Section 11.2's `ClaimMatcher`/`dict_resource_satisfies_claim`
  injection seam — this change's structured shape gets parsed into that
  existing contract, not around it.
- `pools-8-capacity-projection-and-listing-hints` also touches claim
  construction (mapping projected resource identity into reservation
  claims) — coordinated (2026-08-04, see `design.md`'s symmetric-nesting
  decision): the resource/inventory side adopts this change's shape too,
  flattened by the same shared utility, rather than the two changes
  defining independent shapes. POOLS-8's own inventory work landing
  before this change is implemented (e.g. projecting GPU model) uses the
  already-flattened form (`attributes["gpu_model"]`), forward-compatible
  with this change's eventual nested shape without needing migration.
- A second, later coordination point with the same change, on the
  config/pricing side rather than the wire/inventory side (2026-08-05,
  see `design.md`): `pools-8`'s storefront pricing config
  (`[pricing.defaults.gpu.<model>]`) proactively adopted this change's
  family-grouped vocabulary for the `gpu` family alone. Extending that
  pricing config beyond `gpu` needs this change's own vocabulary to have
  landed and stabilized first — check `pools-8`'s pricing config as a
  second precedent for the family-grouped convention when finalizing
  this change's own shape, not a separate thing to reconcile after.
- Independent of `remove-relative-uv-sources` and Section 11's API-credit
  wheel-isolation work — no overlap.

## Impact

Touches the VM claim builder (`vm_job_spec_service.py`), `kit/site`'s
public matching contract if the wire shape changes, `core_storefront`'s
`CapacityClient` protocol surface if `probe`/`reserve` gain a
`requirement=` parameter alongside or instead of `claim=`, and — only if
the persisted `"required_attributes"` key is renamed — the admin API,
resume-context persistence, and `core/storefront-client`. Scope for the
wire-key rename specifically should be confirmed small before starting;
everything else is additive/parsing-layer work. **Expanded (2026-08-04)
by the symmetric-nesting decision:** also touches wherever a site's own
resource/inventory capability description is produced and consumed —
`kit/site`'s resource-pool projection shape and the shared flattening
utility's other call site, likely provisioning-service-side inventory
projection (`capacity_inventory.py` and siblings) once this change
reaches implementation.
