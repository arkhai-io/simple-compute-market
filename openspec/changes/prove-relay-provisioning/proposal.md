## Why

The relay path is implemented and has never run against real hardware.
`relay-vm-access-without-a-dashboard` made a relay an administered resource, allocates
each VM's tunnel port from the relay's window, binds the relay token late, and splits a
host's buyer-facing tunnel client from its management client; its reload gate
(section 6) and live checks (section 8) wait on "a rented, initialized host and the
deployed relay", and it cannot close until they are run. `ROADMAP.md` records the
consequence as an unowned gap: no end-to-end lane runs a relay-backed pool, which is why
a relay-backed VM's wrong delivered address once went unnoticed.

The real-provisioning lane `prove-real-vm-provisioning` built proves direct access only.
Its target description (version 1) names one KVM host reached at its own address, and it
refuses `access.mode: relay`. It also deals on the host's whole sellable capacity, so it
cannot hold two guests at once, which section 8's "a second VM leaves the first session
alive" needs.

Bare metal has no relay path at all. A bare-metal grant installs the buyer's key for a
tenant account on the whole host and delivers the host's own address; a host that has no
inbound route cannot be sold as bare metal. The relay tables (`relays`,
`relay_port_leases`, the pool's relay reference) are already the provisioning family's,
and the relay design names a GPU pool and a bare-metal pool sharing one rendezvous as the
ordinary case, but the relay services, the port allocator, the terminal-transition port
release, and the buyer-client role live in the VM domain, where
`bare-metal-mock-provisioned-deal` moved them.

## What Changes

- **Relay access for bare metal.** A bare-metal pool may reference a relay, as a VM pool
  does. A grant on a relay-backed pool allocates a port from the relay's window, adds one
  buyer proxy from the host's `127.0.0.1:22` to that port in the host's buyer-facing
  tunnel client, and delivers `ssh -p <port> <tenant>@<relay address>`. A reclaim removes
  the proxy and releases the port for reuse. Neither touches the host's management
  tunnel client, which the operator configures when preparing the host and the
  application never reads, writes, or reloads. Bare-metal host preparation gains the
  buyer-facing client, as VM host preparation has it. Where the relay services live once
  two domains use them, and whether bare metal reuses the VM domain's buyer-client role,
  are this change's design questions; the VM and bare-metal access paths differ in more
  places than this (where the buyer's key enters, the roles, the delivered endpoint),
  and the design should say which of those it unifies and which it leaves.
- **Real-provisioning target, version 2.** The target describes several hosts, each with
  its domain (VM or bare metal), the address and port the provisioning service reaches it
  at (which, for a relay-reached host, is its management tunnel, not its own address),
  the provisioning user, and the capacity it sells; and, for relay access, the relay's
  address, control port, and window. The relay token is never in the target: the stack
  supplies it through the provisioning profile. Version 1 stays readable or is retired;
  the design decides.
- **The real VM lane over a relay.** The lane runs with relay access, deals on a small
  shape so the host holds two guests at once, and produces the evidence for
  `relay-vm-access-without-a-dashboard`'s section 6 and section 8: a live buyer session
  held across a second VM's creation, a proxy inside the window accepted and one outside
  refused, the management tunnel unaffected by VM churn, the delivered string connecting
  from outside the cluster, and teardown releasing a port that a later VM reuses.
- **A real bare-metal lane over a relay.** A grant on a relay-backed bare-metal host
  delivers a string that connects; an unrelated key is refused; after reclaim the string
  is refused and the port is released and reused by a later grant; the management tunnel
  is unchanged across grant and reclaim. Whether this extends the release-qualified
  `e2e_bare_metal_deal` scenario or follows the real VM lane's shape (registering its own
  supply from the target) is a design question.
- **Live verification** against operator-provided hosts and relays, supplied by the owner
  as `prove-real-vm-provisioning`'s was. A bare-metal host for the live run may be a
  virtual machine: the bare-metal domain grants and reclaims access on a running host over
  SSH and touches no hardware, so the run proves the access flow, not anything about
  hardware.

## Capabilities

### Modified Capabilities

- `physical-provisioning`: relay access for bare-metal pools; where the relay services
  and the buyer-facing client belong once two domains use them.
- `test-compatibility`: the real-provisioning target's version 2; the real VM lane over a
  relay; a real bare-metal lane over a relay.

### New Capabilities

None expected; the design confirms.

## Non-Goals

- Several sites or storefronts admitted to one shared relay. A token admits its holder to
  every port the relay allows, so per-site admission on a shared relay is its own change.
- Configuring a host's management tunnel client. It stays the operator's, outside the
  application, as the relay design decided.
- A recovery path to a host that does not depend on its SSH daemon.
- Per-lease buyer keys. Reusing a buyer's key across leases is acceptable.
- A DNS name or certificate for a relay; the delivered string may name its address.
- Running the real lanes in the end-to-end pipeline; like the direct real lane, they run
  outside every lane.
- Relay deletion semantics (`relay-vm-access-without-a-dashboard` decision gate 1A.7)
  and the concurrent-allocation retry gap `ROADMAP.md` records, unless the design finds
  this change cannot avoid them.

## Impact

- `domains/bare_metal/provisioning/`: the adapter's grant and reclaim, its codec's
  delivered endpoint, the pool configuration handler, and the `bare-metal-access` role and
  a host-preparation step for the buyer-facing client.
- `domains/vms/provisioning/adapter/` and possibly `provisioning/compute/`: the relay
  services, port allocator, and terminal-transition release, wherever the design places
  them.
- `domains/vms/provisioning/iac/ansible/`: the buyer-client role if it becomes shared.
- `e2e-tests/`: the target model and its `.example`, the real VM lane's driver and stages,
  the bare-metal real lane, and their unit tests.
- Chart: none expected; the relay definitions document already carries relays.

## Dependencies and Related Changes

- `relay-vm-access-without-a-dashboard` (blocked in closeout): its implemented relay
  resource, allocator, and split clients are what this change exercises, and its sections
  6 and 8 are closed with evidence this change's live run produces. It does not gate this
  change; this change unblocks it.
- `prove-real-vm-provisioning` (archived): the real lane, target description, and shared
  stage split this change extends.
- `repair-compute-purchase-recovery` (archived): the release-qualified bare-metal deal
  scenario and its recovery commands.
- `contain-embedded-host-key-material` (ready for design): independent; hosts here are
  reached with the deployment's shared key.
- Takes ownership of the `ROADMAP.md` gap "No end-to-end lane runs a relay-backed pool".

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `physical-provisioning` (spec and architecture),
      `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion. Expected: relay access for bare metal and where
relay machinery lives → `physical-provisioning`; the target's version 2 and the relay
lanes → `test-compatibility` and `docs/development/TESTING.md`; the operator procedure →
`docs/development/VALIDATION_RUNBOOK.md` and the bare-metal seller quickstart; the closed
gap → `docs/development/ROADMAP.md`.
