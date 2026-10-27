# Design review: unbacked-bare-metal-listings (second round)

## Summary

**Purpose.** Goal 7 exists so a seller whose capacity the marketplace cannot admit against can still be discovered and introduced. Bare metal is the goal's primary domain, yet every bare-metal listing is still backed. This change lets bare metal publish unbacked listings that settle by introduction. It reuses the kit publication runtime, the declaration reader and the backing delegate that VM already uses, and deletes bare metal's last branch on a particular backing. Where designing this showed VM and bare metal diverging for no reason, it picks one behaviour for both. It also takes in twelve carried items: six Alkahest settlement questions and six defects found when bare metal was deployed with Helm next to Bob. One of those, stage events, goes to `redesign-storefront-stage-events`, now proposed on this branch.

**Scope and non-goals.** Four groups of work, delivered in three rounds (B+D, then C, then A):
- **A. Unbacked bare metal** and the unifications (decisions 1–15).
- **B. Alkahest settlement inputs** (16–19).
- **C. Deployment and test hygiene** (20–22).
- **D. The provisioning service** (23).

Non-goals: finite unbacked supply; hosted settlement over unbacked supply; unified delivery route surfaces; an accept reply carrying only the Agreement; a stage-event redesign; pipeline scenarios run against the Helm charts; the two-seller scenario.

**Central decisions, as revised since review 39.**
- **Delivery terms belong to the backing delegate.** The delegate carries or forbids them. Presence is defined per type: a boolean is present as `true` or `false`.
- **The view carries no backing label.** The shared carrier validates a view's terms against a backing its caller supplies (`backings`).
- **Pool context is resolved in the compute provisioning layer.** Resource views get it from the provisioning service's own resource pass, through `compute_provisioning`'s protocol. Views never fail the projection.
- **Optionless candidates are refused.** For an open listing, each mechanism is classified: a listing is closed only when every mechanism is ruled out by configuration, and held while any mechanism is unknown.
- **A new Alkahest chain probe produces reachability blockers.** It is built by `kit/storefront`'s client seam and run in the lifecycle loops. A chain not yet probed reads as reachability, and `ReadinessBlocker` gains a required `kind`.
- **Introductions are answered by one refusal in `kit/storefront`**, which decides by a new `completes_outside_settlement` stage declaration.
- **Settlement uses the committed plan**, including VM's admin dry-run verify, the heartbeat, and the interrupt check.
- **Buyers fund only what they derive.** A run-log written before release conditions were recorded is refused before funding.
- **Storefronts start degraded.** The VM and API-credit storefronts drop their in-process dependency preflights, and the VM chart gains a `startupProbe`.
- **`kit/site` signs a 500 after authentication without recording it.** Recording the outcome is the provisioning service's job.
- **Decision 25 is reaffirmed.** Upgrade order is said to be unable to matter in the supported deployment shape.

## Assessment

The revision answers review 39 thoroughly. Every finding was dispositioned, and 13 of the 14 are resolved in the files (F3 was reaffirmed).
- The new probe gives decision 7's hold branch a real producer.
- The per-mechanism classification fixes the mixed-blocker close.
- The pool-context and carrier seams are now named and placed by responsibility.
- The deltas say what the decisions say, including the modified publication requirement and the restored stale-input refusal.

The claims I checked against the tree hold:
- Pools cannot be hard-deleted (`kit/resource-pools/src/market_resource_pools/service.py:357-366`).
- An accepted plan carries an interruptible term (`kit/alkahest/src/market_alkahest/proposals.py:346`).
- `retired_pricing_keys` is a real VM category (`domains/vms/listings/src/arkhai_vms_listings/reconciler.py:381`).
- The bare-metal buyer pins `arkhai-core-buyer==0.5.0` (`domains/bare_metal/buyer/pyproject.toml:10`).
- Bare metal has no dependency preflight to remove.
- Nothing outside the kits parses a readiness payload through the model.

What now needs attention comes mostly from the new probe and the reworked rules meeting existing code:
1. **Cold start versus one-shot publication (F1).** "Not yet probed reads as reachability" combines with the API-credit storefront's startup seed, which runs before the loops start. The seeded listing the API-credit lane discovers would then never be created.
2. **The classification counts mechanisms the candidate cannot use (F2).** An unbacked listing whose contact is configured away is held for as long as an Alkahest chain it could never use is unreachable.
3. **The probe's scheduling and client rebuild sit in `kit/storefront` (F3).** That rides a recorded scope exception whose remedy moves this code out of the kit. Decision 9 is careful to keep the same kit mechanism-neutral.
4. **`kit/site` must change after all (F4).** It copies projected resources field by field and would drop `publication_view_problems`.

F5–F7 are smaller: probe semantics, the wording of decision 25, and an unowned limit with no roadmap entry. None is blocking.

## Questions

### consistency — Is the change consistent with the codebase and with itself, and are the earlier findings resolved?

**Review 39, finding by finding:**
- **F1 (no reachability producer).** Resolved. Decision 19 adds the probe, splits `chain_unreachable` (reachability) from `chain_id_mismatch` and `contract_missing` (configuration), and deletes the untyped resources. The settlement-configuration delta adds "Alkahest probes its chains apart from readiness". Its cold-start rule creates F1 below.
- **F2 (mixed blockers close).** Resolved for the case raised. Decision 7 now holds while any mechanism is unknown, and the delta has scenarios for the mixed case and for a mechanism reporting both kinds. A symmetric gap remains (F2 below).
- **F3 (Challenges D25).** Reaffirmed by the owner, and decision 25 now records the points and why it says they cannot arise. I accept the disposition. The stated reason overreaches slightly (F6 below).
- **F4 (degraded start contradicted).** Resolved. Both preflights and their settings are removed, a VM `startupProbe` is added, a failed client is rebuilt at its next probe, and the deployment-state delta forbids waits inside the process.
- **F5 (older run-log funds seller terms; wrong premise).** Resolved. The premise is corrected (`design.md:498-503`), and older run-logs are refused before funding, with a buyer-orchestration scenario.
- **F6 (other post-acceptance readers).** Resolved. Decision 16 lists the dry-run verify, the heartbeat and the interrupt. The plan does carry an interruptible term (`kit/alkahest/src/market_alkahest/proposals.py:346`) and a heartbeat in `service_terms` (`core/src/market_core/schemas.py:524-530`). The settlement-servicing delta adds a preview scenario.
- **F7 (lifecycle delta wider than decision 19).** Resolved. Decision 19 covers address, chains and key. The stale-input refusal is kept in both the requirement and the scenario (`specs/storefront-publication/spec.md:319`, `:376-379`), and the known limit is widened.
- **F8 (unmodified publication requirement; API credits).** Resolved. "Publication derives all ready settlement options" is modified, with a per-pool scenario; the API-credit limit and the rule for supplied escrows are recorded. The limit has no roadmap entry (F7 below).
- **F9 (carrier label source).** Resolved. `trusted_bare_metal_projection(*, site_id, projection, backings)`, with the storefront reading pools before views.
- **F10 (pool-context seam).** Resolved as placement: the protocol is in `compute_provisioning` and the service's resource pass supplies the context. The claim that the two reads need not agree holds, since backing and provider are immutable and pools are never hard-deleted. But "`kit/site` does not change" is contradicted by the tree (F4 below).
- **F11 (`kit/site` replay outcomes).** Resolved. Decision 23 and the delta separate the two middlewares, with an API-credits scenario.
- **F12 (derivation log semantics).** Resolved. The log is keyed by source and site; a site with no cycle since start is absent; the example uses `retired_pricing_keys`.
- **F13 (smaller gaps).** Resolved. The adapter's declaration, the presence rule, and the refusal's home and its new declaration are all named.
- **F14 (stale `tasks.md`).** Resolved. The header is rewritten, gate 1.14 appended, 2.1 annotated, and decision 26 corrected.

**03-orchestrator R1 and R2, and 60-orchestrator O3.** These are workflow observations. R1 is fixed in the harness, and R2 and O3 are for the owner's tooling. None bears on this change's design.

**New claims.**
- Decision 19's statement that nothing parses a status payload through the model holds: `ReadinessBlocker` and `MechanismReadiness` are constructed only inside the kits. But the settlement runtime builds its own `not_configured` and `disabled` blockers (`kit/settlement-runtime/src/market_settlement_runtime/configuration.py:631-658`), which decision 19's "set by every preflight" does not cover (F5).
- Decision 20's removal of the VM preflight leaves `load_site_projections` as the next step, and `poll_once` records failures rather than raising (`kit/capacity-publication/src/market_capacity_publication/site_projections.py:155-162`), so a degraded start holds.
- Decision 19's API-credit rule contradicts the API-credit startup order (F1).
- Decision 4's "`kit/site` … do not change" is contradicted by `kit/site/src/market_site/projections.py:107-121` (F4).

**Proposal versus decisions.** `What Changes` now matches the decisions, including the probe, the removed preflights and the two middlewares. The Impact section still says "`kit/site` and `kit/resource-pools` otherwise unchanged" (`proposal.md:148-149`) (F4).

### direction — What would I change?

I engage each decision; where nothing changed since review 39, my earlier view stands.

**Group A**
- **D1–D3, D8, D11–D13, D15:** agree, unchanged.
- **D4 (pool context in `compute_provisioning`):** agree. The service resolving context in its own resource pass keeps `kit/site` free of pool state, which `ARCHITECTURE.md:214` asks for. The responsibility-based placement is better than the `kit/site` plumbing I proposed in review 39. The pass-through gap is F4.
- **D5:** agree. The presence rule now handles the boolean.
- **D6:** agree. A caller-supplied `backings` is the right split between the reader and the carrier.
- **D7:** agree with hold-when-unknown. I challenge it on one further point: which mechanisms are classified (F2).
- **D9:** agree. A dedicated `completes_outside_settlement` declaration is better than overloading `fulfils_through_capacity`, for the reason the design gives: hosted settlement over unbacked supply would take settlement without delivering through capacity.
- **D10:** agree.
- **D14:** agree.

**Group B**
- **D16–D18:** agree. Refusing older run-logs is the honest choice, and the exposure is limited to runs accepted but not yet funded across the upgrade.
- **D19:** agree with the probe and with keeping it apart from readiness. Probing inside the preflight would call the chain once per candidate per cycle. I would change two things:
  - the cold-start rule, which must not defeat publication paths that do not reconcile (F1);
  - where the scheduling lives (F3).

**Group C**
- **D20:** agree. Removing the in-process preflights follows the same reasoning as removing the init containers. With the rebuild-on-probe rule, the service now recovers from a chain that is down at start.
- **D21, D22:** agree, unchanged.

**Group D**
- **D23:** agree with the split.

**Handed elsewhere**
- **D24, D26:** agree.
- **D25:** I accept the owner's reaffirmation on the substance. The stated mechanism needs a word of correction (F6).

**Cadence:** agree. Round 1 now carries the probe that both later rounds depend on.

### architecture — Layers, authority, and the interfaces the design creates or changes

**1. Delegate operations `carry_delivery_terms` and `delivery_term_constraints`**
- *Callers:* the bare-metal adapter's view builder, `TrustedBareMetalResource`, and `BareMetalListing`.
- *Seams:* the adapter now declares the contracts distribution.
- *Semantics:* defined per type, and the delta has a scenario for `available: false`.
- *Versions:* covered by decision 25.

No gap.

**2. `InventoryViewProjection.resource_views(declaration, *, pool)`**
- *Callers:* the VM and bare-metal adapters, and the service's resource pass.
- *Seams:* the resource pass reads pool rows through one row-to-context function shared with `load_capacity_pool_metadata`. But the new per-resource `publication_view_problems` field reaches the wire only through `kit/site`'s `resource_pool_projection`, which builds each projected resource from an explicit list of fields and copies `publication_views` but nothing else (`kit/site/src/market_site/projections.py:107-121`). `kit/site` must change, and so should the site-client fixture (`kit/site-client/src/market_site_client/fixtures/resource_pools.py:43-66`) (F4).
- *Semantics:* a pool created between the two reads has no metadata and resolves as unresolvable under `read_site_declarations`, consistent with decision 4.
- *Versions:* an older storefront reads projected resources as raw mappings and ignores the new field.

**3. `trusted_bare_metal_projection(*, site_id, projection, backings)`**
- *Callers:* publication, the listing-source check (`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/listing_source_check.py:111-117`, which must now read pools before views), and the site's builder.
- *Semantics:* a pool absent from `backings` gets no term check.

No gap.

**4. The `PublicationSource` close hook and per-mechanism classification**
- *Callers:* VM's and bare metal's close paths.
- *Semantics:* the delta defines the cases "ruled out by configuration", "unknown", "no clause", and "both kinds". It does not say which mechanisms are classified, all configured or only those admissible for the candidate's backing (F2).

**5. The site-derivation log**
- Keyed by source and site, with defined absence.

No gap.

**6. The introduction refusal and `completes_outside_settlement`**
- *Callers:* VM's and bare metal's settle routes, and bare metal's fulfillment routes.
- *Seams:* `kit/storefront` already holds framework-free deal-control route services (`kit/storefront/src/market_storefront_kit/deal_control_routes.py`) and `LifecycleRouteError` (`lifecycle_routes.py`).
- *Semantics:* the domain supplies the declaration and the wording.

No gap.

**7. The Alkahest chain probe**
- *Callers:*
  - Alkahest readiness reads the last result.
  - Status reports it.
  - Decision 7's classification consumes its kind.
  - The API-credit create path and the startup seed reach readiness before any probe has run (F1).
- *Seams:*
  - The probe logic is in `kit/alkahest`.
  - Construction, scheduling and rebuild are in `kit/storefront`, on the excepted edge to `kit/alkahest` (F3).
  - Loops are registered by each domain (`domains/vms/storefront/src/market_storefront/startup.py:225`, `domains/apicredits/storefront/src/apicredits_storefront/startup.py:125`), so "with no domain code" needs a stated mechanism (F3).
  - A rebuilt client must reach consumers that took the client map at composition (`kit/storefront/src/market_storefront_kit/alkahest_clients.py:51-106` returns a plain dict) (F5).
- *Semantics:* defined for not-yet-probed, timed-out and wrong-chain results. Not defined for a result that ages while the loops are held, or for the probe's loop name, route and step (F5).
- *Versions:* the `kind` field is safe on the wire.

**8. `ReadinessBlocker.kind`**
- Required. The runtime's own `not_configured` and `disabled` blockers need it too (F5).

**9. The accept reply, the buyer plan check, and refusal of older run-logs**
- Covered in review 39, now defined.

**10. Signed 500 after authentication**
- Two defined behaviours.

**11. Startup refusal of an unserved provider**
- Unchanged.

### documentation — Destinations, deltas, open questions, citations

**Destinations.** Every decision has one. The revision adds the `market-composition` and `settlement-configuration` companions for decision 9's declaration and decision 19's probe.

**Deltas.**
- Each new behaviour has WHEN/THEN scenarios.
- The modified "Publication derives all ready settlement options" now agrees with decision 7.
- The settlement-configuration delta's kind requirement covers "not yet probed". Its wording, "Each mechanism's preflight MUST set the kind", misses the runtime-created blockers (F5).
- The deltas describe only behaviour this change implements.

**Open questions.** There are none, and none is prescribed elsewhere.

**Citations.**
- `openspec/changes/redesign-storefront-stage-events/` now exists.
- The cited paths resolve.

**Roadmap.** Decision 19 records an unowned API-credit limit, but the ROADMAP promotion list names only Goal 7 and Goal 6's unpinned row (F7).

### scope — Has the scope grown?

Since review 39 the scope has grown a little:
- the chain probe;
- removal of two in-process preflights and their settings;
- a new stage declaration.

Each follows from a finding, and none would close out better as its own change. The probe could have been split, but decision 7's hold depends on it, so keeping it here is right. Nothing gives the change a prerequisite it could close out without.

### readiness — Is the design ready for planning?

No related change must land first. `tasks.md` now describes the settled design, through gate 1.14. Nothing blocks. F1–F4 should be dispositioned before planning, because they change what round 1 (F1, F3) and round 3 (F2, F4) must build.

## Findings

### F1 — "Not yet probed reads as reachability" defeats the API-credit startup seed, which runs before the loops start, so the listing the API-credit lane discovers is never created

- **Lens:** consistency
- **Basis:** evidence
- **Severity:** should
- **Evidence:**
  - `design.md:638-643`: the probe runs in the lifecycle loops, and "A chain not yet probed since start reads as reachability".
  - `design.md:589-591`: in API credits an unready Alkahest yields no option for supplied escrows either.
  - `specs/storefront-publication/spec.md:433-437` and `:441`: such a listing "MUST NOT be created".
  - `domains/apicredits/storefront/src/apicredits_storefront/startup.py:116-126`: `_seed_demo_listing()` runs before `register_api_credit_loops` and `loops.start_loops`.
  - `domains/apicredits/storefront/src/apicredits_storefront/services/listing_service.py:115-136`: supplied escrows with no clauses still read readiness, and "no settlement alternative is ready" is raised.
  - The seed's failure is only logged (`startup.py:279-280`).
  - `domains/apicredits/storefront/storefront.credits.toml:152-165` and `domains/apicredits/compose.yml:140-142`: the lane self-seeds.
  - `e2e-tests/tests/e2e/roles/scenarios/apicredits/test_credits_deal_buyer_cli.py:161-173`: the scenario discovers `weather-api`.

Decision 19 chose the cold-start rule so that a fresh storefront holds its open listings rather than closing them. That is right for paths that reconcile. Paths that publish once are a different matter: the API-credit startup seed, and an operator's `publish_from_quota` right after a restart. Both run before any probe and would always see Alkahest as unready. The seed is the concrete case. Under decisions 19 and 7 together, the API-credit lane's seeded listing is never created, its discovery stage finds nothing, and nothing retries. An operator's create in the first interval after a restart fails the same way, naming `alkahest.chain_unreachable` for a chain that is up.

**Suggested action:** state the cold-start rule for paths that do not reconcile. Either:
- run one bounded probe pass (5 s per call, non-fatal) as a startup step before any startup publication, so "not yet probed" lasts only until that pass completes; or
- move the API-credit seed after the first probe, as a step that retries.

The first is simpler and also covers operator creates. Add a scenario: an API-credit storefront starting with its chain up publishes its configured seed.

### F2 — Challenges D7: classifying every configured mechanism lets an outage on a mechanism the candidate could never use hold a listing whose only usable mechanism is configured away

- **Lens:** direction
- **Basis:** judgement
- **Severity:** should
- **Evidence:**
  - `design.md:244-268`: "When any mechanism is unknown, the listing is held … because the offer it published is still one the storefront would make once the chain answers."
  - `specs/storefront-publication/spec.md:87-93`.
  - `kit/resource-pools-contracts/src/market_resource_pools_contracts/backing.py:168`: `admissible_settlement` drops capacity-fulfilled mechanisms for an unbacked candidate.
  - `openspec/specs/storefront-publication/spec.md:1182-1186`.

Decision 7's rationale for holding is that the published offer is still one the storefront would make once the unknown mechanism answers. For an unbacked candidate that holds only for mechanisms the candidate can use.

Take the supply decision 14 builds: a bare-metal storefront offering Alkahest for its backed pools and contact exchange, through a pool override, for its unbacked pool. The seller removes the contact configuration, so the unbacked listing's only mechanism is ruled out by configuration, and meanwhile Alkahest's chain is unreachable or misaddressed. The rule as written holds the listing, still advertising an introduction the storefront can no longer make. It stays that way for as long as a chain it could never settle through stays down. When the chain answers, admissibility drops Alkahest and the listing closes, so the hold only postpones a close that is already due.

This mirrors the case review 39 F2 raised:
- an unrelated *configured* mechanism must not turn a hold into a close;
- an unrelated *unknown* mechanism should not turn a close into a hold.

**Alternatives:**
- **(a)** Classify only the mechanisms admissible for the candidate's backing, after `admissible_settlement`. This is cheap, because the runner already has that set.
- **(b)** Keep classifying all mechanisms, and accept indefinite holds for unbacked supply.

**Suggested action:** (a). Reword the delta to "each mechanism admissible for the candidate's backing", and add a scenario: an unbacked listing whose contact is configured away closes while Alkahest is unreachable.

### F3 — The probe's construction, scheduling and client rebuild go into `kit/storefront` on a recorded scope exception whose remedy moves that code out of the kit

- **Lens:** architecture
- **Basis:** guidance
- **Severity:** should
- **Evidence:**
  - `design.md:634-637`: "`kit/storefront`'s Alkahest client-construction seam builds it … with no domain code".
  - `docs/development/ARCHITECTURE.toml:280-286`: the scope exception `arkhai-kit-storefront` to `arkhai-kit-alkahest`, owned by `move-escrow-into-alkahest`, whose stated remedy is "The Alkahest client factory becomes the Alkahest registration's typed resource model".
  - `docs/development/ARCHITECTURE.md:149`: "None of these is a sanctioned edge"; `ARCHITECTURE.md:103`: "a mechanism-neutral kit never imports a mechanism kit".
  - `kit/storefront/pyproject.toml:10`.
  - `design.md:337-340`: decision 9 keeps the same kit free of mechanism wording.
  - Per-domain loop registration: `domains/vms/storefront/src/market_storefront/startup.py:225`, `domains/apicredits/storefront/src/apicredits_storefront/startup.py:125`.

`kit/storefront` holds Alkahest client construction only by a dated exception that is meant to disappear. Decision 19 adds Alkahest-specific behaviour on that edge: chain-ID and contract-code probing, Alkahest blocker codes, a per-chain schedule, and client rebuild. That makes the move `move-escrow-into-alkahest` plans larger. It is also the opposite of how decision 9 treats the same kit, keeping the introduction refusal mechanism-neutral because "a kit's scope is nothing".

Separately, "with no domain code" does not describe how the probe gets into the loops. Each domain registers its own loops, so either every domain registers a probe loop, or the shell does so on their behalf. The design says neither.

**Suggested action:**
- Put the probe's schedule, and the client map it rebuilds, behind the Alkahest registration's resources in `kit/alkahest`. Each storefront registers the resulting step as a loop beside its others, so domains add one line each.
- Or keep it in `kit/storefront` deliberately, record in `move-escrow-into-alkahest`'s proposal that the probe moves with the factory, and name how the loop is registered.

Either way, name the loop.

### F4 — `kit/site` must change to carry `publication_view_problems`, contrary to decision 4 and the Impact section

- **Lens:** consistency
- **Basis:** evidence
- **Severity:** should
- **Evidence:**
  - `kit/site/src/market_site/projections.py:107-121`: each projected resource is rebuilt from named fields, and only `publication_views` among the contributed ones.
  - `design.md:112`: "`kit/site`, `kit/resource-pools`, and core do not change".
  - `proposal.md:148-149`: "`kit/site` and `kit/resource-pools` otherwise unchanged".
  - `specs/physical-provisioning/spec.md:113-116`: "the provisioning service MUST carry them on the projected resource as `publication_view_problems`".
  - `kit/site-client/src/market_site_client/fixtures/resource_pools.py:43-66`.

The provisioning service's resource pass hands rows to `kit/site`'s `SiteProjectionService`, which builds the wire projection through `resource_pool_projection`. That function copies `publication_views` and nothing else from the contributed fields. A `publication_view_problems` field added by the resource pass would therefore be dropped before it reached a storefront, and decision 4's report, decision 10's `publication_view_unbuildable`, and the delta scenario "A projection cannot build a view" could not be observed.

The change needed is small and opaque: copy one more optional per-resource mapping. It does not add pool state to `kit/site`, so it fits the rejection in decision 4. But it is a `kit/site` change, plus a matching one in the site-client fixture that both sides of the boundary test against.

**Suggested action:**
- Name `kit/site`'s `resource_pool_projection` and the site-client fixture as changed, to carry `publication_view_problems` opaquely when present.
- Correct decision 4's sentence and the Impact section.
- Say that `kit/site` neither reads nor interprets the field.

### F5 — Probe and blocker-kind semantics left undefined

- **Lens:** architecture
- **Basis:** guidance
- **Severity:** minor
- **Evidence:**
  - `design.md:619-645`.
  - `docs/development/TESTING.md:159-171`, "Pause the loop, then advance it explicitly": each loop offers a pause and an explicit step, and the loop table lists every storefront loop.
  - `kit/settlement-runtime/src/market_settlement_runtime/configuration.py:631-658`: the runtime constructs `not_configured` and `disabled` blockers itself.
  - `kit/storefront/src/market_storefront_kit/alkahest_clients.py:51-106`: clients are returned as a plain dict at composition.
  - `specs/settlement-configuration/spec.md:38-43`.

Four gaps:
- **Stale results.** A probe result does not age. While scenarios or an operator hold the loops, readiness keeps reporting the last result however old it is. That is probably fine, but it should be said, the way the source-confirmation window is said for projections.
- **No name or row.** The probe loop has no name, no `run-cycle` route and no row in the `TESTING.md` loop table. End-to-end scenarios that hold the loops before a fresh storefront's first probe need to step it.
- **Rebuild needs a shared map.** "Rebuilt at its next probe" works only if every consumer reads clients from a map the probe updates, not from a copy taken at composition.
- **Runtime blockers need a kind.** A required `kind` must also be set on the runtime's own two blockers, which no preflight creates.

**Suggested action:**
- State that the result does not expire while held.
- Name the loop and its step, and add the `TESTING.md` row.
- State that clients are read through the probe-owned map.
- Extend "set by every preflight" to the runtime's `not_configured` and `disabled` blockers, which are configuration.

### F6 — Decision 25's reason overstates what one Helm release guarantees

- **Lens:** direction
- **Basis:** judgement
- **Severity:** minor
- **Evidence:** `design.md:786-802` ("upgrade together, so neither order occurs"); `docs/development/ARCHITECTURE.md:966-974`.

I accept the owner's reaffirmation that no mitigation is needed. But one release does not make a rollout atomic. A `helm upgrade` rolls the provisioning and storefront Deployments concurrently, and a rollback does the same, so for the length of a rollout an old storefront pod can read a new site's projection, or the reverse. The effect is the whole-site `site_projection_refused` hold the decision describes, and it clears at the first poll after both pods are current. Saying "neither order occurs" leaves a later reader believing a mixed-version window is impossible, which is what the Operators rule exists to prevent.

**Suggested action:** reword the decision: during a rollout or rollback of the one release, a brief whole-site hold can occur and clears once both pods are current, so no mitigation is needed.

### F7 — Decision 19's unowned API-credit limit has no roadmap entry

- **Lens:** documentation
- **Basis:** guidance
- **Severity:** minor
- **Evidence:**
  - `design.md:612-617`: "No change gives API credits a re-deriving publication path, so the limit is unowned".
  - `openspec/README.md`, "Documentation placement": the roadmap records "which change owns each open gap".
  - `docs/development/ROADMAP.md:280-288`.
  - `design.md:896-897`: the promotion list names only Goal 7 and Goal 6's unpinned row.

An API-credit listing keeps advertising an Alkahest option after Alkahest becomes unready. That is a deliberate known limit, but it is recorded only in a change document that will be archived. The roadmap's gap table is where unowned gaps are kept visible.

**Suggested action:** add the limit to the ROADMAP promotion list as an unowned gap row under Goal 6 ("an API-credit listing's options are fixed at creation, so an unready mechanism's option stays advertised until the seller closes it").

## Readiness

The design is close to ready for planning, and nothing blocks. Review 39 is fully dispositioned and its fixes are in the files. No related change must land first, and `tasks.md` now describes the settled design.

Before planning, the owner should disposition four findings:
- **F1:** the cold-start rule against one-shot publication.
- **F2:** which mechanisms decision 7 classifies.
- **F3:** where the probe's scheduling lives and how its loop is registered.
- **F4:** `kit/site` carrying the new field.

F1 and F3 shape round 1; F2 and F4 shape round 3. F5–F7 can be folded into planning.

<!-- reviewer-session: claude:be1e70bf-da28-4d13-9601-32d279dca3df -->
<!-- reviewer: claude claude-opus-5-5 high -->
<!-- reviewer-unavailable: codex gpt-6-sol: codex is not installed -->
<!-- reviewed-commit: 2c344acfe8800a414ac99b2bd9373699be633909 -->
