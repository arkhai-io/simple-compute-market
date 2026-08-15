# Arkhai Market Stack — Directional Roadmap

> **Purpose:** The goals currently being pursued, the value each delivers, what is true today, and which OpenSpec change owns each open gap. This document carries no readiness status, no delivery sequencing, no acceptance criteria, and no implementation tasks — those belong to the changes themselves and to [`openspec/changes/README.md`](../../openspec/changes/README.md).

## How this document relates to the others

Three cross-cutting documents divide the work between them. Each answers a different question and changes at a different rate.

| Document | Answers | Corrected when |
|---|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | What is the system, and why do its boundaries exist? | The system changes |
| `ROADMAP.md` (this document) | Which goals are being pursued, and why? | A goal's truth changes |
| [`openspec/changes/README.md`](../../openspec/changes/README.md) | What can I start, and what is it blocked on? | Changes start, block, and finish |

To find out whether work on a goal is ready, blocked, or deferred, follow the change link and read the active-change index. This document deliberately does not say.

Each goal below carries a present-tense **current state** grounded in the code as it is, and a table of **open gaps** with the change that owns each. When a change completes, its row leaves the table and the result is absorbed into the current-state prose — so this document shows where things stand, not a history of how they got there. Progress is visible in the current-state paragraphs growing and the gap tables shrinking.

A gap identified without an owning change does not become a standing entry here; an OpenSpec change is opened for it and linked. Where a goal has known work that no change yet owns, the current-state section says so plainly rather than the gap table implying coverage that does not exist.

When every gap for a goal closes, the goal is removed. Its durable result is by then in `ARCHITECTURE.md` or the owning capability's specification through the ordinary promotion path, and the record of the work is in Git history and the archived changes.

---

## Goal 1 — Consolidate physical-resource authority in the provisioning service

**Value.** One authority for physical state removes a whole class of divergence bugs, and — less obviously but more consequentially — it is what makes the storefront substitutable. A storefront that owns hardware inventory cannot become a multi-domain storefront (Goal 3), cannot be replaced by a different commercial front-end over the same hardware, and forces every seller to maintain the same facts in two places. It also shrinks the seller's operational surface: hardware inventory stops being something an operator imports into a commercial service.

The boundary this goal draws is between *physical* and *commercial* authority, not between the two services generally. Per [`ARCHITECTURE.md`'s authority boundaries](ARCHITECTURE.md#authority-boundaries), pricing, seller policy, and listing state are correctly storefront-owned. The goal is that the storefront holds no physical authority — not that it holds no per-pool records.

**Current state.** The provisioning service is authoritative for hosts, resource pools, capacity admission, scheduling, and the fulfillment lifecycle. Storefronts consume physical facts through the site resource-pool and capacity-bucket projections, and projection-backed listing derivation is the default path. The bare-metal storefront is fully projection-native and holds no local physical tables at all.

The VM storefront still holds physical state the projection has superseded. It retains `resources`, `hosts`, `compute_pool_members`, and `resource_transition_events`, a local-table listing-derivation path behind a configuration flag, and CSV import as the operator path for seeding inventory — including a startup seeding step and Helm and compose wiring, so retiring it is an operator-facing contract change rather than only a code deletion. It also retains surfaces whose callers are already gone: `compute_allocations`, an execution ledger that `kit/site`'s `CapacityReservation` supersedes and that no production code writes to; admin endpoints for reading and patching resource state whose documented caller no longer makes that call; and a physical-host identifier threaded across the storefront-to-provisioning boundary that the capacity boundary strips, so it is always absent.

Capacity declaration is the one place the provisioning service is not yet the fuller authority. Host inventory carries GPU count and model only, so the projection's host-derived fallback cannot express vCPU, RAM, or disk. The retiring storefront CSV has been the system's only operator-facing expression of multi-dimensional capacity — which is why capacity administration is a prerequisite of the retirement rather than a parallel improvement.

| Open gap | Owned by |
|---|---|
| Sellable capacity has no authoritative multi-dimensional declaration or operator path in the provisioning service | [`capacity-resource-administration`](../../openspec/changes/capacity-resource-administration/) |
| The VM storefront retains local physical tables, the local-table derivation path, CSV import and its deployment contract, the dead execution ledger, the orphaned physical admin surface, and dead physical-identity plumbing | [`pools-9-retire-local-physical-authority`](../../openspec/changes/pools-9-retire-local-physical-authority/) |
| Stale physical-placement fields on the current fulfillment path, and VM shape not reaching the provisioning request | [`fix-vm-fulfillment-capacity-boundary`](../../openspec/changes/fix-vm-fulfillment-capacity-boundary/) |

A schema drop of the frozen columns is deliberately excluded from the retirement and belongs to a later follow-up, after a deployment cycle confirms the freeze never needed rolling back.

---

## Goal 2 — Negotiate full compute capability, not GPU count alone

**Value.** This is the difference between a market that sells fixed SKUs and one that sells capacity. Hardware is heterogeneous and buyer requirements are multi-dimensional; negotiating on GPU count alone forces sellers to pre-partition inventory into fixed shapes and forces buyers to over-buy on every dimension they did not need. Supporting the full shape raises fill rate and utilization revenue on hardware the seller already owns.

**Current state.** The lower layers already carry the full shape. The VM domain defines canonical dimensions for GPU count, vCPU count, RAM, and disk; the site authority admits and matches multidimensionally; scheduling fit-checks every requested dimension and treats the dimensions actually scheduled as authoritative; capacity reservations can be resized by supersede rather than mutation; and the Ansible playbooks create VMs with variable shapes.

The top of the stack does not. A buyer that names a resource shape disagreeing with the listing's own shape is rejected outright at negotiation round zero, deliberately and loudly, because seller policy has no way to price an alternative shape. Rounds after the first carry only price and escrow terms, with no field for a shape change. Reservation resizing is implemented and has no caller anywhere in the repository.

Publication is where the shape is first lost. A listing's `offer_resource` carries GPU model, count, SLA, region, and pool identity only — vCPU, RAM, and disk are never published, though the projection's capacity map reaches the storefront and the listing model declares all three as optional fields. Because the registry's dimension filters fail closed on a missing field, a buyer filtering on RAM matches nothing at all today, despite the registry schema and buyer CLI both supporting it.

Pricing is the binding constraint on negotiating the shape. Commercial resolution produces a single price per GPU model through a three-tier chain of storefront override, pool hint, and configured default; rates scale by duration only. Negotiation carries exactly one degree of freedom, a scalar amount moved by the concession middleware, so no seller policy can evaluate a counter-offer that changes RAM or disk — which is why a buyer naming any shape is rejected at round zero, deliberately and with the reason recorded in the guard itself. The seller's own feasibility check compares region and GPU model by equality and no quantitative dimension. Nothing consults the authoritative site until a hold is placed at terms acceptance, so an unservable shape surfaces after both parties have committed.

| Open gap | Owned by |
|---|---|
| Listings advertise a GPU-only shape, so the registry's existing dimension filters match nothing | [`publish-multidimensional-listing-shape`](../../openspec/changes/publish-multidimensional-listing-shape/) |
| No seller can price a shape other than the one advertised, and negotiation has one degree of freedom where two are needed | [`capacity-shape-pricing`](../../openspec/changes/capacity-shape-pricing/) |
| Nothing expresses which shapes a seller will consider, or what range remains admissible for one dimension given the rest | [`capacity-shape-envelope`](../../openspec/changes/capacity-shape-envelope/) |
| The authoritative site is not consulted until terms are already agreed, so an unservable shape fails after both parties commit | [`negotiation-capacity-feasibility-probe`](../../openspec/changes/negotiation-capacity-feasibility-probe/) |
| Buyer-facing requirement shape is flat and ambiguous; `offering_type` is conflated with the site-inventory `resource_type` discriminator; claim vocabulary is inconsistent across the codebase | [`structured-capacity-requirements`](../../openspec/changes/structured-capacity-requirements/) |
| No negotiation round after the first can express a shape change, and reservation resizing has no caller | [`negotiation-driven-capacity-resize`](../../openspec/changes/negotiation-driven-capacity-resize/) |
| The accepted VM shape does not reach the provisioning request, so a GPU-reserving listing can fulfill without a GPU | [`fix-vm-fulfillment-capacity-boundary`](../../openspec/changes/fix-vm-fulfillment-capacity-boundary/) |
| Buyer-negotiated VM connectivity terms, currently operator-configured only | [`add-buyer-vm-connectivity-terms`](../../openspec/changes/add-buyer-vm-connectivity-terms/) |

`negotiation-capacity-feasibility-probe` is a shared prerequisite rather than exclusively this goal's: charging for a held reservation also requires a buyer to learn feasibility before any hold, and therefore any charge, exists. Not every change belongs to a roadmap goal, and this one is listed here because this goal consumes it, not because it is owned by it.

---

## Goal 3 — One storefront serving several compute-family domains

**Value.** This decouples *how hardware is sold* from *how hardware is partitioned*. Today the listing form factor is a deployment boundary, so a site owner must physically dedicate hosts to VMs rather than bare metal rather than pods. Removing that lets one pool of hardware be offered concurrently as several form factors, priced independently, with the site authority arbitrating exclusivity between them — higher utilization and better price discovery without buying more hardware.

**Current state.** The common storefront shell now discovers installed domain
contributions, applies explicit public registrations, and freezes an exact
mode/domain/version registry. VM and bare-metal publication sources can share
one process. Listings, negotiation threads, and fulfillment contexts carry
immutable domain, offering-mode, selected-site, and provenance bindings;
negotiation, settlement, fulfillment, result recovery, and teardown route from
those records rather than payload guessing, installed order, or a VM default.
Existing single-domain VM databases enter this schema only through the
explicit, preview-first, backed-up transactional migration.

Resource Pools already declare exact deliverable offering modes. Capacity
claims carry that mode through reservation, scheduling, and provider dispatch,
and accepted records retain it when publication changes. The shared
storefront-to-site clients pin mapped work to one trusted authority with no
cross-site fallback. The registry catalogue can now receive the public
`offer_resource.virtualization_type` projected from the frozen binding.

Goal 3's shared storefront boundary is therefore implemented and promoted.
Complete product acceptance still depends on the domain producers and topology
proof below; the shell deliberately does not fake their missing behavior.

| Open gap | Owned by |
|---|---|
| Bare metal has no runnable buyer package or admitted registry identity | [`bare-metal-buyer-domain`](../../openspec/changes/bare-metal-buyer-domain/) |
| The bare-metal seller contribution still owes its real selected-site fulfillment/result/teardown hook | [`market-platform-bare-metal-10-storefront-composition`](../../openspec/changes/market-platform-bare-metal-10-storefront-composition/) |
| One-process VM/bare-metal behavior across more than one authority needs live selected-authority, cross-mode, executor, teardown, and capacity-restoration evidence | [`market-platform-compute-40-multi-domain-proof`](../../openspec/changes/market-platform-compute-40-multi-domain-proof/) |

---

## Goal 4 — Make a domain a composition of kit

**Value.** The architecture's layering is core for what applies to every domain, kit for composable functionality many domains share, and the domain layer for instantiating and configuring kit. The storefront role does not follow it, so the marginal cost of a market domain is roughly three thousand lines of negotiation, settlement, capacity, publication, and failure-handling machinery that is identical in every domain but its codecs.

That cost is why bare metal has been a storefront skeleton and why API credits carries a full parallel copy of eight VM services. It compounds: every defect fixed in one copy stays live in the other, and every new cross-cutting capability — billable holds, shape-aware pricing, feasibility verification — must be built once per domain or silently skip the domains that lack it. A capability that reads as "the market does X" is often really "the VM market does X."

Extracting that machinery into kit changes what adding a domain means. A Kubernetes-pod domain, an inference-token domain, or a model-training domain becomes codecs, a contract, and configuration rather than a fork of the VM storefront. The two domains delivered here are both the beneficiaries and the proof: bare metal because it has none of the machinery, API credits because it has a complete parallel copy, so composing them exercises both directions.

**Current state.** Kit's layering discipline now includes `kit/storefront`,
`kit/negotiation-runtime`, `kit/settlement-runtime`, and
`kit/capacity-publication`. The storefront kit owns application/lifespan
assembly, container construction, route and middleware contribution, Alkahest
client construction, and the stale-negotiation watchdog; VM and API-credit
storefronts contribute their domain routes and timing, while bare metal
composes the shared watchdog and chain factory.

The negotiation kit owns signed round ordering, canonical-principal and
terminal-state guards, durable transcript recovery, and the acceptance
chokepoint. VM and API-credit storefronts inject their listing resolution,
codecs, seller policy, configuration, accepted-artifact construction, and
persistence/effect hooks, so neither retains a lifecycle copy. The settlement
kit owns one stable per-obligation operation journal, conditional-escrow client
port, servicing worker, and failure dispatcher.

The capacity/publication kit owns exact site projections, event-driven
reconciliation, registry fan-out, publication result recording, and
close/reopen mechanics over injected schema-opaque candidate and binding hooks.
VM and API-credit storefronts compose those runtimes rather than maintaining
local copies; pool-declared offering mode and persisted selected-site binding
remain authoritative through publication and recovery. Bare metal consumes the
same seams without a domain-specific fallback, but truthfully remains
fulfillment-unavailable. `kit/policy`, `kit/identity`, `kit/fulfillment`,
`kit/config`, and `kit/alkahest` likewise carry no domain vocabulary.

The remaining Goal 4 work is deployable multi-domain adoption and end-to-end
deal proof rather than another domain-local copy of these extracted
lifecycles.

Settlement assigns stable identity to every accepted-plan obligation, journals
materialize/status/check/collect/reclaim attempts, persists opaque mechanism
state across retry, preserves partial outcomes, and supports directional
interval payments and seller penalty bonds. VM and API-credit roots use this
runtime for exact verified-obligation adoption, fulfillment binding, and
collection. Their connection details, credentials, capacity repair, refund,
and issuance rollback remain at their real domain boundaries rather than
becoming generic settlement state.

API credits now composes hosted Stripe and Alkahest over the shared buyer transport, storefront route service, settlement runtime, credits authority, and portable evidence boundary. Its hosted-only Ed25519 path is locally implementable and packageable without a wallet or chain; provider-authentic acceptance remains external until the exact signed hosted release, protected Stripe inputs, and deployed resolver are available. Bare-metal release evidence remains separately dependent on its live selected-site provisioning prerequisites.

The domain layer's own structure is better than the duplication suggests. All three domains follow one pattern — a base contract with a storefront-side extension — and all three pass the shared conformance suite, which works without assuming a repository layout. Only the directory conventions differ, and a composed domain is small enough that relocating them buys nothing.

**Completion test.** Bare metal and API credits each run a full deal through a composed storefront, with no domain-local copy of an extracted concern.

| Open gap | Owned by |
|---|---|
| Provider-authentic API-credit hosted evidence still requires the exact signed producer release, protected Stripe inputs, and deployed resolver; bare-metal still requires live selected-site provisioning and access/teardown proof | [`add-api-credits-hosted-settlement`](../../openspec/changes/add-api-credits-hosted-settlement/), [`add-bare-metal-hosted-settlement`](../../openspec/changes/add-bare-metal-hosted-settlement/) |

**Design promotion (2026-08-15).** `kit-storefront-composition-seam`,
`kit-owned-negotiation-runtime`, and `kit-owned-capacity-and-publication` are now
implemented by `kit/storefront`, `kit/negotiation-runtime`, and
`kit/capacity-publication` and recorded permanently in the market composition,
negotiation, and storefront-publication specifications and architecture. VM and
API credits preserve their one-domain route and timing behavior through
explicit storefront contributions, inject domain hooks into the shared
negotiation lifecycle, and use the shared durable capacity/publication binding;
bare metal composes the previously missing watchdog and chain factory and the
same capacity seams. The remaining multi-domain, domain-stack, and hosted
settlement adoption gaps build on these seams rather than reopening them.

**Design promotion (2026-08-15, API-credit hosted adoption).** API credits now
publishes independent mechanism-neutral options, uses the core hosted buyer
transport and shared callback-driven storefront route service, derives one
canonical principal-bound fulfillment/grant identity, and orders authoritative
funding before exact-once issuance, signed portable evidence, condition
evaluation, and collection. Credits-service request-digest grants and
storefront private-result/evidence migrations make acknowledgement loss,
restart, collection/reclaim races, and secret separation durable. These
decisions are promoted to the API credits, buyer orchestration, storefront
publication, market composition, settlement servicing, deployment state, and
test compatibility specifications and repository architecture/deployment/test
guides. Remaining signed-producer, protected Stripe, and live resolver evidence
is recorded as external rather than replaced with local simulation.

A compute-dimension name leaking into every domain's capacity declaration is a real defect but too small to own a gap row here; it rides with [`capacity-resource-administration`](../../openspec/changes/capacity-resource-administration/), which already rewrites the code that causes it.

---|---|
| Executor identity falls back implicitly to VM where durable identity is absent, which a growing set of executor kinds cannot tolerate | [`market-platform-compute-40-multi-domain-proof`](../../openspec/changes/market-platform-compute-40-multi-domain-proof/) |

---

## Goal 5 — Make capacity exclusivity compensated

**Value.** A capacity hold is exclusion: while one buyer holds capacity, no other buyer can have it. Today acquiring that exclusion costs two signed HTTP requests and nothing else — no funds, no chain interaction, and no limit on how many a single actor may hold. One adversary can therefore hold a storefront's entire sellable inventory indefinitely, at no cost, denying every legitimate buyer. Shortening the hold window does not fix this; it only raises the request rate the attacker needs.

Pricing held time closes that vector structurally rather than defensively. Cost scales with capacity-time held, so minting identities buys an attacker nothing and no rate limit has to punish a buyer who genuinely wants a lot of capacity. It is the only mechanism that stops the attack without also constraining the customer.

Having closed it, the same mechanism unlocks what the market cannot currently afford to do. Holding capacity earlier — failing a deal at reservation rather than after payment, letting a buyer negotiate seriously over specific hardware, closing the race between two buyers wanting the same machine — is unaffordable today precisely because exclusivity is free. Once it is paid for, capacity can be held for as long as someone is willing to pay, which is the precondition for early reservation and eventually for forward reservation of future capacity windows. A pool whose holds are expensive also becomes a visible scarcity signal before any deal settles.

**Current state.** The vector is closed by denying the capability: both storefronts now ship `capacity.hold_ttl_seconds = 0`, so no capacity is held before the buyer's escrow settles and exclusivity arises only from a settled deal. The two-phase reserve implementation remains and is exercised by local end-to-end profiles that deliberately override the default. The cost of that posture is a reopened race — a buyer whose escrow settles may find the capacity taken and need a refund — which is accepted as a bounded, recoverable failure against an unbounded one.

Nothing else about a hold has changed. A reservation carries no rate, no funding reference, and no price; its duration comes from configuration capped by pool policy rather than from anything the holder committed. Held time is never charged and an early release returns nothing, because there is nothing to return. Hold placement during negotiation bypasses the reservation ledger's idempotency guard entirely, since that guard keys on a settlement identity that does not yet exist, so a retried placement mints a second reservation. Expiry loads every outstanding held reservation on every ledger operation and compares timestamps in application code, and terminal reservations are never pruned — both tolerable only because the population is currently small.

| Open gap | Owned by |
|---|---|
| Holds bypass reservation idempotency; expiry scans all held rows on every operation; terminal reservations accumulate without bound | [`capacity-reservation-lifecycle-hardening`](../../openspec/changes/capacity-reservation-lifecycle-hardening/) |
| Holding capacity is free, so exclusivity cannot be granted before payment without exposing the denial vector | [`billable-capacity-reservations`](../../openspec/changes/billable-capacity-reservations/) |
| Capacity is not held while a buyer is negotiating for it, so two buyers can negotiate the same capacity to completion | [`negotiation-time-capacity-hold`](../../openspec/changes/negotiation-time-capacity-hold/) |
| The shipped default granted unfunded exclusivity, and framed the safe value as a performance trade | [`default-no-pre-settlement-capacity-hold`](../../openspec/changes/default-no-pre-settlement-capacity-hold/) |

Restoring a non-zero hold default is `billable-capacity-reservations`' own work: the posture above is a denial of capability that this goal exists to buy back.

---

## Goal 6 — Make the settlement mechanism a composed choice

**Value.** Escrow is one way to close a deal, not the definition of one. The hosted-fiat work proved a second mechanism can compose from kit; the next mechanism class is introduction-only settlement — a large share of real capacity trade is arranged person-to-person, with commercial terms too exotic to parametrize, where the marketplace's value is discovery, negotiation, and a trustworthy introduction rather than payment custody or provisioning. Finishing mechanism neutrality also changes the marginal cost of every future mechanism: a registration and a config section instead of a conditional arm in every domain.

**Current state.** Settlement mechanisms are composed registrations: `kit/settlement-runtime` owns the registration surface, configuration hierarchy, readiness, publication options, buyer compatibility, and the obligation servicing lifecycle; `alkahest.v1` and `fiat.stripe.v1` both plug in through kit-side factories named only in domain composition roots. The registry accepts option-only listings, a mechanism-neutral durable identity (`obligation_ref`) exists with its own signed route family, and buyer and seller can complete a deal with no wallet or chain resources at all.

Mechanism awareness still leaks at the edges. Every pre-terms decision point — proposal interpretation, accepted-artifact construction, settle-route selection — re-implements the same selection-versus-Alkahest conditional per domain, so a third mechanism needs a third arm in each. The scalar-amount negotiation path is mandatory for every mechanism, so take-it-or-leave-it terms are not expressible. Deal identity is dual rather than neutral: Alkahest deals still live only in the `escrows` table behind the escrow-uid route family. The Alkahest-shaped carriers remain core-owned with a handful of residual consumers, discovery filters project only `accepted_escrows`, and a few mechanism literals are hard-coded outside composition roots. Separately, no mechanism completes a deal by introduction: the accepted plan's `service_terms` are durably persisted, but per-round free text is not, and the only reveal-shaped surface — the hosted transient action — is deliberately not re-readable, while an introduction must be.

| Open gap | Owned by |
|---|---|
| Pre-terms mechanism dispatch, scalar participation, deal-identity convergence, Alkahest vocabulary ownership, option-aware discovery filters, and residual mechanism literals | [`finish-settlement-mechanism-neutrality`](../../openspec/changes/finish-settlement-mechanism-neutrality/) |
| No mechanism completes a deal by introduction; no durable, authenticated contact-reveal surface; no loose-listing discovery profile | [`contact-exchange-settlement-mechanism`](../../openspec/changes/contact-exchange-settlement-mechanism/) |

---

## Buyer identity lifecycle status

Buyer marketplace identity is now a core-owned durable profile rather than
repeated domain-local `[Identity]` configuration. The XDG profile store keeps a
stable random UUID, canonical principal history, redacted credential-provider
references, lifecycle/selection, and opaque authority bindings. Fresh VM and
API-credit work uses the selected primary; version-3 run recovery resolves the
recorded retained principal. Installed buyer plugins must declare the shared
resolved-identity injection contract.

The implemented change mapping is
[`add-persistent-buyer-profiles`](../../openspec/changes/add-persistent-buyer-profiles/).
Remaining external operational evidence belongs to that change's unchecked
verification tasks; it does not restore legacy identity precedence.

---

## Hosted settlement release status

The common VM consumer supports exact hosted funding profiles `card.v1`,
`us_bank_transfer.v1`, and `us_ach_debit.v1` through the released
provider-neutral client. VM publication keeps ready profiles as distinct
options; the persistent buyer profile owns its opaque authority/environment
payer binding; exact post-acceptance purchase authorization is direct; escrow
materialization, status, fulfillment, collection, and reclaim remain
storefront-mediated through the shared settlement runtime. Historical
card-only accepted state is recovery-only, and Alkahest remains an independent
mechanism lane.

The independently signed hosted `v0.2.1` producer release, manifest, client
wheel, service image, API/schema/conformance artifacts, SBOM/provenance,
repository/workflow identity, and source commit have been verified. Production
activation still requires role-scoped credentials and readiness for each
selected Stripe account, rail, instrument or mandate, browser action, webhook,
and condition resolver; local provider fixtures cannot establish those claims.

The protected three-profile provider matrix is not complete. Three signed card
runs reached the real ready connected account and verified loopback webhook,
then reported `payer_profile_unavailable`. That diagnostic means the protected
marketplace lifecycle subprocess exited while constructing the buyer-side payer
fixture—loading the ephemeral durable buyer profile, creating or reusing the
authority-scoped hosted payer profile through the released client, and
persisting its opaque binding—before it returned a successful fixture result.
It is not a Stripe funding decline and no payment was attempted. The current
sanitized report intentionally discards child stderr, so it does not yet
distinguish profile-store/signing/configuration failure from a released-client
or hosted-authority rejection. The next qualification work is to add an
allowlisted stage-specific initialization diagnostic, rerun one interactive
card collection lane to identify and correct the exact prerequisite, then run
saved-card/off-session fallback, bank-transfer, ACH success/failure/return,
collection/reclaim, restart, and loss cases.

API-credit and bare-metal are separate adopters of the shared hosted transport,
route service, configuration registry, and settlement runtime; neither imports
VM lifecycle code. Bare metal ships an installed buyer contribution, dedicated
seller composition, trusted selected-site publication, funding-gated Capacity
Reservation and fulfillment, portable lease-ready evidence, and independent
teardown/recovery. One release-qualified `us_bank_transfer.v1` whole-host lane
has proved authoritative Stripe funding and collection, portable condition
evidence, authenticated SSH access, key revocation and failed subsequent
access, teardown, Capacity Reservation release, and capacity republication.
Card, ACH, automatic-fallback, and failure/recovery whole-host lanes remain
unqualified until the protected payer-profile blocker and remaining provider
matrix are resolved.

---

## Related documents

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — the current system and its boundaries.
- [`openspec/changes/README.md`](../../openspec/changes/README.md) — delivery campaigns, readiness, and blocking.
- [`openspec/specs/README.md`](../../openspec/specs/README.md) — the normative contract for each capability.
