## Why

VM buyers whose provisioned host has no public IP need some tunnel/proxy
mechanism to reach it — today that mechanism is FRP
(`frp_server_addr`/`frp_domain`/`frp_dashboard_password`), and it is entirely
storefront-operator configuration: three flat keys in
`market_storefront/settings.toml`, applied uniformly to every VM fulfillment,
never buyer-specified, never negotiated.

That is a real limitation, not just an implementation detail: a buyer who
wants to run their own FRP server (their own relay, their own domain, their
own credentials) has no way to express that. The seller-operated relay is one
valid choice, not the only one — nothing about VM connectivity requires the
seller to be the one operating the relay, any more than the seller is
required to own the buyer's SSH key.

This surfaced during `pools-7-storefront-fulfillment-cutover` Section 9's
design review, while wiring VM fulfillment requests through the new
`begin_fulfillment` path: `VmFulfillmentRequirements` (the payload the VM
provisioning adapter accepts) had no field for these at all, because the
legacy direct-dispatch path sourced them from storefront config rather than
the request itself. Making them buyer-specified — and, per that discussion,
validating them at negotiation time rather than discovering a bad
configuration after the deal is signed — is a change to the negotiation
protocol's versioned VM provision envelope and to settlement encoding, not a
fulfillment-request field. That is out of proportion for Section 9's actual
scope (cutting over fulfillment dispatch), so it is split out here.

## What Changes

- Extend the VM domain's negotiation-time provision payload (the
  buyer-supplied side of `openspec/specs/negotiation-protocol/spec.md`'s
  "Versioned domain provision envelope") to optionally carry buyer-specified
  connectivity terms: FRP server address, domain, and dashboard credential,
  or an equivalent shape if research during design surfaces a better one.
- Extend the VM seller negotiation strategy to validate buyer-supplied
  connectivity terms before accepting — reachability/shape checks belong at
  the same point other domain-specific buyer terms are already validated,
  not deferred to settlement or fulfillment time. See `design.md`'s Open
  Questions for what "valid" means here and the security consideration
  below.
- Thread validated connectivity terms through settlement encoding
  (`encode_compute_lease`/`order_bytes`) so they survive from negotiation
  acceptance to fulfillment time, the same way other agreed terms do today.
- Populate `pools-7-storefront-fulfillment-cutover`'s `connectivity` field
  (added to the VM fulfillment request payload as a storefront-configured
  stopgap — see that change's design.md) from the negotiated terms instead
  of from storefront settings, once available. Falls back to the existing
  storefront-configured default when a buyer supplies no connectivity terms
  of their own, preserving today's behavior as the default.
- State: **New capability. Not yet planned — see `design.md`'s Open
  Questions before task planning begins.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `negotiation-protocol`: the VM domain's versioned provision envelope gains
  an optional connectivity payload.
- `buyer-orchestration` / VM domain negotiation strategy: validates
  buyer-supplied connectivity terms before acceptance.
- `physical-provisioning`: VM fulfillment request's `connectivity` field
  (introduced by `pools-7-storefront-fulfillment-cutover` as
  storefront-configured) gains a negotiated-terms source.

## Non-Goals

- Do not remove or deprecate storefront-operator-configured FRP as a
  default. Buyer-specified connectivity is additive; a buyer who supplies
  none gets today's seller-operated relay, unchanged.
- Do not redesign VM connectivity delivery generally (e.g. moving away from
  FRP as the mechanism). Scope is *who specifies* today's existing FRP
  parameters, not what the mechanism is.
- Do not implement this as part of `pools-7-storefront-fulfillment-cutover`.
  That change's Section 9 only adds the field shape (`connectivity`,
  storefront-configured) that this change later populates from a different
  source; it does not touch negotiation.

## Dependencies and Related Changes

- Depends on `pools-7-storefront-fulfillment-cutover` Section 9 landing
  first: the VM fulfillment request's `connectivity` field must exist,
  storefront-configured, before this change gives it a second, negotiated
  source. This change reuses that field's shape rather than reshaping it.
- Candidate starting shape and the scope-split rationale are recorded in
  `pools-7-storefront-fulfillment-cutover/design.md`'s Section 9 design
  review (FRP forwarding discussion, 2026-07-26).

## Impact

- VM buyers gain the ability to specify their own connectivity relay as
  part of a deal's negotiated terms.
- VM seller negotiation strategy gains a new validation step.
- Settlement encoding for the VM domain gains a new optional field.
- Deployment/operator configuration is unaffected for sellers who don't
  need this; the existing storefront-configured FRP default keeps working.

## Permanent documentation impact

- [ ] Existing subsystem specification: `openspec/specs/negotiation-protocol/spec.md` (versioned domain provision envelope, VM connectivity payload)
- [ ] Existing subsystem specification: `openspec/specs/physical-provisioning/spec.md` (connectivity field's negotiated-terms source)
- [ ] No `ARCHITECTURE.md` change anticipated unless the design phase concludes repository-wide negotiation vocabulary needs updating

### Knowledge to promote

- <to be completed once the design phase resolves the Open Questions in `design.md`>
