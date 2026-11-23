# Harden the provisioning service's trust in hosts and guests

## Why

Goal 1 makes the provisioning service the one authority over physical resources.
That authority reaches hosts over SSH and places different buyers' guests side by
side. Three gaps in `docs/development/ROADMAP.md` are places where it, or the
services around it, trust more than they should:

- **Host keys go unchecked.** The Ansible configuration the service runs with sets
  `host_key_checking = False`
  (`provisioning/compute/ansible/src/compute_provisioning_ansible/ansible.cfg`), and
  an operator's own configuration replaces it whole. Anyone who can intercept the
  connection can pretend to be a host. They then receive what a playbook sends it —
  the relay's shared client token, the host's frpc admin password, a buyer's access
  material — and the service records success.
- **Guests on one host share a network segment.** VM guests attach to libvirt's
  `default` NAT network (`--network network=default` in the `vm-management` role's
  install tasks), one bridge per host with no isolation rule. Guests on the same host,
  including different buyers', reach each other at layer 2 and layer 3, every host
  port but 22, and the seller's private networks; one can claim another's address.
- **The administrator's reach is not one rule.** The provisioning service and the site
  authorities admit the administrator on every route; the storefronts admit it only on
  administrator routes; nothing records why, or what a new service should do.

These are grouped because they are one theme: what the provisioning boundary trusts.
They are reviewed against one threat model.

A fourth gap the owner first grouped here, protecting an embedded host credential
from submission to use, is deferred to an unowned gap (design D11).

## What Changes

- **A host's SSH key is verified.** The `ssh` connection carries `host_keys` at version
  3. A key is stated at registration, or reported by an operator's connectivity check
  and recorded by a capture route that compares the fingerprint the operator names.
  The Ansible executor checks every host against its pin before a job's recorded
  start, through a per-job `known_hosts` and host variables no Ansible configuration
  overrides, and refuses an unpinned or mismatched host as never started, naming the
  host, its endpoint and both fingerprints.
- **Deployed hosts are adopted once.** Hosts the upgrade migration rewrites are adopted
  by the probe before their first job, which sends nothing secret; the adoption retires
  at a stated release.
- **Guests are isolated.** A VM guest's port on the shared bridge is isolated, an
  anti-spoofing filter holds it to its own address, and the host drops forwarding
  between guests. A guest reaches DHCP and DNS on its host and nothing else there, and
  no link-local or private destination the seller does not list. The host kit
  converges running guests live, until a stated release.
- **Guest isolation is proven on a real host.** An external-topology scenario extends
  the real-provisioning scenario's two guests, reaches the host through an operator
  route its target names, and reports each observation made, failed or unproven;
  closeout waits on the observations it requires.
- **The administrator's reach is one rule.** The administrator is admitted on every
  route acting on its operator's resources and never authorized as a party to a deal.
  It is recorded in `ARCHITECTURE.md`, stated by each service's specification, held by
  tests in each storefront; the API-credits storefront's unauthenticated negotiation
  reads require the administrator.
- **Compatibility code retires on a schedule.** The engineering guidance gains
  retiring compatibility; the release handbook gains the table of compatibility to
  retire, read before a release candidate is loaded.

### Decided by the owner

- **D1: one change for the provisioning trust gaps.** Goal 1's unowned gaps are
  grouped by theme. Design keeps host-key checking, guest isolation and the
  administrator stance (D2), and defers host credential protection (D11).

## Capabilities

### Modified Capabilities

- `physical-provisioning`: host-key verification, its capture and adoption, the `ssh`
  connection at version 3, guest network isolation, and the administrator rule as it
  applies to the provisioning service.
- `site-capacity`: the site authority admits the administrator on every route.
- `api-credits`: the credits ledger's site authority admits the administrator on every
  route.
- `storefront-publication`: a storefront never authorizes its administrator as a
  party, and every storefront's negotiation reads are the administrator's.
- `test-compatibility`: a real VM scenario pins its host only from an independent
  source, and the real-host proof of guest isolation with the target's
  `guest_isolation` section.

### New Capabilities

None.

## Non-Goals

- Host credential protection: sealed submission, a secret-authority reference, managed
  envelope encryption, relay secrets under `ssh_decryption_key`, and migrating
  `fernet-v1` values. Deferred to an unowned gap.
- Shared-relay admission at login, emergency rotation across live hosts, and pinning
  the admission plugin's digest. `harden-shared-relays` owns these.
- Isolating bare-metal tenants from each other. A whole machine goes to one tenant.
- The host's own SSH into a guest it has just created.
- How the registry's administrator authenticates (an unowned gap), and the API-credits
  service's `X-Admin-Key` fallback (`redesign-authenticated-requests`).
- Listing the compatibility paths already in the code (an unowned gap).

## Impact

- `provisioning/compute/ansible/`: the `ssh` codec and connection at version 3, the
  runner's inventory and per-job `known_hosts`, the executor's check before a job's
  start, the connectivity probe, readiness, and the INI import.
- `provisioning/compute/src/compute_provisioning/hosts/`, the provisioning contracts
  and client: the host record's pending-adoption flag, the capture route, the
  connectivity result, the host definitions document and its export.
- The provisioning migration chain: version 2 to version 3, marking hosts for adoption.
- `domains/vms/provisioning/iac/ansible/`: the `vm-management` role's interface
  definition, and the VM host kit's isolation rules, nwfilter, the installed
  convergence command for running guests, removal of the older per-port rules, and
  `guest_allowed_private_destinations`; the VM IaC README.
- `e2e-tests/`: the real-provisioning target's `guest_isolation` section and
  `e2e_vm_guest_isolation` with its guest-side and operator probes.
- `domains/apicredits/storefront/`: authentication of its negotiation reads and its
  advance under the operations the canonical client signs; the three storefronts'
  refusal tests, the deal-servicing kit's for the lifecycle routes they mount, and the
  credits service's administrator case.
- The e2e real-provisioning helpers, which state or capture host keys.
- `docs/operator-handbook.md`, both seller quickstarts, the release handbook, the
  engineering and repository guidance, and `ARCHITECTURE.md`.

## Dependencies and Related Changes

- None.
- `harden-shared-relays` hardens the relay half of the same boundary. It's deferred
  until its triggers.
- `redesign-authenticated-requests` is reworking service request authentication. It
  touches no route roles, and its operation-bound envelope is compatible with the
  administrator rule; it owns retiring the API-credits service's `X-Admin-Key`.
- `kit-owned-storefront-auth-and-persistence` planned to move API credits' advance,
  pause and resume routes onto the operations the canonical client signs. This change
  took the advance (and the negotiation reads it newly authenticates), since the
  administrator's advance must be recorded as its own on every storefront; pause and
  resume remain that change's, and the API-credit storefront's negotiation-list
  resource builder and buyer-filter parsing are third copies of the VM's and bare
  metal's for it to fold in.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`: the administrator's reach
- [x] Existing subsystem specification: `physical-provisioning`, `site-capacity`,
  `api-credits`, `storefront-publication`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: no permanent destination — it groups the work of this change.
- D2: no permanent destination — it settles this change's scope.
- D3: `physical-provisioning`'s specification (a host's pin is stated or captured by an
  operator) and architecture companion ("The host registry owns the connection": why a
  capture is an operator's probe); the operator handbook's host registration.
- D4: `physical-provisioning`'s specification (host connections at version 3, and the
  Ansible executor's verification) and architecture companion;
  `docs/development/DEPLOYMENT_AND_CONFIG.md`'s migrations after the baseline; the
  operator handbook's host definitions and Ansible configuration.
- D5: `physical-provisioning`'s specification (capture, rotation, and the refusal
  before a job's start) and architecture companion ("Proof-driven release"); the
  operator handbook (capturing and rotating a host key, and recovering a refusal).
- D6: `physical-provisioning`'s specification (adoption of deployed hosts); the
  operator handbook's upgrade procedure; the release handbook's "Compatibility to
  retire".
- D7: `physical-provisioning`'s specification (guest isolation) and architecture
  companion; the VM IaC README and the seller quickstart.
- D8: `physical-provisioning`'s specification (what a guest reaches) and architecture
  companion; the seller quickstart (`guest_allowed_private_destinations`) and the VM
  IaC README.
- D9: `physical-provisioning`'s specification (converging running guests); the
  operator handbook's upgrade procedure; the release handbook's "Compatibility to
  retire".
- D10: `physical-provisioning`'s architecture companion (why no guest shares a
  segment).
- D11: `docs/development/ROADMAP.md`, whose credential row names the gap unowned, and
  the unowned gap in `openspec/changes/README.md`, both written with this design.
- D12: no permanent destination — deferred with D11.
- D13: no permanent destination — deferred with D11.
- D14: `docs/development/ARCHITECTURE.md`, "The administrator's reach".
- D15: the specifications of `physical-provisioning`, `site-capacity`, `api-credits`
  and `storefront-publication`; the registry's bearer key as an unowned gap in
  `openspec/changes/README.md`, written with this design.
- D16: the engineering guidance's new `retiring-compatibility.md`, `versioning.md`'s links
  and the engineering README's tag table; `docs/guidance/repository/package-versions.md`;
  `docs/release-handbook.md`'s "Compatibility to retire" and its loading and cutting
  steps; the inventory of existing paths as an unowned gap in
  `openspec/changes/README.md`, written with this design.
- D17: no permanent destination — the implementation cadence is this change's.
- D18: `test-compatibility`'s specification (the real-host proof reaches the host
  through an operator route its target names) and architecture companion; the
  validation runbook's real-target instructions and the E2E README.
- D19: `test-compatibility`'s specification (the scenario and its per-observation
  outcome); the validation runbook and the E2E README.
- D20: `physical-provisioning`'s specification (converging running guests and its
  report) and architecture companion's "Guests are isolated from each other"; the VM
  IaC README.
- D21: `test-compatibility`'s specification (the target's `guest_isolation` section and
  counter attribution, and the listed destination's egress observation); the committed
  example target, the validation runbook's
  "Describe The Target", and the E2E README.
- D22: no permanent destination — it settles this change's closeout gate; the run's
  outcome is recorded in the change and its design-promotion record.
- D23: `docs/release-handbook.md`'s "Compatibility to retire", its third row.
- D24: no permanent destination — the implementation cadence is this change's.
