# Design review: unbacked-bare-metal-listings

## Summary

**Purpose.** Goal 7 exists so that a seller whose capacity the marketplace cannot admit against can still be discovered and introduced. Bare metal is the goal's primary domain, but every bare-metal listing is still backed. This change lets bare metal publish unbacked listings that settle by introduction. It uses the same kit publication runtime, declaration reader, binding, and backing delegate that VM already uses, and deletes bare metal's one remaining branch on a particular backing. While designing this, the author found several places where VM and bare metal diverge for no reason, and unifies them. The change also took in twelve carried items: six Alkahest settlement questions and six defects found when bare metal was deployed with Helm next to Bob. One of those items, stage events, is handed to a follow-up change.

**Scope and non-goals.** There are four groups of work:
- **A. Unbacked bare metal and the unifications.** Decisions 1–15.
- **B. Alkahest settlement inputs.** Verification against the committed plan, buyer-side derivation, refusing unpinned proposals, and an unready Alkahest instead of a fatal one. Decisions 16–19.
- **C. Deployment and test hygiene.** No dependency-waiting init containers, Helm test-pod labels, module-scoped holds. Decisions 20–22.
- **D. Provisioning service.** Startup refusal of unserved providers, and signed failures after authentication. Decision 23.

Non-goals: finite unbacked supply, hosted settlement over unbacked supply, unifying the delivery route surfaces, an accept reply that carries only the Agreement, a stage-event redesign, and running pipeline scenarios against the Helm charts. The two-seller scenario stays unowned.

**Central decisions.**
- **Delivery terms belong to the delegate.** Host identity, physical host, access methods and availability are carried or forbidden by the backing delegate through `carry_delivery_terms` and `delivery_term_constraints`.
- **The view carries no backing label.** The shared `TrustedBareMetalResource` carrier validates a view's terms against the backing its containing pool declares, and refuses the whole generation on a mismatch.
- **Views never fail the projection.** A view builder gets its pool's context and reports `publication_view_problems` instead of raising.
- **No option means no listing.** A candidate with no option is refused. If its listing is open, it is closed for a configuration blocker or held for a reachability blocker.
- **Introductions are answered from the stage.** Settle answers 409 and fulfillment answers 404.
- **One kit site-derivation log.**
- **Settlement uses accepted state.** Every domain verifies against the committed plan, and buyers fund only what they derive themselves.
- **Defects become readiness, not refusal.** Alkahest configuration defects become readiness blockers, and every blocker carries a kind.
- **Degraded start.** The VM storefront starts degraded instead of waiting in init containers.
- **Module-scoped holds** of shared services in every lane.
- **Three implementation rounds:** B+D, then C, then A.

## Assessment

The direction is sound, and group A is the strongest part. It reuses the kit machinery and the delegate rather than adding a bare-metal path. It also turns several real divergences into one rule each: the optionless listing, the introduction answer, and the derivation log. The claims about bare metal's refusal of unbacked pools, the host-less view rule, the escrow-negotiation guard that keeps unbacked listings away from host readers, and the fulfillment-route order all check out against the tree.

What most needs attention is a load-bearing assumption in groups B and C that the code does not support. **No settlement mechanism today ever reports that a dependency is unreachable** (F1). Alkahest's contract probe is wired into no storefront, Arkhai payments' readiness only checks configuration, and the readiness carrier has no kind field. Decision 7's hold branch, decision 19's blocker kinds, and decision 20's degraded start all rest on a reachability blocker that no code produces, so planning would have to invent the probe. That is a design decision, and it blocks.

The other findings fall into three groups:
- **Decisions to reaffirm or change.** F2 challenges decision 7's handling of mixed blockers. F3 challenges decision 25, because version skew in this change refuses a whole site's generation in both directions.
- **Factual claims the files contradict.** F4: VM's provisioning preflight, and no `startupProbe` on the VM chart. F5: `accepted_escrow_terms` is sent by all three domains, not only bare metal. F6: verification sites beyond the ones decision 16 lists. F11: kit/site has no replay outcomes to record into.
- **Interface seams the design leaves unnamed.** F9: who supplies the carrier's backing label. F10: how the resource pass gets pool context. F12 and F13: smaller gaps.

F7 and F8 are delta specs that say more, or less, than the decisions.

## Questions

### consistency — Is the change consistent with the codebase and with itself?

Mostly yes in group A, less so in groups B and C.

**Claims that check out:**
- Bare metal's unbacked refusal is the only backing branch outside the delegate: `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/site_reading.py:129-135`, `publication.py:553-556`.
- A host-less declaration projects without the view: `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/inventory_views.py:41-47`.
- Other malformed attributes (missing `physical_host_id`, `allocation_mode`, `access_methods`) raise into a 500 for the whole projection: `inventory_views.py:54-71`, `domains/bare_metal/src/arkhai_bare_metal/projections.py:45-52`.
- `trusted_bare_metal_projection` refuses a whole generation on any malformed view: `domains/bare_metal/src/arkhai_bare_metal/publication.py:39-81`.
- The `["ssh"]` defaults exist: `projections.py:49-52`, `schema.py:95-98`.
- Escrow negotiation on a listing with no accepted escrows is refused before the round hook reads host fields: `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/negotiation_runtime.py:480-483`.
- Exact selection of a non-capacity stage skips the host-reading admission check: `negotiation_runtime.py:582-593`.
- Bare metal's contact stage records the reveal as evidence, and VM's contact stage refuses settle with 409.
- Both buyer plugins register a root `settlement` group with no duplicate check: `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py:591-592`, `core/buyer/src/core_buyer/cli.py:585-587`.
- The init containers, the test-pod labels, the missing hook-delete policy, the eight pausing VM modules, and the unsigned 500 in both middlewares are as described.

**Contradicted or only partly true:**
- F1: no reachability blocker exists anywhere.
- F4: VM's provisioning preflight and the missing VM `startupProbe`.
- F5: `accepted_escrow_terms` is "sent only by bare metal" — false.
- F6: decision 16 lists only some of the verification sites.
- F11: kit/site has no outcome recording.
- F12: VM's `legacy_overrides_in_effect` category does not exist.

**Do the proposal's promises hold?** The `Why` holds. `What Changes` promises a listing "held when a mechanism is unready only because its chain or service is unreachable" (`proposal.md:43-46`) and a VM storefront that "reports them degraded" (`proposal.md:80-81`). Under the decisions as written, neither can be produced (F1).

**Internal consistency.** Deltas that differ from the decisions: F7 (the bare-metal lifecycle delta widens decision 19) and F8 (decision 7 versus the existing publication requirement). Decision 7's statement that API credits is unaffected does not survive decision 19 (F8).

### direction — What would I change?

I engage each central decision in turn.

**Group A**
- **D1 (one delegate)** and **D11 (delete the refusal):** agree. These are the change's reason to exist, and the tree confirms the refusal is the last label branch.
- **D2 (site and resource identity, no host fields):** agree. It matches VM's resource-granular identity.
- **D3 (site emits the view for unbacked supply):** agree. Deriving from the capacity declaration directly would create a second read path, as the design says.
- **D4 (views never fail the projection):** agree. The tree shows one declaration really can take down a site's projection. The rejection of write-time checks is sound under `ARCHITECTURE.md`'s "No new site read of pool state" rule (`docs/development/ARCHITECTURE.md:214`). The seam is underspecified (F10).
- **D5 (delivery terms as delegate operations):** agree. It follows the delegate pattern in `openspec/specs/resource-pool-management/architecture.md:77-82`, "each operation takes the caller's work as an argument". Removing the default is right under "Omission states no commitment". There are semantics gaps for a boolean term (F13).
- **D6 (no backing label on the view; refuse the whole generation):** I would not decide this differently. One parse rule for "the site sent a malformed view" is coherent. Its cost is that a mismatch holds every listing at the site, which the owner accepted. Two consequences need stating: who supplies the label (F9), and that version skew now triggers that whole-site hold (F3).
- **D7 (no option means no listing; close or hold):** the refusal itself is right, and so is the hold-versus-close test it borrows from `ARCHITECTURE.md`. I challenge the mixed-blocker rule (F2). More fundamentally, the hold branch has no producer (F1).
- **D8 (recheck reads held state):** agree.
- **D9 (introduction answered from the stage):** agree. One shared refusal decided by `fulfils_through_capacity` is better than patching bare metal's routes. The check order (ownership, then stage, then context) is right because an unbacked binding has no host. The package that holds the shared refusal is unnamed (F13).
- **D10 (one derivation log):** agree with one implementation and one status shape. Its semantics are incomplete (F12).
- **D12–D13:** agree. Both are confirmations of what is already composed.
- **D14 (evidence):** agree. Reusing VM's scenario stage for stage on shared stages follows the compute deal stages' driver pattern (`e2e-tests/tests/e2e/roles/helpers/compute_deal_stages.py:1-28`). Namespacing bare metal's `settlement` group and refusing duplicates is right, though it has a version consequence (F3).
- **D15 (single-site evidence closes Goal 7):** agree, given that one storefront serving several sites is not a goal.

**Group B**
- **D16 (verify against the committed plan):** strongly agree. The tree confirms every domain re-derives from the stored listing (`domains/vms/storefront/src/market_storefront/settlement_composition.py:290-331`, `domains/apicredits/storefront/src/apicredits_storefront/settlement_stages.py:299-341`). The list of sites is incomplete (F6).
- **D17 (buyer funds only what it derives):** strongly agree, and the tree shows the gap is wider than the design says. `core/buyer/src/core_buyer/orchestration.py:930-939` prefers the seller's terms on every path. The fallback for an older run-log reopens the gap (F5).
- **D18 (refuse unpinned proposals):** agree. Enforcing it both in the guard and at the kit chokepoint matches how the release condition is already enforced.
- **D19 (unusable Alkahest is unready):** agree with the principle that a storefront must not need Alkahest. Two parts conflict with the tree. The startup refusal it removes was justified by recovery resources (`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/runtime.py:846-849`), and the delta widens the removal beyond the decision (F7). Blocker kinds need a producer (F1).

**Group C**
- **D20 (degraded start):** agree. It is incomplete against the tree (F4).
- **D21 (test labels without `name`):** agree. The alternative of changing the selector really is immutable.
- **D22 (module holds):** agree. It generalises `convergence_paused` (`e2e-tests/tests/e2e/roles/helpers/compute_deal.py:160-193`). The source check must exempt the shared helpers themselves; planning can settle that.

**Group D**
- **D23 (unserved providers stop startup; signed failures):** agree for the provisioning service. Its kit/site half needs rescoping (F11).

**Handed elsewhere**
- **D24:** agree.
- **D25:** I challenge it (F3).
- **D26:** agree.
- **Cadence:** agree. B+D first is right given what groups A and C depend on, provided F1 is settled in round 1.

### architecture — Layers, authority, and the interfaces the design creates or changes

Placement is right. The delegate operations live in `kit/resource-pools-contracts`, beside the label, which both sides of the provisioning boundary consult. The carrier lives in the domain vocabulary package. The derivation log and close hook live in `kit/capacity-publication` and core's runner. Verification by obligation lives in `kit/alkahest`. No core package learns a mechanism, and `core/buyer` still imports no `kit/alkahest` (true today, and the design keeps it). The interfaces, one by one:

**1. Delegate operations `carry_delivery_terms` and `delivery_term_constraints`**
- *Callers:*
  - The bare-metal provisioning adapter's view builder, at the site.
  - `TrustedBareMetalResource`'s validator, at the site and the storefront.
  - `BareMetalListing`'s validator, since the table governs listings.
  - VM and API credits name no terms.
- *Seams:*
  - The adapter does not declare `arkhai-kit-resource-pools-contracts` and would now import it (F13).
  - The adapter reaches the delegate only through the new pool context (interface 2).
  - The storefront carrier needs a label from somewhere (F9).
- *Semantics:* the design does not define these cases (F13):
  - "Present and non-empty" for the boolean `available`, where `False` is a legitimate backed value.
  - Empty term mappings.
  - A term name the domain did not declare.
- *Versions:* see F3.

**2. `InventoryViewProjection.resource_views` with pool context and problems**
- *Callers:* the bare-metal adapter, the VM adapter (an implementer the design does not name), the service's resource pass, and kit/site's merge.
- *Seam:* kit/site calls the resource pass and the pool directory independently (`kit/site/src/market_site/projections.py:183-186`). The resource pass gets no pool rows (`provisioning/compute/service/src/compute_provisioning_service/services/capacity_inventory.py:74`). "The pool rows its metadata pass already reads" therefore needs a change in kit/site or in the service that the design does not name (F10).
- *Semantics:* problems are keyed by view ID, and absence means no problems. Every stored pool resolves at the site because startup refuses invalid declarations, so "unresolved context" cannot arise there. That should be stated.
- *Versions:* an older storefront reads projected resources as raw mappings and ignores the new field (`publication.py:57-98`), so this part is benign.

**3. The `TrustedBareMetalResource` carrier with `capacity_backing`**
- *Callers:* `trusted_bare_metal_projection`, used by publication, the listing-source check (`listing_source_check.py:111`) and status, and the site's view build.
- *Seam:* the joint per-generation reader with the older-producer rule lives in `kit/resource-pools` (`kit/resource-pools/src/market_resource_pools/site_declarations.py:104-137`). `arkhai_bare_metal` declares only the contracts package (`domains/bare_metal/pyproject.toml:13`). See F9.
- *Semantics:* defined for an unresolvable pool (no check). Undefined for who resolves a legacy-producer generation.

**4. The `PublicationSource` close hook and the typed refusal**
- *Callers:* VM's and bare metal's close paths. API credits does not use it.
- *Seam:* the runner has no typed refusal today, and an exception raised by `build_payload` is uncaught (`core/storefront` runner, per `publication_runner.py:336-339`). The design names the change.
- *Semantics:* reopening under the same identity is stated. That a reconciliation close is not a durable seller close is implied by "through reconciliation". Mixed blockers: F2.

**5. The site-derivation log and `publication_derivation` status**
- *Callers:* both storefronts' cycles, their status, and their logs.
- *Semantics:* not defined for a site before its first cycle, or for a shell composing both domains (F12).
- *Versions:* VM's status shape changes, and the Impact section names it.

**6. The shared introduction refusal**
- *Callers:* VM's and bare metal's settle routes, and bare metal's four fulfillment routes.
- *Seam:* the package that holds it is unnamed (F13).
- *Semantics:* stated for both answers and for the order of checks.

**7. The accept reply without `accepted_escrow_terms`**
- *Versions:* an older VM or API-credit buyer facing a new seller falls back to `build_escrow_terms` (`orchestration.py:933-939`), which is a safer path. A new buyer facing an older seller ignores the field. Benign in both directions.
- Older run-logs: F5.

**8. Verification by accepted obligation in `kit/alkahest`**
- *Callers:* the three domains' settle paths, and also VM's admin dry-run verify and the interrupt path (F6).

**9. Blocker kind on `ReadinessBlocker`**
- *Semantics:* there is no producer for "reachability" (F1).
- *Versions:* `ReadinessBlocker` is `extra="forbid"` (`kit/settlement-runtime/src/market_settlement_runtime/configuration.py:43-63`). Any component built before this change that validates a status payload through it would reject the new field. Planning should confirm whether a CLI parses status through it.

**10. The core buyer's duplicate-root refusal**
- *Versions:* an upgraded core buyer next to an older bare-metal plugin, with VM also installed, refuses to start entirely (F3).

**11. Signed 500 after authentication**
- Fine for the provisioning service. Not as stated for kit/site (F11).

**12. Startup refusal of an unserved provider**
- *Semantics:* stated, including for disabled pools.
- The delta says "A service hosting the pool authority". That covers the API-credits service too, while decision 23 names only the provisioning service. Planning should say whether the API-credits service is meant to be covered.

### documentation — Destinations, deltas, open questions, citations

**Destinations.** Every material decision names a permanent destination in "Permanent documentation" and the proposal's "Knowledge to promote", including the `ARCHITECTURE.md` principles and the `TESTING.md` wording.

**Deltas.**
- The deltas generally carry WHEN/THEN scenarios.
- Two modify less, or more, than they should (F7, F8).
- The added "Readiness blockers state their kind" sits beside "Common sanitized mechanism readiness" (`openspec/specs/settlement-configuration/spec.md:65-72`) without modifying its field list. That is acceptable but worth folding into the modification.

**Open questions.** There are none, so nothing is prescribed elsewhere.

**Citations.** Every `openspec/`, `docs/`, and `e2e-tests/` path cited resolves. The change names `redesign-storefront-stage-events` as "proposed in a worktree from dev". It does not exist on this branch, so permanent documents must not cite it until it lands.

### scope — Has the scope grown?

Yes, a great deal: from one refusal lifted to four groups and twelve carried items. The owner chose that knowingly, and the cadence keeps each round reviewable. Groups B and D could each have closed without A. Folding them in is defensible only because A's no-option rule needs B's readiness kinds. Two pieces would be better owned elsewhere:
- The kit/site half of decision 23 adds replay outcome recording to a store that has none, which overlaps `redesign-authenticated-replay-state` (F11).
- A chain reachability probe, if F1 is answered by adding one, may be large enough to warrant its own change.

Nothing gives the change a prerequisite it could close out without.

### readiness — Is the design ready for planning?

No prerequisite is open. Every dependency is archived, as the change index confirms. But the design is not ready.
- **Blocking:** F1 needs a decision, either a reachability probe or no hold branch.
- **Should:** F2 and F3 need the owner to reaffirm or change decisions 7 and 25. The other should findings correct facts planning would otherwise build on.
- **Minor:** the existing `tasks.md` describes the 2026-10-14 design, not the settled one (F14).

## Findings

### F1 — No mechanism produces a reachability blocker, so decision 7's hold branch, decision 19's blocker kinds, and decision 20's degraded start rest on behaviour nothing provides

- **Lens:** consistency
- **Basis:** evidence
- **Severity:** blocking
- **Evidence:**
  - `kit/settlement-runtime/src/market_settlement_runtime/configuration.py:43-63`: `ReadinessBlocker` has only `code` and `message`.
  - `kit/alkahest/src/market_alkahest/settlement_config.py:262-285`: the contract probe runs only when a composition passes `contract_probe`. Any exception and any missing contract both become `alkahest.contract_probe_failed`.
  - No production composition passes `contract_probe`, `observed_chain_id`, `required_addresses` or `deployed_contracts`. They are passed only in tests. VM's resources are at `domains/vms/storefront/src/market_storefront/settlement_composition.py:883-896`.
  - `kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py:208-254`: readiness checks configuration only.
  - `design.md:201-208` (D7 reachability branch), `design.md:479` (D19), `design.md:498-500` (D20).
  - Delta scenarios: storefront-publication "An open listing's mechanism is unreachable"; deployment-state "The VM storefront starts before its registry and chain" ("Alkahest unready with a reachability blocker"); settlement-configuration "A chain cannot be reached".

The design treats "unready because readiness could not be determined" as something that exists today and only needs labelling ("each mechanism's preflight sets it"). In the tree, no storefront's Alkahest readiness touches a chain, so an unreachable chain leaves Alkahest *ready*. The only probe that could touch one conflates "could not reach" with "not deployed". Arkhai payments never contacts its service during readiness.

As written, the hold branch of decision 7 is never taken. The deployment-state scenario cannot pass. Every blocker would be "configuration", so the runner would close every optionless listing, including any that a real reachability problem should have held. Adding a probe is itself a design decision that planning must not invent:
- which compositions supply it, and what it calls;
- how often it runs: once per cycle, or cached;
- its timeouts;
- how "not deployed", a configuration fault, is told apart from "unreachable".

**Suggested action:** decide in the design. Either:
- **(a)** add a chain reachability probe: name the composing packages, the call, its cadence and timeout, and split `contract_probe_failed` into an unreachable code (reachability) and a missing-contract code (configuration); or
- **(b)** state that no mechanism currently reports reachability, keep the kind field for future use, and rewrite decision 20 and the deployment-state scenario so an unreachable chain does not claim an unready Alkahest.

Option (b) keeps decision 7 truthful and the scope smaller.

### F2 — Challenges D7: a misconfigured second mechanism turns an outage hold into a close

- **Lens:** direction
- **Basis:** judgement
- **Severity:** should
- **Evidence:**
  - `design.md:192-211`: "the runner calls it on a typed refusal whose blockers include a configuration blocker".
  - Delta storefront-publication, "A compute candidate with no settlement option yields no listing": "when any mechanism is ruled out by a configuration blocker … closed".
  - `docs/development/ARCHITECTURE.md:564-574`, "Holding or closing a listing".

The design's rationale is `ARCHITECTURE.md`'s test: close when the storefront's own configuration means it cannot say what it would sell, and hold when an input is unknown ("Unknown is not unready").

The rule as written does not apply that test in a mixed case. Take a listing that published only an Alkahest option. Its chain becomes unreachable (reachability), while a contact section with no contact for the listing's origin is also configured (configuration). The listing closes. With no contact section at all it would be held. The last offer published (Alkahest) is still one the storefront would make once the chain answers, so the architecture's test says hold. Configuring an unrelated, unusable mechanism should not decide whether an outage delists supply.

**Alternatives:**
- Close only when every mechanism is ruled out by configuration, and hold whenever any mechanism is unknown. This is simple, and it matches "unknown is not unready".
- Decide per previously published option. This is more precise, but it needs the last published options to be read in the runner.

**Suggested action:** the first alternative. Change the runner's condition to "all blockers are configuration blockers", and add a scenario for the mixed case.

### F3 — Challenges D25: this change's own version skew refuses a whole site's generation, and the architecture asks for that to be recorded

- **Lens:** direction
- **Basis:** guidance
- **Severity:** should
- **Evidence:**
  - `docs/development/ARCHITECTURE.md:966-974`: "Designs record where such ordering would matter."
  - `design.md:591-595`.
  - `domains/bare_metal/src/arkhai_bare_metal/projections.py:45-47`: `host_id`, `physical_host_id` and `available` are required.
  - `domains/bare_metal/src/arkhai_bare_metal/publication.py:60-74`: every bare-metal view in every pool is validated, before any pool-level refusal.
  - `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/inventory_views.py:37-72`: today's builder emits a view for any host-bearing declaration, whatever the pool's backing.
  - `core/buyer/src/core_buyer/cli.py:585-587`.

Decision 25 records nothing, on the ground that "upgrade order will not matter until something other than a storefront and provisioning pair is deployed". The architecture rule exists precisely so that such points are written down for the first major release, and this change has three:
1. **New site, older bare-metal storefront.** An unbacked view has no `host_id`. The older storefront's model rejects it and refuses the whole generation, so every backed listing at the site is held as `site_projection_refused`.
2. **Older site, new storefront.** The older site emits a view carrying `host_id` and `access_methods` for a host-bearing declaration in an unbacked pool. The new carrier rejects that as an unbacked view carrying a delivery term, and refuses the whole generation. Previously the storefront reported `pool_unbacked` and published the rest.
3. **Buyer side.** An upgraded core buyer installed with an older bare-metal plugin that still registers a root `settlement` group, alongside VM, refuses to start. Buyers are independent parties now, not the seller's business.

Points 1 and 2 are bounded, since the outcome is a hold rather than a delisting. That makes them cheap to record and easy to forget.

**Suggested action:** replace decision 25 with a short record of the three points and their effect: a transient whole-site hold, and a refused buyer start. A mitigation is optional; recording is what the rule asks.

### F4 — The degraded-start requirement is contradicted by the VM storefront's own startup, and the VM chart has no `startupProbe`

- **Lens:** consistency
- **Basis:** evidence
- **Severity:** should
- **Evidence:**
  - `domains/vms/storefront/src/market_storefront/startup.py:44-87`: polls provisioning `/health` for `preflight_timeout`, then raises when `fail_on_unreachable` is set.
  - `domains/vms/storefront/src/market_storefront/settings.toml:175-176`: `fail_on_unreachable = true` by default.
  - `domains/apicredits/storefront/src/apicredits_storefront/startup.py:34-63`: the same pattern for the credits service.
  - `helm/charts/storefront/templates/deployment.yaml:171-184`: liveness and readiness probes only.
  - `design.md:494-496`: "the pod relies on a `startupProbe`".
  - Delta deployment-state, "A deployment does not wait on a service's dependencies": "The service MUST start while a dependency is unreachable", with "a site" named.

Decision 20 considers only the registry and the chain, and leaves "nothing earlier in startup … touches either dependency" for planning to confirm. The new requirement covers any external dependency "such as … a site". The VM storefront refuses to start when its provisioning service is unreachable, and the API-credit storefront does the same for its credits service. Both would violate the requirement on landing.

The VM chart has no `startupProbe`, only the bare-metal chart does, so removing the init containers leaves a slow start to the liveness probe.

Separately, Alkahest client construction drops a chain for the life of the process if construction fails (`kit/storefront/src/market_storefront_kit/alkahest_clients.py:82-105`). If `AlkahestClient` connects when constructed, an RPC that is down at start is never recovered. That would contradict the delta's "recover without a restart".

**Suggested action:** either extend decision 20 to make the provisioning and credits preflights degrade instead of failing (site projections already hold an unknown site), or narrow the requirement to init containers. Add a `startupProbe` to the VM chart as part of decision 20. Have planning confirm the Alkahest client construction behaviour.

### F5 — Decision 17's fallback for older run-logs keeps funding seller-supplied terms, and its premise that only bare metal sends them is false

- **Lens:** consistency
- **Basis:** evidence
- **Severity:** should
- **Evidence:**
  - `design.md:392-396` ("sent only by bare metal") and `design.md:413-416` ("An older run-log without them resumes as before").
  - Delta buyer-orchestration, "A buyer funds only what it derives": "MUST NOT fund terms a seller supplied … a run-log that predates them MUST resume as before".
  - The one producer is `kit/alkahest/src/market_alkahest/proposals.py:359-371`, used by VM (`negotiation_runtime.py:269`) and API credits (`settlement_stages.py:204`) as well as bare metal.
  - VM resume funds recorded terms unchecked: `domains/vms/buyer/.../settlement_stages.py:483-486`. API credits does the same: `settle_cli.py:341-344`.
  - Back-fill from the plan: VM `settlement_stages.py:182-186`.

Before this change, resume funds whatever terms the run-log holds, seller-sent or back-filled, with no check. It refuses when only a proposal is recorded. "Resumes as before" for a run-log without recorded release conditions therefore funds seller-supplied terms blindly, which is exactly what the new requirement's first sentence forbids. An older run-log does record the seller's `settlement_plan`, so it can at least be checked.

Separately, the premise that only bare metal sends the field is wrong: every Alkahest seller sends it. Decision 17's direction is unaffected, since the field goes everywhere, but its rationale and the version analysis should say so. Removal is still benign for older buyers, because `orchestration.py:930-939` falls back to the buyer's own derivation when the field is absent.

**Suggested action:**
- Define the older run-log case. Either derive from the recorded accepted proposal and plan and require equality before funding, or refuse with a named reason. Never fund the recorded terms unchecked.
- Correct decision 17's statement of who sends the field.

### F6 — Decision 16 lists some of the sites that read current state after acceptance, so decision 19's "planning confirms" already has a known answer

- **Lens:** consistency
- **Basis:** evidence
- **Severity:** should
- **Evidence:**
  - `design.md:374-383`, `design.md:472-477`.
  - `domains/vms/storefront/src/market_storefront/services/admin_settle_service.py:98-108`: the admin dry-run verify runs against the current listing with no proposal.
  - VM's re-derived plan uses the current heartbeat interval: `negotiation_runtime.py:280-282`.
  - VM's admin interrupt reads the current listing's `interruptible`: `admin_controller.py:614-645`.
  - Verification re-materializes under the current listing's `demands`, which VM refreshes in place from configuration: `escrow_verification.py:416-422`, `listing_comparison.py:62-68`.

Decision 16 names the settle paths, but VM's administrator dry-run verify would still check against the current listing. The administrator's preview would then disagree with the real verification decision 16 introduces. The interrupt path likewise reads the current model from the current listing.

Decision 19 moves the undeliverable-model refusal to readiness only if "no settlement or collection path reads it", and leaves that to planning. The tree already answers part of it. Interrupts are VM-only, and VM delivers every model, so the undeliverable-model move is probably safe. The design should say that, rather than leave it as an open condition.

**Suggested action:** extend decision 16 to every post-acceptance reader: the admin dry-run verify, the re-derived plan's heartbeat, and the interrupt's model. Each should read the committed plan or the accepted thread. Record decision 19's condition as checked, with the interrupt path named as VM-only.

### F7 — The bare-metal lifecycle delta goes beyond decision 19, drops a startup refusal without a decision, and weakens the recovery guarantee

- **Lens:** documentation
- **Basis:** specification
- **Severity:** should
- **Evidence:**
  - Delta storefront-publication, MODIFIED "Complete bare-metal seller lifecycle": the requirement text "wherever its configuration supplies them", and the scenario "lacks its seller address, chains, or wallet key … starts".
  - Current scenario, `openspec/specs/storefront-publication/spec.md:333-335`: "or with any of those supplied and no Alkahest section … refuses".
  - `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/runtime.py:846-874`: "A configured Alkahest section … owns the obligations accepted under it, so its recovery resources are required".
  - `design.md:472-482`: decision 19 moves only "a configured section with no wallet", and records only a removed wallet as a known limit.

Three differences from the decision:
1. The delta makes missing chains and a missing wallet key unready too, which decision 19 does not decide.
2. It silently deletes the refusal of Alkahest inputs supplied with no Alkahest section.
3. It qualifies "MUST build a configured mechanism's recovery resources" with "wherever its configuration supplies them". Without chains or a key, obligations accepted under an earlier configuration cannot be serviced, collected, or refunded: a wider version of the limit decision 19 records only for the wallet.

**Suggested action:** either align the delta with decision 19 (wallet address only, and keep the stale-input refusal), or extend decision 19 explicitly to chains and wallet key. If extended, record the recovery consequence as a known limit, and say whether servicing of already-accepted obligations should still refuse startup.

### F8 — Decision 7's per-candidate close contradicts an existing publication requirement the delta leaves unmodified, and API credits under decision 19 is not addressed

- **Lens:** documentation
- **Basis:** specification
- **Severity:** should
- **Evidence:**
  - `openspec/specs/storefront-publication/spec.md:544-546`: "If no enabled ready mechanism has a valid publication clause, publication MUST fail without mutating accepted negotiations or active settlement state."
  - `design.md:212-214`: "API credits does not publish through the runner and is unaffected."
  - `design.md:467-473`: decision 19 applies to API credits.
  - `domains/apicredits/storefront/src/apicredits_storefront/services/listing_service.py:69-74`.

The existing requirement makes the no-ready-mechanism case a failure of the whole publication. Decision 7 makes it a per-candidate refusal that closes open listings. The delta adds the new requirement but does not modify the old one, so both would be normative.

Decision 19 also makes an unusable Alkahest section unready in the API-credit storefront, which previously refused to start for, say, an undeliverable model. An open API-credit listing whose only option is Alkahest then keeps advertising it: the existing requirement leaves it untouched, and decision 7 does not cover API credits. That is the "advertised options the storefront could not honour" behaviour decision 7 rejects for VM.

**Suggested action:**
- Modify "Publication derives all ready settlement options" so it is consistent with the per-candidate refusal.
- State what an open API-credit listing does when Alkahest becomes unready: close, hold, or "unchanged, owned by" a named change.

### F9 — The carrier's backing label has no named source: the joint declaration reader is not in a package `arkhai_bare_metal` depends on

- **Lens:** architecture
- **Basis:** guidance
- **Severity:** should
- **Evidence:**
  - `design.md:159-165`: the carrier "carries `capacity_backing` … read through the shared declaration resolver".
  - `kit/resource-pools/src/market_resource_pools/site_declarations.py:104-137`: the per-generation reader and the older-producer rule.
  - `domains/bare_metal/pyproject.toml:7-14`: only the contracts package is declared.
  - `domains/bare_metal/src/arkhai_bare_metal/publication.py:23-27`: `trusted_bare_metal_projection(site_id, projection)` takes no declarations.
  - `AGENTS.md`, "Package and dependency discipline"; `docs/development/ARCHITECTURE.md:151` on pool declaration modules held in the authority rather than its contracts.

The right label for a pool depends on the whole generation. A producer that predates the declarations resolves through `legacy_producer_backing`. That rule lives in `kit/resource-pools`, which `arkhai_bare_metal` does not import. If the carrier resolves pools one by one with the contracts resolver, an older-producer generation's pools would read as unresolvable, or diverge from what `SitePoolReading` decides. If it imports `kit/resource-pools`, the light domain vocabulary package takes an edge into the pool authority, which the architecture already counts as misplaced.

**Suggested action:** make the label an input. `trusted_bare_metal_projection` would take the generation's resolved backings, which the storefront already computes through `read_site_pools`. The site's builder would pass the delegate from decision 4's pool context. Name the signature change in the design.

### F10 — Decision 4's pool context needs a seam that does not exist: kit/site reads resources and pools separately, and decision 6 depends on the two agreeing

- **Lens:** architecture
- **Basis:** evidence
- **Severity:** should
- **Evidence:**
  - `kit/site/src/market_site/projections.py:183-186`: `pool_directory()` and `resource_inventory()` are called independently.
  - `provisioning/compute/service/src/compute_provisioning_service/main.py:187-195`: two loaders, two sessions.
  - `provisioning/compute/service/src/compute_provisioning_service/services/capacity_inventory.py:74`: the resource pass gets only `pool_id`.
  - `provisioning/compute/src/compute_provisioning/inventory_views.py:37-40`.
  - `design.md:88-91`.

"The provisioning service resolves that context from the pool rows its metadata pass already reads" cannot happen as things stand. The metadata pass and the resource pass are separate callables that kit/site invokes, each in its own read. This matters beyond plumbing. Decision 6 cross-checks a view's terms against its containing pool entry's label. If a pool is re-created under the same ID with the opposite backing between the two reads (a case `ARCHITECTURE.md` explicitly considers), a correctly built generation is refused whole.

**Suggested action:** name the seam. Either the service composes one loader that reads pools once and passes each resource view its pool's context, from the same rows the pool directory returns, or kit/site's `SiteProjectionService` passes the directory's rows into the resource pass. Prefer the first, which adds no kit/site behaviour. Name `compute_provisioning`'s protocol, the VM adapter, and the service as the packages that change.

### F11 — The kit/site half of decision 23 adds replay outcome recording that kit/site does not have

- **Lens:** scope
- **Basis:** evidence
- **Severity:** should
- **Evidence:**
  - `kit/site/src/market_site/auth.py:278-310`: `InMemoryReplayStore` records reservations only, never outcomes, and exact retries re-execute.
  - `design.md:571-574`: "recorded as the request's replay outcome … `kit/site`'s, which has the same gap".
  - Delta physical-provisioning, "A failure after authentication is answered signed": every service using the site kit's middleware "MUST record that response as the request's replay outcome".
  - `docs/development/ROADMAP.md:287`: `redesign-authenticated-replay-state`.

kit/site does not have "the same gap". It has no outcome store, so a retried request runs again rather than returning a recorded result. Recording a signed 500 as the replay outcome means giving kit/site outcome recording, and durability if exact retries are to survive a restart. Replay state for every authority is the subject of `redesign-authenticated-replay-state`.

**Suggested action:**
- For kit/site, require only the signed, non-revealing 500 here.
- Scope "recorded as the replay outcome" to the provisioning service, whose store records outcomes.
- Record the kit/site remainder against `redesign-authenticated-replay-state`.

### F12 — The site-derivation log's semantics are incomplete, and one VM category it maps does not exist

- **Lens:** architecture
- **Basis:** evidence
- **Severity:** minor
- **Evidence:**
  - `design.md:266-282`.
  - Delta "A compute storefront reports and logs its site derivation": "a site that derived cleanly present with empty lists".
  - `domains/vms/listings/.../reconciler.py:361-383`: the categories.
  - `domains/vms/storefront/tests/integration/test_reconciler_derivation.py:155`: `legacy_overrides_in_effect` appears only as asserted-absent.
  - `docs/development/ARCHITECTURE.md:56`: one shell may compose both compute contributions.

Three gaps:
1. Status before a site's first cycle after a restart is undefined: absent, or empty? An empty entry would read as "derived cleanly".
2. In a shell composing both VM and bare metal, two cycles that each record "the site's summary" would clear and re-raise each other's entries every cycle, defeating "logged once".
3. `legacy_overrides_in_effect` is not one of VM's categories.

**Suggested action:**
- Say that a site with no cycle yet is absent, or marked as not derived.
- Key the log by publication source and site.
- Correct the category list.

### F13 — Smaller interface gaps the design does not name

- **Lens:** architecture
- **Basis:** evidence
- **Severity:** minor
- **Evidence:**
  - `domains/bare_metal/provisioning/adapter/pyproject.toml:10`: the adapter does not declare `arkhai-kit-resource-pools-contracts` and would now import it.
  - `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/inventory_views.py:49-57`: VM implements the changed protocol.
  - `proposal.md:139-141`: the Impact section attributes the resource pass's protocol to `kit/resource-pools`, but it is `provisioning/compute/src/compute_provisioning/inventory_views.py`.
  - `design.md:117-121`: "a backed delegate requires every term present and non-empty".
  - `design.md:243-245`: "one shared refusal", in no named package.

The gaps:
- **Undeclared import.** The bare-metal adapter must declare the contracts distribution it will import (`AGENTS.md`, "declare every distribution it imports").
- **Unnamed implementer.** The VM adapter must adopt the new protocol signature.
- **Boolean term.** "Non-empty" is undefined for the boolean term `available`, where `False` is a valid backed value.
- **No home for the refusal.** The shared introduction refusal has no package. It must be reachable from both domains' routes without a sibling-domain import, which suggests `kit/contact-exchange` or core.

**Suggested action:** name these four in the design: the package changes, presence semantics per term type (boolean present versus collection non-empty), and the refusal's home. Correct the Impact section.

### F14 — The existing `tasks.md` describes the 2026-10-14 design, not the settled one

- **Lens:** readiness
- **Basis:** guidance
- **Severity:** minor
- **Evidence:**
  - `openspec/changes/unbacked-bare-metal-listings/tasks.md:1-8`: "Depends on `share-site-projection-state` (design phase)"; "Design reviewed 2026-10-14 … not yet planned".
  - `tasks.md:80-91`: the closeout evidence names only group A.
  - `AGENTS.md`, "Plan": preserve completed tasks, amend or append.

The task list records no decision gate for the 2026-10-20 redesign, under which twelve items were moved into this change and decided here. Its closeout part names no evidence for groups B to D: the local Helm topology run, the degraded-start test, the source check.

**Suggested action:** when planning, keep 1.1–1.13 as history. Append a gate recording the 2026-10-20 decisions (16–26). Update the header, and write the closeout's pipeline and Helm evidence for all three rounds.

## Readiness

Not ready for planning.
- **F1** must be resolved first. Planning cannot implement decision 7's hold branch, decision 19's blocker kinds, or decision 20's degraded start without a design decision on whether, and how, any mechanism detects that a dependency is unreachable.
- **F2 and F3** challenge settled decisions 7 and 25. The owner should reaffirm or change them before planning.
- **F4–F11** correct facts and name seams that planning would otherwise discover and decide by itself. They should be folded into the design in the same pass.
- **F12–F14** can be handled during planning.

No related change must land first. Every prerequisite is archived.

<!-- reviewer-session: claude:be1e70bf-da28-4d13-9601-32d279dca3df -->
<!-- reviewer: claude claude-opus-5-5 high -->
<!-- reviewer-unavailable: codex gpt-6-sol: codex is not installed -->
<!-- reviewed-commit: 0ccbee3af1ca018437369e36e4f6247cc0ca852b -->
