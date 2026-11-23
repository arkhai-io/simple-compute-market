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

**Section evidence.** The Ansible unit suite passed (198 tests), the contracts
unit suite passed (163 tests), and the focused host authority and definitions
suites passed (86 tests). Typed API integration covers registering and reading
pins, refusal of an empty pin, preservation across a port change and INI
re-import, and pin export with an unchanged re-import that omits it. Those pin
round trips ran through the typed application API in place of the planned
lower-level cases; the unchanged library and unit tests cover the existing
generic paths. Focused API and SQLite migration checks passed. The chart's rendered
host document passed the provisioning parser and SSH codec check. A detached
baseline run fails the new pin test at the missing helper argument. The
existing migration still writes version 2, validating the fields shared with
version 3; the next section advances the resulting rows to version 3.

**End-to-end coverage.** The VM deal, bare-metal mock deal and bare-metal
publication lanes exercise version-3 host registration. Neither those lanes
nor the real reapply scenario supplies evidence of host verification for this
section.

The execution snapshot returns an isolated copy of nested public fields. A
two-session SQLite test overlaps an omitted-field update with explicit pin
rotation. Existing hosts in a batch are locked in host ID order.

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

**Section evidence.** The host authority and migration suites passed with
38 and 15 tests respectively. The migrations retain protected values and queued
jobs, mark rewritten hosts for adoption, and reject a malformed row without
partially applying the rewrite. Authority tests cover the committed pin in an
adoption race, explicit replacement after adoption, and the internal
adoption flag staying out of the public host and definition models. The capture
route uses the authority operation in section 4. The focused host API test passed,
verifying omission from the signed host read and YAML export.

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

**Section evidence.** The Ansible suites passed (209 tests), the job and
teardown suites passed (29 tests), and the service status and unreadable-key
suites passed (28 tests). The SSH command-builder case uses Ansible's own plugin
with an operator configuration that disables host-key checking. The mock
executor case lives with the concrete executor in the Ansible package.
The release test programs a pre-start host-key refusal and verifies that the
job engine schedules the named teardown rerun.

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

**Section evidence.** Six probe tests, 134 contract and route tests, 69
typed service tests, 213 real-lane helper tests, and 56 qualification tests passed. The tests cover
observation, adoption, mismatch, explicit replacement, and the host's pin
round-trip through the typed client. In addition, a local SSH fixture using
Ed25519, RSA, and ECDSA keys exercised discovery and capture against a temporary
database. VM test supply is declared once a pin is available. Reapplying the
VM declaration restates the registered pin if a key is absent from the target
configuration.

**Round 1 triage fixes (26 F1, 26 F2).** 26 F1, settled as the decision recorded
under D5 ("The real-target harness"): task 4.4's observe-and-capture fallback is
replaced. `pin_registered_vm` no longer checks connectivity or captures what a host
presents; it returns the registered host when it holds a pin, the target's stated
key or one stored before the run, and otherwise refuses before capacity is declared,
naming `ssh_host_public_key` and the operator's capture route. The test-compatibility
delta's sentence and its new scenario "A VM target with no pin is refused" say so,
and the committed example target's comment names the requirement. 26 F2: the raw
malformed-fingerprint request in `test_hosts_api.py` asserts only its 422 and is
commented as a rejection-path test. Evidence: the e2e unit suites
`test_real_vm_lane.py`, `test_real_provisioning_target.py` and
`test_real_bare_metal_lane.py` (unit) passed, 214 tests; the new
`test_an_unpinned_vm_is_refused_before_supply_without_capturing_what_it_presents`
failed at `5c911f1af` under `run test-before`, the file's other 94 tests passing
there; the provisioning service's integration suite (application integration)
passed, 579 tests. The fresh-context compliance check found the delta's
prohibition conditional on a fingerprint, which the decision rejects, and the
example target's comment omitting a pin an earlier run stated; both were fixed. It
noted that no unit test drives `provision_e2e_executor` with an unpinned host to show
capacity undeclared; declined, since that order is `provision_e2e_executor`'s, which
runs `before_declare` before declaring and is unchanged, and the gap predates the fix.
`scripts/change-workflow run pre-commit`: "after-functional-change at 5c911f1af…:
passed, exit 0"; "pre-commit-functional at 5c911f1af…: passed, exit 0", its local
evidence for the tree `7ec540110033` passing `check-packaging` and `make test`;
"pre-commit at 5c911f1af…: passed, exit 0".

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
  Done: `vm-management/templates/guest-interface-args.j2` holds `--network
  network=default,model=virtio` and four `--xml` XPath edits for the port and the
  filter. Each site passes `{{ lookup('template', 'guest-interface-args.j2') | trim }}`.
  It is a template rather than a variable because a pool's `extra_vars` reach
  `ansible-playbook --extra-vars` and override any variable. virt-install has no
  sub-option for a filter's parameters, and `--xml` first shipped in virt-install
  3.0, so 5.2's preflight also refuses an older virt-install. `VmGuestInterfaceTests`
  (static configuration) passed. It finds the nine commands, GPU ones included, each
  passing the lookup once and no other `--network`. It renders the template with
  Jinja2 and reads the arguments, and shows the template reads no variable.
  `VmGuestInterfaceNativeTests` (library integration, native gate) passed: Ansible's
  own template lookup, from a play's templates directory, renders the same arguments.
  No test runs the lookup through a role's site. `run test-before` at `d7e3f66c6`
  failed to collect the current module, for want of the `jinja2` it adds. An earlier
  draft of the site check, without the import, ran there: all nine sites failed it,
  each naming `network=default` alone.
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
  Done: `vm-setup/tasks/guest-policy.yml`, included after the KVM network and before
  security hardening, whose existing save writes the rules out. Its preflight refuses,
  naming each, libvirt before 6.1, no `clean-traffic` filter, virt-install before
  3.0, and no `ebtables`, which host preparation now installs. The rules are
  `templates/guest-policy.rules.j2`; `files/guest_policy.sh`, installed as
  `/usr/local/sbin/arkhai-guest-policy`, fills both chains, deletes any existing
  jump by its rule, and inserts each jump first, in one `iptables-restore --noflush`
  transaction, waiting for the xtables lock. It runs from
  `arkhai-guest-policy.service`, a oneshot ordered after UFW, the saved rules and
  libvirtd. The unit is `WantedBy` libvirtd and keeps no active state, so every
  libvirtd start, socket activation included, runs it again. It also runs from
  `/etc/ufw/after.init` on `start`. UFW is expected to run that hook on start and on
  reload; only the hook's text is tested here. Each allowlist entry must be an IPv4
  address or CIDR block, checked with the role's preconditions.
  `test_guest_policy.py` passed:
  - the rendered chains and the role's structure (static configuration);
  - the real installer script against stateful fake `iptables` and
    `iptables-restore` at the subprocess boundary: over existing UFW and libvirt
    jumps, after both re-insert theirs, on a rerun, and with no rules file. The fake
    stores rules as written, not normalised, so real `iptables-restore` parsing is
    not exercised;
  - natively, under ansible-core 2.19.13 in the provisioning image (library
    integration), the preflight tasks against fake `virsh`, `virt-install` and
    `ebtables`. The refusal message names all four missing items, or the one
    missing alone. The allowlist check is also run natively, admitting addresses
    and blocks and refusing a rule fragment, a bad octet, a trailing newline, IPv6,
    a string and a mapping.

  It failed to collect at `d7e3f66c6` under `run test-before`, since the `jinja2`
  dev dependency it adds was absent.
- [x] 5.3 Remove the host kit's `ufw allow in on virbr0 from 192.168.122.0/24` and the
  scattered guest port-22 rules (the iptables `INPUT` drops and logs, the UFW denies,
  the `vm-network-isolation.sh` script and service), keeping `allow out on virbr0`;
  correct the host kit's printed claims to what it installs. (D8.) Verify: a static
  test that none of the removed rules remains and the printed summary names the guest
  policy chains.
  Done: none is installed, and security hardening's first firewall task removes
  each from a host holding it, matching their exact drop and log forms, as D8's "the
  host kit removes" reads. `TestNoPerPortGuestRuleRemains` passed (static
  configuration, and the task's real shell against fake `iptables` and `ufw`). The
  host holds every such rule and five operator rules: three port-22 accepts from a
  bridged uplink, a LAN and `virbr0`, an unrelated drop, and a general accept. Only
  the operator rules stay. The task's removal of `vm-network-isolation.service`
  and its script works on absolute paths, so no test runs that branch. Both printed
  summaries name the chains. They no longer claim an isolation service, its log
  prefixes, or VM attack detection by the fail2ban filter that read those prefixes.
- [x] 5.4 Verification point. Unit (static role tests): `make -C
  domains/vms/provisioning/iac test`; the playbooks' syntax gates, `make -C
  domains/vms/provisioning/iac validate-playbooks`; the native Ansible gate, `make -C
  domains/vms/provisioning/iac native-ansible-gate`. The real-host proof is section 6.
  End-to-end: the lanes run the mock executor and no real VM, so none exercises it.
  Done: `make -C domains/vms/provisioning/iac test` passed (210, 11 native cases
  skipped without Ansible). No local Ansible, so the syntax checks and native gate ran
  as `domains/vms/provisioning/iac/scripts/native_ansible_gate.sh` in the built
  `arkhai:compute-provisioning` image over this tree, mounted read-only: every
  playbook's syntax check, `vm-setup-task-files.yaml` importing `guest-policy.yml`
  included, then its 67 tests passed. The syntax check once failed `vm-create.yml`
  on an apostrophe added to a shell comment; the comment now has none. `docs/guidance/repository/ansible-gates.md`
  names the new native cases. End-to-end confirmed: no lane scenario covers this
  section; `e2e_vm_guest_isolation` (section 6) is its only end-to-end evidence.
  `scripts/change-workflow run pre-commit`: "after-functional-change at d7e3f66c6…:
  passed, exit 0"; "pre-commit-functional at d7e3f66c6…: passed, exit 0", its local
  evidence for the tree `04bdb7c0c9f9` passing `check-packaging` and `make test`;
  "pre-commit at d7e3f66c6…: passed, exit 0". Two fresh-context checks ran, and their
  findings were fixed: a pool's `extra_vars` could override an interface variable,
  the removal patterns matched port-22 accepts, the unit's `RemainAfterExit` kept it
  from re-running on a later libvirtd start, the installer did not wait for the
  xtables lock, the allowlist pattern admitted a trailing newline, and some evidence
  wording overstated the tests. Declined: the preflight's task-level variables can
  be overridden by extra variables, which only the operator sets.

**Outside the plan.** A create inserts its guest's two forwarding accepts at
`FORWARD`'s first position, ahead of the policy's jump, and as written they admitted a
guest's own packets: another guest's connection to this guest's port 22 through the
gateway, and any connection a guest opened from its port 22. The inbound accept now
requires `! -i virbr0` and the reply accept `--ctstate ESTABLISHED`, so neither matches
a packet a guest originates. `VmCreateForwardingTests` holds this; teardown deletes
these rules by their marker, whatever else they match. The host kit's
`iptables-restore.service` fallback never restores at boot; it is recorded unowned in
`openspec/changes/README.md`, not fixed.

**Handoff.** Not proven until 6.3 runs on a real host: that virt-install's `--xml`
creates the filter's two `<parameter>` elements from the `[@name='…']` predicates (no
virt-install was available here to show it); that real `iptables-restore --noflush`
flushes and refills a declared chain and deletes jumps by rule as the fake does; that
libvirtd's start completes its network rules before systemd starts
`arkhai-guest-policy.service` after it; and that `ufw reload` runs `after.init start`. The fail2ban jail `vm-ssh-attacks` matches log
lines only the per-port rules wrote, so it now matches nothing; it is left as it is.
Removing per-port rules from a host prepared by an older release adopts state that
release wrote, so review may judge it a compatibility path owing a retirement row
beside D9's (D16). Closeout's promotion (8.9) should carry the host requirements this
section adds to the seller quickstart and the VM IaC README: libvirt 6.1, virt-install
3.0 and `ebtables`. It should carry `arkhai-guest-policy.service`, the
`/etc/ufw/after.init` hook and `/etc/arkhai/guest-policy.rules` to the architecture
companion's new section. The flat `tests/` layout of the IaC suite, not a Python
package, is kept as it is.

## 6. Running guests converge, and the isolation is proven on a real host

Delivers host preparation's live convergence of running guests and the real-host
proof of D7 and D8 as an external-topology scenario. Implements D9 and the proofs of D7
and D8; requirement "VM host preparation converges running guests", and the scenarios
of the two guest-isolation requirements on a real host. Touches
`domains/vms/provisioning/iac/ansible/roles/vm-setup/` and `e2e-tests/`.

- [ ] 6.1 In host preparation, for each running guest, set its tap's bridge port
  isolated without interrupting its link, apply `clean-traffic` live through `virsh
  update-device --live` where libvirt accepts it and otherwise leave it for the
  guest's next start, write both into its saved definition, and report each guest it
  could not converge by name. (D9; "A host prepared before isolation is prepared
  again", "A guest cannot be converged".) Verify: static tests with
  `domains/vms/provisioning/iac/tests/host_fakes.py` faking `virsh` and `bridge` for a
  converged guest, a guest refusing the live filter, and one whose port cannot be
  isolated, reported.
- [ ] 6.2 Add the external-topology scenario `e2e_vm_guest_isolation`, in no lane and
  blocked without the real-provisioning target: two CPU guests on the target's KVM
  host; ARP, ICMP and TCP from one to the other, directly and through the gateway,
  refused; an ARP claim of the other's address dropped while the other's buyer
  connection still reaches it; DHCP and DNS passing, another host port and a private
  destination refused, before and after restarting libvirt and reloading UFW; a buyer
  connecting from a private address reaching their guest; and a guest created before
  host preparation ran again converged with its buyer session uninterrupted. Register
  its marker in `e2e-tests/pyproject.toml`. (D7, D8, D9.) Verify: its collection and
  its blocked path without the target in the e2e unit suites.
- [ ] 6.3 Run `e2e_vm_guest_isolation` against the owner's controlled CPU target, on the
  owner's word that the target is available, and record the result, its run and the
  target's libvirt version in this task's note; with no target available, record it as
  not run and why, for validation and triage. (D7, D8, D9; D2 makes closeout wait on
  this proof.) Verify: the recorded result.
- [ ] 6.4 Verification point. Unit (static role tests): `make -C
  domains/vms/provisioning/iac test` and `native-ansible-gate`. System: the
  `e2e_vm_guest_isolation` run on the real host (6.3).
  End-to-end: `e2e_vm_guest_isolation`, in no lane; no lane scenario exercises it.

## 7. A storefront never authorizes its administrator as a party

Delivers authentication of the API-credits storefront's negotiation reads and the
storefronts' tests holding the administrator rule. Implements D14 and D15 (held,
fixed); requirement "A storefront never authorizes its administrator as a party", and
the site-capacity, api-credits and physical-provisioning administrator requirements as
the existing checks hold them. Touches `domains/apicredits/storefront/`,
`domains/vms/storefront/tests/`, `domains/bare_metal/storefront/tests/`,
`kit/site/tests/`, `domains/apicredits/service/tests/`.

- [ ] 7.1 Require the administrator on the API-credits storefront's
  `GET /api/v1/listings/{listing_id}/negotiations` and `…/negotiations/{neg_id}` through
  `require_admin_principal`, as its other administrator routes are. (D15, fixed;
  "The API-credits storefront's negotiations are read unsigned", "The administrator
  reads a listing's negotiations".) Verify: application-integration tests in
  `domains/apicredits/storefront/tests/integration/` refusing unsigned and
  buyer-signed reads, and reading them through the canonical storefront client signed
  as the administrator.
- [ ] 7.2 Add, for each storefront — VM (`domains/vms/storefront/tests/integration/`),
  bare metal (`domains/bare_metal/storefront/tests/integration/`), API credits — a test
  that a request signed under `admin` by an active administrator principal is refused
  on every buyer, counterparty-seller and service route and admitted on its
  administrator routes, and that an administrator's advance records the round as the
  administrator's. (D15, held; "The administrator opens a negotiation as a buyer",
  "The administrator advances a negotiation".) Verify: the three tests.
- [ ] 7.3 Confirm the existing checks hold the authorities' form: provisioning's
  assembly refusal (`provisioning/compute/contracts/tests/unit/test_contracts.py`,
  `provisioning/compute/service/tests/unit/test_route_table_composition.py`),
  `kit/site/tests/unit/test_auth_route_parity.py`, and the credits service's
  `tests/integration/test_credits_route_parity.py`; add to the last a case that a
  credits route naming another role admits an `admin`-signed request. (D15; the
  site-capacity and api-credits requirements.) Verify: the four suites.
- [ ] 7.4 Verification point. Unit: `test_contracts.py`,
  `test_route_table_composition.py`, `test_auth_route_parity.py`. Application
  integration: the three storefronts' new tests and the API-credits storefront's
  negotiation-read tests, `test_credits_route_parity.py`.
  End-to-end: `e2e_deal` and `e2e_bare_metal_mock_deal` read negotiations and
  force-accept as the administrator through the canonical client; no lane reads the
  API-credits storefront's negotiations.

## 8. Closeout

- [ ] 8.1 **Comment hygiene.** Run `make check-comment-hygiene`; confirm no comment the
  change added names the change, a section or a task, or describes anything but the
  current system. Anything found returns the change to implementation.
- [ ] 8.2 **Import placement.** Check the imports the change added in
  `provisioning/compute/`, `domains/apicredits/storefront/`, the storefront tests and
  `e2e-tests/` against
  `docs/guidance/engineering/dependencies-python.md#imports-go-at-module-level`; one
  that should move returns the change to implementation.
- [ ] 8.3 **Documentation compliance.** Re-check D3–D10 and D14–D16 against the
  placement tables (`docs/guidance/workflow/openspec-documentation.md`,
  `openspec/README.md#documentation-placement`) and confirm every permanent document
  written describes the current state.
- [ ] 8.4 **Narrative compression.** Shorten completed-task notes to final behaviour,
  the real-host proof's result (6.3), deferred work and destinations, moving any
  rationale into `design.md` first.
- [ ] 8.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, Goal 1: remove the
  gap rows this change closes — host-key checking disabled, VM guests sharing a
  layer-2 segment, and the administrator stance undecided — and state in the current
  state that the provisioning service checks every host against a pinned key, that a
  VM guest reaches no other guest and only DHCP and DNS on its host, and that the
  administrator's reach is one rule; the embedded-credential row stays, unowned.
  Name it in the design-promotion record.
- [ ] 8.6 **Campaign index currency.** Update this change's row in
  `openspec/changes/README.md` and its line in the Goal 1 campaign graph; leave the
  three unowned rows this change's design added; run `make check-change-index`. Name
  it in the design-promotion record.
- [ ] 8.7 **Packaging.** Run `make check-packaging` and resolve every failure; run
  `make check-architecture-change CHANGE=harden-provisioning-trust-boundaries`. The
  change touches no `.agents/`, `.claude/` or `.codex/`, so `make check-agent-skills`
  is not owed. A failure returns the change to implementation.
- [ ] 8.8 **End-to-end pipeline.** Record the pipeline run the latest passing
  validation gathered, its result, and the scenarios exercising the change — `e2e_deal`,
  `e2e_bare_metal_mock_deal`, `e2e_bare_metal_publication` — with the real-target
  scenarios named as run in no lane, and `e2e_vm_guest_isolation`'s real-host result
  (6.3).
- [ ] 8.9 **Promotion.** Write, and complete the design-promotion record in
  `design.md` naming each:
  - `openspec/specs/physical-provisioning/architecture.md`: "The host registry owns the
    connection" (the pin, why capture is an operator's probe, the version-3
    connection, the executor's rule and the mock's exemption — D3, D4); "Proof-driven
    release" (a host-key refusal before the start — D5); a new section "Guests are
    isolated from each other" (port isolation, the filter, the guest policy chains and
    why they lead `INPUT` and `FORWARD`, the allowlist, convergence and its residual
    exposure, why no guest shares a segment — D7, D8, D9, D10). The four `spec.md`
    deltas are merged by the archive.
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
    the new "Compatibility to retire" with its two rows, the introduction's list, the
    first step of "Loading a release candidate", and the second step of "Cutting a
    release" — all as drafted in `design.md` (D16).
  - D1, D2, D12, D13 and D17 have no permanent destination; D11's roadmap row and
    unowned gap were written with the design.
  Promote the target's management SSH pin field, the rule that a VM host is pinned
  from an independent source before capacity is declared (26 F1), and reapply
  evidence to the test-compatibility specification and the real-target
  instructions in the validation runbook and E2E README.

- [ ] 8.10 **Guidance placement.** Read the new engineering file, the package-versions
  section and the release handbook's section against the layer test; run
  `make check-guidance`.
- [ ] 8.11 **Documentation citations.** Run
  `make check-doc-citations CHANGE=harden-provisioning-trust-boundaries` and resolve
  every match; then `scripts/change-workflow openspec validate harden-provisioning-trust-boundaries --strict`.
- [ ] 8.12 **Archival.** Run
  `scripts/change-workflow openspec archive harden-provisioning-trust-boundaries -y`,
  merging the `physical-provisioning`, `site-capacity`, `api-credits` and
  `storefront-publication` deltas.
