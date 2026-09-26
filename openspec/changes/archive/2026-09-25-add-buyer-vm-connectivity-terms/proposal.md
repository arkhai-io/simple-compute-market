<!-- Archived 2026-09-25 as superseded, without implementation. The premise —
buyer-negotiated relay coordinates (FRP server address, domain, dashboard credential)
threaded into the fulfillment request — was foreclosed by
`relay-vm-access-without-a-dashboard`'s promoted contract and by the mechanism it
built. Contract: `physical-provisioning`'s "Ansible fulfillment adapter" requires that
the request's `connectivity` field carry no relay configuration and that a relay never
be selectable per request, because which relay a host dials is a physical fact about
that host; `vm-storefront-fulfillment` forbids the storefront from holding a relay
credential; and the dashboard credential no longer exists. Mechanism: the
buyer-facing tunnel client runs on the *host* (`/etc/frp/frpc-vms.toml`, one process
with one `serverAddr` carrying one proxy per rented VM), not in the guest, so there
is no per-VM relay choice to expose — this design's assumption that "the provisioned
VM connects out to the buyer's FRP server" describes a client that does not exist.
The seller's relay is the bootstrap path for every VM: it is the only route to a host
with no inbound port, and a buyer receives a port on it in the fulfillment result. A
buyer who wants their own relay reaches the VM through that port once and starts a
client inside the guest, which has outbound connectivity. If a buyer ever needs to
avoid the seller relay's port entirely, the shape of that work is a buyer-supplied
first-boot configuration (cloud-init user data or a guest agent) that starts a tunnel
client inside the VM at creation — a guest-side concern, more general than FRP, not
touching the host's relay or port lease — and it should be opened fresh under the
"Reach hosts" lesser goal rather than built on this change's mechanism. The SSRF
question this design raised applies there too: a guest dialing a buyer-named address
is the point; a storefront dialing one during negotiation is not. -->

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
- State: **Not yet planned — see `design.md`'s Open Questions before task
  planning begins.** (**Corrected 2026-08-06:** previously read "New
  capability," contradicting the "New Capabilities: None" declaration below.
  This change modifies existing capabilities.)

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `negotiation-protocol`: the VM domain's versioned provision envelope gains
  an optional connectivity payload.
- `buyer-orchestration`: the VM domain's negotiation strategy validates
  buyer-supplied connectivity terms before acceptance. **Corrected
  2026-08-06:** previously written as two entries joined by a slash, which
  does not resolve to a capability.
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
- **Added 2026-08-06:** two changes now reshape the same negotiation envelope
  this change extends. `capacity-shape-pricing` makes the negotiated quantity
  a rate multiplier rather than an absolute amount, and
  `negotiation-driven-capacity-resize` Section 2 adds a revised-terms field as
  a child of `proposal`. Connectivity terms are round-zero provision payload
  rather than per-round terms, so no direct conflict is expected — but the
  envelope's shape should be settled with those changes rather than extended
  independently.

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
