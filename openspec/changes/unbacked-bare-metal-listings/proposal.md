## Why

Goal 7 exists so a seller whose capacity the marketplace cannot admit against —
typically whole machines arranged directly between the parties — can still be
discovered and introduced. Bare metal is that goal's primary target domain, and
bare metal cannot publish such a listing.

Every bare-metal listing is backed. Bare-metal publication's pool reading refuses a
pool declaring itself unbacked — the one comparison of the backing label
`encapsulate-capacity-backing` left in the tree — and each listing requires a `host_id`
and `physical_host_id` from a Physical Resource's publication view, which the site
emits only for a declaration naming a host.

The rest of what an unbacked listing needs already exists:

- every backing decision is the backing delegate's, which VM and bare metal both ask:
  one `PublicationBinding` carries it, `CapacityEffects` refuses an effect for an
  unbacked listing, `judge` never asks availability of one, and settlement
  admissibility keeps only options a domain does not fulfil through capacity;
- VM derives unbacked listings from projected pool declarations through that delegate;
- bare metal already composes `contact-exchange.v1`, the introduction mechanism
  unbacked supply settles through.

What is missing is bare metal using that machinery.

## What Changes

- Derive bare-metal listings from every enabled pool advertising `bare_metal`,
  whatever its backing, through the kit publication runtime, declaration reader, and
  source reconciliation VM uses. Every difference from backed supply is decided by the
  backing delegate `encapsulate-capacity-backing` introduces, and bare metal's
  temporary refusal of unbacked pools, which that change keeps, is deleted.
- Have the site emit the bare-metal publication view for a resource in an unbacked
  pool, host or no host. Resource views receive their pool's context, the backing
  delegate among it, and carry delivery terms only as the delegate passes them.
- Make host identity, physical host identity, access methods, and availability
  delivery terms the delegate carries or forbids: present and required on a backed
  listing, absent on an unbacked one. The `["ssh"]` access-method default goes.
- Bind each listing with the kit's `PublicationBinding`, carrying its pool's backing,
  and publish `capacity_backing: unbacked`. Never reserve, hold, schedule, or fulfil an
  unbacked bare-metal listing.
- Publish only settlement options bare metal does not fulfil through capacity, so an
  unbacked bare-metal listing settles by introduction, revealing the contact of the
  listing's origin seller through the domain-neutral composition
  `compose-contact-exchange-across-compute` promoted.
- Refuse any bare-metal candidate, backed or unbacked, whose payload carries no
  settlement option and no accepted escrow, recording the refusal in the publication
  report.
- Recheck an unbacked bare-metal listing against the projection the storefront holds
  for its site, never its availability, through the held projections
  `share-site-projection-state` gives bare metal.
- Answer not found from the bare-metal fulfillment routes for a deal whose accepted
  stage does not fulfil through capacity, before building fulfillment.
- Move bare metal's buyer `settlement` command group under `market bare-metal`, and
  have the core buyer application refuse at startup a root command name two installed
  domains register.
- Own the bare-metal system evidence for Goal 7, a new
  `e2e_bare_metal_unbacked_introduction` scenario running VM's introduction scenario
  stage for stage on shared introduction stages that VM also moves onto: unbacked
  discovery through the buyer CLI (including an exact `capacity_backing` filter),
  the payload's absent delivery terms, the reveal, seller-side delivery to a mail sink
  the bare-metal lane gains, and the fulfillment route's not-found answer.
- Within that scenario, own the bare-metal evidence that unbacked supply is comparable
  on price: a buyer query bounded by asking rate returns backed and unbacked
  bare-metal listings together and excludes one publishing no rate. Transferred from
  `publish-indicative-listing-rates` (its 7.13), which proved the asking-rate path on
  backed supply.
- Address six pre-existing defects a local Helm deployment of bare metal beside Bob
  exposed (raised 2026-10-19; `design.md` open question 11, whose design is not yet
  decided): a stored resource pool whose provider no registered handler serves makes
  the provisioning service's pool read fail with an unsigned 500, and startup does not
  refuse the row; the VM storefront chart's `wait-for-registry` init container polls
  with no timeout; stage events fill `listing_id` with the negotiation id; Helm test
  pods carry their Deployment's selector labels; a failed VM deal Helm test leaves Bob's
  loops paused; and bare metal logs its regionless-pool notice every publication cycle
  rather than once per projection generation, as VM logs its derivation warnings.

## Capabilities

### Modified Capabilities

- `storefront-publication`: bare-metal publication derives unbacked listings; delivery
  terms only on backed listings; no listing without a settlement option; one-unit
  allocation and the opening availability refusal scoped to backed listings;
  introduction deals have no fulfillment.
- `physical-provisioning`: the bare-metal view carries delivery terms as the pool's
  delegate passes them and is emitted for unbacked resources without a host; resource
  views receive their pool's context.
- `resource-pool-management`: the backing delegate decides delivery terms.
- `registry-discovery`: a bare-metal listing publishes its binding's backing, backed or
  unbacked.

### New Capabilities

None.

## Non-Goals

- Finite unbacked listings, or hosted settlement over unbacked supply. Both are
  anticipated and unowned in Goal 7.
- A bare-metal-specific introduction composition. Bare metal uses the promoted one.
- Asking rates, which `publish-indicative-listing-rates` adds for backed and unbacked
  listings alike.

## Impact

- `kit/resource-pools-contracts`: the delegate's delivery-term operations.
- `domains/bare_metal/src/arkhai_bare_metal/`: the listing schema's backing and
  delivery-term validation.
- The compute provisioning service's resource pass and the bare-metal provisioning
  adapter's publication view.
- The bare-metal storefront's pool reading, publication, recheck, and fulfillment
  routes.
- `core` buyer application composition and the bare-metal buyer plugin's commands.
- `e2e-tests/`: shared introduction stages, the new bare-metal scenario, VM's
  introduction scenario, and the bare-metal lane's mail sink and delivery
  configuration.
- For open question 11's defects, as its design decides: the compute provisioning
  service's pool read and startup checks, the VM storefront chart's init container and
  the umbrella's Helm test pod labels, `core/storefront`'s stage log, the e2e-tests
  chart's deal test, and bare metal's publication logging.
- No wire or database break: a backed listing's payload and binding are unchanged.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the bare-metal commitment sentence.
- [x] Existing subsystem specification — `storefront-publication`,
      `physical-provisioning`, `resource-pool-management`, `registry-discovery`, and
      the publication architecture companion's bare-metal passages.
- [ ] New subsystem specification
- [ ] No permanent documentation change

Also: the bare-metal seller quickstart, `docs/development/TESTING.md`,
`docs/development/DEPLOYMENT_AND_CONFIG.md`, and the roadmap's Goal 7.

## Dependencies

- **Depends on `bare-metal-publication-reads-pool-declarations`** (complete), for
  projected pool declarations and the kit publication runtime. That change added the
  requirement that an unbacked pool yields no bare-metal listing, now promoted into
  `openspec/specs/storefront-publication/spec.md`; this change's delta removes it.
- **Depends on `bare-metal-listing-shapes`** (complete), so an unbacked bare-metal
  listing is discoverable by the compute schema's dimension filters.
- **Depends on `compose-contact-exchange-across-compute`** (complete), for the
  promoted introduction composition and the per-origin contact payload.
- **Depends on `share-site-projection-state`** (design phase), which gives bare metal
  held per-site projections and runs its publication on the storefront's lifecycle
  loop controller, as VM's runs. An unbacked listing is never judged against
  availability, so source reconciliation is the only reconciliation it gets, and it
  must run without an operator; and the opening recheck then reads a held projection
  rather than calling the listing's site.
- **Depends on `encapsulate-capacity-backing`** (archived 2026-10-14), which
  gathers every decision that differs between backed and unbacked supply into one
  backing delegate and moves VM and bare metal onto it. This change resolves bare
  metal's unbacked pools through that delegate and adds its delivery-term operations,
  rather than adding bare-metal branches on backing.
- **Depends on `bare-metal-mock-provisioned-deal`** (archived 2026-10-09), which
  composed bare-metal negotiation and settlement onto the kit negotiation runtime.
- **Carries** the bare-metal half of `publish-indicative-listing-rates`' unbacked
  supply system evidence, transferred here because this change creates the listing it
  needs.
- **Does not carry** the two-seller introduction scenario (two seller sites behind one
  storefront) it was once assigned. One storefront serving several sites is not
  supported today and is not yet a goal of its own; the scenario is recorded as
  unowned in the change index, and Goal 7 closes without it.
- **Builds on `contact-payload-retention`'s bare-metal introduction scenario**, the
  first end-to-end scenario to reach an introduction, rather than writing its own
  introduction flow.
