# Harden the provisioning service's trust in hosts and guests

## Why

Goal 1 makes the provisioning service the one authority over physical resources.
That authority reaches hosts over SSH, holds their credentials, and places
different buyers' guests side by side. Four gaps in `docs/development/ROADMAP.md`
are places where it trusts more than it should:

- **Host keys go unchecked.** Both Ansible configurations the service runs with set
  `host_key_checking = False`
  (`provisioning/compute/ansible/src/compute_provisioning_ansible/ansible.cfg` and
  `domains/vms/provisioning/iac/ansible/ansible.cfg`). Anyone who can intercept the
  connection can pretend to be a host. They then receive a buyer's workload, or the
  deployment's own key material, and the service records success.
- **Guests on one host share a network segment.** VM guests attach to libvirt's
  `default` NAT network (`--network network=default` in the `vm-management`
  role's install tasks). That is one bridge per host with no isolation rule, so
  guests on the same host, including different buyers', can reach each other at
  layer 2.
- **An embedded host credential travels in plaintext, under one key.** A host
  registered with its own key (`POST /api/v1/hosts` with `secrets`, or the INI
  import's `embedded` mode) sends that key over the operator-to-provisioning hop
  protected only by the authenticated transport. At rest it's protected by
  `fernet-v1`, which is one symmetric key the service holds
  (`provisioning/compute/ansible/src/compute_provisioning_ansible/connection.py`).
  `bare-metal-mock-provisioned-deal` left this open. Sealed submission to the
  service's public key, references to a secret authority, and managed envelope
  encryption each need only a new protected-value scheme and its codec.
- **Every provisioning route admits the administrator.** Nobody has decided
  whether every other service should take the same stance. Until someone does,
  each service's answer is an accident of how it was built.

These are grouped because they are one theme: what the provisioning boundary
trusts. They'll be reviewed against one threat model.

## What Changes

- **A host's SSH key is verified.** The service checks every host it reaches
  against a host key it recorded or was given. A host whose key doesn't match is
  refused, and the refusal names the host.
- **Guests are isolated from each other.** A VM guest can reach the host's
  uplink but not another guest on the same host, unless design finds a reason a
  seller would opt into sharing.
- **A host credential is protected from submission to use.** A new
  protected-value scheme removes plaintext submission, a single service-held key,
  or both. `fernet-v1` stays readable until every stored value has moved.
- **The administrator's reach is decided once, for every service.** The decision
  is recorded where the repository's cross-system rules live, and each service
  either conforms or carries a stated exception.

### Decided by the owner

- **D1: one change for the provisioning trust gaps.** Goal 1's unowned gaps are
  grouped by theme. This change takes host-key checking, guest isolation, host
  credential protection, and the administrator stance.

### Open for design, not decided here

- **Where a host key comes from.** Captured on first contact (trust on first use),
  stated in the host's registration and its definition document, or both. How a
  host's key is rotated. Whether a relayed host's key is checked through its
  tunnel port.
- **The isolation mechanism.** A libvirt network per guest, a filtering rule on the
  shared bridge, or private VLANs. What a GPU passthrough guest needs. How a host
  prepared before this change moves over without stranding a running guest.
- **The credential scheme.** Sealed submission to the service's public key, a
  reference to a secret authority, or managed envelope encryption. How the stored
  values migrate, and what readiness reports while they do.
- **The administrator stance.** Whether every service admits the administrator on
  every route, on none but an administration surface, or by a per-route
  declaration. Whether this decision belongs in this change or in a
  repository-wide change of its own, if it reaches beyond provisioning.
- **Whether a gap should leave the change.** If one of the four needs a design of
  its own, design can split it out.

## Capabilities

### Modified Capabilities

Provisional; settled in design.

- `physical-provisioning`: host-key verification and host credential protection.
- `resource-pool-management` or the VM provisioning adapter's capability: guest
  network isolation.
- `deployment-state`: the host key and credential fields in the host definition
  document.

### New Capabilities

None.

## Non-Goals

- Shared-relay admission at login, emergency rotation across live hosts, and
  pinning the admission plugin's digest. `harden-shared-relays` owns these.
- Isolating bare-metal tenants from each other. A whole machine goes to one
  tenant.

## Impact

- Both `ansible.cfg` files and the inventory the executor writes
  (`provisioning/compute/ansible/`).
- The host registration API, its INI import, and the host definition document.
- The `vm-management` role's install tasks and the VM host kit's preparation.
- `provisioning/compute/ansible/src/compute_provisioning_ansible/connection.py`
  and its codecs.
- Every service's authorization where the administrator stance changes it.
- `docs/operator-handbook.md`, both seller quickstarts, and the VM host kit's
  README.

## Dependencies and Related Changes

- None.
- `harden-shared-relays` hardens the relay half of the same boundary. It's
  deferred until its triggers.
- `redesign-authenticated-requests` is reworking service request authentication.
  Design checks that the administrator stance doesn't cut across it.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`, if the administrator stance becomes a
  cross-system rule
- [x] Existing subsystem specification: `physical-provisioning`,
  `deployment-state`, and, as design settles, `resource-pool-management`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion. Expected destinations: the
`physical-provisioning` specification and architecture companion, the operator
handbook's host registration, `docs/development/DEPLOYMENT_AND_CONFIG.md`, and
`docs/development/ROADMAP.md`'s Goal 1 current state.
