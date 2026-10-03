# Active Change Campaigns

This index groups active OpenSpec changes by delivery sequence. It is a planning map, not a normative specification or an umbrella change. Each linked change retains its own acceptance, validation, synchronization, and archive boundary. Capability behavior remains authoritative under [`openspec/specs/`](../specs/README.md).

Statuses here describe readiness, not merely whether a checklist exists:

- **active** — implementation may proceed subject to dependencies in the change;
- **blocked** — retain design/specification, but do not begin blocked implementation;
- **deferred** — no implementation checklist until the recorded activation condition is met.

## How this index is organized

Campaigns come in two kinds.

**Roadmap goals** are the directional goals in [`docs/development/ROADMAP.md`](../../docs/development/ROADMAP.md). Those sections carry sequencing and readiness only — why a goal exists, the value it delivers, and what is still true today all live in the roadmap, which is the single place they are maintained.

**Lesser goals** are coherent bodies of work with no roadmap goal behind them. Each gets a short summary, because a reader landing on four registry changes deserves to know what they add up to. A lesser goal is not a smaller roadmap goal: it is work that improves how the system is built without changing what the market can do.

A change appears exactly once, in its primary home. Where a change serves more than one goal, the other goal notes it rather than listing it again.

## Roadmap goal — Consolidate physical-resource authority in the provisioning service

```text
unify-host-identity (archived) ──► capacity-resource-administration (archived) ──┐
repair-multi-storefront-scenario (archived) ────────────────────────────────────┴──► pools-9-retire-local-physical-authority
fix-vm-fulfillment-capacity-boundary (archived) ──► retire-vm-remove-job-id (archived)
remove-dead-storefront-physical-surfaces, fix-resource-pool-provider-at-creation (independent)
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`version-accepted-artifacts`](version-accepted-artifacts/) | proposed; not planned; must land before bare-metal release | A repository-wide rule for evolving signed and content-addressed state: never rewrite accepted bytes, verify over stored bytes, retire a kind by stopping production while keeping a read-only decoder, and remove the decoder only when a measured count of live references is zero. Fixes bare-metal digest verification, which re-serializes through the live model. Found by `unify-host-identity` |
| [`pools-9-retire-local-physical-authority`](pools-9-retire-local-physical-authority/) | planned; the separate multi-storefront repair prerequisite is archived, including Alice's projection cutover and passing two-storefront evidence | Retires local derivation, its flag, CSV import and deployment contract, startup seeding, legacy home-site overrides, and local diagnostics/cleanup in one coordinated cutover with the schema freeze. Fresh databases omit retired schema; upgrades retain inert history for rollback or operator provisioning seeding. The site-scoped override store remains the only override tier, without legacy carry-over. Inventory counts remain per site and projection family. Self-hosting operators choose deployment timing after preparing site inventory and commercial overrides |
| [`remove-dead-storefront-physical-surfaces`](remove-dead-storefront-physical-surfaces/) | planned; no blocking dependency | Retires the storefront's zero-caller physical surfaces: the `compute_allocations` execution ledger (frozen, not dropped), the always-`None` `vm_host` plumbing, the orphaned resource admin routes with their client methods, the legacy half of `release_reservations`, four dead `SQLiteClient` methods, and `resource_count` on the health surface. Removes code only; the terminal requirement stays `pools-9`'s |
| [`fix-resource-pool-provider-at-creation`](fix-resource-pool-provider-at-creation/) | planned; no blocking dependency | A Resource Pool's provider is fixed at creation: replace and patch refuse a differing provider without deleting existing configuration, matching the immutable backing declaration; inventory moves executors through a second pool and member migration, safe under `capacity-resource-administration`'s drain invariant |
| [`fix-vm-fulfillment-capacity-boundary`](archive/2026-09-28-fix-vm-fulfillment-capacity-boundary/) | **archived** 2026-09-28 | Removes stale physical-placement fields from the current fulfillment path and derives fulfillment shape from committed reservation dimensions. Also serves Goal 2. Proven by a green e2e run on 2026-09-14. Its one deferral, retiring the `vm_remove_job_id` mirror, is complete in `retire-vm-remove-job-id` below |
| [`bring-host-inventory-under-definition-documents`](bring-host-inventory-under-definition-documents/) | design phase; not planned | Host inventory seeds the registry only when it is empty and is never reconciled against its file, unlike relay, pool, and capacity definition documents. Brings it under the digest-gated definition-document mechanism. Open: what happens to hosts the document stops naming, the first post-upgrade startup, secrets in the inventory, and format |
| [`retire-vm-remove-job-id`](archive/2026-09-28-retire-vm-remove-job-id/) | **archived** 2026-09-28. Promoted to `site-capacity` and `RELEASING.md` | Retires `capacity_reservations.vm_remove_job_id`, a VM-conditional mirror of `release_job_id` and the one domain-prefixed column on a reservation table bare-metal pools share. Scoped to the mirror only: the legacy `vm_leases` column the backfill reads and the storefront's own column are out of scope. The published field is removed outright with a version bump — pre-1.0 APIs may break — and the lease PATCH body names the handle `release_job_id`, ignoring the old name like any unknown field. One compute-provisioning migration drops the column, an approved exception to expand/contract with a recorded rollback recovery; bare-metal and API-credits databases need none |

No change owns these yet. Both were found by `project-capacity-resources-without-hosts`.

| Item | Origin |
|---|---|
| The bare-metal access playbook (`domains/vms/provisioning/iac/ansible/playbooks/bare-metal/node-access.yaml`) reports no tenant address, so bare-metal access coordinates carry none. The execution inventory already passes it `public_host` as a host variable | `project-capacity-resources-without-hosts` design amendment A2 |
| Adding a fulfillment provider touches its adapter bundle and, separately, the service container's host-requirement merge. One descriptor per adapter package could supply both; drift between them is refused at startup today | `project-capacity-resources-without-hosts` design, follow-up after A7 |

## Roadmap goal — Negotiate full compute capability, not GPU count alone

```text
publish-multidimensional-listing-shape (archived) ──► capacity-shape-pricing (archived) ──► negotiation-driven-capacity-resize §2
capacity-shape-envelope, negotiation-capacity-feasibility-probe ────────────────────┘ (consumed by §2; independent otherwise)
settle-capacity-claim-vocabulary (independent; was structured-capacity-requirements)
negotiation-driven-capacity-resize §2 ──► negotiation-time-capacity-hold (Goal 5) for resize_reservation's first call
store-registry-listings-as-published (Registry productionization) ··► decision input to negotiation-driven-capacity-resize §2 task 2.1a (not a dependency)
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`publish-multidimensional-listing-shape`](archive/2026-09-25-publish-multidimensional-listing-shape/) | **archived** 2026-09-25 | Every VM listing is a listing shape — the storefront's site-scoped override, else the pool's `listing_shapes` hint, else the GPU-only default generator — published and reserved at exactly its declared quantities, and only where a source member is feasible for it; so the registry's dimension filters match stated shapes. Adds site-scoped storefront pool overrides, administered through an authenticated API checked against the site's live projection, as a market-neutral storefront kit (`kit/pool-overrides`) each market joins with its own vocabulary, so the planned container market reuses it; the core storefront client keeps only universal transport. A site whose projection is unknown now holds its listings rather than closing them, and an operation that changes a site's capacity refreshes that site before reconciling inline. Implements the family-grouped shape form, its shared utility (`kit/capability-shape`), and the VM family schema from `structured-capacity-requirements` |
| [`settle-capacity-claim-vocabulary`](settle-capacity-claim-vocabulary/) | planned; independent. Its flat-spelling gate now renames both compute domains at once, by editing `arkhai_compute` (`domains/compute`) | Vocabulary cleanup on the capacity-claim path: rename the storefront's whole-claim `required_attributes` key to `capacity_claim`, decide as a gate whether the VM flat dimension names become family-prefixed (with bare metal's names in view), and promote the claim term table. Nothing waits on it |
| [`capacity-shape-pricing`](archive/2026-10-01-capacity-shape-pricing/) | **archived** 2026-10-01. Promoted to `storefront-publication` (spec and architecture), `negotiation-protocol`, `resource-pool-management`, `ARCHITECTURE.md`, and `DEPLOYMENT_AND_CONFIG.md` | Per-family rates under an explicit domain pricing projection, resolved through the site-scoped override, pool hint, and configured default; a listing is shape-priced when any family resolves rates, else flat-priced exactly as today; unrated families are not charged and a listing that would be free is refused; unreadable rates hold the pool, reported in system status, and the provisioning service refuses malformed rate lists at write; an exact, replaceable aggregator in `kit/capability-pricing`; exact base-unit conversion and reference amounts; the seller's reference amount is the selected option's rate, shared through `kit/policy`'s `selected_settlement_artifact`; every resolved family's rates recorded as a storefront term of sale, with the registry payload unchanged; the dead `min_price`/`token` resolution retired |
| [`capacity-shape-envelope`](capacity-shape-envelope/) | active; independent | Kit-level admissibility: whether a whole shape is one the seller will consider, and what range remains admissible for one dimension given the rest, behind an interface shaped for the occupancy-dependent feasible region expected later |
| [`negotiation-capacity-feasibility-probe`](negotiation-capacity-feasibility-probe/) | active; independent | Verifies a requested shape against the authoritative site before terms are agreed, consuming nothing, reporting unservable distinctly from seller-declined. Shared prerequisite: also required before a held reservation can be billed |
| [`negotiation-driven-capacity-resize`](negotiation-driven-capacity-resize/) | Sections 0–1 complete; Section 2 planned; depends on `capacity-shape-pricing` (archived), and on `capacity-shape-envelope` for task 2.4's quantitative check; the deployment boundary of the campaign | Round-0 shape-mismatch guard shipped. Section 2: a revised shape carried as a child of `proposal` in the family-grouped form, the negotiated quantity reinterpreted as a rate multiplier in basis points over the advertised minimum (amounts stay exact integers), the seller's round evaluated in a fixed order with distinct refusal reasons, the round-0 guard retired, and the agreed shape reaching the accepted artifacts and the claim. Where a buyer reads the rate structure is decision gate 2.1a, taking `store-registry-listings-as-published`'s carrier policy as an input. `resize_reservation` is not wired here: with no pre-settlement hold there is nothing to resize, so its first caller is `negotiation-time-capacity-hold`. Task 2.4 also owns the seller's commercial feasibility guard for a requested shape, ordered after the envelope's admissibility and before pricing |

### Unowned work found by `capacity-shape-pricing`

| Item | Origin |
|---|---|
| The legacy pricing migration reads `default_min_price` as a display-unit Alkahest rate while the negotiation floor reads it as base units per hour | Planning-time finding; only pre-clause configurations reach the migration |

### Unowned work left by `publish-multidimensional-listing-shape`

No change owns these yet. The first three are the archived design's open questions.

| Item | Origin |
|---|---|
| A time bound on holding an unknown site's listings, so a site decommissioned without closing them stops advertising unbookable capacity | Decision 11; deferred at the maintainer's direction |
| The admin projection refresh rebuilds every site's cache and discards last-known generations, so pressing it during an outage turns a stale site unknown |
| How a shape generator is assigned to a pool; the generator seam exists, with the VM default as its one implementation |
| Thirteen anchor-form spec citations (in `listing_cardinality_mode.py`, `legacy_backfill.py`, `kit/site`'s ledger, and seven `kit/fulfillment` modules) omit the `requirement-` prefix their headings' slugs carry, so none resolves |
| `core_storefront`'s `SQLiteClient.listing_id_for_derivation_key` calls an undefined `self._connect()`, so it raises whenever reached |

## Roadmap goal — One storefront serving several compute-family domains

```text
storefront-domain-parameterization (complete) ──► multi-domain-storefront-composition (shell landed; closeout) ──┐
bare-metal-and-credits-domain-stacks §4a (bare metal onto the shell's routes; Goal 4) ─────────────────────────────┼──► compute-40
bare-metal-mock-provisioned-deal (pipeline bare-metal deal; bare metal on the kit negotiation runtime) ─────────────┘

market-platform-bare-metal-10 and bare-metal-buyer-domain archived (delivered)
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`storefront-domain-parameterization`](storefront-domain-parameterization/) | complete but for closeout (5.7–5.9) and two evidence notes | Composes the VM storefront around an injected market-domain contract, matching the bare-metal runtime's existing shape. Behavior-preserving refactor |
| [`multi-domain-storefront-composition`](multi-domain-storefront-composition/) | shell implemented and promoted; validation (Section 9) and closeout (Section 10) remain | Hosts several compute-family contracts in one storefront process, resolving each record's contract from the listing's recorded offering mode. Bare metal composing the kit negotiation runtime is `bare-metal-mock-provisioned-deal`'s; moving its routes onto the shared routes is `bare-metal-and-credits-domain-stacks` 4a |
| [`market-platform-compute-40-multi-domain-proof`](market-platform-compute-40-multi-domain-proof/) | blocked on `multi-domain-storefront-composition`'s closeout, `bare-metal-and-credits-domain-stacks` 4a, and `bare-metal-mock-provisioned-deal` | Deterministic proof of one multi-domain storefront against two provisioning authorities. Rewritten 2026-08-06: most of its implementation work has shipped, and many-to-many storefront-to-authority ownership was removed from scope rather than deferred |

Goal 3's remaining gap — bare metal negotiating through the kit runtime rather than
its own service — is `bare-metal-mock-provisioned-deal`'s (Goal 7), with the move onto
the shell's routes left to `bare-metal-and-credits-domain-stacks` (Goal 4); Goal 3
completes when `compute-40` proves the two-authority topology on it. The seller
composition and the buyer package are delivered; the changes that planned them are
listed under "Archived and superseded".

## Roadmap goal — Make a domain a composition of kit

```text
kit-storefront-composition-seam
      ├──► kit-owned-negotiation-runtime ─────────┐
      └──► kit-owned-capacity-and-publication ────┴──► bare-metal-and-credits-domain-stacks ──► compute-40 (Goal 3)
bare-metal-mock-provisioned-deal ──────────────────────┘ (pipeline deal evidence)

Next wave:
kit-owned-storefront-loop-lifecycle (archived) ──► kit-owned-storefront-shell ──┬──► kit-owned-listing-and-fulfillment-lifecycles
     │                                                               └──► kit-owned-storefront-auth-and-persistence
     ├──► contact-payload-retention (Goal 6, archived)
     └──► bare-metal-mock-provisioned-deal (Goal 7 section)
bare-metal-mock-provisioned-deal ──► kit-owned-storefront-shell (mounts the deal-control route services it builds)
bare-metal-mock-provisioned-deal ──► bare-metal-and-credits-domain-stacks §4a.3–4a.6 (shell routes over the composed runtime)
bare-metal-mock-provisioned-deal ──► apicredits-end-to-end-lane (loop holding in the lane it builds)

kit-owned-settlement-runtime archived 2026-08-10
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`kit-storefront-composition-seam`](kit-storefront-composition-seam/) | implemented and promoted; validation and closeout remain | Defines where kit-owned storefront runtime sits and proves it with the two smallest duplicated concerns, composing all three domains. Establishes the rule that an extracted concern leaves no domain-local copy |
| [`kit-owned-negotiation-runtime`](kit-owned-negotiation-runtime/) | implemented and promoted for VM and API credits; validation and closeout remain | Extracts the synchronous negotiation runtime; VM and API credits inject domain hooks and retain no lifecycle copy. Bare metal's composition onto it is `bare-metal-mock-provisioned-deal`'s |
| [`kit-owned-capacity-and-publication`](kit-owned-capacity-and-publication/) | implemented and promoted for all three domains; validation and closeout remain | Extracts the storefront capacity client and publication runtime; all three storefronts compose them |
| [`kit-owned-storefront-loop-lifecycle`](archive/2026-10-01-kit-owned-storefront-loop-lifecycle/) | **archived** 2026-10-01. Promoted to `market-composition`, `ARCHITECTURE.md`'s kit layers and operator lifecycle controls, and `TESTING.md`'s loop table; both end-to-end lanes passed. Carved out of `kit-owned-storefront-shell`; prerequisite of `contact-payload-retention` and `bare-metal-mock-provisioned-deal` | One instance-scoped kit loop controller per storefront process and a framework-free lifecycle route service, adopting VM's pause, step, quiescence, and loop-state semantics unchanged. VM binds its lifecycle module to it with every imported name preserved; bare metal and API credits gain pause and a step for every loop by composition. Every timer loop gates on entry, works when due, and waits through the controller, so a pause is observed within its bound whatever the interval. Wire paths and the canonical client are unchanged |
| [`apicredits-end-to-end-lane`](apicredits-end-to-end-lane/) | design phase; not planned; loop holding follows `bare-metal-mock-provisioned-deal`, which builds the lane (migrated 2026-10-01) | Holds and steps the API-credit storefront's loops while its deal scenario runs in its own lane, and gives the storefront production-application integration tests, which it has never had. Found by `kit-owned-storefront-loop-lifecycle`. The lane itself moved to `bare-metal-mock-provisioned-deal` |
| [`kit-owned-storefront-shell`](kit-owned-storefront-shell/) | design phase; not planned; depends on the seam, the three runtime kits, and `kit-owned-storefront-loop-lifecycle`; mounts the deal-control route services `bare-metal-mock-provisioned-deal` builds | Extracts what every storefront still duplicates beneath the runtimes: the route set over the core models, executable assembly, and health, with the kit composition root owning the loop controller. A domain contributes codecs, hooks, extra routes, and timings, not a controller or a server. The other two next-wave changes land as contributions to it |
| [`kit-owned-listing-and-fulfillment-lifecycles`](kit-owned-listing-and-fulfillment-lifecycles/) | design phase; not planned; depends on the shell | Extracts the seller listing lifecycle over the common binding (close, pause, reopen, successor carry-over) and restart-safe fulfillment convergence (obligation resumption, terminal-state driving, executor-result reconciliation), and replaces the VM per-site projection cache with the capacity kit's state |
| [`kit-owned-storefront-auth-and-persistence`](kit-owned-storefront-auth-and-persistence/) | design phase; not planned; depends on the shell | One core- or kit-owned v2 authentication middleware set applied by the shell, and a stated persistence boundary: core owns market state, a domain's client holds only its own tables |
| [`bare-metal-and-credits-domain-stacks`](bare-metal-and-credits-domain-stacks/) | active; owns moving bare metal's negotiate and listing routes onto the shell (4a.3–4a.6) after `bare-metal-mock-provisioned-deal` composes bare-metal negotiation onto the kit runtime (4a.1, 4a.2, and the runtime half of 4a.3 migrated there 2026-10-01); gained the bare-metal buyer CLI requirements (4b.6–4b.9) from it; the stack and both deal scenarios exist | Moves bare metal's negotiate and listing routes onto the shell, recomposes API credits onto kit, and verifies the bare-metal buyer requirements (clean wheel, independent authorities, package boundary, negotiation ownership). Its deal evidence comes from `bare-metal-mock-provisioned-deal`. Delivers the goal's completion test |

## Roadmap goal — Make capacity exclusivity compensated

```text
default-no-pre-settlement-capacity-hold (interim posture, reversed by billing)
capacity-reservation-lifecycle-hardening ──┬──► billable-capacity-reservations ──► negotiation-time-capacity-hold
capacity-shape-pricing (archived) ─────────┘                                                   ▲
negotiation-driven-capacity-resize §2 (Goal 2) ── shape in a round; resize_reservation's first caller ┘ (Section 3 only)
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`default-no-pre-settlement-capacity-hold`](default-no-pre-settlement-capacity-hold/) | active; configuration applied 2026-08-06, validation outstanding | Ships `capacity.hold_ttl_seconds = 0` for both storefronts, closing a denial vector by denying the capability. Reversed by `billable-capacity-reservations` once holding is charged |
| [`capacity-reservation-lifecycle-hardening`](capacity-reservation-lifecycle-hardening/) | active; no blocking dependency | Fixes three reservation-row defects: holds placed during negotiation bypass the idempotency guard, expiry scans all held rows on every ledger operation, and terminal reservations accumulate without bound |
| [`billable-capacity-reservations`](billable-capacity-reservations/) | active; depends on `capacity-shape-pricing` (archived) and `capacity-reservation-lifecycle-hardening` | A hold carries a burn rate from a posted, seller-set hold rate in the lease rate's form and tiers, defaulting to the lease rate and untouched by the negotiated multiplier; maximum duration derives from committed funds rather than a configured TTL; held time is charged as a serviced obligation with the remainder returned. Where a buyer reads the posted hold rate is decision gate 1.3b, taking `store-registry-listings-as-published`'s carrier policy as an input |
| [`negotiation-time-capacity-hold`](negotiation-time-capacity-hold/) | active; depends on `billable-capacity-reservations` and `capacity-reservation-lifecycle-hardening`; its shape-change section on `negotiation-driven-capacity-resize` | Moves the hold from terms acceptance to the counterparty's first differing-terms proposal through the kit's hooks, adds a release hook the kit and watchdog call on terminal states, keeps one superseded reservation per negotiation, and is `resize_reservation`'s first caller. Inquiry stays unheld and unfunded |

## Roadmap goal — Make the settlement mechanism a composed choice

The mechanism work is delivered (`finish-settlement-mechanism-neutrality` and
`contact-exchange-settlement-mechanism`, archived 2026-08-19 and since pruned; their
requirements are live in `openspec/specs/`).
[`ROADMAP.md`](../../docs/development/ROADMAP.md)'s Goal 6 carries the current state.

Two changes took on what that goal recorded as its remaining gap. `contact-payload-retention` is complete and archived; `compose-contact-exchange-across-compute` owns the rest; `pass-through-storefront-config`, complete, made the VM storefront chart able to deploy a further settlement mechanism.

```text
kit-owned-storefront-loop-lifecycle (Goal 4, archived) ──► contact-payload-retention (archived) ──► compose-contact-exchange-across-compute
pass-through-storefront-config (archived) ──────────────────────────────────────────────────────────┘
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`contact-payload-retention`](archive/2026-10-01-contact-payload-retention/) | **archived** 2026-10-01. Promoted to `contact-exchange-settlement`, `introduction-delivery`, `ARCHITECTURE.md`, `DEPLOYMENT_AND_CONFIG.md`, and `TESTING.md`; both end-to-end lanes passed in [Actions run 36928047725](https://github.com/arkhai-io/simple-compute-market/actions/runs/36928047725), the bare-metal introduction scenario covering disclosure, reveal, operator deletion, and the held sweep | Makes the bounded-PII retention requirement executable, kit-first and composed into bare metal, the only domain composing the mechanism. Deletion redacts in place and leaves a tombstone, because the existing primitive removed the row and let a buyer reveal a deleted introduction again; triggers keep the table's active part append-only. A `retention_seconds` window in the mechanism's seller configuration, 30 days by default or `indefinite`, applied as an aggregate policy; one deletion operation behind a held-and-stepped sweep and an operator path; a machine-readable disclosure on the public readiness projection and at reveal; and the first introduction scenario on the bare-metal lane. Requires every composing storefront to run retention, so VM inherits it through the change below. Recorded responses in the authenticated replay store are out of scope, owned by `redesign-authenticated-replay-state` |
| [`pass-through-storefront-config`](archive/2026-10-02-pass-through-storefront-config/) | **archived** 2026-10-02. Promoted to `deployment-state`, `ARCHITECTURE.md`, `DEPLOYMENT_AND_CONFIG.md`, and `TESTING.md`; both end-to-end lanes passed. Its CI follow-up is `add-full-stack-ci-job` | The VM storefront chart passes each agent's service configuration through instead of enumerating it: no chart-supplied service defaults and no chart-side validation of the storefront's own configuration. The chart renders `storefront.json`, which the storefront reads between its file and its Secret overlay, adds only release-known values, and keeps checks that relate release parts. A values-schema definition generated from the storefront's typed models keeps secret-marked fields, private identity material, and hosted payer data out of ConfigMaps. Does not move the storefront onto the profile-based loader |
| [`compose-contact-exchange-across-compute`](compose-contact-exchange-across-compute/) | implemented except 6.5; awaiting the 6.3/6.4 lane run, the 6.6 Helm run, and VM lock regeneration; its Helm-deployability prerequisite `pass-through-storefront-config` is complete; its 6.5 is blocked on `bare-metal-mock-provisioned-deal`'s two-storefront topology; also wires that change's kit retention into VM (its 3a). Owns the system evidence for unbacked listings (its 6.4 and 6.5, transferred from the archived `unbacked-listing-publication`); its 6.4 also bounds the buyer query by asking rate, transferred from `publish-indicative-listing-rates` 7.13 | Promotes the domain-neutral introduction composition glue out of bare metal so accepted-state interpretation has one implementation, composes the mechanism in the VM storefront — the one remaining compute-family domain — extends delivery to it, and resolves the seller's contact payload per listing origin rather than per storefront. Goal 7's multi-seller introduction value depends on that last part |

## Unblocking work — the local end-to-end stack

```text
provide-e2e-development-identities (archived) ──► repair-e2e-fixture-drift (archived)
                                                          │
                                                          ▼
                                          repair-storefront-alkahest-configuration
                                                          │
                                                          ▼
                                       sign-multi-language-credits-middleware
```

The stack starts and the e2e suite reports results rather than setup errors.
The active change addresses the larger of the two findings that repair left:
the VM storefronts cannot settle, which accounts for ten of the eleven
remaining failures.

| Change | Status | Acceptance boundary |
|---|---|---|
| [`provide-e2e-development-identities`](archive/2026-09-12-provide-e2e-development-identities/) | **archived** 2026-09-12 | `docker compose up` had been unable to start since mid-August. Committed the development signer, wallet, admin-key, and buyer-config values; split the compose overrides out of the `include` files; and repaired five pre-existing defects the startup path had been masking. The stack now comes up healthy with no repository secrets, so a contributor or a fork can run it |
| [`repair-e2e-fixture-drift`](archive/2026-09-13-repair-e2e-fixture-drift/) | **archived** 2026-09-13 | The e2e suite reached pytest reporting 12 passed and 88 fixture errors. The drift was wider than two signature mismatches: six construction sites and three payload shapes, four of them masked because pytest reports only the first fixture to raise. Rebuilt the fixtures as one client per role, corrected a misfiled route role in the storefront (system status is an administrator operation also readable by a service peer), and separated storefront administrators from their sellers in development configuration. The suite now reports **0 errors, 38 passed, 11 failed**, and every failure is classified |
| [`repair-storefront-alkahest-configuration`](repair-storefront-alkahest-configuration/) | implemented locally; stack verification and closeout remain | Alkahest is the VM storefronts' only enabled settlement mechanism and never becomes ready, so composition refuses every listing. Three configuration gaps: the storefront never receives its EVM credential because the wallet env files use a name only the buyer-side loader resolves, and both Alkahest address-config paths point into a source tree the image does not contain. Settles the stack so the on-chain escrow phases run for the first time since mid-August |
| [`repair-multi-storefront-scenario`](archive/2026-10-01-repair-multi-storefront-scenario/) | **archived** 2026-10-01; the 21-stage scenario passed, with typed registry reads in Phase 4 and production buyer fan-in in Phase 5; full local pipeline 127 VM/API-credit + 11 bare-metal passed, no skips; prerequisite for `pools-9-retire-local-physical-authority` satisfied | Alice has her own provisioning authority and projection-backed listings; Bob retains his own authority. The complete two-storefront registry scenario includes both negotiations. Multiple storefronts per site remain out of scope; existing identity and push topology assumptions stay intact |
| [`sign-multi-language-credits-middleware`](sign-multi-language-credits-middleware/) | planned; opened by `repair-storefront-alkahest-configuration` task `3ax.10` | The TypeScript and Rust API-credits middlewares authenticate to a credits service with signed authentication enabled, which they cannot today: both send only the legacy shared secret, and the service accepts signed requests or the secret and never both. Owes its validation layer first -- neither client has an e2e scenario, so signing code for them cannot currently be proven against a real service |
| [`retain-authenticated-request-outcomes`](retain-authenticated-request-outcomes/) | **blocked** on `redesign-authenticated-replay-state`, whose decision 1.7 settles whether this is superseded, narrowed, or folded in; opened by `repair-storefront-alkahest-configuration` | `SiteAuthMiddleware` reserves `(principal, request_id)` and rejects changed reuse, but keeps no outcomes, so an exact retry cannot resolve to the recorded one. Conformance is currently delegated to handlers and declared per route by `exact_retry_safe`; this retains outcomes so the middleware can honour the requirement itself, with a durable provider for services that must survive an authority restart |

### Unowned work left by this campaign

No change owns these yet. Recorded here so the next reader sees them rather
than rediscovering them. The storefront settlement fault that this table also
held is now owned by `repair-storefront-alkahest-configuration` above.

| Item | Origin |
|---|---|
| `market credits buy` exits `rc=2` before writing a run-log, indicating its argument interface has moved | `repair-e2e-fixture-drift` finding |
| A run-id seam for tailing a live buyer-CLI run, so the streaming case can synchronize on a transition rather than a bounded sample | `repair-e2e-fixture-drift`, deferred (changes `core/buyer`) |
| Compose configuration is assembled by hand across a root file, domain files, an identity overlay, and legacy env files, with duplicated paths and per-value TOML workarounds; the Helm charts express the same deployment more coherently. Converging compose onto one source shared with the tests | accepted as follow-up during `repair-storefront-alkahest-configuration` |
| `domains/vms/storefront/.env.{bob,alice}.docker` carry configuration for a layout that no longer exists, including a stale Alkahest address path | `repair-storefront-alkahest-configuration`, left in place because compose still references them |
| Four questions about the API-credits capacity topology: a stale ed25519 authority pin, a capacity-site table where the loader expects a string, an `include`-plus-override compose shape, and `kit/config` TOML-parsing `0x` values into integers | inherited from `provide-e2e-development-identities`, carried through `repair-e2e-fixture-drift` |

## Roadmap goal — Sell capacity the marketplace cannot admit against

```text
unify-host-identity (archived) ──► capacity-resource-administration (archived) ──► project-capacity-resources-without-hosts (archived) ──┐
settle-listing-vocabulary (archived) ─────────────────────────────────────┤
pool-declared-advertisement-and-backing (archived) ─────────────────────────────┴──► unbacked-listing-publication (archived)

bare-metal-publication-reads-pool-declarations (archived) ──► bare-metal-listing-shapes (archived) ──► unbacked-bare-metal-listings
bare-metal-publication-reads-pool-declarations (archived) ──► bare-metal-mock-provisioned-deal
kit-owned-storefront-loop-lifecycle (Goal 4, archived) ───────► bare-metal-mock-provisioned-deal (lifecycle controls)
kit-owned-storefront-loop-lifecycle (Goal 4, archived) ──► contact-payload-retention (archived) ──► compose-contact-exchange-across-compute (Sections 1–3, 3b) ──► unbacked-bare-metal-listings
pass-through-storefront-config (archived) ──► compose-contact-exchange-across-compute
bare-metal-mock-provisioned-deal (bare metal on the kit negotiation runtime) ──────────────────┘

publish-indicative-listing-rates (archived)
  unbacked-supply rate evidence       transferred to unbacked-bare-metal-listings and
                                      compose-contact-exchange-across-compute (its 6.4)
```

Bare metal is Goal 7's primary target domain, and the goal's critical path runs
through it: `bare-metal-publication-reads-pool-declarations` (archived), then
`bare-metal-listing-shapes` (archived), then `unbacked-bare-metal-listings`. Both compute-family
domains reach the goal through the same kit mechanisms rather than solving it
separately. Rate comparison, through `publish-indicative-listing-rates` (archived),
is in place for both; what remains is unbacked supply.

An unbacked VM listing publishes only settlement options the VM composition does not
fulfil through capacity, and contact exchange is the first such option. The system
scenarios for unbacked VM listings therefore live in
`compose-contact-exchange-across-compute` (its 6.4 and 6.5), transferred from the
archived `unbacked-listing-publication`, whose implementation and integration
coverage did not need them. The bare-metal counterparts belong to
`unbacked-bare-metal-listings`.

`capacity-resource-administration`, a Goal 7 prerequisite archived 2026-09-21,
delivered what Goal 7 relies on: digest-gated capacity-definition import, a composition-supplied mirror
dimension, and a drain invariant forbidding a capacity resource from moving pools
under a live obligation.
`pools-9-retire-local-physical-authority` depends on that invariant too — its
two-pool executor-migration path has the same hazard.

Goal 7 owns every change it needs. Unbacked bare metal was recorded as having no
owner until `bare-metal-listing-shapes` and `unbacked-bare-metal-listings` were
opened on 2026-09-25. `publish-indicative-listing-rates` was
originally graphed behind `capacity-shape-pricing` and transitively behind the
unstarted `structured-capacity-requirements`; that dependency was removed once it
was clear those changes price a shape a buyer proposes during negotiation, while a
published asking price prices a listing's fixed advertised shape. The two remain
forward-compatible — see that change's `design.md`.

`pools-9-retire-local-physical-authority` is a **completion dependency** of
`unbacked-listing-publication`, not a blocking one: implementation may proceed
before it, closeout may not. It owns promoting "projection is the listing-candidate
origination path" into `ARCHITECTURE.md`, alongside which this goal's own promoted
text sits.

`pool-declared-advertisement-and-backing` amends `resource-pool-management`, a
contract established by the archived `pool-declared-offering-modes` change. No
active change owns it, so there was nothing to split a minimal piece out of. It
carries both new pool tags rather than one: splitting them across changes made the
advertisement change's subset rule depend on a concept its own dependent owned.

| Change | Status | Acceptance boundary |
|---|---|---|
| [`settle-listing-vocabulary`](archive/2026-09-15-settle-listing-vocabulary/) | **archived** 2026-09-15 | One name for the offering mode across the claim wire, pool declarations, the durable binding, and the published listing. Provisioning contract on 2.0 with majors {2}; the registry refuses the retired spellings at the publish boundary, not only in its dry run; the deprecated `listing_mode` cardinality alias is retained one-way and proven across deployed services. Closed on a green end-to-end run of 113 passed following the `filter-spec` v6 bump |
| [`pool-declared-advertisement-and-backing`](archive/2026-09-22-pool-declared-advertisement-and-backing/) | **archived** 2026-09-22 | Two pool declarations, both required on every pool write: what a pool's listings may advertise, separate from what its provider proves it can deliver; and whether the pool can be admitted against. A backed pool advertises a subset of what it delivers, an unbacked pool delivers nothing, a malformed backing value fails closed, backing is fixed at creation, and every existing pool is migrated to explicit values. A service refuses to start with a pool lacking valid declarations. Supplies one shared resolver for projected declarations. Leaves `deliverable_modes` and every execution recheck untouched. Observable to operators only — no listing behaviour changes until `unbacked-listing-publication` reads the tags |
| [`project-capacity-resources-without-hosts`](archive/2026-09-22-project-capacity-resources-without-hosts/) | **archived** 2026-09-22 | Builds the resource-pool projection from capacity declarations alone, so a declaration naming no host reaches storefronts instead of succeeding into a void, and generic entries carry no host connection identity. Joins the host only at dispatch, which fails closed on an unregistered host with the static-inventory fallback removed. Providers declare whether delivery needs a host, and admission and scheduling refuse a declaration naming none in such a pool, closing a stranded-assignment defect. Hands disabled-host admission and placement to `pools-6-fair-scheduling-policy`. Also serves Goal 1 |
| [`unbacked-listing-publication`](archive/2026-09-24-unbacked-listing-publication/) | **archived** 2026-09-24. Its system evidence for unbacked listings moved to `compose-contact-exchange-across-compute` (6.4, 6.5), which first makes it runnable | Backing as an explicit declared listing property: sibling `CapacityBinding` and `UnbackedBinding` types, a binding discriminator distinct from the listing's origin site, pool advertise-authorization separated from execute-authorization, capacity-availability reconciliation scoped to backed listings while source-publication reconciliation applies to all, and an exact backing filter in the compute registry schema, published by VM and bare metal alike. Listing identity is the physical resource offered and terms of sale refresh in place; the seller's inventory guard checks each listing against a fresh derivation of its own source; older producers are detected jointly per site with unresolvable pools held; publication stops using `derived_compute_listings`. Publication runs as a controllable storefront lifecycle loop with terms only from durable sources, a seller's close is durable, and an unbacked listing publishes only settlement options its domain does not fulfil through capacity |
| [`publish-indicative-listing-rates`](archive/2026-10-01-publish-indicative-listing-rates/) | **archived** 2026-10-01. Promoted to `registry-discovery`, `storefront-publication`, `resource-pool-management`, the `storefront-publication` architecture companion, `ARCHITECTURE.md`, and `DEPLOYMENT_AND_CONFIG.md`. Both end-to-end lanes passed in [Actions run 36841346733](https://github.com/arkhai-io/simple-compute-market/actions/runs/36841346733), the bare-metal publication scenario covering a declared rate, a storefront override, and its removal. Also joined bare metal to the site-scoped pool-override store (its section 3b). The system evidence that unbacked supply carries a comparable rate is transferred to `unbacked-bare-metal-listings` and `compose-contact-exchange-across-compute`, which create that supply; nothing here waits on another change | A seller's asking rate per listing shape as a frozen three-part object — decimal-text amount, opaque asset, `hour` period — declared by the site in a domain-neutral `asking_rates` pool tag keyed by shape, with the storefront's site-scoped override having final authority and no configuration default. Filters match the period and asset rather than normalizing across either. Normatively a listing attribute rather than a settlement option rate: nothing is constructed from it. Carries two domain-neutral filter-engine primitives, neither rotating any existing specification's etag: an exact-decimal declared value type and declarative filter co-requirements. Closes Goal 7's comparison gap. Also joins bare metal to the site-scoped pool-override store (its section 3b), moved here from `bare-metal-listing-shapes` |
| [`bare-metal-publication-reads-pool-declarations`](archive/2026-09-25-bare-metal-publication-reads-pool-declarations/) | **archived** 2026-09-25. Promoted to `site-capacity` and `storefront-publication`; both end-to-end lanes passed in [Actions run 36148752453](https://github.com/arkhai-io/simple-compute-market/actions/runs/36148752453) | Bare-metal publication derives its candidates from each site's resource-pool projection and its `bare_metal.v2` views rather than the capacity projection, resolving every pool through the kit's site declaration reader: no listing from a pool that does not advertise `bare_metal` or is disabled, unresolvable pools held, unbacked pools refused until `unbacked-bare-metal-listings` lifts the refusal, and a site whose projection cannot be fetched held rather than delisted. Publishes, reconciles, and converges through the kit publication runtime, recording each listing locally before any registry is told, and tracks listings by the common binding alone, dropping `derived_bare_metal_listings`, so a pool move is an identity change. Carries no upgrade path: bare metal is not yet deployed. Also renames the site projections' `resource_pool_id` to `pool_id` in one step, the site and every reader together; extracts the async publication cycle driver into the capacity-publication kit; and aligns the bare-metal administrator routes with the canonical storefront client |
| [`bare-metal-mock-provisioned-deal`](bare-metal-mock-provisioned-deal/) | design decided 2026-10-01; not planned; no active dependency (its lane and the bare-metal lifecycle controls exist). Scope widened to parity with VM's typed-client deal, absorbing bare metal on the kit negotiation runtime from `bare-metal-and-credits-domain-stacks`, the deal-control route services from `kit-owned-storefront-shell`'s scope, and the API-credit lane from `apicredits-end-to-end-lane`; the buyer CLI requirements moved to `bare-metal-and-credits-domain-stacks` | A mock-provisioned whole-host deal on the bare-metal lane on every pipeline run, stage for stage with VM's typed-client deal including every dry run, from stage definitions shared across compute domains. Builds `kit/compute-executor-mock` and an action-keyed executor seam with a bare-metal mock; composes bare metal onto the kit negotiation runtime; moves the deal controls into kit route services every storefront binds; starts bare-metal fulfillment at settlement; makes the lease lifecycle the only owner of release for every offering mode. Builds pipeline images once for three lanes, the third API credits'. Real access and revocation stay the protected lane's |
| [`bare-metal-listing-shapes`](archive/2026-09-27-bare-metal-listing-shapes/) | **archived** 2026-09-27. Promoted to `storefront-publication`, `market-composition`, `ARCHITECTURE.md`, and `DEPLOYMENT_AND_CONFIG.md`; both end-to-end lanes passed in [Actions run 36318761586](https://github.com/arkhai-io/simple-compute-market/actions/runs/36318761586) | Each bare-metal listing carries a capability shape derived from its Physical Resource's declaration, through a compute-family schema the VM and bare-metal domains share from one `domains/compute` package, and publishes it where the compute filters read it, with its pool's region. The shape completes the listing's derivation identity, the claim holds one whole unit and requires the published model, and opening rechecks shape and region against the site. It also converged the two compute domains where they had diverged without reason: a settlement request restates no negotiated term, and negotiation routes verify the body a caller sent. Typed-client test coverage surfaced and fixed unauthenticated bare-metal negotiation reads. Joining bare metal to the pool-override store moved to `publish-indicative-listing-rates` |
| [`unbacked-bare-metal-listings`](unbacked-bare-metal-listings/) | design decided; not planned; blocked on `compose-contact-exchange-across-compute` Sections 1–3b and on `bare-metal-mock-provisioned-deal` composing bare metal onto the kit negotiation runtime (moved there from `bare-metal-and-credits-domain-stacks` 4a) | Bare metal publishes unbacked listings from unbacked pools through the same kit runtime, binding, and reconciliation as VM, settling by introduction through the promoted composition. Owns the bare-metal system evidence that unbacked discovery reaches a usable introduction, and that a rate-bounded query returns backed and unbacked bare-metal listings together (from `publish-indicative-listing-rates` 7.13) |

## Lesser goal — POOLS capacity and fulfillment foundation

**What it adds up to.** The durable capacity and fulfillment substrate every roadmap goal builds on: a central Settlement Record, transactional scheduling and assignment, pull-correct fulfillment results, recovery, and the projections a storefront consumes instead of owning hardware itself. POOLS-1 through POOLS-6's foundations are archived. This is not a roadmap goal because it changes how the system is built rather than what the market can do — but nearly every goal has a dependency edge into it.

```text
archived POOLS-1…6 foundations ──► POOLS-7 durable fulfillment cutover ──► POOLS-8 projection consumption
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`pools-7-storefront-fulfillment-cutover`](pools-7-storefront-fulfillment-cutover/) | implementation substantially complete; change-specific end-to-end confirmation and closeout remain | Central durable Settlement Record, scheduling, fulfillment, pull result, recovery, storefront cutover, and teardown path |
| [`pools-8-capacity-projection-and-listing-hints`](pools-8-capacity-projection-and-listing-hints/) | implementation complete; closeout remains | Persists already-produced projections, maps them into commercial publication and claims, and adds advisory domain-owned hints |
| [`inject-site-pool-authority`](inject-site-pool-authority/) | design phase; no blocking dependency | Brings `kit/site` back inside `ARCHITECTURE.md`'s kit layers: the site ledger reads pool facts through a session-scoped port its composition root injects instead of importing `kit/resource-pools`, a capacity row's `pool_id` becomes non-null so no default pool is substituted, and a boundary test forbids the import. Should land before any new site read of pool state, including a backing check at admission |

`add-host-capacity-filters` was archived as superseded by site admission and fulfillment scheduling.

## Lesser goal — Service-to-service trust and event delivery

**What it adds up to.** A storefront and its site authorities authenticate each other with one shared secret that both gates inbound requests and signs outbound callbacks, and the storefront learns about everything by polling. These two changes replace the secret with mutual asymmetric identity, then replace three polling loops with authenticated delivery. Not a roadmap goal — no market behavior changes — but it closes an impersonation path, makes key rotation possible without downtime, gives each site a wallet identity that later collateral work can build on, and is what lets end-to-end scenarios wait on facts rather than intervals.

```text
service-identity-signing ──► replace-polling-with-authenticated-push
redesign-authenticated-replay-state ──► retain-authenticated-request-outcomes (local end-to-end stack campaign)
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`redesign-authenticated-replay-state`](redesign-authenticated-replay-state/) | design phase; not planned; no blocking dependency. Found by `contact-payload-retention`; blocks `retain-authenticated-request-outcomes` | Every authority's replay store grows without bound, and the storefront and registry keep every authenticated response body indefinitely — reads included, so introduction reveals leave copies of a counterparty's contact that retention cannot reach. Separates the store's three jobs (replay refusal, exactly-once resolution, in-flight leasing) and bounds each by its own lifetime; reservations are pruned past the horizon where a timestamp check would refuse a captured request anyway; routes declare whether an exact retry re-runs, as every read and every domain-idempotent mutation can, or resolves to a retained outcome kept for a stated period; one contract and store for the storefront, registry, provisioning service, and site authorities; `marketplace-identity`'s exact-reuse requirement restated to match |
| [`service-identity-signing`](service-identity-signing/) | active; supersedes `add-storefront-principal-authentication` (2026-08-06) | Asymmetric eip191 request signing in both directions; storefronts hold a `(site_id, url, identity)` registry; identities rotate through overlapping acceptance |
| [`replace-polling-with-authenticated-push`](replace-polling-with-authenticated-push/) | active; supersedes `provisioning-result-push-delivery` (2026-08-06); depends on `service-identity-signing` and POOLS-7 | Replaces all three cross-service polling loops with authenticated delivery from a transactional outbox, and refactors scenarios to await events. Pull and the local resume sweep stay authoritative; disabling delivery must leave the system correct and only slower |

## Lesser goal — Settlement and deal servicing depth

**What it adds up to.** Settlement handles one escrow shape well. Generalizing it to arbitrary obligation plans landed with `add-settlement-plan-shapes` (archived 2026-08-10). The changes still open here add the automation a seller needs to run spot inventory without manual intervention, and close a recovery gap where an ambiguous on-chain submission can currently only be resolved by an operator. Not a roadmap goal — the market's capabilities are unchanged — but every goal that touches money lands on this machinery, and `billable-capacity-reservations` reuses its per-obligation lifecycle directly.

| Change | Status | Acceptance boundary |
|---|---|---|
| [`automate-seller-spot`](automate-seller-spot/) | active | Residual active-deal view and client, splitter execution, reference runner, and durable cross-authority decision evidence |
| [`add-alkahest-attestation-reference-query`](add-alkahest-attestation-reference-query/) | externally blocked | Bounded attestation lookup by reference UID, making ambiguous submissions automatically reconcilable. Blocked on an upstream release; nothing in this repository can unblock it |

## Lesser goal — Registry productionization

**What it adds up to.** The registry runs on SQLite with an embedded-by-default topology suited to development and not to a shared marketplace. This sequence makes migrations explicit, separates the registry into a genuinely shared external service, makes it keep every listing field it acknowledges, moves it to PostgreSQL, and only then indexes filters against measured load. Not a roadmap goal — discovery semantics do not change — but it is what lets one registry serve more than one seller's storefront.

```text
add-database-migration-commands ──► separate-marketplace-registry ──► migrate-registry-to-postgres ──► index-registry-filters
add-database-migration-commands ──► store-registry-listings-as-published ··► migrate-registry-to-postgres
```

`··►` is preferred order, not a dependency: landing `store-registry-listings-as-published` first puts its migration in the chain PostgreSQL inherits rather than adding it to both engines.

| Order | Change | Status | Acceptance boundary |
|---|---|---|---|
| 1 | [`add-database-migration-commands`](add-database-migration-commands/) | active | Explicit migration and runtime-guard behavior for VM and API-credit stateful roles; provisioning is the reference baseline. Five in-flight changes each add a migration that would have to conform, so landing this first is materially cheaper than retrofitting them |
| 2 | [`separate-marketplace-registry`](separate-marketplace-registry/) | active | External-registry provider default, explicit embedded profiles, and one canonical full URL |
| 2b | [`store-registry-listings-as-published`](store-registry-listings-as-published/) | active; proposal stage, own design review before any implementation plan; no roadmap goal blocks on it | The registry stops acknowledging listing content it discards: a field it accepts is stored and served, a field it will not store is refused at publish. The review chooses between storing the published document opaquely and closing the served schema to the stored carriers. Its carrier policy is a decision input to `negotiation-driven-capacity-resize` §2 and `billable-capacity-reservations` |
| 3 | [`migrate-registry-to-postgres`](migrate-registry-to-postgres/) | blocked | Complete Alembic chain, preserved SQLite state, Secret-backed PostgreSQL rollout; waits for external infrastructure and step 2 |
| 4 | [`index-registry-filters`](index-registry-filters/) | deferred | Activate only after PostgreSQL workload measurements exceed a named p95/SLO threshold |

## Lesser goal — Package and release readiness

**What it adds up to.** Internal dependencies now install from built wheels and packaging checks cover the repository's environments and images. Type checking is advertised but not enforced, and the publisher inventory does not match the packages that exist. The remaining changes restore the checks and reconcile the distribution graph. Not a roadmap goal — no behavior changes — but nothing outside this repository can consume the packages until it is done.

Two changes joined this campaign on 2026-09-02. The first completed and was archived on 2026-09-04: the settlement client is published to the public index, every consuming lockfile resolves it from there, the release gate is off the build and test path, and `.dist` holds only what this repository builds. It left one residual, named below, that no change yet owns. Separately, twenty-eight distributions reach public PyPI on every merge to `main` with no gate — which is how `arkhai-kit-hosted-settlement` 0.1.4 came to be published declaring a dependency PyPI does not carry, uninstallable for everyone outside this repository and, because PyPI is write-once, not correctable in place.

```text
publish-wheels-through-a-gate (its prerequisite archived 2026-09-04)
converge-python-packaging (archived) ──► type-core-packages ──► configure-pypi-trusted-publishing
(remove-relative-uv-sources: superseded and archived)
```

`converge-python-packaging` absorbed the open sections of `remove-relative-uv-sources` (its path-source guard, remaining cutovers, and `reinit` inventory) when it was planned on 2026-09-27; that change's completed CI wheelhouse repair is unaffected, and it has no remaining open work.

| Order | Change | Status | Acceptance boundary |
|---|---|---|---|
| 1 | [`publish-wheels-through-a-gate`](publish-wheels-through-a-gate/) | active; the interim half needs no prerequisite | Automated publication to PyPI stops; merge to `main` publishes all twenty-eight distributions to the development registry; one inventory-derived list replaces the two enumerations; a human-invoked promotion copies bytes to PyPI and fails the whole set if any version there holds different content |
| — | [`remove-relative-uv-sources`](archive/2026-09-28-remove-relative-uv-sources/) | **archived as superseded** 2026-09-28; remaining work transferred to `converge-python-packaging` | Its CI wheelhouse repair landed separately; the remaining package cutover and checks were completed by `converge-python-packaging` |
| 2 | [`type-core-packages`](type-core-packages/) | active after affected public surfaces stabilize | Restore advertised checks, ratchet package by package, verify `py.typed` in installed wheels. Its deferred `kit/site` question should wait for the kit-composition goal's extraction scope |
| 3 | [`configure-pypi-trusted-publishing`](configure-pypi-trusted-publishing/) | externally blocked | Reconcile the consumable distribution graph and verify trusted publishers plus PyPI-only downstream installation. Should follow the kit extraction, which changes wheel contents |
| — | [`converge-python-packaging`](archive/2026-09-28-converge-python-packaging/) | **archived** 2026-09-28. Promoted to `deployment-state`, `planning-governance`, `docs/development/BUILD_AND_PACKAGING.md`, and `docs/development/RELEASING.md` | Two slices. Environments: `reinit`, image installs, and a new `make lock` derive internal-package flags from each project's lock through one script; the three outlier images install from their lock; Python 3.13 declared once; `make check-packaging` replaces `check-reinit` and `check-internal-locks` and joins every closeout. Layout: nine projects move to one package under `src/` (six nested-import projects plus the registry, API-credits service, and e2e harness), the eight published ones under new versions, and every project installs editable. Design reviewed and planned 2026-09-27 |

The two sequences are independent of each other and share this campaign because they share its completion test: nothing outside this repository can install what it publishes.

**Unowned residual from the archived first change.** Twelve projects declare an uncapped `requires-python = ">=3.12"` and depend on `pydantic` or `fastapi`: `core/registry`, `core/storefront`, `domains/bare_metal` and its `provisioning/adapter`, `domains/vms/provisioning/adapter` and `client`, `kit/fulfillment`, `kit/resource-pools`, `kit/site-client`, `kit/site`, `provisioning/compute`, and `provisioning/compute/service`. `uv` selects the newest interpreter a project admits, `pydantic-core` publishes no wheel for it, and resolution falls into a source build that fails before any test runs. Twenty-two other projects already cap at `<3.14` and both CI workflows pin 3.13.7, so this is an unapplied convention rather than an open question. [`resolve-hosted-client-from-an-index`](archive/2026-09-04-resolve-hosted-client-from-an-index/) fixed only the two projects in its own path and recorded the rest as needing its own change, which no change yet owns.

`publish-wheels-through-a-gate` reads its package list from the cross-repository release inventory format, which is defined outside this repository, and uses a plain manifest until that lands.

`configure-pypi-trusted-publishing` overlaps `publish-wheels-through-a-gate` on the distribution inventory and on proving PyPI-only installation. Reconcile the two before either is archived rather than letting both claim the same acceptance.

## Lesser goal — End-to-end harness determinism

**What it adds up to.** End-to-end scenarios assert on internal identifiers and advance by waiting for poll intervals, which makes them slow, timing-sensitive, and expensive to extend to a second domain. These changes align scenarios with the fulfillment lifecycle contract and decide whether the harness becomes an independently consumable project. Not a roadmap goal, but three goal-owned changes each carry a task requiring observable barriers rather than sleeps, and all of them land here.

| Change | Status | Acceptance boundary |
|---|---|---|
| [`refactor-e2e-fulfillment-lifecycle`](refactor-e2e-fulfillment-lifecycle/) | implementation sections complete; live scenario verification and closeout remain | Scenarios assert on fulfillment identity rather than provisioning job identity. Its remaining validation must show the affected stages execute and pass against live services |
| [`extract-e2e-project`](extract-e2e-project/) | deferred | Activate only for a named external consumer, compatibility profile, and release owner |

## Lesser goal — Agent-driven issue-discovery harness

**What it adds up to.** `tools/issue-discovery` runs build and environment phases and turns failures into deduplicated issue candidates. It has no actor in it, its phase configuration names three directories that no longer exist, and no Make target invokes it. These changes repair it, declare a finite set of capacity scenarios it can validate without executing, establish who is allowed to perform which action, make a recorded run project into one deterministic result, and prove that supporting a second domain costs an adapter rather than a core edit. Not a roadmap goal — the harness is a tool and changes nothing the market can do. Its jurisdiction is documented in [`docs/development/TESTING.md`](../../docs/development/TESTING.md), which places it outside the four test levels rather than beside them.

```text
restore-issue-discovery-thin-runner ──► add-harness-scenario-contract ──┬──► add-harness-findings-projection ──► add-deterministic-regression-contract
                                                                        └──► add-harness-buyer-action-slice ──► add-future-domain-shape-validation
```

| Order | Change | Status | Acceptance boundary |
|---|---|---|---|
| 1 | [`restore-issue-discovery-thin-runner`](restore-issue-discovery-thin-runner/) | active | The inherited runner resolves against the current tree, drift fails at load rather than at runtime, and Make targets exist to invoke it. Removes the `TESTING.md` section describing a subsystem that has never existed on `dev`. Carries one open design question: the successor of the removed `service` workdir |
| 2 | [`add-harness-scenario-contract`](add-harness-scenario-contract/) | active | A finite set of capacity scenarios is declared and validated, executing nothing. Scenarios declare the hold posture they assume, name a refusal match mode rather than an exact string, and require per-buyer discovery evidence. Contention is declared over markets, not seller processes |
| 3a | [`add-harness-findings-projection`](add-harness-findings-projection/) | active | A recorded event corpus projects to one deterministic result. Offered demand, served capacity, and load-generator limit stay distinct and are never derived from one another. The existing issue engine gains update and reopen and no other mutation |
| 3b | [`add-harness-buyer-action-slice`](add-harness-buyer-action-slice/) | active | Documented buyer actions are performed by the actor through the entry points the quickstart names; the controller has no code path that performs one. Requests are frozen before release, observation is independent of the observed, and live adapters fail closed on configuration |
| 4 | [`add-deterministic-regression-contract`](add-deterministic-regression-contract/) | active | What a generated regression must be: representation separated from its execution adapter, evidence that it fails without the fix it protects, an evidence class travelling with the artifact that refuses a concurrency or capacity claim, sanitization through the same allowlist as any other crossing, and placement at the level owning the behaviour it protects. Generates nothing |
| 4 | [`add-future-domain-shape-validation`](add-future-domain-shape-validation/) | active | An adapter the runtime has never seen round-trips an opaque payload with no core edit. Prepared domains validate and dry-plan with zero effect on attempted execution. A testing seam, not a plugin platform |

One dependency points outside this campaign; a second, [`fix-vm-fulfillment-capacity-boundary`](archive/2026-09-28-fix-vm-fulfillment-capacity-boundary/), is archived, so a scenario can now assert that the GPU reserved is the GPU received. Separately, nothing the harness exercises can complete a buyer journey until a composed domain wheel-and-policy path exists here — and that dependency has no owner on this branch. The change previously named for it has never existed on `dev`, so the citation is not a stale link but an unowned requirement; `add-harness-buyer-action-slice` still names it in its proposal, design, and task 1.4, and cannot bind to a real target until a change on this branch owns the work. The `reinit` coverage gap the harness surfaced was resolved by [`converge-python-packaging`](archive/2026-09-28-converge-python-packaging/), which superseded `remove-relative-uv-sources`.

## Lesser goal — Reach hosts and VMs that have no inbound route

A rented node typically sits behind a firewall or NAT with nothing listening
from outside. Provisioning can name a host whose SSH answers on a tunnel port,
and the VM-creation path no longer depends on a relay management dashboard.
The remaining work proves the relay path on live hardware and lets an operator
register a host with its own SSH credential. The product already sells VMs on
hosts it reaches by tunnel; these changes make that path usable across independently
prepared hosts and relays without a management surface.

```text
never-strand-the-host-on-passthrough ──► (prerequisite for exercising any below on real hardware)
contain-embedded-host-key-material ──► relay-vm-access-without-a-dashboard §8 live verification
relay-vm-access-without-a-dashboard (implementation and promotion complete)
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`never-strand-the-host-on-passthrough`](never-strand-the-host-on-passthrough/) | implemented; promoted; live verification outstanding | Host preparation cannot render a rented machine unreachable. Passthrough viability is audited read-only before anything is written, unsafe IOMMU groups are refused rather than bound, device binding is scoped to a PCI address and applied after boot, and the rollback target is a state that contends for no device |
| [`contain-embedded-host-key-material`](contain-embedded-host-key-material/) | planned; no blocking dependency | A host may be reached with its own SSH key rather than the deployment's shared one. Decrypted key material exists only for the operation that needs it, on failing paths as well as succeeding ones. Takes no position on who generates a host's keypair |
| [`relay-vm-access-without-a-dashboard`](relay-vm-access-without-a-dashboard/) | implemented and promoted; live-hardware verification (sections 6 and 8), decision gates 1A.7 and 2A.7, and closeout remain | VM tunnel allocation and verification stop depending on a relay dashboard, DNS name, certificate, and second credential. A relay becomes an administered resource with its own controller, holding its own window and encrypted token, changeable against a running service rather than by redeployment, and no longer reverted when a pod restarts against an unchanged definition document. The host's management and buyer tunnel clients are split, and adding a VM stops restarting the tunnel client — and with it every buyer's live session |

`never-strand-the-host-on-passthrough` shares no code with the others and
blocks none of them. It is sequenced first because they are verified by
preparing and provisioning a real rented host, and host preparation is the step
that can lose the machine.

`contain-embedded-host-key-material` is what allows a host prepared by someone
else to be registered at all. Every host in an environment is currently reached
with one key, which is workable while one party operates them all and is not
workable for a rented machine whose operator supplies its own credential. It
shares no code with the relay work and either may land first.

`add-buyer-vm-connectivity-terms`, which would have negotiated the relay a VM's
tunnel used, was archived as superseded on 2026-09-25: the contract this campaign
promoted forbids per-request relay selection, and the host-side VM tunnel client it
built has one `serverAddr` for every rented VM. The relay itself is unchanged and is
the bootstrap path to every VM. A buyer-supplied first-boot configuration starting a
guest-side tunnel client would be the fresh change if a buyer ever needs to avoid the
seller relay's port; it belongs here if opened.

The relay and host-key work also serves Goal 1: provisioning owns the physical
facts and credentials that the storefront previously carried.

## Lesser goal — Hosted fiat settlement

**What it adds up to.** A buyer holding no wallet and no chain resources completes a deal through the shared hosted financial authority, and every refusal that path can produce is nameable from outside it. Four changes carry the funding contract itself: a durable core-owned buyer identity, the expanded signed payer/funding profiles consumed from the authority, and the two domains that compose them. The rest close gaps the protected Stripe lanes surfaced. Three landed and archived on 2026-09-04 — a refusal that names its cause instead of timing out, the return address the authority demands before it will refund a bank transfer, and one coordinate binding the hosted release. Still open are a response the client cannot authenticate, and the projections and partial dispositions those lanes assert on. Not a roadmap goal: the market sells the same things either way. It earns a campaign because these changes share one external dependency surface — an independently produced signed release and protected Stripe inputs this repository cannot supply — and because the lane work is only legible as a group.

```text
add-persistent-buyer-profiles ──► consume-expanded-stripe-funding ──┬──► add-api-credits-hosted-settlement
                                                                    └──► add-bare-metal-hosted-settlement

lane legibility:  name-unverifiable-responses
lifecycle depth:  project-an-authoritative-funding-loss, disburse-a-settlement-disposition
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`add-persistent-buyer-profiles`](add-persistent-buyer-profiles/) | active; no blocking dependency | A core-owned buyer profile selects a stable local buyer, retains exact signer history across rotation, and associates authority-owned opaque payer bindings without putting secrets in marketplace state |
| [`consume-expanded-stripe-funding`](consume-expanded-stripe-funding/) | active; depends on `add-persistent-buyer-profiles` and on an externally produced signed release | Exact versioned payer/funding profiles with persistent buyer ownership and off-session authorization, importing no Stripe models and weakening no storefront mediation or fulfillment gate |
| [`add-api-credits-hosted-settlement`](add-api-credits-hosted-settlement/) | active; local work complete, qualification externally blocked | A non-EVM buyer purchases and tops up API credits through the shared hosted authority by composing the mechanism-neutral seams rather than copying VM lifecycle code. Its open tasks need protected Stripe inputs and a signed producer acceptance record this checkout does not carry |
| [`add-bare-metal-hosted-settlement`](add-bare-metal-hosted-settlement/) | active; local work complete, qualification externally blocked | Bare-metal hosted settlement. Production qualification waits on operator-supplied signed manifests and protected Stripe inputs, plus a disposable real host on which access and later revocation can be observed |
| [`name-unverifiable-responses`](name-unverifiable-responses/) | active; no blocking dependency | A client refusing a response it cannot authenticate distinguishes that case from a malformed or legacy one, so an ordinary `404` stops being reported as a protocol fault |
| [`project-an-authoritative-funding-loss`](project-an-authoritative-funding-loss/) | active; no blocking dependency, and explicitly not externally blocked | Incident and blocked-delivery projections become readable on the public settlement payload rather than dropped by the hosted adapter. Unblocks the two `us_ach_debit.v1` lanes withheld as `loss_projection_unimplemented` |
| [`disburse-a-settlement-disposition`](disburse-a-settlement-disposition/) | active; no blocking dependency | An obligation's amount moves partially and in more than one direction; expiry becomes a mechanism's answer; the hosted rail gates on a declared capability, and rollback stays safe only while every disposition is degenerate |

The two qualification-blocked changes are blocked on inputs, not on each other: local deterministic contracts and generated configuration are complete in both, and neither substitutes for a protected run. `project-an-authoritative-funding-loss` states in its own proposal that nothing external blocks it — the producer release already carries what it consumes — which makes it the cheapest way to retire two permanently-excluded lanes.

## Independent active changes

Changes with no campaign; each stands alone.

| Change | Status | Audited scope |
|---|---|---|
| [`pools-6-fair-scheduling-policy`](pools-6-fair-scheduling-policy/) | design-gated; POOLS-7 blocker cleared 2026-08-06 | Fairness policy over contended capacity. Also owns refusing new admission and placement against a disabled host while honouring existing assignments and teardown, handed over by `project-capacity-resources-without-hosts`. Its stated blocker — transactional assignment state — has landed, but its design inputs changed: negotiable shapes and negotiation-time holds alter what contention means, so the fairness subject should be chosen against those rather than against July's inputs |
| [`fix-golden-image-config`](fix-golden-image-config/) | active | Align generated and consumed keys and deliver secrets through the provisioning Secret profile |
| [`add-full-stack-ci-job`](add-full-stack-ci-job/) | proposed; design not started; opened by `pass-through-storefront-config` finding 9 | One CI job that runs `make test`, `make build-dev`, and the Helm render tests together, so checks needing both Helm and a service environment — the storefront chart's chart-to-loader check — run rather than skip |
| [`deduplicate-dynaconf-bootstrap`](deduplicate-dynaconf-bootstrap/) | active | Parameterized kit/config construction with exact provisioning and e2e parity; storefront loader excluded. Useful precedent for the kit-composition extractions |

## Archived and superseded

`bare-metal-buyer-domain` and `market-platform-bare-metal-10-storefront-composition` were archived on 2026-09-26 as delivered rather than superseded: the parallel bare-metal producer this repository merged built the buyer package and the seller composition they planned. Their draft requirements were dispositioned one by one — promoted under another heading, dropped as process text, or migrated with a verification task to `bare-metal-and-credits-domain-stacks` and `bare-metal-mock-provisioned-deal` — in [`bare-metal-and-credits-domain-stacks/design.md`](bare-metal-and-credits-domain-stacks/design.md). Their directories are [`archive/2026-09-26-bare-metal-buyer-domain`](archive/2026-09-26-bare-metal-buyer-domain/) and [`archive/2026-09-26-market-platform-bare-metal-10-storefront-composition`](archive/2026-09-26-market-platform-bare-metal-10-storefront-composition/).

`add-buyer-vm-connectivity-terms` was archived as superseded on 2026-09-25 without implementation. Buyer-negotiated relay coordinates in the fulfillment request are forbidden by the contract `relay-vm-access-without-a-dashboard` promoted (`physical-provisioning`'s "Ansible fulfillment adapter": which relay a host dials is a physical fact, never selectable per request), and the mechanism it built has no per-VM relay choice to expose: the buyer-facing tunnel client runs on the host with one `serverAddr` for every rented VM, not in the guest as this change assumed. The seller-operated relay is the bootstrap path to every VM; a buyer wanting their own relay reaches the VM through its relay port once and starts a client inside the guest. A version that avoids the seller relay entirely would be a buyer-supplied first-boot configuration starting a guest-side client — a fresh change under the "Reach hosts" lesser goal, not this one. Its directory is [`archive/2026-09-25-add-buyer-vm-connectivity-terms`](archive/2026-09-25-add-buyer-vm-connectivity-terms/). `structured-capacity-requirements` was re-scoped and renamed to `settle-capacity-claim-vocabulary` the same day; the row above records what landed elsewhere.

`prune-storefront-database` was archived because dead policy tables are already gone and the remaining candidates carry continuation, idempotency, or observability state. `complete-development-documentation` was synchronized and archived after audience-owned documentation became permanent planning governance. `add-storefront-principal-authentication` and `provisioning-result-push-delivery` were superseded on 2026-08-06 by `service-identity-signing` and `replace-polling-with-authenticated-push` respectively.

`settle-listing-vocabulary` was archived on 2026-09-15. The offering mode is `offering_mode` and a seller's published shape is `listing_resource` on every surface, the provisioning contract is on 2.0 admitting major 2 only, and the requirements it added are live across [`openspec/specs/`](../specs/) -- site-capacity, registry-discovery, storefront-publication, compute-provisioning-contract, resource-pool-management, physical-provisioning and deployment-state. Its directory is [`archive/2026-09-15-settle-listing-vocabulary`](archive/2026-09-15-settle-listing-vocabulary/).

`add-registry-self-description` was archived on 2026-09-14 and its row removed from the independent-changes table: a registry now publishes one strict operator-authored descriptor through the existing signed-response path, and the requirement it added is live in [`openspec/specs/registry-discovery/spec.md`](../specs/registry-discovery/spec.md). Its directory is [`archive/2026-09-14-add-registry-self-description`](archive/2026-09-14-add-registry-self-description/).

Five changes this index still listed as active had in fact been archived, and their rows were removed on 2026-09-04: `add-settlement-plan-shapes`, `finish-buyer-cli-residue`, and `kit-owned-settlement-runtime` (all 2026-08-10), and `finish-settlement-mechanism-neutrality` and `contact-exchange-settlement-mechanism` (both 2026-08-19). The first three are under [`archive/`](archive/); the two 2026-08-19 archives were pruned once nothing active referenced them. [`add-development-roadmap`](archive/2026-09-04-add-development-roadmap/) was archived 2026-09-04, synchronizing the two `planning-governance` requirements that authorize `docs/development/ROADMAP.md` and make roadmap currency owed — neither had reached the permanent spec before archival. [`resolve-hosted-client-from-an-index`](archive/2026-09-04-resolve-hosted-client-from-an-index/) was archived the same day, promoting three `deployment-state` requirements: that an externally produced dependency resolves from a declared index, that release verification is a publication-time activity gating no build or test, and that deployment documentation states how such a dependency is obtained. [`add-host-ssh-port`](archive/2026-09-04-add-host-ssh-port/) and [`pool-declared-offering-modes`](archive/2026-09-04-pool-declared-offering-modes/) were archived the same day; their delta requirements had been promoted early but had since diverged from the change's accepted text, so the four affected requirements in `physical-provisioning`, `resource-pool-management`, and `site-capacity` were brought up to it first — recovering the repository's official capacity vocabulary and one missing scenario. Three hosted-settlement changes were archived the same day once their closeouts were worked: [`bind-one-hosted-release-coordinate`](archive/2026-09-04-bind-one-hosted-release-coordinate/), [`carry-the-payer-return-address`](archive/2026-09-04-carry-the-payer-return-address/), and [`name-a-refusal-that-will-not-converge`](archive/2026-09-04-name-a-refusal-that-will-not-converge/). The last two modify the same `test-compatibility` requirement from diverged bases, so the permanent spec carries the union of both rather than whichever archived last. They persisted here because campaign-index currency was owed by no closeout step until `openspec/README.md#plan-closeout-requirements` gained part 6.

Archived changes are pruned once no active change, permanent specification, or
document references them and their accepted requirements are live in
`openspec/specs/`; the archive is not a permanent record. Thirteen August 2026
archives were pruned on that basis: `add-hosted-fiat-settlement`,
`add-local-hosted-settlement-e2e`, `add-resource-and-settlement-cli-dsls`,
`replace-hosted-simulator-with-stripe-test-e2e`, `add-introduction-delivery-sinks`,
`contact-exchange-settlement-mechanism`, `finish-settlement-mechanism-neutrality`,
`build-hosted-producer-locally`, `confirm-checkout-was-completed`,
`consume-direct-instrument-setup`, `keep-a-parked-reason`,
`resolve-development-client-in-ci`, and `write-development-run-evidence`.
