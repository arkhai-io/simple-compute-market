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
  lease with a key the relay row holds, conforming to the plugin's grant
  specification — type `frp-grant+jwt`, the key named by its RFC 7638 thumbprint,
  RFC 8785 serialization, an integer expiry, the host and the owning reservation as
  string subject and identifier, no `iat` — through `cryptography` and `rfc8785`, with
  no JWT library; the proxy carries it; a plugin on the relay admits a proxy only for
  the port its grant names, within its issuer's range. Every
  relay is configured for admission: every proxy carries a grant, and a relay with no
  active key is refused. That a relay enforces it is the operator's installation,
  stated as the relay's requirements and proven by the runbook's admission check
  before its pools serve buyers; the service does not verify it. The operator supplies
  a relay's key through the secrets profile as base64 PKCS#8 DER, refused by name when
  malformed, so a reinstall keeps it; rotation stages a supplied key, redacted
  everywhere, or one the service generates. A retired key stays
  valid while a lease allocated before its retirement is unreleased and its grant
  unexpired. Management ports use another relay. One relay per operator, with its own
  token, is the recommended deployment; a relay may be shared by several provisioning
  services, each bound to its own range, the relay's window lying within it, with its
  limits stated. A released port is not reissued until its grant's expiry plus a
  configured reuse margin has passed, with the relay's and the service's clocks kept
  synchronised. The plugin itself is the prerequisite change
  `admit-relay-proxies-by-grant`'s, building the tool `frp-grant-admission`; SCM's tests
  check the signer against its vector and the frp pin against its pins file.
- **Relays run the plugin.** `relay-server` prepares a VPS relay — frps under systemd
  and the plugin as a plain program from a wheel it is given — and discloses no
  secret; a containerised relay runs the plugin's image as a sidecar beside frps, as
  the runbook describes, which is the kind the live run uses.
- **Hardened hosts.** The buyer-facing tunnel tasks become shared family roles; the
  client's admin API is authenticated on a privileged loopback port; frps and frpc
  come from one pinned frp version (0.61.1), checked against a pinned SHA-256 and
  installed at a versioned path; every reclaim policy ends the tenant's sessions,
  processes, and scheduled jobs.
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
  one verified frp pin; relay preparation running admission and disclosing no secret;
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
- Emergency rotation of a relay's credentials across live hosts — re-issuing grants
  under a new key, and rotating the relay token — recorded as a `ROADMAP.md` gap for a
  follow-up change; the runbook states the per-incident choice meanwhile.
- Relay deletion semantics (`relay-vm-access-without-a-dashboard` decision gate 1A.7)
  and the concurrent-allocation retry gap `ROADMAP.md` records.
- Moving the admission plugin to its own repository, which is a later change, and
  publishing its wheel to PyPI or a public image, which belong with that move.
- Live evidence for `relay-server`'s plugin install: the live run's relay is
  containerised, and the role is proven by its tests.

## Impact

- `provisioning/compute/` (`compute_provisioning`, its contracts and client, the
  service): the relay package, `pool_relays` and its fail-forward migration, grant
  signing (the family kit declaring `cryptography` and `rfc8785` at runtime) and the
  relay secret fields every relay-carrying codec redacts, relay keys and their
  rotation, the expiry grace and reuse-margin settings, the holdings read,
  preparation's admission checks, and the vector and pins checks.
- `domains/vms/provisioning/adapter/` and its operator client: the relay machinery
  leaves; the plan, codec, and mock output keep VM's share.
- `domains/bare_metal/provisioning/adapter/`: pool configuration, the plan's
  allocation, the codec's relay endpoint.
- `provisioning/compute/iac/` (new): `relay-client`, `relay-proxy`, `relay-server`,
  `frp-binary`.
- `domains/vms/provisioning/iac/`: VM's tasks onto the family roles; `frp-setup` and
  its playbook leave for `relay-server`; the create facts' relay block.
- `domains/bare_metal/provisioning/iac/`: the access role's relay proxy and reclaim
  policy; a host-preparation playbook.
- `provisioning/compute/service` image: copies the family IaC tree and sets
  `ANSIBLE_ROLES_PATH` to its roles; each domain's `ansible.cfg` (bare metal gaining
  one) adds the family roles to its `roles_path`.
- `e2e-tests/`: the target model and example, both real lanes, the SSH helper, and
  their unit tests.
- Documentation: the validation runbook, the seller relay and bare-metal guides.

## Dependencies and Related Changes

- `admit-relay-proxies-by-grant` (prerequisite, gating the plugin-dependent sections
  and closeout): builds the relay admission plugin, the tool `frp-grant-admission`,
  which owns the grant specification, test vector, and frp pins this change's signer
  and roles conform to; its settled design (D1–D23, on this branch as copied from its
  branch at `c792653e5`) and its notes for this change are reconciled in `design.md`
  (D16, D17, D18, D20, D22, D23).
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
  architecture; `docs/development/VALIDATION_RUNBOOK.md` (plugin configuration, the
  admission check as a precondition before a relay-backed pool serves buyers, key
  rotation and a retired key's retention, an emergency rotation, site onboarding with
  the window within its range, the drain rule, a host teardown cannot reach);
  `docs/seller-frp-setup.md` (what a relay must run).
- The grant's conformance to the plugin's specification (no `iat`, JCS signing, claim
  types, `jti` the owning reservation, thumbprint key ids, public keys in the plugin's
  format) and the vector and pins checks (D16, D17, D18) → `physical-provisioning` spec
  and architecture, the section on relay admission.
- The grant key's profile form and its refusal, rotation with a supplied key keeping
  the profile current, and its redaction (D17) → `physical-provisioning` spec;
  `docs/development/DEPLOYMENT_AND_CONFIG.md` (the secrets-profile key and its form);
  the runbook (rotation, a service-generated key surviving only with the database).
- One relay per operator as the recommended deployment, a shared relay's limits, the
  emergency choice per incident, and the host- and relay-side steps for a host teardown
  cannot reach — the leased port blocked and its connections ended, the block's record
  and lifting, the step's limit to access through the relay, and on a shared relay who
  does what (D16, D17, D20) → `physical-provisioning` architecture; the runbook;
  `docs/seller-frp-setup.md`.
- Tracing a plugin log line's `jti` to its tenancy — the holdings read while the row
  stands, the lease read once it has been reused (D16) → the runbook.
- The plugin wheel as the operator's trusted input, with its dependencies checked
  against the tool's lock (D23) → `physical-provisioning` architecture; the runbook.
- The reuse margin, the grant expiry's grace, and the clock-synchronisation
  requirement (D16) → `physical-provisioning` spec;
  `docs/development/DEPLOYMENT_AND_CONFIG.md` "Definition documents", a subsection
  "Relay grants and port reuse" (`relay_port_reuse_margin_seconds`,
  `relay_grant_expiry_grace_seconds`); the runbook (clocks).
- One verified frp pin at versioned paths (D22) → `physical-provisioning`
  architecture; `docs/seller-frp-setup.md` (the frp version).
- How a relay runs the plugin — `relay-server` from a given wheel on a VPS, the image
  as a sidecar on a containerised relay — and `relay-server` disclosing no secret (D3,
  D23) → `physical-provisioning` spec and architecture; the runbook (relay
  preparation, both kinds of relay, building the wheel until it is published).
- The fail-forward drop of `ansible_pool_configs.relay_id`, with its pre-upgrade
  backup (D2) → `docs/development/DEPLOYMENT_AND_CONFIG.md`, beside the
  `hosts.gpu_count` drop.
- The family roles found through the role search path (D3) → `physical-provisioning`
  architecture.
- Secrets kept out of job logs by `no_log` and the family's relay secret fields (D3,
  D16) → `physical-provisioning` spec and architecture.
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
- The closed relay-lane gap; the unowned gaps for `host_key_checking = False`, for
  admission at login on a shared relay, and for emergency rotation of both relay
  credentials across live hosts (D4, D21, D17) → `docs/development/ROADMAP.md` Goal 1.
