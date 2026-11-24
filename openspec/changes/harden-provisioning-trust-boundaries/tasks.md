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

**Correction (planning after design review 41).** The real-host proof this section's
notes defer to "6.3" is now section 6a's scenario, run in section 7a. Removing the
per-port rules from a host an earlier release prepared (5.3) is a compatibility path
(D23): its retirement row is written at closeout (8.9), and 5.3's code stays as it is.
The `physical-provisioning` scenario "A host lacks a prerequisite of isolation" is held
by 5.2's native preflight case, which names every missing item.

**Pre-closeout triage, 69 F1 (decision, fix).** The chains matched only IPv4, so a
running guest whose filter waits for its next start (D9) could reach the host's open
ports over IPv6, and be forwarded, on a host whose `default` network carries IPv6. The
owner chose to drop it in the policy (D8, "Settled at 69 F1"), over refusing such a
bridge at host preparation or recording a limit, with no new real-host run (Risks).
`files/guest_policy.sh` now runs, after the IPv4 transaction, an
`ip6tables-restore -w --noflush` transaction filling `ARKHAI-GUEST-V6` with one drop and
putting its jumps first in ip6tables' `INPUT` and `FORWARD` for `-i virbr0`, deleting
any present by rule; it skips it, saying so, where `$PROC_ROOT/sys/net/ipv6` (`/proc` by
default) is absent. The unit and the UFW hook run the same script, so the jumps are
re-asserted with the IPv4 ones; nothing saves the IPv6 chain, which the unit restores at
boot. The printed summaries name the chain. The `physical-provisioning` delta's
requirement drops IPv6 from the bridge, with the scenario "A guest whose filter waits
for its next start sends IPv6". `host_fakes`' `iptables` and `iptables-restore` also
serve as `ip6tables` and `ip6tables-restore`, over rules of their own.
`test_guest_policy.py` passed (unit, the real installer against the fakes; `make -C
domains/vms/provisioning/iac test`, 233 passed, 15 native cases skipped without local
Ansible). Its new cases: IPv6 dropped ahead of UFW's and libvirt's ip6tables jumps,
the jumps first and single after both re-add theirs, no ip6tables call on a kernel
without IPv6, and a refused IPv6 transaction failing the installer with the IPv4 policy
standing; the rerun case and the printed summaries cover IPv6 too. `run test-before`
at `b6c2d299b` (the test file against the earlier code and fakes): 8 failed, 22 passed,
6 native skipped. The no-IPv6 message, the refused transaction's exit 0 and the
summaries failed on the code; the three cases seeding ip6tables rules failed on the
earlier fake's missing `family` argument. Real `ip6tables-restore` parsing is not
exercised, as for the IPv4 transaction (5.2). `scripts/change-workflow run pre-commit`
over both fixes: "after-functional-change …: passed, exit 0"; "pre-commit-functional
…: passed, exit 0"; "pre-commit …: passed, exit 0". The fresh-context check found no
defect in the script, its order or the design and delta; it found a comment's "one jump
to each chain", untrue of a chain jumped from both built-ins, the role's claim that
hardening saves the installed rules, untrue of the IPv6 chain, three lines left
unwrapped, the refused-transaction case not holding the IPv4 policy, and the fake's
`rules()` relaxed to return nothing for an unwritten table. All were fixed, the last by
reverting it; nothing was declined.

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
  Done: a POSIX `sh` script that orchestrates `virsh` and `bridge`, with an embedded
  `python3` helper that reads and edits libvirt's XML and writes the JSON line, so
  nothing is parsed or quoted by hand; `python3` joins `virsh` and `bridge` as what it
  needs to run. Both definitions are edited by `virsh update-device`: `--live` with the
  running interface element, its filter replaced and its `<port>` left as libvirt holds
  it (the port is isolated through the bridge, and whether libvirt takes a live `<port>`
  change varies by version, so asking for one could refuse the filter with it), and
  `--config` with the saved element carrying both, rather than a `define` of the whole
  domain, which would drop what `dumpxml` omits without `--security-info`. Two
  differences from the plan's fields: `filter` has a third value, `none`, when neither
  definition holds the filter (so a guest whose saved definition was not written, or
  could not be read, is never reported as waiting for a next start that would not bind
  it), and each line carries `changed`, which host preparation's `changed_when` reads
  and which says an already converged guest was left alone. The command also fails
  when `virsh list` fails or no working directory can be made. `TestTheCommand` in
  `test_guest_convergence.py` passed: the real script run whole against the stateful
  doubles of `virsh` and `bridge` added to `host_fakes.py`, at its subprocess boundary,
  on a `PATH` of those doubles and the ordinary tools alone, so no real `virsh` or
  `bridge` is reached (the plan calls this unit; it is the script's orchestration
  against doubles of the commands it wraps). It covers each case the task lists, and a
  transient guest, a live filter refused on a transient guest (`none`), a guest with no
  interface on `default`, a guest whose interfaces cannot be read beside one that
  converges, an unreadable running definition (`next_start`), and unreadable running
  guests. No test reaches a failing `bridge -d link show`, either definition lacking
  the interface `domiflist` named, or a failing `mktemp`. The double refuses a live
  `<port>` change and, for a domain marked so, a live filter change; that libvirt does
  either is not shown here.
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
  Done: four tasks at the end of `tasks/guest-policy.yml`, after the unit's restart,
  tagged `guest_policy`: the install, the run (`changed_when` from the lines'
  `changed`, no `failed_when`, so only a non-zero exit fails host preparation), and two
  looping `debug` tasks naming each guest whose port is not isolated or whose saved
  definition was not written, with whether its filter is bound, and each whose filter
  waits for its next start, each with its reason. `main.yml`'s flow comment and
  post-installation notes say running guests are converged.
  `TestHostPreparationConvergesRunningGuests` passed (structure tests over the task
  file, read with PyYAML: the install's source, destination, owner and mode, the order
  after the policy's unit restart, the run's lack of `failed_when`, and the report
  reading the run's registered lines). `TestTheReportNatively` passed (library
  integration, native gate): the run and both report tasks under ansible-playbook, the
  run's command replaced by a fake printing an unconverged guest, a `next_start` guest,
  a guest with no filter in either definition and a converged guest, the play naming
  the first three by name, state and reason and not the fourth, and a fake exiting 1
  failing the play. No test runs the install task or the role as a whole. The new
  module is in the native gate's `NATIVE`, and `ansible-gates.md` names the case.
- [x] 6.3 Verification point. Unit (static configuration and the real script against
  fakes): `make -C domains/vms/provisioning/iac test`. Library integration (native
  gate): `make -C domains/vms/provisioning/iac validate-playbooks` and
  `native-ansible-gate`, or, with no local Ansible,
  `domains/vms/provisioning/iac/scripts/native_ansible_gate.sh` in
  the provisioning image over this tree, as section 5 ran it.
  End-to-end: the lanes run the mock executor and no real VM, so none exercises it;
  `e2e_vm_guest_isolation`'s O8 and O9 (section 6a, run in section 7a) are its only
  end-to-end evidence.
  Done: `make -C domains/vms/provisioning/iac test` passed (226, 15 native cases
  skipped without local Ansible). With no local Ansible, `native_ansible_gate.sh` ran
  in the built `arkhai:compute-provisioning` image (ansible-core 2.19.13) over this
  tree mounted read-only: every playbook's syntax check, `vm-setup-task-files.yaml`
  parsing `guest-policy.yml` with the new tasks, then 85 tests passed, the two new
  native cases among them. End-to-end confirmed: no lane scenario covers this
  section; O8 and O9 of `e2e_vm_guest_isolation` are its only end-to-end evidence.
  `scripts/change-workflow run pre-commit`, before and again after the fresh-context
  fixes: "after-functional-change …: passed, exit 0"; "pre-commit-functional …:
  passed, exit 0", `check-packaging` and `make test` passing for the trees
  `440b01681af5` and `e5df3fd67cb9`; "pre-commit …: failed", its one failure each time
  the citations check naming `e2e-tests/tests/unit/test_vm_guest_isolation.py`, which
  this plan cites and 6a.2 creates.
  The fresh-context check found: two comments stating as fact that libvirt refuses a
  live `<port>` change (now stated as varying by version), comments naming the
  real-host proof before it exists and a release-relative docstring (reworded),
  `filter: next_start` reported for a guest whose saved definition was not written or
  whose interfaces could not be read (the `none` state above), an unchecked `mktemp`,
  untested error branches (four now tested, three named above as untested), the level
  labels "unit" and "static configuration" (corrected above), a structure test
  restating the report's expressions the native case proves (trimmed), and the flat
  IaC test layout with no gap row (added to `openspec/changes/README.md`). Declined: a
  fallback line when the report's own `python3` fails, since `python3` is checked
  present first and a failure there is no guest's state to report.
  After the commit, `run test-before` of `test_guest_convergence.py` at `eccfbd790`
  failed as intended: 17 failed, 1 passed, 2 native cases skipped, each failure the
  absent script or the absent tasks (and one the double's new `isolation_refused`
  argument), not a collection error.
  **Round 2's triage, 50 F2 (fix).** The command reported a filter `live` from the
  running definition alone, so a guest whose definition names `clean-traffic` but whose
  tap libvirt binds nothing was reported filtered. It now reads `virsh
  nwfilter-binding-list` after the definition check or an accepted live update, and
  reports the filter `live` only when the tap's `clean-traffic` binding is listed; a
  missing binding, or a list it cannot read, is reported as not live (`next_start`
  when the saved definition carries the filter), with "libvirt binds no clean-traffic
  filter to <tap>" or the read's failure as its reason. Nothing is repaired: libvirt
  ignores a live update repeating the same filter, and the next start binds what the
  saved definition carries. The report's fields and values are unchanged. The double's
  `virsh` lists a binding for each running tap whose live definition names a filter,
  unless the interface is marked `binding_absent`. In 6a, `live_restoration` keeps O9
  failing where the command now says `next_start` while the live definition names the
  filter (libvirt took the live change and binds nothing), leaving O9 unproven only
  for a filter libvirt did not take live; D20, D22 and the `test-compatibility` delta
  say so. `test_guest_convergence.py` passed (unit, the real script against the
  doubles; `make -C domains/vms/provisioning/iac test`, 229 passed, 15 native cases
  skipped without local Ansible), three new cases among them: a definition naming the
  filter with no binding, a live update accepted with no binding, and an unreadable
  binding list. `make -C e2e-tests test-unit` passed (unit, 1138, 1 skipped), with
  `test_a_live_filter_libvirt_took_but_does_not_bind_fails_o9` new and the next-start
  case's converged state corrected to a filter absent from the live definition. `run
  test-before` at `82ec390c8`: the three convergence cases failed (each reported
  `live`, no error), the other 16 passed; the O9 case failed (`unproven`), the other 75
  passed. The native gate was not run: the fix changes no task, and the tasks that read
  the report read the same fields. `scripts/change-workflow run pre-commit`, first run:
  "after-functional-change …: passed, exit 0"; "pre-commit-functional …: failed, exit
  2", only its tree check, the worktree having been edited during the run
  (`check-packaging` passed, and `make test` failed on nothing but the changed tree);
  "pre-commit …: passed, exit 0". Final run, on the committed tree:
  "after-functional-change …: passed, exit 0"; "pre-commit-functional …: passed, exit
  0"; "pre-commit …: passed, exit 0". The fresh-context check found: O9 left unproven,
  not failed, for a live update libvirt took but did not bind (fixed above); D21's
  "makes O6 when it is private" still true only by implication, here and in 6a.3
  (now "private and outside the guests' network"); D22's "until a run makes it" for an
  O6 no run can make (reworded); and line wrapping. No finding was declined; its note
  that the double's generic refusal message names the subcommand as the domain was
  left, since the test asserts only the command's own prefix.

**Handoff.** Not shown until 7a's run: that libvirt accepts `update-device --live` with
the running element as `dumpxml` prints it (target, alias and address included) and
binds the filter (O9), whether it would take a live `<port>` change (the command never
asks for one), and that `bridge link set ... isolated on` keeps the guest's sessions
(O8). The running definition of a converged guest still says its port is not isolated,
so a tap libvirt re-attaches before the guest restarts, as after a restart of the
`default` network, would come up not isolated; O7 restarts libvirtd, not the network,
so no observation shows either way, and the saved definition keeps the isolation from
the guest's next start. The 6a operator probe runs `/usr/local/sbin/arkhai-guest-converge`
and reads its lines, `changed` and the three `filter` values among them.

**Pre-closeout triage, 69 F2 (fix, accepted by default).** The comments heading
`files/guest_converge.sh` and the convergence command in `tasks/guest-policy.yml`
explained it as for a guest "created before guests were isolated", the feature's
history. Both now state the current condition: a running guest may hold a bridge port
that is not isolated and no filter, and an isolated port can still be reached from one
that is not. Comments only; the IaC suite run for 69 F1 (section 5) passed over them.

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
  Done: `GuestIsolation` (`operator`, optional `private_destinations`) on `VmHost`. The
  route reuses `CleanupOperator`, whose docstring now names both its users, rather than
  a copy of it. "A private range" is the guest policy's four
  (`GUEST_POLICY_PRIVATE_RANGES`: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`,
  `100.64.0.0/10`), not Python's `is_private`, which admits the RFC 5737 documentation
  ranges; both destinations are required once the section is given. The example shows
  the section commented, with `127.0.0.1:16002`, an invented user and key path, and
  `10.20.0.7`/`10.20.0.8`. `test_real_provisioning_target.py` passed (unit, 118, a
  documentation-range address in place of a real public one after the fresh-context
  check): the
  section accepted and absent by default, the destinations optional, unknown, missing
  and relative-path fields named, documentation-range, link-local, malformed, IPv6 and
  CIDR destinations refused naming each, a destination on the guests' own network
  (`192.168.122.0/24`, which the policy's other rules decide) refused, equal
  destinations refused, the section refused on a bare-metal host, and the example's
  commented block valid once uncommented.
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
  Done, with one difference from the plan: the probe code is its own file,
  `guest_isolation_probe.py`, read as text and carried as `working_data_probe.py` is,
  one program for both sides selected by its `operation`; `guest_isolation.py` holds
  `probe_command`, `IsolationProbes` (the operator route, each guest's buyer session,
  and the guest probe run while the host watches for egress, in a thread of its own),
  the judgements and the stages' state. Each judgement returns the faults it finds:
  `refusal_faults` (a refusal counts only when its drop's counter rose, and an answer
  or a reset is a reach), `host_service_faults` (O3), `metadata_faults` (O4),
  `admission_faults` and `private_destination_faults` (O5, the accept's counter and
  the egress both required), `jump_faults` (O7), `guest_to_guest_faults` (O1 and O8),
  `claim_faults` and `filter_faults` (O2), `private_buyer_skip` (O6),
  `planted_faults` and `converged_faults` (O8), and `live_restoration` (O9's made;
  unproven, naming the libvirt version, only when libvirt reports the fixture's live
  removal unsupported or convergence left the filter for the next start; otherwise
  failed). Every probe operation exits 0 having printed what it saw, or prints an
  `error` the harness fails on. How each probe observes: ARP, the claim and DHCP are
  raw frames on the guest's own interface (a DHCPDISCOVER from its own MAC takes no
  lease); the gateway path is a `/32` route the probe adds and removes, with the
  guest's `accept_redirects` off meanwhile and restored after, since the host sends a
  redirect for a packet it would forward back onto the bridge before its filter drops
  it, and an accepted redirect would send the rest straight to the other guest; O2's
  effect is the host's neighbour entry for the other guest, refreshed by a host ping
  before the claim and read after it; the egress watch is an `AF_PACKET` socket on the
  device `ip route get <listed>` names, counting outgoing TCP to the listed address and
  port for 30 seconds while the guest makes five attempts, each started at least three
  seconds after the last ended, since each side starts only once its own SSH connection
  is made; the plant writes its interface files in a private temporary directory; the
  libvirtd restart waits, bounded, for `arkhai-guest-policy.service`'s next exit, and
  09k9 requires that run to have succeeded; the UFW reload is skipped when UFW is not
  enabled. Every operation's bounds keep it within the shared SSH seam's 70-second
  attempt, which re-sends a command that outlasts it. A host read that failed is a
  named fault, never read as a port left open or a filter detached.
  `test_vm_guest_isolation.py` passed (unit, but for its two tests that run pytest over
  the module in a subprocess; see 6a.3): each judgement over sample `iptables -L -v -x
  -n` (one chain read the same in both listing forms), `bridge -d link show`, `virsh`
  and convergence output, including the two named cases, a rule missing from a read, a
  counter that fell across a refill, a failed fixture step, a guest with no tap, a
  failed host read, a convergence that failed or named nothing, and a live removal
  that failed other than by libvirt's "Operation not supported" (an XML or an
  unsupported-configuration error); the probe's pure framing and parsing — its ARP
  request, claim and reply match, its echo request and reply match, its DHCPDISCOVER
  and offer match, its egress match, and its reading of `virsh domiflist`, `virsh
  version` and `systemctl show`; the command's form; every operation the stages ask
  for being one the probe offers; and the checksum against RFC 1071's example. No test
  runs the probe's sockets or commands against a real kernel or host; that is the
  real-host run's.
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
  Done: the module subclasses every stage of `test_real_provisioning_deal.py` with an
  empty body, in its order, imports its fixtures by name (deal state, keys, driver,
  recovery, execution check), and replaces only its target fixture with
  `qualification.target_host`, so a missing target is a blocked skip. Its fourteen own
  stages, `09k1` to `09k14`, sit between `09k` and `09l`; the shared stages require
  every observation, as in the qualification modules. O7 is four stages (after each of
  the restart and the reload, O3 and O4 with the jumps, then O5), so a target without
  `private_destinations` leaves O5 and O7 unproven while no other stage skips. Every
  isolation stage names the earlier results it uses with `require_state`, the first
  guest's access among them. O8 attempts
  convergence whatever the fixture managed, in a `finally`; a convergence that fails
  leaves the guest planted, and no test runs either path. The operator route has an SSH
  session of its own, pinned to the target's `ssh_host_public_key` where it states one,
  since the route reaches the host's own sshd; without it, the key the route first
  presents is trusted for the run. The module is listed with the real VM modules in
  `test_scenario_cleanup_order.py`, whose target-before-hold check now covers it. All
  of 6a.3's checks are in `tests/unit/test_vm_guest_isolation.py` rather than split
  with `test_real_vm_lane.py`, reusing `test_qualification_modules.py`'s marker and
  lane readers (the module is not a row of its `MODULES`, whose README check waits on
  closeout's promotion): the shared stages unchanged and the isolation stages inside
  the window; every own stage declaring observations, O1 to O9 each required; the
  marker registered and in no lane; the module collected under its marker, one item
  per declared stage, and run without a target, every stage skipped at setup by the
  module's target fixture, each item's skip reading `blocked: no real-provisioning
  target` in the run's JUnit report (both static configuration tests in the sense of
  `static-configuration-tests.md`: pytest, the tool that consumes the module, run over
  it in a subprocess, as the hold checks read pytest's setup plan); and the outcomes through `observation_outcomes`, each own stage run
  with its fixtures stood in for until it skips or reaches its first fixture, the shared
  stages taken as passed — which shows which stages skip on the target's account, not
  that any passes: without `guest_isolation`, only O1 and O6 have no skip and the rest
  are unproven naming it; without `private_destinations`, O5 and O7 unproven naming it;
  a relayed target, O6 unproven naming the route; under direct access, 09k8 passing for
  a private buyer address and skipping for a public one and for the host's address on
  the guests' network.

  **Outside the plan, for the owner (O6).** D21's reading of O6 — a guest-side stage
  reads its buyer session's peer address — cannot see a direct buyer's address: a VM
  create masquerades the buyer's forwarded connection to the guest (`vm-create.yml`,
  its `POSTROUTING ... --dport 22 -j MASQUERADE`), so the guest's peer is always
  `192.168.122.1`, which is private. As first written, 09k8 would have made O6 on every
  direct-access run. It now skips for any address on the guests' network, naming the
  private-source buyer route, so under direct access O6 is unproven on every run and
  never falsely made. D22 admits O6 unproven only for want of a private-source buyer
  route; whether this counts, or O6 should instead be read host-side (the DNAT
  session's original source in the host's conntrack, through the operator route), is a
  design question for the round's review and triage. It was found by the fresh-context
  check. Settled in the round's triage (50 F1): the owner chose to keep the guest-side
  read and amend D21, D22 and the `test-compatibility` delta (its scenario "A buyer's
  forwarded connection is masqueraded") so that O6 is unproven under the create's
  masquerade, naming it, rather than read host-side; 09k8's skip already names the
  masquerade, so no code changed.
- [x] 6a.4 Verification point. Unit: `e2e-tests/tests/unit/test_real_provisioning_target.py`,
  `test_vm_guest_isolation.py`, `test_real_vm_lane.py` (`make -C e2e-tests test-unit`).
  System: the module's run on a real host is section 7a's.
  End-to-end: `e2e_vm_guest_isolation`, in no lane; no lane scenario exercises it, and
  none is owed, since a lane has no real host.
  Done: `make -C e2e-tests test-unit` passed (1137, 1 skipped, as before), the new
  module's 75 tests and the cleanup-order and hold checks over it among them.
  `scripts/change-workflow run pre-commit` before the first fresh-context fixes:
  "after-functional-change …: passed, exit 0"; "pre-commit-functional …: passed, exit
  0"; "pre-commit …: failed", on two comments saying "no longer", since reworded; after
  them, all three passed.
  The fresh-context check found: O6 falsely made under direct access (the note
  above); the gateway path open to an accepted redirect; a counter that fell read as
  risen; any failed live removal read as libvirt's refusal; the egress watch racing
  the guest's attempts; fixed root-owned files in `/tmp`; a claim docstring naming a
  send it does not make; a change reference and release-relative wording in comments;
  duplicated marker and lane readers; a real public address in a target test; a test
  name claiming more than it compared; and note claims overstating the stand-in runs,
  the `finally`, and the blocked-skip check. Each is fixed above. A second fresh-context
  check, after those fixes, found: a comment naming a design decision; two inaccurate
  comments; stages using the first guest's access without naming it; probe framing and
  parsing left untested; operations that could outlast the SSH seam's attempt and run
  twice; failed host reads judged as facts; the policy unit's result unchecked after
  the restart; a probe that raised on a request with no operation; O9's refusal match
  also admitting libvirt's "unsupported configuration"; destinations admitted on the
  guests' own network; a test name covering two modules in the singular; and note
  claims overstating the destinations tested, the attempts' spacing, the stand-in
  outcomes, where the blocked skip comes from, and an import of `checked_key_reference`
  elsewhere. Each is fixed above. Declined, from both checks: moving
  `checked_key_reference` out of the bare-metal qualification's module into the shared
  helpers, a refactor of that module this section does not otherwise touch, so the VM
  scenario imports it from there; reading the two readers of `test_qualification_modules.py`
  as private, since the target tests already import that module's neighbour's
  `EXAMPLE` the same way; counting O3's host-port refusal on anything narrower than the
  chain's one drop, which the policy offers no rule for (a handoff item below); and the
  `_host_read`-style names of the stages' own state flags, the form
  `RealVmDealState` uses.
  End-to-end confirmed: `e2e_vm_guest_isolation` runs in no lane; no lane scenario
  exercises this section, and its only evidence beyond these tests is 7a's run.

**Handoff for 7a.** The run needs, beyond the real VM scenario's target: the
`guest_isolation` section with an operator route whose user may `sudo -n` Python as
root, and that reaches the host's own sshd (it is pinned to `ssh_host_public_key` when
the target states one); `private_destinations` whose `listed` address host preparation
was given in `guest_allowed_private_destinations`; UFW enabled on the host, or O7's
reload stage skips; and the guests alone on the host. What no test here shows, each a
likely first finding: that the guest image's sudo and Python run the probe (it uses
`ip -j`, raw sockets and the walrus operator, so Python 3.8 or later); that dnsmasq
answers the probe's crafted DHCPDISCOVER through `clean-traffic`; that the host's
neighbour entry for the second guest exists after the ping and is read through `ip -j
neigh`; that `iptables -L -v -x -n` on the host prints a form `parse_rules` reads (two
forms are covered); that libvirtd's restart reruns the policy's unit within the probe's
60-second bound; and that the egress watch's 30 seconds cover some of the guest's five
spaced attempts once both SSH connections are made. `ARKHAI-GUEST-IN`'s only drop is
its closing catch-all, so O3's host-port refusal may also be counted by the guests' own
broadcast or multicast in the window. The base module's `09n` asserts the heartbeat
over the whole session, so a pause longer than five seconds from the restart, the
reload or the convergence fails it as well as O8. If 09k13 fails before the plant is
recorded, 09k14 skips naming the missing prerequisite, so O9 then reads unproven for a
reason D22 does not admit; 7a's judgement reads O9's reason, not only its outcome.
Closeout's promotion (8.9) should also name `e2e_vm_guest_isolation` in
`docs/development/TESTING.md`'s account of the real-provisioning modules, beside the
validation runbook and the E2E README it already lists.

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
  Done, with one difference from the plan: `require_admin_principal` verified the
  FastAPI route's name as the operation and the request path as the resource, which no
  client signs, so a read behind it would still have refused the canonical client. Both
  reads now verify `authenticate_admin` under the client's own contract,
  `admin_list_negotiations` over the listing and its sorted, percent-encoded query
  (`limit` and `offset` defaulted, any other or repeated name refused with 400, as the
  VM and bare-metal storefronts rebuild it; the builder, `negotiation_list_resource`,
  sits beside `authenticate_admin` in `middleware/admin_auth.py`) and
  `admin_get_negotiation` over `{listing}/negotiations/{neg_id}`, and their responses
  are signed. The list also takes the buyer filter (`buyer_scheme`,
  `buyer_identifier`) the client signs, which the route ignored, refusing one without
  the other or an invalid principal with 422.
  **Outside the plan, taken from another change.** The advance had the same mismatch,
  so the canonical client could not advance an API-credit negotiation, and it called
  the negotiation service without the `actor_principal` it requires, so it answered 500
  to any caller. It now verifies `admin_advance_negotiation` over `{listing}/{neg_id}`
  and passes the authenticated administrator, as "The administrator advances a
  negotiation" needs on every storefront. `kit-owned-storefront-auth-and-persistence`
  owns moving API credits' advance, pause and resume onto the client's contracts; this
  section took the advance only, named in this change's proposal and that change's
  index row, with the third copy of the list-resource builder for it to fold in.
  Pause and resume keep `require_admin_principal`. The package moves to 0.23.0, its
  negotiation routes' signed contract having changed.
  `test_administrator_reach.py` (application integration: the routers the storefront
  mounts over the real API-credit runtime and a migrated SQLite database, the canonical
  client signing) passed: the administrator lists, filters and reads negotiations,
  verifying signed responses; an unsigned list and detail answer 401 and the same
  reads signed by the buyer's key under `buyer` are refused; an unknown or repeated
  query name answers 400 and a half or invalid buyer filter 422 (each a rejection-path
  test, status only). `run test-before` of the module at `d7e3f66c6`, as it then
  stood: the four administrator tests failed (the reads' responses unsigned, so
  `invalid_proof`; the advance refused), its eight route-sweep and classification
  tests passing there, since they hold behaviour that predates the change. (The
  unsigned-read and query-name cases were added after that run; before the change both
  reads answered unsigned and ignored unknown names.)
- [x] 7.2 Add, for each storefront — VM (`domains/vms/storefront/tests/integration/`),
  bare metal (`domains/bare_metal/storefront/tests/integration/`), API credits — a test
  that a request signed under `admin` by an active administrator principal is refused
  on every buyer, counterparty-seller and service route and admitted on its
  administrator routes, and that an administrator's advance records the round as the
  administrator's. (D15, held; "The administrator opens a negotiation as a buyer",
  "The administrator advances a negotiation".) Verify: the three tests.
  Done: `tests/integration/test_administrator_reach.py` in each storefront, at the level
  of what each runs: bare metal drives its composed app
  (`build_bare_metal_storefront_app` over a runtime with held loops, application
  integration); VM mounts its seven party-route routers behind its three
  authentication middlewares in production's order, and API credits the routers its
  app mounts behind its response signing, each over a real migrated database with
  container state set, not the composed application. Each classifies every route its
  production app mounts — party,
  administrator, public, and for bare metal its lease-ready evidence read, a record of
  its own deals its administrator may read — and fails on an unclassified route or a
  party route (or kit route) the table names but the app does not mount. Each party
  route is then called through the canonical client's generic `authenticated_request`
  (a rejection-path test, status only), signed under `admin` by the storefront's active
  administrator over the operation and resource that party's client signs, with a body
  the route reads up to its authentication (not the full body a client sends: VM
  create and arbitrate send `{}`), naming the administrator as the buyer, payer or
  claimant where the body names one; each is refused 401 or 403, no negotiation is
  opened, and the deal's thread is unchanged. The tests show the refusal, not its
  cause: each operation and resource was read against the route's own authentication
  call, but no positive control signs the same request under the party's role (it
  would run the party's action on each route), and on VM and bare metal the swept
  deal's buyer is the fixture's buyer, not the administrator, so a deal-bound route
  that checks the stored owner first (VM's settle does) refuses for ownership before
  it reaches the role. Only the API-credit sweep opens its deal with the administrator
  as buyer. The state each route reads before it authenticates
  is set up so authentication is reached: an opened API-credit thread; for bare metal,
  `test_http_settlement`'s accepted deal, a fulfillment row holding a reservation
  (service-internal setup) and a trusted site peer; for VM, `test_vm_delivery_path`'s
  settled payments deal, a trusted site peer and a site-signed lease-ended report.
  Routes swept: API credits 7 (publish-from-quota, close, negotiate new and continue,
  settle, settle status, refund); bare metal 11 (close, negotiate new and continue,
  settle, settle status, refund, the three fulfillment reads, capacity-released,
  lease-ended); VM 14 (create, close, refund, claim, arbitrate, reclaim, negotiate new
  and continue, settle, settle status, settlement refund, heartbeat, capacity-released,
  lease-ended). The introduction routes, on both: an accepted contact-exchange deal
  served over loopback (bare metal `test_http_introductions`' harness, VM
  `tests/publication_app.py` and `tests/introduction_deals.py`), the administrator's
  start refused 403 before the buyer starts and its read refused 403 after. The
  lifecycle routes both storefronts mount from `kit/deal-servicing` are held once there
  (`tests/integration/test_routes.py`, library integration, a new case: the buyer's
  peer submission and read, signed under `admin` by the active administrator, refused
  403 and nothing reaching the peer). The administrator routes are admitted through
  the canonical client on a representative set, not swept: the negotiation list and
  detail on bare metal and API credits, the detail on VM (its list is
  `test_negotiations_api.py`'s existing `TestListNegotiations`), and the advance on VM
  and API credits. Bare metal serves no advance; its force-accept route passes the
  authenticated administrator as the actor (`api.py`), and `kit/negotiation-runtime`'s
  administrative acceptance test (unit) shows the runtime records such an acceptance
  under `admin`, but no bare-metal test force-accepts through the route. Most other
  administrator routes are already exercised through the client by each storefront's
  suites. The advance cases (VM, over `test_negotiations_api`'s harness;
  API credits) show the exit round recorded with `sender_role` `admin` and the
  administrator's principal. Passed: API credits 12, bare metal 14, VM 17 (VM run
  through its Makefile's `--find-links ../../../.dist`, its lock needing the
  wheelhouse), `kit/deal-servicing`'s `test_routes.py` 4.
- [x] 7.3 Confirm the existing checks hold the authorities' form: provisioning's
  assembly refusal (`provisioning/compute/contracts/tests/unit/test_contracts.py`,
  `provisioning/compute/service/tests/unit/test_route_table_composition.py`),
  `kit/site/tests/unit/test_auth_route_parity.py`, and the credits service's
  `tests/integration/test_credits_route_parity.py`; add to the last a case that a
  credits route naming another role admits an `admin`-signed request. (D15; the
  site-capacity and api-credits requirements.) Verify: the four suites.
  Done. Confirmed, unchanged: provisioning's `test_family_routes_name_their_roles` and
  `test_every_relay_route_is_the_administrators_alone` (`test_contracts.py`, unit, 71
  passed) and `test_every_contributed_route_admits_admin` and
  `test_site_routes_admit_their_named_role_and_admin`
  (`test_route_table_composition.py`, unit, 120 passed); `kit/site`'s
  `test_admin_is_accepted_on_every_route_without_being_enumerated`
  (`test_auth_route_parity.py`, unit, 26 passed). One difference from the plan: the
  case is not in `test_credits_route_parity.py`, a static check of the contract table,
  where `permits("admin")` is true whatever the table says, so a case there could not
  fail and would restate `kit/site`'s own test. It is in the same suite's
  `test_signed_authority.py` (application integration),
  `test_the_operator_role_reaches_a_credits_route_naming_the_seller`: the canonical
  `CreditsServiceClient`, signing under `admin` as the operator, lists keys through
  `GET /api/v1/keys`, whose contract names only `seller`, and verifies the authority's
  signed response, beside the existing capacity-route case. Both modules passed (29).
- [x] 7.4 Verification point. Unit: `test_contracts.py`,
  `test_route_table_composition.py`, `test_auth_route_parity.py`. Application
  integration: the three storefronts' new tests and the API-credits storefront's
  negotiation-read tests, `test_credits_route_parity.py`.
  End-to-end: `e2e_deal` and `e2e_bare_metal_mock_deal` read negotiations and
  force-accept as the administrator through the canonical client; no lane reads the
  API-credits storefront's negotiations.
  End-to-end confirmed: `e2e_deal` lists, force-accepts and reads negotiations through
  the canonical administrator client (`roles/helpers/compute_deal_stages.py`), and
  `e2e_bare_metal_mock_deal` force-accepts and reads one; neither touches the
  API-credit storefront, whose changed routes no lane scenario calls. No owed
  evidence.
  The fresh-context check found: the first draft also moved API credits' pause and
  resume onto the client's contracts and removed `require_admin_principal`, work
  `kit-owned-storefront-auth-and-persistence` owns, unrecorded (now the advance alone,
  recorded as above); a hand-built happy-path request to the credits service (now the
  typed `CreditsServiceClient`, which also verifies the signed response the old
  assertion only saw a header of); a route-table case `permits` could never fail
  (dropped); the VM introduction check calling the callback directly from the
  integration suite (now through the routes); a third copy of the list-resource
  builder in a controller (moved beside `authenticate_admin`, and recorded for the
  owning change); sweeps not commented as rejection-path tests; the new 400 and 422
  refusals untested (now tested); notes and docstrings claiming the exact bodies a
  client signs and that an admitting route would answer (reworded; the positive
  control declined, above); "no negotiation opened" checked only on API credits (now
  on all three); the kit routes not checked as mounted (now checked); missing levels
  and the reads signed by the seller's key (fixed). Its finding on
  `tests/unit/test_admin_auth.py` lapsed with the pause and resume edits withdrawn.
  A second check, after those fixes, found: the refusals' cause claimed where VM's and
  bare metal's deal-bound routes may refuse for ownership; the VM and API-credit tests
  labelled application integration; bare metal's force-accept claimed recorded; its
  loops not held in the sweep's fixture; the index row's summary still naming the
  advance; the buyer-filter parsing, a third copy too, unrecorded; the proposal's
  Impact; the handoff's test name; the VM list read; and the test-before explanation.
  Each is fixed above. Declined: setting up the bare-metal fulfillment row through the
  API rather than inserting it (only a delivered deal reaches it, and
  `test_site_trust.py` sets up the same row the same way); patching the
  administrator-configuration readers the admin modules import, as the storefronts'
  existing suites do; and making the administrator the buyer of the VM and bare-metal
  swept deals, which would mean seeding a deal of their own (the note states the
  limit instead).

**Handoff.** The administrator-refusal sweeps are tables of each storefront's party
routes; a new route fails each module's classification test
(`test_every_mounted_route_is_classified_once`, API credits'
`test_every_mounted_route_is_a_party_administrator_or_public_route`) until it is
classified, and is swept only if it is classified as a party route. Their contracts were read from each route's
authentication call, and no positive control proves one: when a route's operation or
resource changes, its row changes with it. API credits' pause and resume still verify
the route's name and path, so the canonical client's `pause_listing` and
`resume_listing` cannot reach them; that is `kit-owned-storefront-auth-and-persistence`'s.
The VM storefront's tests run only with the wheelhouse: `uv run --find-links
../../../.dist` from its directory, as its Makefile does.

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
  Done: the first run is recorded, and it does not meet D22. Later runs are recorded
  under 7a.2.
  **Run 1** (system, external topology): `guest-isolation-20261124T102647Z`, commit
  `d90458802`, host libvirt 10.0.0. The module: 8 failed, 49 passed, 5 skipped.
  - O1 failed. The guest probe, run as the buyer as `sudo -n -- python3 -c <probe>`,
    exited 1 with "sudo: a password is required" (09k1); 09k3 skipped for want of
    09k1's state.
  - O2, O3, O4 and O5 failed, from the same cause (09k1; 09k4 skipped, and 09k5, 09k6
    and 09k7 failed).
  - O6 unproven: the target's buyers reach its guests through a relay (09k8). D22
    admits this.
  - O7 failed at each guest probe (09k9–09k12). The host steps before those probes
    passed: libvirtd restarted and came back active, the policy unit ran again and
    succeeded, and `ufw reload` exited 0.
  - O8 and O9 failed: never reached (09k1); 09k13 and 09k14 skipped.

  Passed: every shared real-VM stage, both deals and teardowns among them, with the
  heartbeat surviving the second guest's create. 09k2 passed, and so did the counter
  reads before each failed guest probe, so the operator route works. The deployment
  reports UFW still active after the run, and the guest chains as prepared.
  Judged against D22: not met. O1–O5, O7 and O8 must be made, and O9 made or unproven
  for one of its two admitted reasons; O9 failed. Every failure has one
  cause, the guest probe's sudo (7a.2); no observation reached a judgement of the
  policy itself.
  **Correction to the pre-run assessment.** Before the run, this section's session
  told the deployment that the guest probe's `sudo -n` would work because the create
  gives the buyer `NOPASSWD:ALL`. That was wrong: `vm-create.yml`'s `NOPASSWD` entry
  is cloud-init's for `root`. The tenant user is made later in the same file
  (`useradd`, a generated password by `chpasswd`, `usermod -aG sudo`), so its sudo asks
  for that password.
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
  Three runs; the third meets D22 (below).
  **Run 1's finding: the guest probe's sudo (6a).** The buyer's tenant user has sudo
  through the `sudo` group, with a password. The deal delivers that password to the
  buyer: settle status's `tenant_credentials` carry `password` (the VM storefront's
  `fulfillment_result_connection`). The fix uses that credential, inside D21's "a fixed
  Python probe run under `sudo` in a guest". It gives the scenario no reach the buyer
  lacks, and it changes neither the create nor any design decision. Rejected:
  - the create granting the buyer passwordless sudo, which changes every guest's tenant
    setup, a product change outside D7–D9;
  - running the probes without sudo, since raw ARP, ICMP and DHCP frames, the `/32`
    route and `accept_redirects` all need root in the guest.

  What changed:
  - `ssh_access.SshSession.run` takes an optional `stdin`, written to the remote
    command on every attempt and never part of the command, so no argument list or
    raised failure carries it.
  - `guest_isolation.probe_command` takes the sudo prefix: `OPERATOR_SUDO`
    (`sudo -n --`) on the host, as before; `BUYER_SUDO` (`sudo -S -p '' --`) in a
    guest; none for `peer`.
  - `IsolationProbes` takes a `tenant_password` lookup by delivered endpoint. On a
    guest's first sudo probe it reads the password, then keeps it in a field with
    `repr=False`. `guest()` sends the password and a newline as standard input.
  - `guest_isolation.deal_tenant_passwords` is the module's lookup: the first deal's
    password for its delivered endpoint, and the second deal's for the second
    endpoint. Any other endpoint fails, naming it, before anything runs.
  - `RealVmComputeDealDriver.tenant_password` reads the password from the deal's
    settle status, and a failure names only the credential's fields.

  The password is read when a probe first needs it, not in a stage, so every
  isolation stage still names its prerequisites with `require_state` as 6a.3 says:
  the delivered endpoints, which settle status has delivered by then.

  Tests (unit), all passing (252 in the three files):
  - `test_ssh_access.py`: standard input reaches the command on a retried attempt and
    is in no argument; it is in no failure the command raises.
  - `test_vm_guest_isolation.py`:
    - the guest command's form, with the password on standard input, read once per
      guest and not in the command or the probes' `repr`;
    - a probe without sudo reads and sends no password;
    - through the real driver over a settle-status double keyed by escrow, each
      endpoint gets its own deal's password;
    - an endpoint no deal delivered fails naming it, and nothing runs.
  - `test_real_vm_lane.py`: the password is read from the deal's settle status, and
    the second deal's from the second escrow; a missing or empty one fails without
    naming a value.

  `run test-before` at `d90458802`, of the files as first written: each new test
  failed there, but only because the API it calls does not exist (`TypeError` or
  `AttributeError`). Every existing test passed. No test shows the guest's real sudo
  accepting the password; that is the next run's. Run 2, at the commit that carries
  this note, is owed by the deployment.

  The fresh-context check found, all fixed above:
  - stages depending on 09k1 having read the passwords without naming it (the
    passwords were first read in 09k1);
  - doubles set on the driver after it was built, rather than passed in;
  - an SSH test's name claiming every attempt;
  - a stand-in driver where the real one could be used;
  - run 1's judgement omitting O9;
  - 7a.3 naming 7a.1 as the run that must meet D22.

  It also found that design.md's Context ("What the real-host proof can reach") says
  the tenant user has passwordless sudo, which run 1 shows is false. The fix is a
  mechanism inside D21's "run under `sudo` in a guest" and changes no decision, so the
  change has not returned to design. Correcting that Context sentence is left to the
  round's triage, with the owner's word on whether it needs more than a correction.

  **Run 2** (system, external topology): `guest-isolation-20261124T121352Z`, commit
  `201c4c0bd`, the host re-prepared from that commit's host kit, libvirt 10.0.0. The
  module: 3 failed, 58 passed, 1 skipped.
  - Made: O1, O2, O3, O4, O8 and O9. O9's live restoration was observed, so live
    filter convergence now has real-host evidence.
  - O5 failed at 09k7 on one fault only: no packet to the listed destination on port
    80 was seen leaving the host on its routed interface. Every other O5 check held:
    the chain admits the listed destination and refuses the other, the refused
    destination's drop counter rose, and the listed accept's counter rose.
  - O6 unproven: the target's buyers reach its guests through a relay (09k8). D22
    admits this.
  - O7 failed at 09k10 and 09k12, the private-destination stages after the restart
    and the reload, on the same egress fault. 09k9 and 09k11 passed: O3, O4 and both
    jumps held after each.

  Judged against D22: not met, on O5 and O7 alone, from one probe defect. Section 5's
  handoff items, so far:
  - the `--xml` filter parameters are shown by O2 being made;
  - the unit's order after libvirtd and `ufw reload` running `after.init` are shown
    by 09k9 and 09k11, both jumps first after the restart and after the reload;
  - real `iptables-restore --noflush` flushing and refilling the chain and deleting
    jumps by rule is not shown. `jump_faults` reads only each built-in chain's first
    rule, so a leftover duplicate jump lower down would pass. It stays open until O7
    is made, as this task says, or becomes a finding here.
  **Run 2's finding: the egress watch cannot see a sent frame (6a).** The probe's
  `egress` opened its packet socket for IPv4 alone (`ETH_P_IP`). Linux hands
  transmitted frames only to packet sockets bound to every protocol (`ETH_P_ALL`, the
  `ptype_all` taps); a protocol-specific one sees only received frames. The deployment
  confirmed this on the host. During one TCP connect from the host to the listed
  destination, an `ETH_P_IP` socket on the routed interface saw no outgoing SYN, while
  an `ETH_P_ALL` socket saw five: the SYN and its retransmits. It also confirmed the
  forward path is as designed:
  - FORWARD jumps to the guest chain first;
  - the listed accept counted 15 packets, which the deployment read as five attempts
    in each of three stages;
  - no other forward-hook table drops;
  - forwarding is on, and the route goes via a gateway on that interface.

  Fixed: the watch is `watch_egress`. It reads from `packet_socket()`, the probe's
  module-level factory, which opens `EGRESS_SOCKET`, a cooked `AF_PACKET` socket bound
  to `ETH_P_ALL`. `is_outgoing_tcp_to` now also takes the frame's link-layer protocol
  from its socket address and requires IPv4. With that check, and the rest of the
  match (outgoing, TCP, destination and port), the count stays as narrow as before
  even though the socket now reads every frame on the device.
  Tests in `test_vm_guest_isolation.py`, all 82 passing (unit, but for the module's
  two pytest-subprocess static configuration tests):
  - over a socket double put in place of `packet_socket`, the watch binds the device
    and counts only sent IPv4 frames to the destination: not a received copy, a
    frame whose link-layer protocol is ARP, or one to another destination. This
    also pins which fields of the socket address it reads;
  - `EGRESS_SOCKET` binds every protocol. That is the choice the fix rests on, not
    the kernel's behaviour;
  - the match refuses another port, another destination, UDP, a frame that was not
    sent, and a non-IPv4 link-layer protocol.

  `run test-before --at 201c4c0bd`, of the tests as first written: both failed
  there, but only on the API they call (`TypeError`, `AttributeError`); the other 79
  passed. No test shows the kernel handing the socket a sent frame. That is the
  deployment's host observation above, for run 3 to confirm. Run 3, at the commit
  that carries this note, is owed by the deployment.

  The fresh-context check of this fix found, fixed above:
  - this note claiming all of section 5's handoff items discharged;
  - an IPv4 version check guarding nothing the kernel can deliver, and a test that
    could not tell it apart;
  - the socket passed as a keyword parameter, where a command module's seam is a
    module-level factory;
  - a test named for a rationale it cannot show, and claims credited to the wrong
    test;
  - `egress`'s docstring saying "whether" for a count.

  Declined: replacing the hand-written socket double with `MagicMock`, since the
  file's other doubles are hand-written. Also declined: dropping the socket-address
  test as unit-testing the last code before an external boundary, since it is the
  only test that pins the regression and the fields the watch reads. It also noted
  that on a busy uplink the socket's buffer could overflow during the 30 seconds and
  drop the guest's SYN. That would be a false failure, never a false pass, so it is
  left for a run to show.

  **Run 3** (system, external topology): `guest-isolation-20261124T140115Z`, commit
  `8e38ee217`, the host re-prepared from that commit's host kit, libvirt 10.0.0. The
  module: 61 passed, 1 skipped, 0 failed (16m10s). Runs 1 and 2 are superseded.
  - O1 made: ARP, ICMP and TCP from one guest to the other, directly and through the
    gateway, refused.
  - O2 made: the address claim dropped while the other buyer still reaches its guest,
    and the filter's parameters present in each guest's live definition.
  - O3 made: DHCP and DNS pass, and the host port got no answer while
    `ARKHAI-GUEST-IN`'s closing drop counted packets. That drop is a catch-all, so
    the guests' own broadcast or multicast may also count there (the 6a handoff).
  - O4 made: the metadata address is refused by its drop, whose counter rose.
  - O5 made: the refused destination is refused by its drop, whose counter rose. The
    listed one is admitted by its accept, whose counter rose, and the guest's packets
    to it were seen leaving on the routed interface. The deployment reports 15 seen
    in each of the three stages and attributes them to five attempts and their
    retransmits; the scenario reports only the count.
  - O6 unproven: the target's buyers reach its guests through a relay (09k8), the
    run's only skip.
  - O7 made: O3–O5 held, with both jumps first, after a libvirtd restart and after a
    UFW reload.
  - O8 made: each fixture step exited 0, and the host read the guest planted (port
    not isolated, saved definition stripped). After convergence, which reported the
    port isolated, the filter live and the saved definition carrying both, the host
    read the port isolated from `bridge` and the saved definition carrying both. The
    heartbeat's longest gap and the guest-to-guest refusals held.
  - O9 made: the filter was bound live again on libvirt 10.0.0.

  Judged against D22: met. O1–O5, O7 and O8 are made, O6 is unproven only for want of
  a private-source buyer route, and O9 is made.
  Section 5's handoff items are discharged now that O2 and O7 are made, as this task
  reads them. One limit stays, on real `iptables-restore --noflush`: the run shows
  each jump first in its built-in chain and the policy's decisions holding after the
  restart and the reload, not that nothing was left behind.
  - `jump_faults` reads only the first rule, so a leftover duplicate jump lower down
    would pass.
  - `deciding_rule` takes the first matching rule, so an `ARKHAI-GUEST-FWD` refilled
    without being flushed, its rules doubled, would pass too.

  Either leftover would change no decision: a packet would meet the same rules again
  and be decided the same way. So this is recorded here, not fixed.

  Done. Each run's finding was diagnosed from its summary and fixed in the section
  that owns it, 6a both times, with a focused unit test (runs 1 and 2 above). The
  third run meets D22. No finding needed a decision D7, D8, D9 or D22 does not make.
- [x] 7a.3 Verification point. System: the recorded `e2e_vm_guest_isolation` run
  meeting D22 (7a.1, or a later run 7a.2 records). Unit, library integration: the suites of whatever 7a.2 changed,
  as their sections name them.
  End-to-end: `e2e_vm_guest_isolation` on the deployment's real host, in no lane; no
  lane scenario exercises it.
  Done. System: run 3, `guest-isolation-20261124T140115Z` at `8e38ee217`, meets D22
  (7a.2). 7a.2 changed only e2e harness code: section 6a's scenario, its probe and
  its driver, and the shared SSH helper (`ssh_access.py`). Its suites pass at
  `8e38ee217`:
  - `test_vm_guest_isolation.py`, 82: unit, but for the module's two
    pytest-subprocess static configuration tests;
  - `test_ssh_access.py` and `test_real_vm_lane.py`, unit;
  - the whole e2e unit suite among `make test`, which `run pre-commit`'s
    pre-commit-functional ran: "local evidence for the tree c0b38146f6aa …: PASSED",
    "pre-commit-functional at 201c4c0bd…: passed, exit 0". That was the tree
    committed as `8e38ee217`.

  7a.2 changed nothing under sections 5 or 6, so neither section's suites are owed
  again. End-to-end confirmed: `e2e_vm_guest_isolation` ran on the deployment's real
  host, in no lane; no lane scenario exercises section 7a. No owed evidence.

**Handoff.** Section 7a is complete. The real-host evidence for D7, D8 and D9 is run 3
(7a.2). Closeout's promotion (8.9) should name `e2e_vm_guest_isolation` in `TESTING.md`
(the 6a handoff). It should also carry what a target needs for this module to
`VALIDATION_RUNBOOK.md` "24. Describe The Target" and `e2e-tests/README.md`, where
8.9 already places the section:
- an operator route whose user may `sudo -n` Python as root, reaching the KVM host's
  own sshd (the runs used one);
- `private_destinations` whose listed address host preparation was given in
  `guest_allowed_private_destinations` (the runs used one);
- a listed address the host sends to rather than holding for ARP: through a gateway,
  or answered on its link (the probe's egress watch, not shown by a run);
- UFW active, or O7's reload stage skips;
- the run's guests alone on the host (D21's precondition).

Guest probes get root with the tenant password each deal delivers, so no target
needs to change the guest's sudo.

**Round 3 triage (7a handoff, edit).** design.md's Context ("What the real-host proof
can reach") said the tenant user has passwordless sudo, which run 1 showed is false. It
now says the tenant user has sudo through the `sudo` group with a generated password
the deal delivers to the buyer. The owner agreed a correction is enough: no decision
rests on the sentence.

## 8. Closeout

- [ ] 8.1 **Comment hygiene.** Run `make check-comment-hygiene`; confirm no comment the
  change added names the change, a section or a task, or describes anything but the
  current system. Anything found returns the change to implementation.
- [ ] 8.2 **Import placement.** Check the imports the change added in
  `provisioning/compute/`, `domains/apicredits/storefront/`, the storefront tests and
  `e2e-tests/` against
  `docs/guidance/engineering/dependencies-python.md#imports-go-at-module-level`; one
  that should move returns the change to implementation.
- [ ] 8.3 **Documentation compliance.** Re-check D3–D10, D14–D16 and D18–D23 against the
  placement tables (`docs/guidance/workflow/openspec-documentation.md`,
  `openspec/README.md#documentation-placement`) and confirm every permanent document
  written describes the current state.
- [ ] 8.4 **Narrative compression.** Shorten completed-task notes to final behaviour,
  the real-host proof's per-observation result (7a.1), deferred work and destinations, moving any
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
  scenarios named as run in no lane, and `e2e_vm_guest_isolation`'s real-host
  per-observation result (7a.1), with O6 and O9 named where they are unproven and why
  (D22).
- [ ] 8.9 **Promotion.** Write, and complete the design-promotion record in
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

- [ ] 8.10 **Guidance placement.** Read the new engineering file, the package-versions
  section and the release handbook's section against the layer test; run
  `make check-guidance`.
- [ ] 8.11 **Documentation citations.** Run
  `make check-doc-citations CHANGE=harden-provisioning-trust-boundaries` and resolve
  every match; then `scripts/change-workflow openspec validate harden-provisioning-trust-boundaries --strict`.
- [ ] 8.12 **Archival.** Run
  `scripts/change-workflow openspec archive harden-provisioning-trust-boundaries -y`,
  merging the `physical-provisioning`, `site-capacity`, `api-credits`,
  `storefront-publication` and `test-compatibility` deltas.
