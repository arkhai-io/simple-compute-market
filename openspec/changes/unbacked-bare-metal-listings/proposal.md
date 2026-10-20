## Why

Goal 7 exists so a seller whose capacity the marketplace cannot admit against —
typically whole machines arranged directly between the parties — can still be
discovered and introduced. Bare metal is that goal's primary target domain, and
bare metal cannot publish such a listing.

Every bare-metal listing is backed. Bare-metal publication's pool reading refuses a
pool declaring itself unbacked — the one branch on a particular backing
`encapsulate-capacity-backing` left outside the delegate — and each listing requires a
`host_id` and `physical_host_id` from a Physical Resource's publication view, which the
site emits only for a declaration naming a host.

The rest of what an unbacked listing needs already exists: every backing decision is the
backing delegate's, VM derives unbacked listings from projected pool declarations through
it, bare metal composes `contact-exchange.v1`, and bare metal publishes on a loop over held
site projections. What is missing is bare metal using that machinery, and designing it
showed several places where VM and bare metal diverge without reason.

The change also carries twelve items moved to it on 2026-10-19 and 2026-10-20, designed
and fixed here rather than handed on again: six defects a local Helm deployment of bare
metal beside Bob exposed, and six Alkahest settlement questions raised in
`share-site-projection-state`'s implementation. One of them, stage events, goes to a
follow-up change.

## What Changes

### A. Unbacked bare metal

- Derive bare-metal listings from every enabled pool advertising `bare_metal`, whatever
  its backing, through the kit publication runtime, declaration reader, and source
  reconciliation VM uses; delete bare metal's refusal of unbacked pools.
- Have the site emit the bare-metal view for a resource in an unbacked pool, host or no
  host. Resource views receive their pool's context, never fail the projection, and report
  why a view could not be built (`publication_view_problems`).
- Make host identity, physical host identity, access methods, and availability delivery
  terms the backing delegate carries or forbids, through `carry_delivery_terms` and
  `delivery_term_constraints`. The view carries no backing label; the shared trusted
  carrier validates its terms against its pool's backing, and an inconsistent view refuses
  the site's generation. The `["ssh"]` default goes.
- Bind each listing with its pool's backing and publish `capacity_backing: unbacked`;
  never reserve, hold, schedule, or fulfil an unbacked listing.
- Refuse a VM or bare-metal candidate with no settlement option and no accepted escrow,
  recorded per site. An open listing closes as `no_settlement_option` when the storefront's
  configuration rules every mechanism out, and reopens when an option returns; it is held
  while any mechanism is unready only because its chain or service cannot be reached.
- Recheck an unbacked listing against the projection the storefront holds, never its
  availability.
- Answer an introduction deal from its accepted stage in both domains, through one
  refusal in `kit/storefront` deciding by a required stage declaration that the stage
  completes outside settlement: settle answers 409, bare metal's fulfillment reads and
  teardown answer 404, and bare metal's contact stage stops recording the reveal as
  settlement evidence.
- Keep one site-derivation summary in `kit/capacity-publication` for VM and bare metal:
  recorded by publication cycles only, served as one `publication_derivation` status shape,
  and logged when an entry appears or clears.
- Move bare metal's buyer `settlement` command group under `market bare-metal`, and have
  the core buyer application refuse at startup a root command name two domains register.
- Own the bare-metal system evidence for Goal 7: `e2e_bare_metal_unbacked_introduction`,
  running VM's introduction scenario stage for stage on shared introduction stages, with
  a mail sink on the bare-metal lane, including the rate-bounded query returning backed
  and unbacked bare-metal listings together (transferred from
  `publish-indicative-listing-rates`, its 7.13).

### B. Alkahest settlement inputs

- Verify and settle every Alkahest deal against the plan committed at acceptance, in VM,
  bare metal, and API credits.
- Remove `accepted_escrow_terms` from the accept reply and every reader. A buyer always
  derives the escrow from its acceptance and the listing, compares it with the seller's
  plan before funding on every path including resume, and records the listing's release
  conditions in its run-log.
- Refuse an escrow proposal that names no escrow contract, in the shape guard and at the
  kit's materialization chokepoint, removing every unpinned branch.
- Make an Alkahest section that cannot settle — no oracle, an oracle equal to the wallet,
  no wallet address or key, no chains, an undeliverable release model — unready rather
  than fatal, derive release conditions only for ready clauses, and have every readiness
  blocker state whether it is a configuration or a reachability blocker.
- Probe each Alkahest chain apart from readiness, at most once per interval with bounded
  calls, telling an unreachable chain (reachability) from a wrong chain or a missing
  contract (configuration), and rebuilding a chain client that could not be constructed.

### C. Deployment and test hygiene

- Remove the VM storefront chart's dependency-waiting init containers and give the chart
  a startup probe; remove the VM and API-credit storefronts' in-process dependency
  preflights. Each starts with its dependencies unreachable and reports them degraded.
- Give Helm test pods labels no Deployment selector matches.
- Hold shared services' loops for a whole scenario module through one fixture mechanism in
  every lane, released in a finaliser, with stages asserting holds and a source check
  forbidding direct pauses.

### D. The provisioning service

- Refuse startup while a stored pool names a provider no handler serves.
- Answer a failure after authentication with a signed 500, in the provisioning service's
  middleware, which records it as the request's outcome, and in `kit/site`'s, whose store
  keeps no outcomes.

## Capabilities

### Modified Capabilities

- `storefront-publication`: unbacked bare-metal listings; delivery terms only on backed
  listings; no listing without a settlement option, with close or hold for open listings;
  introduction deals answered from the stage; one site derivation reported and logged; the
  recheck on held projections; an unpinned opening refused; an undeliverable release model
  unready.
- `physical-provisioning`: the bare-metal view's delivery terms, pool context, and
  problems; signed failures after authentication.
- `resource-pool-management`: the delegate's delivery-term operations; stored pools with
  unserved providers stop startup.
- `registry-discovery`: a bare-metal listing publishes its binding's backing, backed or
  unbacked.
- `negotiation-protocol`: an unpinned escrow proposal is refused; the accept reply carries
  no escrow terms.
- `settlement-servicing`: settlement verifies against the accepted plan.
- `settlement-configuration`: an unusable Alkahest section is unready; readiness blockers
  state their kind.
- `buyer-orchestration`: a buyer funds only what it derives; no root command name is
  registered twice.
- `deployment-state`: no dependency-waiting init containers; Helm test-pod labels.
- `test-compatibility`: scenarios hold shared services for the whole module.

### New Capabilities

None.

## Non-Goals

- Finite unbacked listings, or hosted settlement over unbacked supply. Both are
  anticipated and unowned in Goal 7.
- A bare-metal-specific introduction composition. Bare metal uses the kit's.
- Asking rates, which `publish-indicative-listing-rates` added for backed and unbacked
  listings alike.
- Unifying VM's and bare metal's delivery route surfaces, which is
  `kit-owned-listing-and-fulfillment-lifecycles`'.
- An accept reply carrying only the Agreement, recorded as `move-escrow-into-alkahest`'s
  end state.
- Redesigning stage events, which is `redesign-storefront-stage-events`'.
- Running pipeline scenarios against the Helm charts, which is `helm-e2e-pipeline-parity`'s.

## Impact

- `kit/resource-pools-contracts`: the delegate's delivery-term operations.
- `provisioning/compute` (`compute_provisioning`): the view protocol's pool context and
  view problems. The compute provisioning service: the resource pass's pool context, the
  stored-provider startup check, and signed failures after authentication. `kit/site`'s
  middleware: signed failures. `kit/site` and `kit/resource-pools` otherwise unchanged.
- `domains/bare_metal/src/arkhai_bare_metal/`: the listing schema, the view carriers and
  their validation, classification, and the recheck; the bare-metal provisioning adapter's
  view builder.
- `kit/capacity-publication` and `core/storefront`'s publication runner: the
  site-derivation log, and the source close hook for optionless listings.
- The VM and bare-metal storefronts' publication, status, settlement stages, and settle and
  fulfillment routes; the VM and API-credit storefronts' startup; the API-credit
  storefront's settlement verification and release conditions.
- `kit/storefront`: the shared introduction refusal and the Alkahest chain probe beside
  client construction.
- `kit/alkahest`, `kit/policy`, and `kit/settlement-runtime`'s readiness carrier;
  `core/buyer` and the VM and API-credit buyers; the bare-metal buyer's commands.
- `helm/`: the VM storefront chart's init containers and startup probe, every chart's
  test-pod labels, and a topology render test.
- `e2e-tests/`: hold helpers and fixtures in every lane, the source check, shared
  introduction stages, the new bare-metal scenario, VM's introduction scenario, and the
  bare-metal lane's mail sink and delivery configuration.
- Wire: the site projection gains an optional per-resource field; the accept reply loses
  `accepted_escrow_terms`; VM's administrator status reports `publication_derivation` in the
  shared shape; readiness blockers carry a `kind` and status reports each Alkahest chain's
  last probe; an unpinned escrow proposal is refused; bare metal's fulfillment routes
  answer 404 for an introduction deal.
- Configuration: the VM storefront's `[seller.provisioning]` `fail_on_unreachable` and
  `preflight_timeout`, and the API-credit storefront's `credits` counterparts, are
  removed; an Alkahest probe interval is added. A backed bare-metal listing's payload and binding are
  unchanged.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the wire principle, derived settlement inputs,
      unready settlement mechanisms, settlement in the holding-or-closing rule, one
      behaviour for one concern across domains, and the bare-metal commitment.
- [x] Existing subsystem specification — `storefront-publication`,
      `physical-provisioning`, `resource-pool-management`, `registry-discovery`,
      `negotiation-protocol`, `settlement-servicing`, `settlement-configuration`,
      `buyer-orchestration`, `deployment-state`, and `test-compatibility`, and the
      `storefront-publication`, `physical-provisioning`, `resource-pool-management`,
      `market-composition`, and `settlement-configuration` architecture companions.
- [ ] New subsystem specification
- [ ] No permanent documentation change

Also: `docs/development/DEPLOYMENT_AND_CONFIG.md`, `docs/development/TESTING.md`,
`docs/development/ROADMAP.md` (Goals 6 and 7), the bare-metal and VM seller quickstarts,
and the change index.

### Knowledge to promote

- Unbacked bare-metal derivation, delivery terms, the no-option refusal with close or hold,
  the introduction answer, the site derivation, and the recheck — `storefront-publication`
  spec and architecture companion.
- The bare-metal view contract, pool context, view problems, and signed failures —
  `physical-provisioning` spec and companion.
- Delivery terms among the delegate's decisions; the stored-provider startup refusal —
  `resource-pool-management` spec and companion.
- Settlement against the accepted plan — `settlement-servicing`; derived settlement inputs
  and the reply without escrow terms — `buyer-orchestration` and `negotiation-protocol`;
  the unpinned refusal — `negotiation-protocol`; unready Alkahest, blocker kinds, and the
  chain probe — `settlement-configuration` spec and companion.
- The `completes_outside_settlement` stage declaration and the introduction refusal as a
  `kit/storefront` stage convention — `market-composition` companion.
- Anything a counterparty can send is handled on its own terms; what an Agreement and its
  listing determine each party derives; a settlement mechanism that cannot settle is
  unready; unknown readiness holds a listing; one behaviour for one concern across domains
  — `ARCHITECTURE.md`.
- No dependency-waiting init containers and degraded start; incoherent own configuration
  stops startup; Helm test-pod labels — `DEPLOYMENT_AND_CONFIG.md` and `deployment-state`.
- Module-scoped holds of shared services — `TESTING.md` and `test-compatibility`.

## Dependencies

- **Prerequisites, all archived:** `bare-metal-publication-reads-pool-declarations`,
  `bare-metal-listing-shapes`, `compose-contact-exchange-across-compute`,
  `encapsulate-capacity-backing`, `share-site-projection-state`, and
  `bare-metal-mock-provisioned-deal`. No open change gates this one.
- **Carries** the bare-metal half of `publish-indicative-listing-rates`' unbacked-supply
  rate evidence.
- **Closes** Goal 6's unowned gap on pricing an escrow proposal that names no contract.
- **Hands to other changes**, with edits on this branch: the Agreement-only reply to
  `move-escrow-into-alkahest`; the introduction rule for a unified delivery surface to
  `kit-owned-listing-and-fulfillment-lifecycles`; two corrected items in
  `resolve-compute-family-findings`; stage events to the proposed
  `redesign-storefront-stage-events`.
- **Does not carry** the two-seller introduction scenario, recorded as unowned in the change
  index; Goal 7 closes without it.
- **Builds on** `contact-payload-retention`'s bare-metal introduction scenario.
