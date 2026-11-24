# Tasks

Every section bumps each package it changes once, against its version on the branch
this change merges into (`make check-version-bumps`), relocks through the
`after-functional-change` hook (`make lock`), and passes
`scripts/change-workflow run pre-commit harden-provisioning-trust-boundaries` before
its commit.

## 1. The `ssh` connection at version 3 carries a host's pin

Delivers `host_keys` on the `ssh` connection, served at version 3 alone, kept across
submissions that omit it, carried by the host definitions document and its export,
and left alone by the INI import. Implements D4 (representation) and D3 (stated
keys); requirements "A host's pinned keys are stated or captured by an operator"
(stating, keeping, replacing by submission) and the MODIFIED "Host connections are
typed by their implementation's codec" (version 3 served, earlier versions refused
and resubmitted). Touches `provisioning/compute/ansible/` (the `ssh` codec),
`provisioning/compute/src/compute_provisioning/hosts/` (the authority's carry-forward,
document equality and export), `provisioning/compute/contracts/`,
`provisioning/compute/client/`, and the chart's example host document.

- [x] 1.1 In `compute_provisioning_ansible/connection.py`, serve the `ssh` kind at
  version 3 alone, add `host_keys` to `SshConnection` as an optional non-empty list of
  OpenSSH public keys, each parsed and stored as its key type and base64 with any
  comment dropped, refusing `[]`, a malformed key, or an unknown key type, naming the
  field; give `ssh_connection()` a `host_keys` argument; update the module docstring
  to describe version 3. (D4; codec requirement.) Verify: unit tests in
  `provisioning/compute/ansible/tests/unit/test_ssh_connection.py` cover a stated pin,
  an empty pin, a malformed key, a comment dropped, a version-2 submission refused
  naming version 3, and the existing carry-forward of a protected key from a stored
  version-2 connection.
- [x] 1.2 In the `ssh` codec's `build`, keep the previous connection's `host_keys` when
  a submission omits them, whatever else it changes, `ssh_host` and `ssh_port`
  included, and replace them when it states others; in the host authority
  (`hosts/service.py`), take equality after the codec with the stored connection as
  `previous`, so a document entry or INI line that omits `host_keys` equals a pinned
  host otherwise unchanged and writes nothing. (D4; pinning requirement, "An update
  omits the pin" and "An INI import names a pinned host".) Verify: unit tests of the
  codec, and library-integration tests in
  `provisioning/compute/tests/integration/test_host_authority.py` and
  `test_host_definitions.py` for an update omitting the pin at a new port, an INI
  import of a pinned host, and a document entry omitting the pin applying nothing.
- [x] 1.3 Carry `host_keys` through the host definitions document's parsing and
  validation (`hosts/definitions.py`) and the canonical export
  (`HostAuthority.host_definitions()`), and update the contracts' host-document models
  and examples (`compute_provisioning_contracts/hosts.py`, the `definitions.py`
  docstring) to version 3. (D4; pinning requirement, "A host is registered with its
  key".) Verify: `provisioning/compute/contracts/tests/unit/test_host_definitions.py`
  and `provisioning/compute/tests/unit/test_host_definitions.py` round-trip a pinned
  entry through import and export.
- [x] 1.4 Move every in-repository registration and fixture that states `ssh`
  version 2 to version 3: the client's helpers (`compute_provisioning_client`), the
  mock executor's fixtures (`compute_provisioning_ansible/mock.py`), the chart's
  example host document (`helm/charts/provisioning/values.yaml`) and its render test
  (`helm/charts/provisioning/tests/test_render.py`), with the chart's version bumped,
  and the provisioning, contract and e2e unit suites that build connections. (D4.)
  Verify: `git grep -n '"version": 2\|version: 2'` over `provisioning/`, `helm/` and
  `e2e-tests/` lists no `ssh` connection; `make -C helm test-render` passes.
- [x] 1.5 Verification point. Unit: the ansible package's
  `test_ssh_connection.py`, `test_inventory.py`, `test_host_import.py`; the contracts'
  `test_host_definitions.py`, `test_contracts.py`. Library integration:
  `provisioning/compute/tests/integration/test_host_authority.py`,
  `test_host_definitions.py`. Application integration through the typed client:
  `provisioning/compute/service/tests/integration/test_hosts_api.py` gains a host
  registered with `host_keys`, read back with them, and one submitted with `[]`
  refused with nothing stored; `test_host_definitions_api.py` exports a pinned host.
  Render: `make -C helm test-render`.
  End-to-end: `e2e_deal`, `e2e_bare_metal_mock_deal` and `e2e_bare_metal_publication`
  register hosts at version 3 through the API under the mock executor;
  `e2e_real_provisioning_reapply` reapplies registrations but runs in no lane.

**Section evidence.** Unit: the Ansible suite (198) and the contracts suite (163)
passed; library integration: the host authority and definitions suites (86). Typed API
integration covers registering, reading and exporting pins, refusing an empty pin, and
keeping a pin across a port change, an INI re-import and an unchanged document
re-import, in place of the planned lower-level pin cases. The chart's rendered host
document passes the codec. A two-session SQLite test overlaps an omitted-field update
with a pin rotation. End-to-end: the VM deal and bare-metal lanes register hosts at
version 3; no lane evidences verification.

## 2. Version-2 connections migrate to version 3, and deployed hosts are marked for adoption

Delivers the migration that rewrites every `ssh` connection stored at version 2 to
version 3, marks each rewritten host pending adoption, and the host authority's
compare-and-set adoption that every later caller uses. Implements D4 (the exact
mapping) and D6 (the mark and the compare-and-set); requirements "Hosts deployed
before pins are adopted before their first job" (the mark, the compare-and-set, the
races) and the MODIFIED codec requirement's scenario "A provisioning database holding
version-1 connections is migrated". Touches
`provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`,
`provisioning/compute/src/compute_provisioning/hosts/` (`db.py`, `migrations.py`,
`service.py`, `execution.py`).

- [x] 2.1 Add to the provisioning migration chain, after the v1-to-v2 rewrite, a
  migration that adds the pending-adoption flag to `hosts` and rewrites every `ssh`
  connection stored at version 2 to the literal version 3 with the same public fields
  and protected values and no `host_keys`, setting the flag on each row it rewrites,
  validated with a key-less version-3 codec and failing whole, naming the host, on any
  row the codec refuses, as `SSH_CONNECTIONS_VERSION_2` does; it reads no
  configuration. (D4, D6.) Verify: migration tests in
  `provisioning/compute/service/tests/integration/test_ssh_connection_version_migration.py`
  migrate a database holding version-1 and version-2 hosts and a queued create and
  teardown job naming them to version 3, every host marked, jobs unchanged; the floor
  fixture adoption in `test_migration_chain.py` and
  `test_migration_reads_no_configuration.py` pass with the new migration listed.
- [x] 2.2 Expose the flag on the host record (`hosts/db.py`) and on the execution-host
  value an executor receives (`hosts/execution.py`), outside the connection, never in
  the host read, the export or the document; give the host authority one operation
  that records an observed key as a pending host's pin and clears the flag in a single
  conditional write that takes effect only while the host is still pending, returning
  the committed pin either way; and clear the flag on any submission stating
  `host_keys` and on a capture. (D6; adoption requirement, "Two first jobs adopt one
  host", "A capture races an adoption", "An operator pins a pending host", "A host
  registered after the upgrade".) Verify: library-integration tests in
  `provisioning/compute/tests/integration/test_host_authority.py` for two adoptions of
  one pending host with different keys (one commits, both callers receive the
  committed pin), a stated pin clearing the flag, a capture after an adoption meeting a
  pinned host, and a host registered after the migration never marked.
- [x] 2.3 Verification point. Library integration:
  `provisioning/compute/tests/integration/test_host_authority.py`,
  `test_ssh_connection_version_migration.py`, `test_migration_chain.py`, and
  `test_migration_reads_no_configuration.py`. Application integration:
  `test_hosts_api.py` verifies omission from the host read and YAML export.
  End-to-end: none runs the migration over a version-2 database; the lanes start from
  empty databases.

**Section evidence.** The host authority (38) and migration (15) suites passed: the
migrations keep protected values and queued jobs, mark rewritten hosts, and refuse a
malformed row whole; the authority returns the committed pin in an adoption race and
keeps the flag out of the host read, the export and the document.

## 3. The Ansible executor reaches only hosts matching their pin

Delivers verification in every inventory the runner renders, the check before a
job's recorded start with adoption of a pending host, the refusal and its message,
and readiness. Implements D4 (rendering, the executor's rule, mock exempt), D5
(refusal) and D6 (adoption on the executor's path); requirements "The Ansible
executor reaches only hosts matching their pinned key" and "Hosts deployed before pins
are adopted before their first job" (the job path). Touches
`provisioning/compute/ansible/src/compute_provisioning_ansible/` (`runner.py`,
`executor.py`, `readiness.py`, `connection.py`'s refusal error) and the job engine's
use of the executor's start report where it needs the refusal to count as never
started (`provisioning/compute/src/compute_provisioning/jobs/`).

- [x] 3.1 Give `InventoryTarget` the host's pin, and in `AnsibleRunner.write_inventory`
  write, for each host, an owner-only transient `known_hosts` holding its pin under
  `[ssh_host]:ssh_port`, owned and removed by `MaterializedInventory` with any
  decrypted key file, and render on its inventory line `ansible_host_key_checking=true`,
  `ansible_ssh_args` with the service's baseline, and `ansible_ssh_common_args` naming
  that file with `GlobalKnownHostsFile=/dev/null` and `StrictHostKeyChecking=yes`;
  keep `ansible.cfg`'s `host_key_checking = False` out of play by those variables.
  (D4; executor requirement, "A job runs against a pinned host".) Verify: unit tests in
  `test_runner.py` for the rendered line, the file's mode and contents, its removal on
  every ending, and a test running Ansible's own ssh connection plugin command builder
  against an operator `ansible.cfg` stating `host_key_checking = False` and its own
  `ssh_args`, showing the command checks strictly against the job's file ("An
  operator's configuration turns checking off").
- [x] 3.2 In `AnsibleExecutor`, before reporting the execution's start, refuse a host
  with no pin that is not pending adoption without connecting, and otherwise make one
  SSH connection that runs nothing on the host, against the pin; for a pending host,
  connect accepting the presented key into an empty file and record it through the
  host authority's compare-and-set (2.2), then check against the committed pin
  returned. A mismatch or an unpinned host raises a host-key refusal naming the host,
  `[ssh_host]:ssh_port`, the presented and pinned fingerprints and how to recover,
  carrying no key material; the job fails unretried with no execution start recorded,
  as a `ProtectedKeyUnreadableError` does. The mock executor reads no pins. (D5, D6;
  executor requirement, "A host presents another key", "A job meets an unpinned host",
  "A lane runs the mock executor"; adoption requirement, "A deployed host's first job
  after the upgrade", "Two first jobs adopt one host".) Verify: unit tests in
  `test_executor.py` with the SSH invocation behind the runner's subprocess seam (a
  fake `ssh` on `PATH`, as `test_runner.py` fakes `ansible`) for each case, the refusal
  carrying no key material, no playbook spawned, and no start reported; a unit test in
  `provisioning/compute/tests/unit/test_executor_mock.py` that the mock executor runs
  a job against an unpinned host.
- [x] 3.3 Prove that a teardown refused for its host key counts as never started and
  is run again once the host is pinned. (D5; executor requirement, "A teardown is
  refused for its host key".) Verify: a library-integration test in
  `provisioning/compute/tests/integration/test_teardown_rerun.py` with an executor
  refusing for the host key, then a pin captured, and the rerun dispatched under
  `{reservation}:teardown:rerun-{n}`.
- [x] 3.4 In `readiness.py`, once any Ansible executor is real, report not ready naming
  every enabled host with no pin that is not pending adoption, and list pending hosts
  as information without reporting not ready for them, bumping the detail envelope's
  schema version. (D5, D6; executor and adoption requirements.) Verify: unit tests in
  `test_readiness.py`; an application-integration case in
  `provisioning/compute/service/tests/integration/test_system_api.py` reading system
  status with one pinned, one unpinned and one pending host under a real executor.
- [x] 3.5 Verification point. Unit: `test_runner.py`, `test_executor.py`,
  `test_readiness.py`, `test_probes.py` (the probe's inventory carries verification),
  `test_executor_mock.py`. Library integration: `test_teardown_rerun.py`,
  `test_host_authority.py`. Application integration through the typed client:
  `test_system_api.py`; `test_unreadable_host_key_api.py` still passes.
  End-to-end: the lanes run the mock executor, so none exercises verification;
  `e2e_vm_real_provisioning`, `e2e_bare_metal_real_provisioning`,
  `e2e_vm_qualification` and `e2e_bare_metal_qualification` do against a real target
  and run in no lane.

**Section evidence.** The Ansible suites (209), the job and teardown suites (29) and
the status and unreadable-key suites (28) passed. The command-builder case runs
Ansible's own ssh plugin under an operator configuration that turns checking off; the
mock executor's case lives with the executor in the Ansible package; the release test
shows a pre-start host-key refusal scheduling the teardown's rerun.

## 4. The connectivity check reports a host's key, and an operator captures it

Delivers the connectivity result's `host_key`, adoption of a pending host by the
connectivity check, the capture route with its answers, the typed client's
`capture_host_key`, and the e2e real-provisioning helpers stating or capturing keys.
Implements D3 (capture as an operator's probe), D5 (capture, rotation by `replace`)
and D6 (adoption by the connectivity check); requirements "A host's pinned keys are
stated or captured by an operator" (checks and capture) and the MODIFIED "Host
connectivity is probed by connection kind". Touches
`provisioning/compute/ansible/src/compute_provisioning_ansible/probes.py`,
`provisioning/compute/contracts/` (`ConnectivityResult`, the capture route contract,
admin-only), `provisioning/compute/src/compute_provisioning/hosts/route_service.py`,
`provisioning/compute/service/src/compute_provisioning_service/controllers/hosts_controller.py`,
`provisioning/compute/client/`, and `e2e-tests/`.

- [x] 4.1 Add `host_key` to `ConnectivityResult`: the endpoint, whether pinned, the
  presented key's type and SHA-256 fingerprint, and for a pinned host whether it
  matched and the pinned fingerprints; null when no key was presented, with
  `reachable: false` and the probe's reason in `detail`; omitted for a kind whose hosts
  present no key. In `probes.py`, probe an unpinned host accepting the presented key
  into a file it discards, storing nothing; a pending host adopted through the
  compare-and-set (2.2); a pinned host checked against its pin, a mismatch answering
  unreachable with the refusal's reason. (D5, D6; pinning requirement, "An operator
  checks an unpinned host"; connectivity requirement.) Verify: unit tests in
  `test_probes.py` for each case, a timed-out probe giving a null `host_key`, and the
  contracts' `test_contracts.py` for the result's shape.
- [x] 4.2 Add `POST /api/v1/hosts/{host}/host-keys/capture` to the family route table
  among the administrator's operations, served by the host route service: 404 for an
  unknown host; 422 for a kind that presents no key, naming the kind, and for an empty
  or malformed fingerprint, naming the field; 409 coded `host_key_mismatch` with the
  endpoint and presented fingerprint, `host_key_pinned` with the pinned fingerprints
  unless `replace` is true, and `no_host_key_presented` with the endpoint and the
  probe's reason, recording nothing; on success the endpoint and pinned fingerprints,
  clearing any pending mark. (D5, D14; pinning requirement's capture scenarios.)
  Verify: unit tests in `provisioning/compute/tests/unit/test_host_route_service.py`;
  `provisioning/compute/contracts/tests/unit/test_route_table.py` shows the route
  admin-only.
- [x] 4.3 Give the typed client `capture_host_key(host_id, fingerprint, *, replace=False)`,
  surfacing each refusal's code, and the connectivity result's `host_key`. (D5.)
  Verify: application-integration tests through the client in
  `provisioning/compute/service/tests/integration/test_hosts_api.py` for a capture
  matching, a mismatch, a pinned host without and with `replace`, a malformed
  fingerprint, an unknown host, and a connectivity check of an unpinned, a pinned, and
  a mismatched host, the SSH side behind the runner's seam; and
  `test_provisioning_client_endpoint_coverage.py` covering the new route.
- [x] 4.4 Have the e2e real-provisioning helpers pin each host: the bare-metal driver
  (`e2e-tests/tests/e2e/roles/scenarios/bare_metal/real_compute_deal_driver.py`)
  states `host_keys` from the target's `ssh_host_public_key`; the VM helper
  (`e2e-tests/tests/e2e/roles/helpers/real_provisioning.py`) checks connectivity and
  captures the presented fingerprint, or states the key where the target configuration
  gives one (`e2e_harness/real_provisioning_target.py` and the target configuration's
  committed example under `e2e-tests/config/`); the reapply scenario
  restates the pins it registered. (D3, D5.) Verify: `e2e-tests/tests/unit/test_real_vm_lane.py`
  and `test_real_bare_metal_lane.py` show each registration pinned.
- [x] 4.5 Verification point. Unit: `test_probes.py`, `test_host_route_service.py`,
  the contracts' `test_contracts.py` and `test_route_table.py`, the e2e unit suites
  `test_real_vm_lane.py` and `test_real_bare_metal_lane.py`. Application integration
  through the typed client: `test_hosts_api.py`,
  `test_provisioning_client_endpoint_coverage.py`.
  End-to-end: none in the lanes exercises capture; the smoke test
  `e2e-tests/tests/smoke/test_provisioning_smoke.py` reads a connectivity result;
  `e2e_vm_real_provisioning`, `e2e_bare_metal_real_provisioning` and
  `e2e_real_provisioning_reapply` pin hosts against a real target and run in no lane.

**Section evidence.** The probe (6), contract and route (134), typed service (69),
real-lane helper (213) and qualification (56) tests passed, covering observation,
adoption, mismatch, replacement and the pin's round trip through the typed client. A
local SSH fixture with Ed25519, RSA and ECDSA keys exercised discovery and capture
against a temporary database.

**Round 1 triage (26 F1, 26 F2).** Task 4.4's observe-and-capture fallback is replaced
(D5, "The real-target harness"): `pin_registered_vm` returns a host holding a pin, the
target's stated key or one stored before the run, and otherwise refuses before
capacity is declared, naming `ssh_host_public_key`; the `test-compatibility` delta's
scenario "A VM target with no pin is refused" says so. The raw malformed-fingerprint
request in `test_hosts_api.py` asserts only its 422, as a rejection-path test. The e2e
unit suites (214) and the service's integration suite (579) passed; the new refusal
test failed at `5c911f1af` under `run test-before`.

## 5. A VM guest reaches no other guest and only DHCP and DNS on its host

Delivers every guest's isolated, filtered interface and the VM host kit's guest
policy chains. Implements D7 and D8; requirements "A VM guest reaches no other guest on
its host" and "A VM guest reaches only DHCP and DNS on its host and no undeclared
private destination". Touches `domains/vms/provisioning/iac/ansible/roles/vm-management/`
(`vm-create.yml`, `gpu-virt-install-multi.yml`, `gpu-virt-install-retry.yml`,
`gpu-virt-install-multi-retry.yml`, defaults) and `roles/vm-setup/`
(`security-hardening.yml`, `system-packages.yml`, `kvm-network.yml`, `kvm-setup.yml`,
`main.yml`, defaults).

- [x] 5.1 Define the guest interface once — `default` network, virtio, `port
  isolated='yes'`, `clean-traffic` with `CTRL_IP_LEARNING=dhcp` and
  `DHCPSERVER=192.168.122.1` — and use it at all nine `virt-install` sites, GPU guests
  included. (D7; "A GPU guest is created".) Verify: a static test in
  `domains/vms/provisioning/iac/tests/test_vm_management_contracts.py` that every
  `virt-install` in the role uses the one definition and no site states
  `network=default` alone.
  Done: `vm-management/templates/guest-interface-args.j2`, looked up by every site,
  holds `--network network=default,model=virtio` and four `--xml` XPath edits (D7).
  `VmGuestInterfaceTests` (static configuration) and `VmGuestInterfaceNativeTests`
  (library integration, native gate: Ansible's own template lookup) passed. No test
  runs the lookup through a role's site.
- [x] 5.2 In host preparation, fail naming what is missing on a host whose libvirt is
  older than 6.1 or lacks the nwfilter driver; install the chains `ARKHAI-GUEST-IN`
  and `ARKHAI-GUEST-FWD` exactly as D8 lists them, the hairpin drop first in
  `ARKHAI-GUEST-FWD`, the forwarded established/related accept after it, one accept per
  `guest_allowed_private_destinations` entry (empty by default) ahead of the
  link-local and private-range drops; jump each from the first position of `INPUT` and
  `FORWARD`; save them through the existing `iptables-restore` unit; and re-assert both
  jumps at the first position after libvirt restarts and after UFW reloads. (D7, D8;
  "The host's firewall rules are reloaded".) Verify: static tests in
  `test_ansible_structure.py` or a new `test_guest_policy.py` over the rendered rules,
  their order, the allowlist's placement, and the re-assertion hooks.
  Done: `vm-setup/tasks/guest-policy.yml`, after the KVM network and before security
  hardening, with the preflight (libvirt 6.1, `clean-traffic`, virt-install 3.0,
  `ebtables`, which host preparation installs), `templates/guest-policy.rules.j2`,
  `files/guest_policy.sh` as `/usr/local/sbin/arkhai-guest-policy`,
  `arkhai-guest-policy.service` and the `/etc/ufw/after.init` block (D8; the
  `physical-provisioning` architecture companion describes each). Allowlist entries
  are checked as IPv4 addresses or CIDR blocks. `test_guest_policy.py` passed: the
  rendered chains and the role's structure (static configuration); the real installer
  against stateful fake `iptables` and `iptables-restore` (which store rules as
  written, so real parsing is not exercised); natively, under ansible-core 2.19.13,
  the preflight and the allowlist check (library integration).
- [x] 5.3 Remove the host kit's `ufw allow in on virbr0 from 192.168.122.0/24` and the
  scattered guest port-22 rules (the iptables `INPUT` drops and logs, the UFW denies,
  the `vm-network-isolation.sh` script and service), keeping `allow out on virbr0`;
  correct the host kit's printed claims to what it installs. (D8.) Verify: a static
  test that none of the removed rules remains and the printed summary names the guest
  policy chains.
  Done: none is installed, and security hardening's first firewall task removes each
  exact drop and log form from a host holding it, leaving operator rules, port-22
  accepts among them (a compatibility path, D23). `TestNoPerPortGuestRuleRemains`
  passed (static configuration, and the task's shell against fake `iptables` and
  `ufw`); no test runs the removal of `vm-network-isolation.service`, which works on
  absolute paths. Both printed summaries name the chains.
- [x] 5.4 Verification point. Unit (static role tests): `make -C
  domains/vms/provisioning/iac test`; the playbooks' syntax gates, `make -C
  domains/vms/provisioning/iac validate-playbooks`; the native Ansible gate, `make -C
  domains/vms/provisioning/iac native-ansible-gate`. The real-host proof is section 6.
  End-to-end: the lanes run the mock executor and no real VM, so none exercises it.
  Done: `make -C domains/vms/provisioning/iac test` passed; with no local Ansible, the
  syntax checks and native gate ran as
  `domains/vms/provisioning/iac/scripts/native_ansible_gate.sh` in the built
  `arkhai:compute-provisioning` image over this tree, and passed.
  `docs/guidance/repository/ansible-gates.md` names the new native cases. No lane
  covers this section; its real-host evidence is section 7a. Declined from the
  fresh-context checks: the preflight's task-level variables can be overridden by
  extra variables, which only the operator sets.

**Outside the plan.** A create's two forwarding accepts for buyer SSH, inserted ahead
of the policy's jump, admitted a guest's own packets; the inbound accept now requires
`! -i virbr0` and the reply accept `--ctstate ESTABLISHED` (D8), held by
`VmCreateForwardingTests`. The host kit's `iptables-restore.service` restoring nothing
at boot on some hosts is an unowned gap in `openspec/changes/README.md`. The fail2ban
jail `vm-ssh-attacks` matches only lines the removed per-port rules wrote, so it
matches nothing; it is left as it is.

**Pre-closeout triage, 69 F1.** The policy drops IPv6 from the bridge (D8, "Settled at
69 F1"): `files/guest_policy.sh` runs an `ip6tables-restore -w --noflush` transaction
filling `ARKHAI-GUEST-V6` after the IPv4 one, skipped where
`$PROC_ROOT/sys/net/ipv6` is absent, re-asserted by the same unit and hook; the
`physical-provisioning` delta has the scenario "A guest whose filter waits for its
next start sends IPv6". `test_guest_policy.py` passed (233 in the IaC suite), its new
cases failing at `b6c2d299b` under `run test-before`. Real `ip6tables-restore` parsing
is not exercised, and no real-host run probes IPv6 (design, Risks).

## 6. Running guests converge through one installed command

Replanned against the reviewed design (D18–D24, design review 41) after section 6 was
returned to design before any of its tasks ran (commit 3ea0e74ce); its scenario moved to
section 6a and its real-host run to section 7a.

Delivers `arkhai-guest-converge`, installed and run by host preparation, which
converges every running guest and reports each by name. Implements D9 and D20 (the
command and its report); requirement "VM host preparation converges running guests",
its scenarios "A host prepared before isolation is prepared again", "A guest cannot be
converged" and "libvirt refuses a live filter". Touches
`domains/vms/provisioning/iac/ansible/roles/vm-setup/` (`files/guest_converge.sh`, a
new task file or `tasks/guest-policy.yml`, `tasks/main.yml`) and
`domains/vms/provisioning/iac/tests/` (`host_fakes.py`, a new
`test_guest_convergence.py`).

- [x] 6.1 Write `vm-setup/files/guest_converge.sh`. For each running guest
  (`virsh list --state-running`), with its interface on `default` (`virsh domiflist`),
  it: sets the tap's bridge port isolated (`bridge link set dev <tap> isolated on`),
  which does not drop the link; applies the guest's interface with `clean-traffic`
  (`CTRL_IP_LEARNING=dhcp`, `DHCPSERVER=192.168.122.1`) through `virsh update-device
  --live` where libvirt accepts it, and otherwise leaves the filter for the next start;
  and writes the isolated port and the filter into the saved definition (`--config`, or
  `virsh dumpxml --inactive` edited and `virsh define`d). It prints one JSON line per
  guest — `name`, `port_isolated`, `filter` (`live` or `next_start`),
  `saved_definition`, `error` — and exits non-zero only when it cannot run at all (no
  `virsh`, no `bridge`), never because one guest failed. A guest already converged is
  reported converged with nothing changed. (D9, D20; "A host prepared before isolation
  is prepared again", "libvirt refuses a live filter".) Verify: unit tests (static
  configuration, the real script against fakes at the subprocess boundary) in a new
  `domains/vms/provisioning/iac/tests/test_guest_convergence.py`, extending
  `host_fakes.py` with a stateful fake `bridge` and the `virsh` subcommands the script
  uses, for: an unconverged guest converged live, its saved definition carrying both; a
  guest whose live filter libvirt refuses, reported `next_start` with its port isolated
  and its saved definition carrying the filter; a guest whose port cannot be isolated,
  reported with its error while the others converge; an already converged guest
  unchanged; a host with no running guest; and a missing `bridge`, failing the command.
  Done: a POSIX `sh` script orchestrating `virsh` and `bridge`, with an embedded
  `python3` helper that reads and edits libvirt's XML and writes the JSON line; both
  definitions are edited by `virsh update-device`, and the report adds `filter: none`
  and `changed` (D20). `TestTheCommand` in `test_guest_convergence.py` passed: the real
  script against stateful doubles of `virsh` and `bridge` at its subprocess boundary,
  each listed case and a transient guest, a guest with no interface on `default`, and
  unreadable interfaces, definitions and running guests. No test reaches a failing
  `bridge -d link show`, a definition lacking the interface, or a failing `mktemp`.
- [x] 6.2 In host preparation, after the guest policy is installed, install the script as
  `/usr/local/sbin/arkhai-guest-converge` (owner root, mode 0755), run it, and name in
  the play's output each guest it reports unconverged — its port not isolated, or its
  saved definition not written — with the reason, and each guest whose filter waits for
  its next start; host preparation fails only when the command cannot run. (D9, D20; "A
  guest cannot be converged".) Verify: static tests in `test_guest_convergence.py` over
  the task file — the install, the order after the guest policy, and the report's
  wording read from the command's lines — and a native case under the native Ansible
  gate running the task against a fake command printing an unconverged guest and a
  `next_start` guest, the play naming both; name the new native case in
  `docs/guidance/repository/ansible-gates.md`.
  Done: four tasks at the end of `tasks/guest-policy.yml`, tagged `guest_policy`: the
  install, the run (only a non-zero exit fails host preparation), and two reports
  naming each unconverged guest and each whose filter waits for its next start, with
  the reason. `TestHostPreparationConvergesRunningGuests` (structure) and
  `TestTheReportNatively` (library integration, native gate, against a fake command)
  passed; no test runs the install task or the role whole. `ansible-gates.md` names
  the native case.
- [x] 6.3 Verification point. Unit (static configuration and the real script against
  fakes): `make -C domains/vms/provisioning/iac test`. Library integration (native
  gate): `make -C domains/vms/provisioning/iac validate-playbooks` and
  `native-ansible-gate`, or, with no local Ansible,
  `domains/vms/provisioning/iac/scripts/native_ansible_gate.sh` in
  the provisioning image over this tree, as section 5 ran it.
  End-to-end: the lanes run the mock executor and no real VM, so none exercises it;
  `e2e_vm_guest_isolation`'s O8 and O9 (section 6a, run in section 7a) are its only
  end-to-end evidence.
  Done: `make -C domains/vms/provisioning/iac test` passed, and the native gate in the
  provisioning image, the two new native cases among its tests. No lane covers this
  section; O8 and O9 are its end-to-end evidence (7a). Declined from the fresh-context
  check: a fallback report line when the helper's own `python3` fails, since `python3`
  is checked present first. The flat IaC test layout is an unowned gap in
  `openspec/changes/README.md`.
  **Round 2's triage, 50 F2.** The command reports a filter `live` only when libvirt
  lists the tap's `clean-traffic` binding (`virsh nwfilter-binding-list`); a missing
  binding, or an unreadable list, is reported not live, with its reason (D20). In 6a,
  O9 fails for a live update libvirt took but does not bind. Three convergence cases
  and one O9 case were added and passed, each failing at `82ec390c8` under
  `run test-before`.

**Pre-closeout triage, 69 F2.** The two comments explaining convergence by the
feature's history now state the current condition.

## 6a. The real-host proof of guest isolation, as a scenario

Delivers the VM target's `guest_isolation` section and `e2e_vm_guest_isolation`, with
its guest-side and operator probes and its per-observation outcome. Implements D18
(the operator route and its fixed Python probe), D19 (extending the real VM scenario's
two-guest window), D20 (the planted fixture, O8 and O9), D21 (the section, counter and
egress attribution) and D22's observation list; requirement "VM guest isolation is
proven on a real host" and its scenarios, in the `test-compatibility` delta. Touches
`e2e-tests/src/e2e_harness/real_provisioning_target.py`,
the committed example target `config-real-provisioning-target.yml.example` under
`e2e-tests/config/`,
`e2e-tests/tests/e2e/roles/scenarios/vms/` (a new `test_vm_guest_isolation.py`, a new
`guest_isolation.py` beside it with its guest and operator probes, as
`bare_metal/working_data_qualification.py` sits beside `working_data_probe.py`),
`e2e-tests/pyproject.toml`, and `e2e-tests/tests/unit/`.

- [x] 6a.1 Add to `VmHost` an optional `guest_isolation` section at target version 2:
  `operator` (`host`, `port`, `user`, `key_path`, the key path harness-local and
  validated as `CleanupOperator.key_path` is) and an optional `private_destinations`
  (`refused`, `listed`, each an IPv4 address in a private range, distinct). Show it in
  the committed example, commented and visibly fictitious, as `cleanup_qualification`
  is. (D21.) Verify: unit tests in `e2e-tests/tests/unit/test_real_provisioning_target.py`
  for the section accepted, an unknown field and a public or equal destination refused
  naming the field, and the example still loading.
  Done: `GuestIsolation` on `VmHost`, its route reusing `CleanupOperator`; "a private
  range" is the guest policy's four (`GUEST_POLICY_PRIVATE_RANGES`), not Python's
  `is_private`, and a destination on the guests' own network is refused.
  `test_real_provisioning_target.py` passed (unit, 118), the example's commented block
  valid once uncommented.
- [x] 6a.2 Write the probes in `guest_isolation.py`, each fixed Python carried with JSON
  arguments over the shared SSH seam (`ssh_access.SshSession.run`), as
  `working_data_qualification.probe_command` carries `working_data_probe.py`:
  - the **guest probe**, run under `sudo` in a guest as its buyer: ARP, ICMP and TCP to
    the other guest's address and through the gateway; an ARP claim of the other
    guest's address; a DHCP request and a DNS query to `192.168.122.1`; TCP to the
    host's port 22 at `192.168.122.1`; TCP to `169.254.169.254`; TCP to each private
    destination; and its buyer session's peer address;
  - the **operator probe**, run as `sudo -n -- python3 -c <probe> <arguments>` through
    the target's operator route: restart libvirtd; reload UFW; read `ARKHAI-GUEST-IN`'s
    and `ARKHAI-GUEST-FWD`'s rules with their packet counters and the jumps' positions
    in `INPUT` and `FORWARD`; hold a packet socket on the interface `ip route get
    <listed>` names and report whether the guest's packet to the listed destination left
    there while the guest probes; plant the fixture on a named guest — clear its tap's
    isolation, detach its filter live (reporting whether libvirt refused), strip the
    isolation and the filter from its saved definition — and read its port, its live
    filter binding (`virsh nwfilter-binding-list`) and its live and saved definitions;
    run `/usr/local/sbin/arkhai-guest-converge` and return its lines; and report the
    host's libvirt version.

  Keep the judgements as pure functions beside them: a refusal counts only when the
  matching rule's counter rose; the listed destination counts as forwarded only when its
  accept counter rose and its egress was seen; the chain confirms `listed` is admitted
  and `refused` is not; O9 is made only when the fixture detached the filter live and it
  is bound live after convergence. (D18, D20, D21.) Verify: unit tests in a new
  `e2e-tests/tests/unit/test_vm_guest_isolation.py` for each judgement, over sample
  `iptables -L -v -x -n`, `bridge -d link show`, `virsh` and convergence output — a
  counter unchanged with no answer failing, an accept counter risen with no egress
  failing O5 ("A listed destination's packet does not leave the host"), the fixture's
  live removal refused leaving O9 unproven naming the libvirt version, a `next_start`
  convergence leaving O9 unproven — and for the operator command being `sudo -n --
  python3 -c` with the probe's own text and JSON arguments.
  Done, with one difference from the plan: the probe is its own file,
  `guest_isolation_probe.py`, one program for both sides selected by its `operation`,
  carried as `working_data_probe.py` is; `guest_isolation.py` holds `probe_command`,
  `IsolationProbes`, the judgements (each returning the faults it finds) and the
  stages' state. ARP, the claim and DHCP are raw frames on the guest's own interface;
  the gateway path is a `/32` route with the guest's `accept_redirects` off meanwhile;
  O2's effect is the host's neighbour entry for the other guest; the egress watch is a
  packet socket on the routed device counting outgoing TCP to the listed address for
  30 seconds while the guest makes five spaced attempts. Every operation stays within
  the shared SSH seam's 70-second attempt, and a failed host read is a named fault,
  never read as a port left open. `test_vm_guest_isolation.py` passed: each judgement
  over sample host output, the probe's framing and parsing, and the command's form. No
  test runs the probe's sockets against a real kernel; that is 7a's.
- [x] 6a.3 Write `test_vm_guest_isolation.py`, marked `e2e_vm_guest_isolation` and
  registered in `e2e-tests/pyproject.toml`, in no lane: it declares
  `OBSERVATIONS = ("O1", …, "O9")` for `tests/e2e/roles/helpers/qualification.py`, runs
  `test_real_provisioning_deal.py`'s shared stages for the two deals — subclassing them,
  and reusing its fixtures, driver and recovery so the teardown is the same — and adds
  its own stages inside the window in which both guests run and the first holds its
  heartbeat (after `09j`, before `09l`), each declaring the observations it requires:
  O1, O2 (the claim, the other buyer still reaching its guest, the filter's parameters
  in the live definition), O3, O4, O5, O6 (made only when the peer address is private
  and outside the guests' network under direct access; otherwise skipped naming the
  private-source buyer route), O7
  (O3–O5 again after the libvirtd restart and after the UFW reload, with both jumps
  first), and O8 and O9 on the first guest (the fixture, the convergence, the heartbeat's
  longest gap at most five seconds, the port, the saved definition, the guest-to-guest
  probes again, and the live filter). Every host-side stage skips naming
  `guest_isolation` when the target has none, and O5's stages skip naming
  `private_destinations` when it names none; the run logs the host's libvirt version
  and states that its guests are expected alone on the host. (D19, D21, D22; the
  delta's scenarios "The target names no operator route", "Buyers reach the guests
  through a relay", "A planted guest is converged", "libvirt refuses the fixture's live
  filter removal".) Verify: unit tests in `e2e-tests/tests/unit/test_vm_guest_isolation.py`
  and `test_real_vm_lane.py`: the module collects under its marker, every stage declares
  its observations, a run without the target skips every stage blocked, a target with no
  `guest_isolation` leaves every observation but O1 and O6 unproven naming it (through
  `qualification.observation_outcomes` over the module's declared stages), and a relayed
  target leaves O6 unproven naming the route.
  Done: the module subclasses every stage of `test_real_provisioning_deal.py`, imports
  its fixtures by name, and replaces only its target fixture, so a missing target is a
  blocked skip. Its fourteen stages, `09k1` to `09k14`, sit between `09k` and `09l`; O7
  is four of them. O8 attempts convergence whatever the fixture managed. The operator
  route is pinned to `ssh_host_public_key` where the target states one, and otherwise
  trusts the key it first presents for the run. All of 6a.3's checks are in
  `tests/unit/test_vm_guest_isolation.py`, reusing `test_qualification_modules.py`'s
  marker and lane readers: the stages and their observations, the marker in no lane,
  the module collected and blocked without a target (pytest over it in a subprocess,
  static configuration), and the outcomes through `observation_outcomes` for a target
  without `guest_isolation`, without `private_destinations`, and with relay access.
  O6 under direct access is unproven, naming the create's masquerade (50 F1, D21).
- [x] 6a.4 Verification point. Unit: `e2e-tests/tests/unit/test_real_provisioning_target.py`,
  `test_vm_guest_isolation.py`, `test_real_vm_lane.py` (`make -C e2e-tests test-unit`).
  System: the module's run on a real host is section 7a's.
  End-to-end: `e2e_vm_guest_isolation`, in no lane; no lane scenario exercises it, and
  none is owed, since a lane has no real host.
  Done: `make -C e2e-tests test-unit` passed (1137, 1 skipped). Declined from the
  fresh-context checks: moving `checked_key_reference` into the shared helpers, a
  refactor of a module this section does not otherwise touch; reading
  `test_qualification_modules.py`'s readers as private; counting O3's host-port refusal
  on anything narrower than `ARKHAI-GUEST-IN`'s one closing drop, which the policy
  offers no rule for, so the guests' own broadcast may also count there.

## 7. A storefront never authorizes its administrator as a party

Delivers authentication of the API-credits storefront's negotiation reads and the
storefronts' tests holding the administrator rule. Implements D14 and D15 (held,
fixed); requirement "A storefront never authorizes its administrator as a party", and
the site-capacity, api-credits and physical-provisioning administrator requirements as
the existing checks hold them. Touches `domains/apicredits/storefront/`,
`domains/vms/storefront/tests/`, `domains/bare_metal/storefront/tests/`,
`kit/site/tests/`, `domains/apicredits/service/tests/`.

- [x] 7.1 Require the administrator on the API-credits storefront's
  `GET /api/v1/listings/{listing_id}/negotiations` and `…/negotiations/{neg_id}` through
  `require_admin_principal`, as its other administrator routes are. (D15, fixed;
  "The API-credits storefront's negotiations are read unsigned", "The administrator
  reads a listing's negotiations".) Verify: application-integration tests in
  `domains/apicredits/storefront/tests/integration/` refusing unsigned and
  buyer-signed reads, and reading them through the canonical storefront client signed
  as the administrator.
  Done, with one difference from the plan: both reads verify the administrator under
  the canonical client's own contracts, not `require_admin_principal`, which no client
  could satisfy, and the advance moved onto its client contract with the authenticated
  administrator, taken from `kit-owned-storefront-auth-and-persistence` (D15); pause
  and resume stay that change's. The package moves to 0.23.0.
  `test_administrator_reach.py` (application integration over the real API-credit
  runtime and a migrated SQLite database) passed: the administrator lists, filters and
  reads negotiations with signed responses; unsigned and buyer-signed reads are
  refused; unknown or repeated query names answer 400 and a half buyer filter 422. Its
  administrator tests failed at `d7e3f66c6` under `run test-before`.
- [x] 7.2 Add, for each storefront — VM (`domains/vms/storefront/tests/integration/`),
  bare metal (`domains/bare_metal/storefront/tests/integration/`), API credits — a test
  that a request signed under `admin` by an active administrator principal is refused
  on every buyer, counterparty-seller and service route and admitted on its
  administrator routes, and that an administrator's advance records the round as the
  administrator's. (D15, held; "The administrator opens a negotiation as a buyer",
  "The administrator advances a negotiation".) Verify: the three tests.
  Done: `tests/integration/test_administrator_reach.py` in each storefront (bare metal
  over its composed app; VM and API credits over the routers their apps mount behind
  production's middleware, each over a migrated database). Each classifies every
  mounted route and sweeps its party routes signed under `admin` through the canonical
  client's `authenticated_request` (rejection-path tests, status only): API credits 7,
  bare metal 11, VM 14, and on both compute storefronts the introduction routes. Each
  is refused 401 or 403 with no negotiation opened; the tests show the refusal, not its
  cause (D15). The lifecycle routes from `kit/deal-servicing` are held once there
  (`tests/integration/test_routes.py`). Administrator routes are admitted on a
  representative set, and the advance cases on VM and API credits record the round
  under `admin`; bare metal serves no advance, and no bare-metal test force-accepts
  through its route. Passed: API credits 12, bare metal 14, VM 17, `kit/deal-servicing`
  4.
- [x] 7.3 Confirm the existing checks hold the authorities' form: provisioning's
  assembly refusal (`provisioning/compute/contracts/tests/unit/test_contracts.py`,
  `provisioning/compute/service/tests/unit/test_route_table_composition.py`),
  `kit/site/tests/unit/test_auth_route_parity.py`, and the credits service's
  `tests/integration/test_credits_route_parity.py`; add to the last a case that a
  credits route naming another role admits an `admin`-signed request. (D15; the
  site-capacity and api-credits requirements.) Verify: the four suites.
  Done. Confirmed unchanged: provisioning's route-table checks (`test_contracts.py`,
  71; `test_route_table_composition.py`, 120) and `kit/site`'s
  `test_admin_is_accepted_on_every_route_without_being_enumerated` (26). The credits
  case is `test_the_operator_role_reaches_a_credits_route_naming_the_seller` in
  `test_signed_authority.py` (application integration, through
  `CreditsServiceClient`), not the static route-parity table, where it could not fail
  (D15); both modules passed (29).
- [x] 7.4 Verification point. Unit: `test_contracts.py`,
  `test_route_table_composition.py`, `test_auth_route_parity.py`. Application
  integration: the three storefronts' new tests and the API-credits storefront's
  negotiation-read tests, `test_credits_route_parity.py`.
  End-to-end: `e2e_deal` and `e2e_bare_metal_mock_deal` read negotiations and
  force-accept as the administrator through the canonical client; no lane reads the
  API-credits storefront's negotiations.
  End-to-end confirmed: `e2e_deal` lists, force-accepts and reads negotiations through
  the canonical administrator client, and `e2e_bare_metal_mock_deal` force-accepts and
  reads one; no lane calls the API-credit storefront's changed routes. Declined from
  the fresh-context checks: setting up the bare-metal fulfillment row through the API,
  which only a delivered deal reaches; patching the administrator-configuration
  readers; and seeding deals with the administrator as buyer on VM and bare metal.

**Deferred.** API credits' pause and resume still verify the route's name and path, so
the canonical client cannot reach them: `kit-owned-storefront-auth-and-persistence`'s,
named in its index row. A new storefront route fails its module's classification test
until it is classified, and is swept only as a party route; each sweep row's contract
was read from its route's authentication call and changes with it.

## 7a. Guest isolation is proven on a real host

Delivers the recorded real-host run of `e2e_vm_guest_isolation` and the fixes it
calls for. Implements D22 (the closeout gate) and the real-host proofs of D7, D8 and D9
(D2 makes closeout wait on them); requirement "VM guest isolation is proven on a real
host", and the real-host scenarios of the two guest-isolation requirements and of "VM
host preparation converges running guests". Touches this task list, and whatever code
the run's findings name (sections 5, 6 and 6a's files).

- [x] 7a.1 Record the run. The deployment providing the controlled target and its
  operator route runs `e2e_vm_guest_isolation` against a stack deployed from this
  branch (`make -C e2e-tests test-module MODULE=e2e_vm_guest_isolation
  ACTIVE_PROFILES=local,real-provisioning-target`, as `VALIDATION_RUNBOOK.md` sections
  21–25 describe the real-provisioning runs), its host prepared by this branch's host
  kit, and supplies a sanitized summary: each observation O1–O9 made, failed or unproven
  with what an unproven one named, the run identifier, the commit, and the host's
  libvirt version. Record that summary in this task's note, naming no host, address,
  project or credential (`docs/guidance/engineering/system-tests.md`, "Locally
  verifiable and external-topology scenarios"; this repository is public). Judge it
  against D22: O1–O5, O7 and O8 made; O6 unproven only for want of a private-source
  buyer route or because the create's masquerade hides the buyer's address from the
  guest (09k8's skip naming it); O9 unproven only because libvirt refused the fixture's
  live filter removal or convergence reported `next_start` with the live definition not
  naming the filter. With no target, or no operator route,
  this task waits; if the deployment reports that the route cannot be provided, stop
  and return the change to design (design.md, Open Questions, "The host-side steps
  without an operator route"). (D22.) Verify: the recorded summary, and its judgement
  against D22.
  Done. Runs 1 and 2 did not meet D22, each failing from one probe defect fixed in 6a
  (7a.2); run 3 meets it, and its per-observation result is recorded under 7a.2.
  **Run 1** (system, external topology): `guest-isolation-20261124T102647Z`, commit
  `d90458802`, libvirt 10.0.0; 8 failed, 49 passed, 5 skipped. Every guest probe
  failed at its `sudo -n` ("a password is required"), so O1–O5, O7, O8 and O9 failed
  and O6 was unproven (relay access). The operator route, the counter reads, the
  libvirtd restart with the policy unit's rerun, and `ufw reload` all worked.
- [x] 7a.2 Fix what the run finds. For each failed observation, or each unproven one
  D22 does not admit, diagnose it from the summary, fix the code it names in the section
  that owns it — the guest interface, the policy chains or their re-assertion (5), the
  convergence command (6), the scenario or its probes (6a) — with a focused test at the
  lowest level that holds the fix, and have the deployment run the module again; record
  each run's summary as 7a.1 does. A finding the design does not cover — a decision D7,
  D8, D9 or D22 does not make — returns the change to design instead. Section 5's
  handoff items (the `--xml` parameters, real `iptables-restore --noflush`, the unit's
  order after libvirtd, `ufw reload` running `after.init`) are discharged by O2 and O7
  being made, or each becomes a finding here. (D7, D8, D9, D22.) Verify: the focused
  tests of each fix, and a recorded run meeting D22.
  Three runs; the third meets D22.
  **Run 1's finding (6a).** The tenant user's sudo asks for the password the deal
  delivers in settle status (the create's `NOPASSWD` entry is cloud-init's, for
  `root`). The guest probe now runs `sudo -S -p '' --` with that password on standard
  input (D21, "Settled by the real-host runs"): `SshSession.run` takes an optional
  `stdin`, in no argument or raised failure; `IsolationProbes` reads each guest's
  password from its own deal on first need and keeps it out of its `repr`. Unit tests
  in `test_ssh_access.py`, `test_vm_guest_isolation.py` and `test_real_vm_lane.py`
  passed (252); the new ones failed at `d90458802` under `run test-before`.
  **Run 2** (system, external topology): `guest-isolation-20261124T121352Z`, commit
  `201c4c0bd`, libvirt 10.0.0; 3 failed, 58 passed, 1 skipped. O1–O4, O8 and O9 made;
  O5 and O7 failed on one fault, no packet to the listed destination seen leaving the
  host, every other O5 check holding; O6 unproven (relay access).
  **Run 2's finding (6a).** The egress watch's socket was bound to IPv4 alone, which
  sees only received frames; it is now bound to every protocol and matches only
  outgoing IPv4 TCP to the listed address and port (D21). The deployment confirmed the
  kernel behaviour on the host. Tests in `test_vm_guest_isolation.py` passed (82); the
  new ones failed at `201c4c0bd` under `run test-before`. A socket buffer overflowing on
  a busy uplink could drop the guest's SYN, a false failure, never a false pass; left
  for a run to show.
  **Run 3** (system, external topology): `guest-isolation-20261124T140115Z`, commit
  `8e38ee217`, the host re-prepared from that commit's host kit, libvirt 10.0.0. The
  module: 61 passed, 1 skipped, 0 failed (16m10s).
  - O1 made: ARP, ICMP and TCP from one guest to the other, directly and through the
    gateway, refused.
  - O2 made: the address claim dropped while the other buyer still reaches its guest,
    and the filter's parameters present in each guest's live definition.
  - O3 made: DHCP and DNS pass, and the host port got no answer while
    `ARKHAI-GUEST-IN`'s closing drop counted packets. That drop is a catch-all, so the
    guests' own broadcast or multicast may also count there.
  - O4 made: the metadata address refused by its drop, whose counter rose.
  - O5 made: the refused destination refused by its drop, whose counter rose; the
    listed one admitted by its accept, whose counter rose, and the guest's packets to
    it seen leaving on the routed interface.
  - O6 unproven: the target's buyers reach its guests through a relay (09k8), the
    run's only skip.
  - O7 made: O3–O5 held, with both jumps first, after a libvirtd restart and after a
    UFW reload.
  - O8 made: the fixture planted (port not isolated, saved definition stripped);
    after convergence, which reported the port isolated, the filter live and the saved
    definition carrying both, the host read the port isolated and the saved
    definition carrying both; the heartbeat's longest gap and the guest-to-guest
    refusals held.
  - O9 made: the filter bound live again on libvirt 10.0.0.

  Judged against D22: met. O1–O5, O7 and O8 are made, O6 is unproven only for want of
  a private-source buyer route, and O9 is made. Section 5's handoff items — the
  `--xml` filter parameters, the unit's order after libvirtd, `ufw reload` running
  `after.init`, and real `iptables-restore --noflush` — are discharged by O2 and O7,
  with one limit recorded in design.md's Risks: a leftover duplicate jump or doubled
  rule would pass, and would decide nothing differently. No finding needed a decision
  D7, D8, D9 or D22 does not make.
- [x] 7a.3 Verification point. System: the recorded `e2e_vm_guest_isolation` run
  meeting D22 (7a.1, or a later run 7a.2 records). Unit, library integration: the suites of whatever 7a.2 changed,
  as their sections name them.
  End-to-end: `e2e_vm_guest_isolation` on the deployment's real host, in no lane; no
  lane scenario exercises it.
  Done. System: run 3 meets D22 (7a.2). 7a.2 changed only e2e harness code — the
  scenario, its probe and driver, and `ssh_access.py` — whose suites passed at
  `8e38ee217`, with the whole e2e unit suite in `make test` through `run pre-commit`;
  sections 5 and 6 owe nothing again. `e2e_vm_guest_isolation` ran in no lane.

**Round 3 triage.** design.md's Context now says the tenant user has sudo through the
`sudo` group with a generated password the deal delivers; the owner agreed a
correction is enough.

## 8. Closeout

- [x] 8.1 **Comment hygiene.** Run `make check-comment-hygiene`; confirm no comment the
  change added names the change, a section or a task, or describes anything but the
  current system. Anything found returns the change to implementation.
  Done: `make check-comment-hygiene` passed (no change ids, task numbers or change
  names outside `openspec/`). Every comment line the change added since `a714a65a1`
  (some 475, and the guest interface template's block) was read: each describes the
  current system; 69 F2's two history comments are rephrased. The observation ids
  (O1–O9) the scenario's comments name are its own module's. Nothing returns.
- [x] 8.2 **Import placement.** Check the imports the change added in
  `provisioning/compute/`, `domains/apicredits/storefront/`, the storefront tests and
  `e2e-tests/` against
  `docs/guidance/engineering/dependencies-python.md#imports-go-at-module-level`; one
  that should move returns the change to implementation.
  Done: the change's Python diff adds no indented `import` or `from … import` line;
  every import it added is at module level. Nothing returns.
- [x] 8.3 **Documentation compliance.** Re-check D3–D10, D14–D16 and D18–D23 against the
  placement tables (`docs/guidance/workflow/openspec-documentation.md`,
  `openspec/README.md#documentation-placement`) and confirm every permanent document
  written describes the current state.
  Done: each decision went to its home by the placement tables — requirements to the
  five specifications (the archive), rationale to the `physical-provisioning` and
  `test-compatibility` companions, the cross-system administrator rule to
  `ARCHITECTURE.md`, migrations to `DEPLOYMENT_AND_CONFIG.md`, operator procedures to
  the operator handbook, release procedure to the release handbook, the
  compatibility-retirement rule to engineering guidance with this repository's form in
  `docs/guidance/repository/package-versions.md`, developer procedures to the
  validation runbook and the projects' READMEs, and the real-provisioning module to
  `TESTING.md`. The promoted text was read for wording relative to the change and a
  scan of its added lines for "now", "no longer", "previously" and the change's name
  found none.
- [x] 8.4 **Narrative compression.** Shorten completed-task notes to final behaviour,
  the real-host proof's per-observation result (7a.1), deferred work and destinations, moving any
  rationale into `design.md` first.
  Done: the notes of sections 1–7a are shortened (the file from 1558 lines to about
  890), keeping each task's text, its final behaviour, evidence, deferrals and run 3's
  per-observation result in full. Moved into `design.md` first: D15's implemented
  contracts and the sweeps' limit, D20's `none` and `changed` and the use of
  `update-device`, D21's two run findings, and the leftover-rule limit in Risks. The
  fresh-context checks' fixed findings and handoff lists are dropped as discharged;
  their declined findings stay in brief.
- [x] 8.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, Goal 1: remove the
  gap rows this change closes — host-key checking disabled, VM guests sharing a
  layer-2 segment, and the administrator stance undecided — and state in the current
  state that the provisioning service checks every host against a pinned key, that a
  VM guest reaches no other guest and only DHCP and DNS on its host, and that the
  administrator's reach is one rule; the embedded-credential row stays, unowned.
  Name it in the design-promotion record.
  Done: Goal 1's three rows this change owned are removed, and a paragraph of its
  current state states the host-key check and capture, adoption, guest isolation and
  its real-host proof, and the administrator's reach, linking `ARCHITECTURE.md`; the
  embedded-credential row stays, unowned. Named in the record.
- [x] 8.6 **Campaign index currency.** Update this change's row in
  `openspec/changes/README.md` and its line in the Goal 1 campaign graph; leave the
  three unowned rows this change's design added; run `make check-change-index`. Name
  it in the design-promotion record.
  Done: the row is `in closeout`, its Notes rewritten to the validated state, and the
  Goal 1 graph line reads `(closeout)`; the archive step points the row at the archive.
  The unowned rows from the design and implementation stay; no other row's
  `Depends on` or status changed. `make check-change-index` passed. Named in the
  record.
- [x] 8.7 **Packaging.** Run `make check-packaging` and resolve every failure; run
  `make check-architecture-change CHANGE=harden-provisioning-trust-boundaries`. The
  change touches no `.agents/`, `.claude/` or `.codex/`, so `make check-agent-skills`
  is not owed. A failure returns the change to implementation.
  Done: `scripts/change-workflow run pre-archive harden-provisioning-trust-boundaries`
  passed at `a09948565` (exit 0): `make check-packaging`, every check OK, and
  `make check-architecture-change`, "owns no architecture row". `make check-agent-skills`
  is not owed; the skills check ran among `run pre-commit`'s defaults.
- [x] 8.8 **End-to-end pipeline.** Record the pipeline run the latest passing
  validation gathered, its result, and the scenarios exercising the change — `e2e_deal`,
  `e2e_bare_metal_mock_deal`, `e2e_bare_metal_publication` — with the real-target
  scenarios named as run in no lane, and `e2e_vm_guest_isolation`'s real-host
  per-observation result (7a.1), with O6 and O9 named where they are unproven and why
  (D22).
  Done, from validation 75, which passed at `a0994856544f`, the merged `HEAD` this
  closeout commit builds on and changes no code of: pipeline run 45438642286, success
  — native Ansible gate 19 run, 0 failed; VM lane 513 passed; bare-metal lane 249
  passed; API-credits lane 4 passed — with local (`check-packaging` and `make test` for
  the tree `f7e92d5e99d9`) and Helm (14 scenarios passed) passed and CI not owed.
  `e2e_deal` passed in the VM lane, and `e2e_bare_metal_mock_deal` and
  `e2e_bare_metal_publication` in the bare-metal lane; the lanes run the mock executor,
  so they evidence version-3 registration and the administrator's negotiation reads,
  not verification, capture or guest isolation. Run in no lane: the real-target
  scenarios `e2e_vm_real_provisioning`, `e2e_bare_metal_real_provisioning`,
  `e2e_real_provisioning_reapply` and the qualification modules, and
  `e2e_vm_guest_isolation`, whose run 3 (`guest-isolation-20261124T140115Z` at
  `8e38ee217`, libvirt 10.0.0) made O1–O5, O7, O8 and O9, with O6 unproven for want of
  a private-source buyer route, the target's buyers reaching its guests through a
  relay (7a.2). O9 was made. No `Owed by validation:` line is in this plan.
- [x] 8.9 **Promotion.** Write, and complete the design-promotion record in
  `design.md` naming each:
  - `openspec/specs/physical-provisioning/architecture.md`: "The host registry owns the
    connection" (the pin, why capture is an operator's probe, the version-3
    connection, the executor's rule and the mock's exemption — D3, D4); "Proof-driven
    release" (a host-key refusal before the start — D5); a new section "Guests are
    isolated from each other", after "Host preparation cannot cost the machine" (port
    isolation, the filter and its interface template, the guest policy chains and why
    they lead `INPUT` and `FORWARD`, `arkhai-guest-policy.service`, the
    `/etc/ufw/after.init` hook and `/etc/arkhai/guest-policy.rules`, the create's
    narrowed per-guest accepts, the allowlist, convergence through
    `arkhai-guest-converge` and its report, its residual exposure, why no guest shares a
    segment — D7, D8, D9, D10, D20). The five `spec.md` deltas are merged by the
    archive.
  - `openspec/specs/test-compatibility/architecture.md`: a new section "The real-host
    proof of guest isolation", after "Ordinary Arkhai purchase evidence" (the
    scenario's extension of the real VM scenario's two guests, the target-named
    operator route and its fixed probe, the planted fixture, counter and egress
    attribution, and the per-observation outcome — D18, D19, D20, D21). The principle
    that such a route adds no reach the deployment lacks is recorded in D18 only, and
    goes into no guidance (the owner declined its promotion).
  - `docs/development/VALIDATION_RUNBOOK.md`: "24. Describe The Target" (the optional
    `guest_isolation` section, its operator route and private destinations, and that
    host preparation must be given the listed destination in
    `guest_allowed_private_destinations` — D21); "25. Run The Real-Provisioning
    Scenario" (running `e2e_vm_guest_isolation`, its observations and what each
    unproven one names — D18, D19, D22).
  - `e2e-tests/README.md`: "Real provisioning target and VM lane" (the
    `guest_isolation` section and the module, D19, D21).
  - `domains/vms/provisioning/iac/README.md` and `docs/seller-quickstart.md`, "4.
    Prepare your KVM hosts": the host requirements libvirt 6.1, virt-install 3.0 and
    `ebtables` (D7), and that host preparation converges running guests and reports any
    it could not (D9, D20).
  - `docs/development/ARCHITECTURE.md`: "The administrator's reach" under "Shared
    vocabulary and identities", after "Authenticated service boundaries", as drafted
    in `design.md` (D14, D15).
  - `docs/development/DEPLOYMENT_AND_CONFIG.md`: "Migrations at startup", the list of
    migrations after the v0.3.0 baseline, gains the v2-to-v3 rewrite and its mark
    (D4, D6).
  - `docs/operator-handbook.md`: "Host definitions" (version 3 and `host_keys`, D4);
    a new "Capturing and rotating a host key" under "Host definitions", with recovering
    a host-key refusal (D3, D5); "Ansible configuration" (verification is rendered per
    host and an operator's file cannot turn it off, D4); "Upgrading a deployment", its
    procedure and "What the upgrade from v0.3.0 changes" (adoption, running the host
    kit on every VM host before the retirement release, D6, D9).
  - `docs/seller-quickstart.md`: "4. Prepare your KVM hosts" (stating or capturing a
    host's key, `guest_allowed_private_destinations`, D3, D8);
    `docs/bare-metal-seller-quickstart.md`: "Define the selected site" (stating a
    host's key, D3).
  - `domains/vms/provisioning/iac/README.md`: "Core Capabilities" and "Global Settings"
    corrected to the isolation the host kit installs, the unapplied
    `tenant_isolation.network` block removed (D7, D8).
  - The engineering guidance's new `retiring-compatibility.md`, `versioning.md`'s two
    links, and the engineering README's `versioning` tag description; the new section
    "Compatibility paths retire on a schedule" in
    `docs/guidance/repository/package-versions.md`; and in `docs/release-handbook.md`
    the new "Compatibility to retire" with its three rows (D6, D9, D23), the
    introduction's list, the first step of "Loading a release candidate", and the second
    step of "Cutting a release" — all as drafted in `design.md` (D16, D23).
  - D1, D2, D12, D13, D17, D22 and D24 have no permanent destination; D11's roadmap row
    and unowned gap were written with the design.
  Promote the target's management SSH pin field, the rule that a VM host is pinned
  from an independent source before capacity is declared (26 F1), and reapply
  evidence to the test-compatibility specification and the real-target
  instructions in the validation runbook and E2E README.
  Done: each document above written as listed, the pin rule also in the
  `test-compatibility` companion and `TESTING.md`'s real-provisioning lane, which
  names `e2e_vm_guest_isolation` (the 6a handoff); the validation runbook's
  "21. Provide Real Compute Hosts" gains the isolation prerequisites and section 25 a
  "Prove guest isolation" subsection with the target's needs from 7a's handoff. The
  `physical-provisioning` companion's version paragraphs now describe version 3 and
  the second migration. The design-promotion record in `design.md` names every
  decision's location. The capability index needs no row, no capability being new,
  and none of the five capabilities has an `index.md`. The five deltas merge at the
  archive (8.12).

- [x] 8.10 **Guidance placement.** Read the new engineering file, the package-versions
  section and the release handbook's section against the layer test; run
  `make check-guidance`.
  Done: `retiring-compatibility.md` holds without the workflow or this repository,
  linking only engineering files; `package-versions.md`'s section is this
  repository's form, spanning its packages; the release handbook's table is a
  procedure, outside the guidance. `ansible-gates.md`'s implementation edit stays in
  repository guidance. `make check-guidance` passed: 105 files tagged, no link to a
  higher layer, every cited anchor a heading. Nothing needs a decision.
- [x] 8.11 **Documentation citations.** Run
  `make check-doc-citations CHANGE=harden-provisioning-trust-boundaries` and resolve
  every match; then `scripts/change-workflow openspec validate harden-provisioning-trust-boundaries --strict`.
  Done: the citation check first found two unresolvable paths the compression and
  the record wrote, a shortened script path and the example target's name; both
  fixed, and it passed: every cited path resolves. `scripts/change-workflow openspec
  validate harden-provisioning-trust-boundaries --strict`: "Change
  'harden-provisioning-trust-boundaries' is valid".
- [x] 8.12 **Archival.** Run
  `scripts/change-workflow openspec archive harden-provisioning-trust-boundaries -y`,
  merging the `physical-provisioning`, `site-capacity`, `api-credits`,
  `storefront-publication` and `test-compatibility` deltas.
  Done: no permanent spec held the deltas' content, so the archive merged them
  without `--skip-specs`: 10 requirements added and 6 modified (`physical-provisioning`
  6 and 5, `test-compatibility` 1 and 1, one added in each of the others), each added
  requirement present once, the modified ones replaced in place, nothing else touched.
  Archived as `openspec/changes/archive/2026-11-24-harden-provisioning-trust-boundaries/`,
  the index row pointing there. `scripts/change-workflow run pre-commit` then passed:
  every specification strictly valid, and the index, tasks, skills and repository
  checks.
