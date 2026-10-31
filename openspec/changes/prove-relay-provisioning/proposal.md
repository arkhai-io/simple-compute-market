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
Its target description (version 1) names one KVM host and refuses
`access.mode: relay`, and its listing takes the host's whole capacity, so it cannot hold
two guests at once.

Bare metal cannot be sold over a relay with a leased port. Its pools accept no relay
reference, the relay machinery is the VM domain's, and a tunnel-reached bare-metal host
is delivered at whatever route its connection names. And no relay may be sold over as
it stands: the buyer-facing client's admin API is unauthenticated on loopback, which
gives any account on a host other than root the relay token and local root, and whoever
holds a relay's token can register any free port the relay allows.

## What Changes

- **The relay machinery becomes the compute family's.** Relays, port leases, the
  allocator, relay administration, the definitions importer, the rebinding refusals,
  execution-time resolution, reconciliation, and the release effect move from the VM
  adapter into `compute_provisioning`, with their contracts and client in the family's
  thin distributions. Every pool's relay reference is stored once, in `pool_relays`.
- **Bare-metal relay access.** A bare-metal pool may reference a relay. A grant leases
  a port, adds one buyer proxy from the host's `127.0.0.1:22`, and delivers
  `ssh -p <port> <tenant>@<relay address>`; a reclaim removes the proxy and releases
  the port. Bare-metal host preparation installs the buyer-facing client.
- **Relay admission by signed grants.** The provisioning service signs a grant per
  lease with a key the relay row holds; the proxy carries it; a plugin on the relay
  admits a proxy only for the port its grant names, within its key's range. Every
  relay enforces admission; management ports use another relay; a relay may be shared
  by several provisioning services, each bound to its own range. A released port is
  not reissued until its grant expires. The plugin itself is the prerequisite change
  `frp-grant-admission`'s.
- **Hardened hosts.** The buyer-facing tunnel tasks become shared family roles; the
  client's admin API is authenticated on a privileged loopback port; every reclaim
  policy ends the tenant's sessions, processes, and scheduled jobs.
- **Relay holdings are readable** through an administrator-only leases route.
- **Real-provisioning target, version 2.** One section describes a host per domain,
  each with its connection, its access (a relay by id, or direct with a buyer
  address), its capacity, and, for VM, the listing shape the lane publishes. Version 1
  is retired.
- **The real VM lane over a relay** holds a live session across a second deal's
  create and teardown, and produces the evidence for the relay change's sections 6
  and 8.
- **A real bare-metal lane over a relay**: delivery, an unrelated key refused, access
  ended and the port released after reclaim, the management tunnel unchanged.
- **Live verification** against operator-provided hosts and relays. A bare-metal host
  for the live run may be a virtual machine: the bare-metal domain grants and reclaims
  access on a running host over SSH and touches no hardware.

## Capabilities

### Modified Capabilities

- `physical-provisioning`: relay ownership by the compute family; bare-metal relay
  access; signed grants, relay keys, admission on every relay, port quarantine, the
  holdings read, and the management-address check; the hardened buyer-facing client;
  reclaim ending the tenant's activity.
- `test-compatibility`: the real-provisioning target's version 2; the real VM lane
  over a relay; a real bare-metal lane over a relay.

### New Capabilities

None. The plugin's capability is `frp-grant-admission`'s.

## Non-Goals

- Admission at login on a shared relay: a shared token still lets every site's hosts
  log in. Deferred, with its trigger in `design.md`.
- Revoking a grant before it expires; teardown removes the proxy and the access.
- Configuring a host's management tunnel client. It stays the operator's.
- A recovery path to a host that does not depend on its SSH daemon.
- Per-lease buyer keys. Reusing a buyer's key across leases is acceptable.
- A DNS name or certificate for a relay; the delivered string may name its address.
- Running the real lanes in the end-to-end pipeline; like the direct real lane, they
  run outside every lane.
- Extending a lease without dropping its session.
- Relay deletion semantics (`relay-vm-access-without-a-dashboard` decision gate 1A.7)
  and the concurrent-allocation retry gap `ROADMAP.md` records.
- Moving the admission plugin to its own repository, which is a later change.

## Impact

- `provisioning/compute/` (`compute_provisioning`, its contracts and client, the
  service): the relay package, `pool_relays` and its migration, grant signing, relay
  keys and their rotation, the holdings read, preparation's admission checks.
- `domains/vms/provisioning/adapter/` and its operator client: the relay machinery
  leaves; the plan, codec, and mock output keep VM's share.
- `domains/bare_metal/provisioning/adapter/`: pool configuration, the plan's
  allocation, the codec's relay endpoint.
- `provisioning/compute/iac/` (new): `relay-client`, `relay-proxy`, `relay-server`.
- `domains/vms/provisioning/iac/`: VM's tasks onto the family roles; `frp-setup`
  moves out; the create facts' relay block.
- `domains/bare_metal/provisioning/iac/`: the access role's relay proxy and reclaim
  policy; a host-preparation playbook.
- `provisioning/compute/service` image: copies the family IaC tree.
- `e2e-tests/`: the target model and example, both real lanes, the SSH helper, and
  their unit tests.
- Documentation: the validation runbook, the seller relay and bare-metal guides.

## Dependencies and Related Changes

- `frp-grant-admission` (prerequisite, gating implementation): builds the relay
  admission plugin and owns the grant specification and test vector this change's
  signer conforms to.
- `relay-vm-access-without-a-dashboard` (blocked in closeout): its implemented relay
  resource, allocator, and split clients are what this change moves and exercises, and
  its sections 6 and 8 are closed with evidence this change's live run produces. It
  does not gate this change.
- `prove-real-vm-provisioning` (archived): the real lane, target description, and
  shared stage split this change extends.
- `repair-compute-purchase-recovery` (archived): `e2e_bare_metal_deal` and its
  recovery commands, which move onto the shared SSH helper unchanged.
- `contain-embedded-host-key-material` (ready for design): independent; hosts here are
  reached with the deployment's shared key.
- Takes ownership of the `ROADMAP.md` gap "No end-to-end lane runs a relay-backed
  pool".

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `physical-provisioning` (spec and architecture),
      `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The relay machinery and the pool's relay reference are the compute family's (D2) →
  `ARCHITECTURE.md` "Family kits"; `openspec/specs/physical-provisioning/spec.md` and
  `architecture.md` "Buyer access to rented VMs", renamed for both domains.
- Bare-metal relay access, and a tunnel-reached bare-metal host's buyer route (D1,
  D15b) → `physical-provisioning` spec; its architecture "The host registry owns the
  connection"; the bare-metal seller guide.
- Shared buyer-facing tunnel roles, and host-level client configuration belonging to
  the host (D3) → `physical-provisioning` architecture; `docs/seller-frp-setup.md`.
- The admin API's lockdown and the token's boundary on a host (D4) →
  `physical-provisioning` spec and architecture; the seller guides (a buyer-only relay
  by default, the management client's admin API).
- Signed-grant admission, the grant's lifecycle, relay keys, admission on every relay,
  shared relays (D14, D16, D17, D19, D20) → `physical-provisioning` spec and
  architecture; `docs/development/VALIDATION_RUNBOOK.md` (plugin configuration, key
  rotation, site onboarding, a host teardown cannot reach).
- Relay infrastructure never calls an SCM service (D14) → `ARCHITECTURE.md`
  "Authority boundaries".
- SCM does not own generic infrastructure that is not specific to it; having to build
  it is a warning sign to weigh (D18) → `ARCHITECTURE.md` "Package and dependency
  layers".
- Reclaim ends the tenant's activity (D15) → `physical-provisioning` spec.
- The holdings read (D9) → `physical-provisioning` spec.
- The target's version 2, both real lanes, and the evidence split (D5–D11) →
  `openspec/specs/test-compatibility/spec.md`; `docs/development/TESTING.md` "The
  real-provisioning lane"; `e2e-tests/README.md`; the runbook.
- The closed relay-lane gap; the unowned gaps for `host_key_checking = False` and for
  admission at login on a shared relay (D4, D21) → `docs/development/ROADMAP.md` Goal 1.
