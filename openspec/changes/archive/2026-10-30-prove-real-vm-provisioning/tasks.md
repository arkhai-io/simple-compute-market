# Tasks

Planned against the design settled in `design.md` and advanced by
`reviews/10-design.triage.md`. Every task answers to a decision (D1–D11, with D2a,
D4a, D4b, and D9d), a delta
requirement under `specs/`, or a repository obligation cited at the task:
`openspec/README.md#plan-closeout-requirements`, the task rules in
`openspec/config.yaml`, `docs/development/TESTING.md`'s level definitions, and
`AGENTS.md`'s package discipline.

Test levels follow `docs/development/TESTING.md`: unit (no stack); system (the
`e2e-tests` markers, run by the pipeline lanes). The IaC tests under
`domains/vms/provisioning/iac/tests/` are unit tests of the playbooks' structure and of
their shell logic against a fake filesystem.

Order: sections 1–5 deliver everything the mock lanes and unit tests can prove; sections
6–8 deliver the real lane, its documentation, and its live verification; section 7A,
added after 8.1's run, fixes the SSH restart handler that run found (D9d) and 8.4
re-runs host preparation to show it; section 7B, added after 8.2's first run, fixes
the direct-access port (D4b); section 7C, added after 8.2's and 8.3's runs at 7B's
revision, adopts a rerun's listing and corrects 11b's claim (D2a); section 7D, added
after 8.3's run at 7C's revision, makes 08b wait for this deal's own dispatch and
recovery find it (D4); section 9 is the
closeout. Section 6 needs sections 1, 2, 4, and 5; 8.4 needs section 7A; 8.2 and 8.3
need sections 7B, 7C, and 7D. Section 8 is evidence the owner
supplies from a run against a real host (`design.md`, "Implementation cadence"); until it
is supplied the change is `blocked in implementation`. No dependency gates
implementation.

Permanent documentation — `TESTING.md`, the validation runbook, the IaC README, and the
roadmap — is written at closeout (9.9). Sections change code, tests, and the e2e
package's own README and example profile.

Public-repository discipline (`AGENTS.md`) applies to every task note and to the
section 8 evidence: no address, project, cluster, namespace, host name, or private
path.

Completed-task notes were compressed at closeout (9.4) to final behaviour, evidence,
deferrals, and destinations; what they carried beyond that — trade-offs, things left as
found, and declined suggestions — is in `design.md`.

## 1. Shared deal stages split at their mock gates

Delivers the split of the canonical deal's gated stages and the `MockGates` driver part
(D4a; delta `test-compatibility` "The canonical compute deal's shared stages are
defined once", scenarios "A mock lane holds a job", "The preflight before settlement
fails", and "A real lane runs the canonical deal").

Files: `e2e-tests/tests/e2e/roles/helpers/compute_deal_stages.py`;
`e2e-tests/tests/e2e/roles/scenarios/vms/compute_deal_driver.py`,
`…/vms/test_full_deal.py`; `…/bare_metal/compute_deal_driver.py`,
`…/bare_metal/test_bare_metal_mock_deal.py`; `e2e-tests/tests/unit/test_compute_deal_stages.py`
and `e2e-tests/tests/unit/stage_sources.py`.

- [x] 1.1 Add a `MockGates` protocol beside `ComputeDealDriver` and move to it
      `create_rule_id`, `teardown_rule_id`, `arm_create_gate`, `release_create_gate`,
      `evaluate_create_job`, `arm_teardown_gate`, and `release_teardown_gate`. Both mock
      drivers (VM and bare metal) implement both protocols, unchanged in behaviour. The
      module docstring and `ComputeDealDriver`'s say a shared stage never uses
      `MockGates` and why (D4a: a gate hook answered by a no-op would make a shared
      assertion vacuous under one driver). (D4a)
      Done; a marker base, `MockLaneStage`, identifies the mock-lane stages in source.
- [x] 1.2 Split each gated stage at its gate, as D4a names them: 07 into the shared
      on-chain escrow stage and a mock-only create-gate arm; 09a into a mock-only create
      release-and-drain and the shared advance to `active`; 10a into a mock-only
      teardown-gate arm and the shared expiry; 11b into a mock-only teardown
      release-and-drain and the shared completion and release. 08c becomes mock-only and
      `Stage00e_ProvisioningMockMode` stays mock-only. Mock-only stages take the driver
      as `MockGates`; shared stages take it as `ComputeDealDriver`. Each new class name
      says what the stage does. (D4a)
      Shared: `Stage07_OnChainEscrow`, `Stage09a_FulfillmentConvergesToActive`,
      `Stage10a_LeaseExpirySetup`, `Stage11b_TeardownCompletion`. Mock-lane:
      `Stage07a_ArmCreateGate`, `Stage08b2_ReleaseCreateGateAndDrain`,
      `Stage09c2_ArmTeardownGate`, `Stage11a2_ReleaseTeardownGateAndDrain`, 00e, 08c.
      Beyond the plan: 00e's output became the lane-neutral
      `_provisioning_execution_confirmed` (the real lane's execution check writes it);
      readiness fields `_create_job_completed` and `_teardown_job_completed` make a
      failed release skip its dependent.
- [x] 1.3 Replace 08b's prerequisite `_provision_job_evaluated` with a readiness field
      `_settle_preflight_passed` on `ComputeDealState`; 08c writes it once its
      assertions pass and no longer writes `_provision_job_evaluated` (remove the field
      if nothing else reads it). 08b's assertion message says the fulfillment is
      dispatched and not yet converged. 08b and 11a stay shared, unchanged otherwise.
      (D4a; scenario "The preflight before settlement fails")
      `_provision_job_evaluated` removed; nothing else read it.
- [x] 1.4 List the new stages in both mock lane modules in the mock-lane order D4a
      gives, so each lane runs the same assertions in the same order as before.
      (D4a; scenario "A mock lane holds a job")
      A mock lane declares every stage in definition order. One step moved: 11b's
      stage-event mark is taken after teardown's release and drain, sound because
      convergence and the watchdog are held. Order and assertions checked by hand
      against the planning commit.
- [x] 1.5 Unit (`test_compute_deal_stages.py`, `stage_sources.py`):
      `test_every_compute_state_field_is_consumed_after_it_is_produced` passes with the
      new field; a new test fails if any shared stage's source references a `MockGates`
      member or the mock test client; a new test that 08b skips when
      `_settle_preflight_passed` is unset; the existing stage-list tests are updated for
      the new classes in both lanes. (D4a; scenarios "A mock lane holds a job", "A real
      lane runs the canonical deal")
      Unit: `test_no_shared_stage_touches_a_mock_gate` (a gate reached through a helper
      or another attribute is beyond it), `test_each_stage_takes_the_driver_part_its_kind_may_use`,
      `test_the_shared_driver_part_names_no_mock_gate`,
      `test_settlement_skips_until_the_preflight_before_it_passes`; the gate check
      confirmed to fail on a planted gate call. `stage_sources.py` unchanged.
- [x] 1.6 Verification: `make -C e2e-tests test-unit`; `make test`.
      End-to-end: `e2e_deal` (VM lane) and `e2e_bare_metal_mock_deal` (bare-metal
      lane) run the reordered stages; their outcome must be unchanged, so the
      validation pipeline's result for both lanes is this section's evidence.
      Unit 176 passed; `make test` passed. End-to-end evidence: the pipeline's VM and
      bare-metal lanes (9.8). The diagrams and TESTING.md's gate wording were owed to
      9.9.

## 2. GPU-less shapes in the VM helpers

Delivers capacity sources and provision terms that carry GPU fields only when the shape
does (D6; delta requirement "A real-provisioning VM scenario proves delivery on a real
host", "MUST be able to deal on a shape that declares no GPUs").

Files: `e2e-tests/tests/e2e/roles/scenarios/vms/conftest.py`,
`…/vms/compute_deal_driver.py`, `…/vms/host_registry.py`; a new unit test under
`e2e-tests/tests/unit/`.

- [x] 2.1 `capacity_source_for` emits the GPU family only when the resource carries a
      positive `gpu_count` and a `gpu_model`, and otherwise emits `cpu.count`,
      `memory.gib`, and `storage.gib` from `vcpu_count`, `ram_gb`, and `disk_gb`. If the
      function cannot be imported by a unit test from the scenarios' `conftest.py`,
      move it into `host_registry.py` unchanged in behaviour and import it back.
      (D1, D6)
      The predicate is `resource_gpus` in `host_registry.py`; `capacity_source_for`
      stays in the VM `conftest.py`. A resource naming only one of `gpu_count` and
      `gpu_model` now yields a GPU-less shape; no caller passes one.
- [x] 2.2 The VM driver's provision terms and required attributes name GPU fields only
      when its shape carries them; the mock lanes keep their GPU shapes, so their terms
      are unchanged. (D6)
      Provision terms named no GPU field already; `claim_attributes`
      (`host_registry.py`) requires `gpu_count` only of a GPU shape, so the mock
      driver's claim is unchanged.
- [x] 2.3 Unit: a GPU-less resource (`vcpu_count: 7, ram_gb: 28, disk_gb: 160`) yields
      a shape with no `gpu` family and those three dimensions; a GPU resource yields the
      same shape as before; a resource with `gpu_count: 0` yields no `gpu` family. (D6)
      Unit, `e2e-tests/tests/unit/test_vm_shapes.py`, as listed plus the predicate and
      `claim_attributes`.
- [x] 2.4 Verification: `make -C e2e-tests test-unit`; `make test`.
      End-to-end: `e2e_deal`, `e2e_listing_shapes` — unchanged in outcome.
      Unit 182 passed; `make test` and `make check-packaging` passed. Every VM scenario
      calling `capacity_source_for` passes GPU resources, so its shapes are unchanged;
      the pipeline's VM lane is the evidence (9.8).

## 3. Host preparation and VM creation fail closed

Delivers the virtualization requirement, the presence-gated passthrough configuration,
the override, and the scratch default (D9; delta `physical-provisioning` "Passthrough
binding cannot strand a host", "VM hosts must provide hardware virtualization", "Host
preparation defaults to the image VM creation uses").

Files: `domains/vms/provisioning/iac/ansible/playbooks/host-kit/vm-setup.yaml`;
`…/roles/vm-setup/tasks/{main,kvm-setup}.yml` and a new task file for GPU presence;
`…/roles/vm-management/tasks/vm-create.yml` and `gpu-virt-install-retry.yml`; tests in
`domains/vms/provisioning/iac/tests/` (`test_ansible_structure.py`,
`test_vm_management_contracts.py`, and a new presence test using `shell_harness.py`).

- [x] 3.1 `vm-setup.yaml` defaults `vm_image_type` to `scratch`; `golden` stays
      selectable by `image_setup_type`. `single-tenant/vm-operations.yaml` is not
      changed: the service always passes the image setup type. (D9c; scenarios "A host
      is prepared without options", "The operator names the golden image")
      Every golden step was already conditioned on `vm_image_type == "golden"`.
- [x] 3.2 Validate `gpu_passthrough` (`auto`, `enabled`, `disabled`; default `auto`) as
      the role's first task, failing with the value named before anything on the host
      changes. (D9b; scenario "The override names an unknown value")
      An `assert` tagged `always`; the default is in `defaults/main.yml`.
- [x] 3.3 Fail before any host mutation when `/proc/cpuinfo` shows neither `vmx` nor
      `svm`, as a read-only precondition at the start of the role, replacing
      `kvm-setup.yml`'s `ignore_errors` check; after the KVM modules load in
      `kvm-setup.yml`, fail when `/dev/kvm` is absent. Both messages say hardware
      virtualization is unavailable and why. (D9a; scenario "A host without
      virtualization extensions")
      The probe and its refusal are `main.yml`'s second and third tasks, tagged
      `always`.
- [x] 3.4 Add a GPU-presence task file that reads PCI class and vendor from sysfs,
      needing no IOMMU, and sets presence when a display or 3D controller (`0300`,
      `0302`) has vendor `10de` or `1002`. In `main.yml`, include `gpu-passthrough.yml`,
      `rescue-boot-entry.yml`, and `gpu-detection-service.yml` when `gpu_passthrough` is
      `enabled`, or is `auto` with presence; skip them when `disabled`, or `auto`
      without presence. Binding is unchanged: it still follows the audit after the
      reboot. Comment why presence is vendor-keyed (a BMC display controller and a KVM
      instance's emulated VGA are class `0300`) and why the audit cannot gate boot
      configuration (it reports nothing with the IOMMU off). (D9b; scenarios "A host
      has no GPU", "A GPU host's IOMMU starts disabled", "The operator forces
      passthrough configuration")
      `tasks/gpu-presence.yml` sets `gpu_present` and `gpu_passthrough_configured`.
      Correction to "binding is unchanged": the `gpu-bind.yml` include carries the same
      condition, since binding writes into a directory only the configuration creates;
      recorded in D9b, the delta, and the proposal. Skipping configuration does not undo
      an earlier one.
- [x] 3.5 Pass `--virt-type kvm` on every `virt-install` invocation in the
      `vm-management` role, the GPU retry path included, and fail a create before
      `virt-install` when `/dev/kvm` is absent, naming KVM as unavailable. (D9a;
      scenario "KVM disappears after preparation")
      Nine invocations across `vm-create.yml` and the three `gpu-virt-install-*.yml`;
      the KVM check is `vm-create.yml`'s first two tasks, on the target host.
- [x] 3.6 Unit: structural tests that `vm-setup.yaml`'s default is `scratch`; that the
      override check and the virtualization precondition precede every task that
      changes the host; that the three passthrough includes carry the D9b condition;
      that every `virt-install` command in the role names `--virt-type kvm`; and that
      the create checks `/dev/kvm` before `virt-install`. Presence, through
      `shell_harness.py` over a fake sysfs: an NVIDIA `0300` and an AMD `0302` device are
      presence; an ASPEED BMC (`1a03`, `0300`), a QEMU emulated VGA (`1234`, `0300`),
      and a host with no display device are not. (D9)
      Unit: `test_ansible_structure.py` (`TestHostPreparationFailsClosed`, the four
      gated includes, the decision expression read as text since the suite runs without
      Ansible or Jinja); `test_vm_management_contracts.py`
      (`VmCreationRequestsKvmTests`); `test_gpu_presence.py` (the five cases plus four).
- [x] 3.7 Verification: `make -C domains/vms/provisioning/iac validate` (inventory,
      playbook syntax, tests); `make test`.
      End-to-end: none in the pipeline — the mock profile runs no playbook. Section 8's
      live run exercises 3.1, 3.3, 3.4, and 3.5 on a GPU-less host.
      `make test-provisioning-iac` 82 passed; `make test` and `make check-packaging`
      passed. Not run: `validate`'s inventory and syntax-check parts (no Ansible in the
      environment; no CI workflow runs them). Live evidence: 8.1 and 8.4.

## 4. The real-provisioning target description

Delivers the typed, versioned target section, its example, and its ignore rule (D1;
delta requirement "A real-provisioning target is a typed, versioned settings
section").

Files: a new `e2e-tests/src/e2e_harness/real_vm_target.py`;
the example profile `config-real-vm-target.yml.example` in `e2e-tests/config/`; `e2e-tests/.gitignore`;
`e2e-tests/tests/unit/test_real_vm_target.py`; `e2e-tests/pyproject.toml` when the
model needs a dependency not yet declared.

- [x] 4.1 A typed model of `REAL_VM_TARGET` version 1: `version` exactly 1; one `host`
      mapping (`host_id`, `ssh_host`, `ssh_user`, `ssh_port`, `ssh_key_path`,
      `public_host`, `capacity` with `vcpu_count`, `ram_gb`, `disk_gb` each a positive
      integer, all required); `access.mode` admitting only `direct`; unknown fields
      refused at every level. A loader reads the section from the e2e settings and
      returns either the validated target or an explicit "not configured" result naming
      the `real-vm-target` profile and `config-real-vm-target.yml`; a present but
      invalid section raises an error naming the field. The model's field descriptions
      are the format's documentation. Declare any distribution the module imports that
      `e2e-tests/pyproject.toml` does not already declare. (D1)
      `RealVmTarget` (frozen, `extra="forbid"`, strict counts);
      `load_real_vm_target(settings)` returns the target or `TargetNotConfigured`, and
      raises `TargetInvalid` naming `REAL_VM_TARGET.<path>`; the version is checked
      first. An empty section is invalid, not unconfigured. `pydantic>=2.0` declared and
      relocked. The root `.dockerignore` excludes the rendered file.
- [x] 4.2 Commit `config-real-vm-target.yml.example` in the D1 shape with RFC 5737
      addresses and fictitious names, and a header saying it is an example, that an
      environment owner renders the real file, and that the real file is never
      committed. (D1)
- [x] 4.3 Ignore `config-real-vm-target.yml` in `e2e-tests/.gitignore`. (D1)
- [x] 4.4 Unit (`test_real_vm_target.py`): the example loads and validates; a missing
      field, a misspelled field, and an unknown nested field each fail naming the field;
      version 2 is refused; `access.mode: relay` is refused; a zero or negative
      capacity is refused; an absent section yields "not configured" naming the profile
      and file. (scenarios "A field is misspelled", "A newer target reaches an older
      reader", "Relay access is requested under version 1")
      Unit, 31 cases: the example through the harness's bootstrap beside the `local`
      profile, plus the listed refusals and further malformed versions and values.
- [x] 4.5 Verification: `make -C e2e-tests test-unit`; `git check-ignore -v` on the
      real profile file's path in the e2e config directory names the rule; `make test`; `make
      check-packaging` when 4.1 declared a dependency.
      End-to-end: none until section 6.
      Unit 213 passed; the ignore rule is `e2e-tests/.gitignore:18`; `make lock`, `make
      check-packaging`, and `make test` passed.

## 5. SSH access helper

Delivers the domain-neutral helper the real lane proves access with (D7).

Files: a new `e2e-tests/tests/e2e/roles/helpers/ssh_access.py`; a new
`e2e-tests/tests/unit/test_ssh_access.py`; `e2e-tests/pyproject.toml` (declare
`cryptography` if it is not declared).

- [x] 5.1 Generate an ed25519 key pair per run with `cryptography` into an owner-only
      temporary directory, returning the private key's path and the OpenSSH public
      line; the directory is removed when the run ends. (D7, "Keys")
      `ssh_session()` yields an `SshSession` over a `0700` directory; `new_key(name)`
      writes the key `0600`. `cryptography>=42.0` declared and relocked.
- [x] 5.2 Run a command over SSH with the system `ssh`: `BatchMode=yes`,
      `ConnectTimeout`, `IdentitiesOnly=yes` (so only the given key is offered, which
      the refused-key check depends on), `StrictHostKeyChecking=accept-new`, and a
      run-scoped `UserKnownHostsFile`; retry connection failures within a named bound to
      absorb the guest's cloud-init reboot; log the host-key fingerprint on first
      contact; fail when a later connection presents another host key. (D7, "Client",
      "Host key")
      `SshSession.run`, also isolated from the operator's configuration (`-F /dev/null`,
      no agent, no global known hosts). Any `ssh` failure is retried within
      `CONNECT_RETRY_SECONDS` (600); a changed host key raises `HostKeyChanged` at once;
      a command failing once connected is not retried.
- [x] 5.3 Assert a connection is refused, or times out, within a named bound — used both
      for the unrelated key and for access after teardown. (D7)
      As corrected by 5.8: `assert_refused(endpoint, key)` (`REFUSAL_BOUND_SECONDS`
      120) counts only `ssh`'s own failure as refused. For the unrelated key,
      `assert_key_refused` requires the host to answer `Permission denied`.
- [x] 5.4 Probes returning the remote user (`id -un`), vCPU count (`nproc`), memory in
      GiB from `MemTotal`, and the root disk's size in GiB, with the memory tolerance a
      named constant that starts strict. (D7, "What a connection proves")
      `SshSession.probe` returns a `GuestShape`; the root disk is the whole device
      holding `/`. `MEMORY_SHORTFALL_TOLERANCE = 0.05`, nothing above.
- [x] 5.5 Unit (`test_ssh_access.py`) with a fake `ssh` on `PATH`: the argv carries every
      option in 5.2 and only the given identity; connection failures are retried until
      success and fail at the bound; a changed host key fails; refusal and timeout are
      reported as refused; probe output is parsed, including `MemTotal` in kB; the key
      directory is owner-only and gone afterwards. (D7)
      Unit, against a fake `ssh` executable given by path and a fake clock; "timeout
      reported as refused" corrected by 5.8. The probe command first ran live in 8.2.
- [x] 5.6 Verification: `make -C e2e-tests test-unit`; `make test`; `make
      check-packaging` when 5.x declared a dependency.
      End-to-end: none until section 6.
      Unit 238 passed; `make lock`, `make check-packaging`, and `make test` passed.
- [x] 5.7 Round-1 triage fix (25 F1): `assert_refused` must see the refusal by the time
      its bound closes, and 5.3's "returns the refusal's reason on the first `ssh`
      failure" overshot it by up to one attempt plus a retry interval.
      `assert_refused` starts no attempt after the bound, caps each attempt at the time
      left, and fails a refusal returned after the bound; every retry sleep stops at
      its window. Unit 29 cases; unit 243 passed; `make test`, `make check-packaging`,
      and `make check-comment-hygiene` passed.
- [x] 5.8 Round triage fix (53 F1): `assert_refused` counted an attempt that ran its
      full time out as refused. `ssh` gives up within its `ConnectTimeout` when nothing
      answers, so such an attempt shows something answered and stayed connected, and
      after teardown that is what 11d must catch. 5.3's "refused, or times out", 5.5's
      "counted as refused by `assert_refused`", 5.7's "a full-length attempt's timeout
      still counts as refused", and D7's "refused or timed out" now read as `ssh`'s own
      failure: refused, or its `ConnectTimeout` expiring (exit 255).
      An unfinished attempt is retried within the bound and fails there as "not shown
      to refuse" or "still accepted". The live runs' 11d reasons were `ssh`'s own
      `Connection timed out`, so they meet the rule unchanged. Unit 32 cases; unit 315
      passed; `make test`, `make check-packaging`, and `make check-change` passed.

## 6. The real-provisioning lane

Delivers the real VM driver and the `e2e_vm_real_provisioning` scenario (D2, D3, D4,
D4a's real stages, D5, D7, D8; delta requirement "A real-provisioning VM scenario
proves delivery on a real host" and its scenarios).

Files: `e2e-tests/tests/e2e/roles/scenarios/vms/host_registry.py`; new
`…/vms/real_compute_deal_driver.py` and `…/vms/test_real_provisioning_deal.py`;
`e2e-tests/pyproject.toml` (marker); unit tests under `e2e-tests/tests/unit/`.

- [x] 6.1 `register_e2e_host` takes an optional SSH connection; when given, a new host is
      registered with it and an existing host whose connection differs has it replaced
      through `HostUpdate.connection`, besides the pool reconcile; without it, the mock
      lanes' placeholder is unchanged. Unit with a fake provisioning client: new host,
      unchanged host, changed connection replaced, no connection given. (D2)
      Unit, `e2e-tests/tests/unit/test_real_vm_lane.py`, the four cases plus another
      port.
- [x] 6.2 A real VM driver implementing `ComputeDealDriver` alone: supply from the
      validated target (a pool stating the GPU-less listing shape derived from
      `capacity`, the host with its connection, one declaration with `capacity`
      unchanged); provision terms carrying the run's public key (5.1); delivery
      assertions that read the delivered access; the lease view as the VM driver reads
      it. Access mode is a parameter it reads from the target. (D2, D6, D8)
      `RealVmComputeDealDriver` on `VmDealDriverBase`, which holds what both VM drivers
      supply alike and no gate. Fixed ids `compute-e2e-real-pool` and
      `compute-e2e-real-001`. Beyond the plan: `DealLease.resource_consumed` falls back
      to the declared dimensions where a GPU-less declaration has no GPU mirror. The
      re-reservation's claim is corrected by 7C.1.
- [x] 6.3 The module, marker `e2e_vm_real_provisioning`: skips naming the profile and
      file when the target is not configured; overrides
      `_ensure_provisioning_host_registered` with a fixture that registers nothing; its
      setup fixtures depend on the validated target and on a first real-only stage that
      reads `execution.executors` and requires the `vm` entry with `mocked=false`,
      failing with the reported executors otherwise, so nothing is written to the stack
      before both pass; it then checks the registered host's public connection against
      the target before any deal stage. (D1, D2, D4a; scenarios "No target is present",
      "The service's VM execution is mocked")
      Correction: the holds are set up before any stage runs, so the execution check is
      a module fixture, `real_vm_execution`, set up before the holds (pinned by
      `test_scenario_cleanup_order.py`); stage 00e1 repeats it for the results. 00f2
      checks the registered host. The module has its own listing stages (02b, 03b) and
      09a2, the latter over `step_listing_reconciliation`, extracted unchanged and shared
      with the mock deal.
- [x] 6.4 A real-only settlement preflight between 08a and 08b that writes
      `_settle_preflight_passed` only when the preview's chosen host
      (`_evaluate_settle_host_id`) is the target's `host_id`. (D4a; scenario "The
      settlement preview chooses another host")
      Stage 08a2; unit, both outcomes.
- [x] 6.5 A create-job poll between 08b and 09a: list the fulfillment reservation's jobs
      (`list_jobs(capacity_reservation_id=…)`), require exactly one, on the target host;
      poll it to terminal within a named bound; require `succeeded`; record its id and the
      guest's `vm_name`. No match, several matches, failure, and timeout each fail with
      D4's named diagnostics and the job's logs. A real-only stage after 09c checks the
      lease's `create_job_id` equals the recorded id. (D4, "Finding the jobs")
      Stage 08b3 over `JobWatch` (`JOB_BOUND_SECONDS` 1800, every 10 s); stage 09c3.
- [x] 6.6 SSH access stages after 09c, with the section 5 helper and the delivered
      access: the delivered user, `nproc` equal to `vcpu_count`, memory within tolerance
      of `ram_gb`, root disk at least `disk_gb`; then an unrelated generated key refused
      for the delivered user. (D7; scenarios "A real deal is delivered", "An unrelated
      key is refused")
      Stages 09d (probe, logging the endpoint, fingerprint, shape, and capacity) and 09e.
- [x] 6.7 A teardown-job poll between 11a and 11b (exactly one job besides the create
      job, on the target host, polled as in 6.5); after 11b, a `list_vms` job on the
      target host through the VM operator client, polled within the bound, requiring a
      succeeded, well-formed list without the recorded `vm_name`; then the delivered
      access refused within its bound. (D4, "Observing the guest's absence"; scenario
      "Teardown removes the VM and its access")
      Stages 11a3, 11c (reading the playbook's list from `ansible_result`), and 11d,
      which requires `_teardown_job_completed`, not 11c's result.
- [x] 6.8 A module finalizer, when a fulfillment was dispatched and the lane's own
      teardown did not complete: truncate this deal's lease through the site and advance
      the held workers; look for the teardown job and the guest's absence as in 6.7;
      fail naming fulfillment, reservation, create and teardown job ids, guest, and host
      where removal is not confirmed; then release the module's holds. The module never
      calls `release_reserved_resources`. (D4, "When the run fails"; scenario "The run
      fails with a guest on the host")
      `recover_failed_run`, keyed to settlement submission (`_settle_preflight_passed`
      without `_guest_absent`), through `tear_down_after_failure`: a create still
      dispatching is waited for and converged first; a lease 10a back-dated is not
      truncated again. How it finds an accepted settlement's fulfillment is 7D.2's. Unit
      over a stateful fake of convergence and the watchdog; the real service's steps run
      only on a failing live run.
- [x] 6.9 Register the marker in `e2e-tests/pyproject.toml` and in no lane variable of
      `e2e-tests/Makefile`; the module's stage list follows D4a's real-lane order.
      (D5)
      The Makefile's lane comment says why.
- [x] 6.10 Unit: job correlation (exactly one, none, several, a failed job, a timeout)
      and the `list_vms` absence check against fake clients; the preflight's host
      comparison; a stage-list test that the real module runs every shared stage in
      D4a's real-lane order and no mock-only stage. (D4, D4a)
      Unit, `test_real_vm_lane.py`, `test_compute_deal_stages.py` (`REAL_LANE_ORDER`,
      the real lane in the generic field checks, a lane-scoped consumption test), and
      `test_scenario_cleanup_order.py`. Not unit-tested: the driver's composition of
      these, and the stored connection view 00f2 compares against.
- [x] 6.11 Verification: `make -C e2e-tests test-unit`; `make test`; `make -C e2e-tests
      test-module MODULE=e2e_vm_real_provisioning ACTIVE_PROFILES=local` with no stack
      running skips naming the profile and file.
      End-to-end: `e2e_vm_real_provisioning` is in no lane; the pipeline's lanes must
      still pass. Live evidence is section 8.
      Unit 293 passed; with no stack, 37 skipped, each naming the profile and file; `make
      test`, `make check-packaging`, and `make check-change` passed. The VM lane
      modules run the reworked mock driver and extracted 09a2; the pipeline's VM lane is
      that evidence (9.8).
- [x] 6.12 Round triage fix (53 F2): the comment on `provision_terms`'s negotiated key
      in `real_compute_deal_driver.py` said it is "the only one that can pass", the
      claim D7 narrowed (10 F4). It now says the access checks show that the key
      negotiated here was installed. Checks as 5.8's.

## 7. Dead e2e material

Delivers D11's removals and the e2e package's own run instructions (D11, D5).

Files: the e2e package's nested `e2e.yml` workflow (deleted); `e2e-tests/README.md`.

- [x] 7.1 Delete the e2e package's nested `e2e.yml` workflow, and the directory if it is
      left empty. (D11)
      Deleted with its directory.
- [x] 7.2 Remove `e2e-mock-happy`/`e2e-mock-failure` from `e2e-tests/README.md`, and add
      how to run `e2e_vm_real_provisioning`: copy the example profile, render or fill the
      real file, forward the stack's services to the `local` ports, run the module with
      `ACTIVE_PROFILES=local,real-vm-target`. (D5, D11)
      The README's "End-to-end lanes" and "Real VM provisioning" sections; its "CI/CD"
      section now points to the root `E2E` workflow and `TESTING.md`.
- [x] 7.3 Verification: no tracked file references the deleted workflow or the removed
      targets; `make check-doc-citations CHANGE=prove-real-vm-provisioning` reports
      nothing for them.
      End-to-end: none.
      Search clean outside this change's own documents; `make check-doc-citations`
      passed; the README's relative links checked by hand; `make test` passed.

## 7A. Host preparation restarts the SSH daemon by its unit name

Delivers D9d: the SSH hardening host preparation writes takes effect through a restart of
the unit the host has, and a failed restart fails preparation. Planned after 8.1's run
found the defect; the golden build's cloud-init template stays out of scope (D9d, D10).

Files: `domains/vms/provisioning/iac/ansible/roles/vm-setup/handlers/main.yml`;
`domains/vms/provisioning/iac/tests/test_ansible_structure.py`.

- [x] 7A.1 The `restart sshd` handler restarts `ssh` when `ansible_os_family` is
      `Debian` and `sshd` otherwise, and carries no `ignore_errors`, so a failed
      restart fails preparation. Keep the handler's name, which
      `security-hardening.yml` notifies, or rename it and every notify with it. A
      comment says why the unit name depends on the OS family. (D9d)
      Name kept; the playbook gathers the fact the expression reads.
- [x] 7A.2 Unit, `test_ansible_structure.py`: the handler names `ssh` for the Debian
      family and `sshd` otherwise through `ansible_os_family`, and has no
      `ignore_errors`; every `notify` of it in the role resolves to a handler that
      exists; no task or handler in `roles/vm-setup` restarts a unit literally named
      `sshd` outside that expression (the golden-only `templates/` and `files/` are
      excluded and say so in the test). Mutation check: restoring `ignore_errors` or the
      literal `sshd` fails the test. (D9d)
      `TestSshRestartHandler` (4 cases), reading the role's tasks and handlers; the test
      lists what it does not cover. Correction: `templates/` is not wholly golden-only;
      the one template restarting `sshd`, `user-data.j2`, is rendered only by the
      golden build. Each listed mutation fails it.
- [x] 7A.3 Verification: `make test-provisioning-iac` (the IaC suite, unit); `make
      test`.
      End-to-end: none in the pipeline — the mock profile runs no playbook. 8.4's live
      re-run of host preparation exercises it.
      IaC unit 86 passed; `make test`, `make check-packaging`, and `make check-change`
      passed. Not run: `validate`'s Ansible parts, as in 3.7. Live evidence: 8.4.

## 7B. A direct-access create reports the port it forwarded

Delivers D4b: a create without a relay reports delivery evidence at the port the
playbook forwarded, so the requirement's scenario "A real deal is delivered" can hold
on the direct path. Planned after 8.2's first run found the defect.

Files: `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/codec.py`;
`domains/vms/provisioning/adapter/tests/unit/test_vm_codec.py`.

- [x] 7B.1 In `build_result_payload`, the relay block's `remote_port` replaces the
      payload's `ssh_port` only when the relay is reported enabled — the rule
      `_relay_reported` already applies — and the value is a port number; otherwise
      the port parsed from the playbook's output stands. The relay block itself is
      still carried into the payload as before. A comment says why: the playbook
      reports the block on every create, with `"N/A"` placeholders when there is no
      relay. (D4b)
      Gated by `_relay_reported` and a new `_is_port` (an integer or its decimal text,
      1–65535, never a `bool`).
- [x] 7B.2 Unit, `test_vm_codec.py`: (a) `build_result_payload` with the playbook's
      disabled relay block (`enabled` false, `relay_addr`, `remote_port`, and
      `ssh_access` all `"N/A"`) keeps the parsed port; (b) an enabled block with a
      port-valued `remote_port` still replaces it (the existing
      `test_relay_remote_port_overrides_ssh_port`, whose block gains `enabled`); (c) an
      enabled block whose `remote_port` is not a port keeps the parsed port; (d) through
      the executor, as `test_a_run_reports_the_vm_result_and_credentials` runs, a
      direct create whose fact has the shape `vm-create.yml`'s create fact actually
      reports — its `network` block with `direct_port_forwarding`, its disabled relay
      block, and a `timestamp` — yields a `CreateJobResult` whose evidence names the
      host's address, the forwarded port, and the tenant user; (e) the same with the
      relay enabled and leased (`relay_id`, `vm_remote_port`) yields the relay's address
      and the leased port. Mutation checks: restoring the unconditional replacement fails
      (a) and (d); dropping the port-number test fails (c). (D4b)
      As listed; (d) and (e) print the fact as the YAML result format prints it, so the
      codec reads it through its real `msg` path. The fact's shape and printing were read
      from the playbooks, not captured; the version assumption is in `design.md`. Each
      mutation fails as planned.
- [x] 7B.3 Verification: `make test-provisioning-adapter` (the adapter's suite, unit);
      `make test`; `make check-packaging`.
      End-to-end: none in the pipeline — the mock lanes never interpret playbook
      output. 8.2's and 8.3's runs exercise it against a real host.
      Adapter unit 273 passed; `make test`, `make check-packaging`, and `make
      check-change` passed. Correction: the mock lanes' create output does pass through
      the codec, but their facts' relay block is disabled with no port, which neither
      rule replaces from, so those lanes are no evidence for this section; 8.2 is. The
      generated-key fact's `relay` block is left for the relay-backed follow-up
      (`design.md`, "Implementation notes").

## 7C. A rerun adopts its listing, and 11b claims capacity as dimensions

Delivers D2a: a second run against the same stack reconciles its listing as it does its
registrations, and the real lane's re-reservation claims the released capacity in the
shape the site matches, so 8.2 ("every stage passes") and 8.3 (a rerun passes) can
hold. Planned after 8.2's and 8.3's runs at 7B's revision found both. Confined to the
e2e package: no published image or chart changes.

Files: `e2e-tests/tests/e2e/roles/scenarios/vms/real_compute_deal_driver.py`;
`e2e-tests/tests/e2e/roles/scenarios/vms/test_real_provisioning_deal.py`;
`e2e-tests/tests/unit/test_real_vm_lane.py`.

- [x] 7C.1 `RealVmComputeDealDriver.reserve_released_capacity` claims
      `required_attributes={"resource_id": REAL_RESOURCE_ID, "dimensions":
      dict(self.capacity)}`: the resource as its one attribute, everything the host
      sells as dimensions, so a reservation coming back still shows all of it was
      released. The comment says why the quantities go under `dimensions` (the site
      matches attributes exactly and reads quantities only from `dimensions`). (D2a,
      "The re-reservation's claim")
      As planned; first live use 8.2's run 3.
- [x] 7C.2 The driver gains the listing reconciliation D2a describes, as a method 02b
      calls (for example `listing_for_run`): it lists the storefront's listings
      (`list_listings`, paging until every listing is read) and selects those whose
      `listing_resource` names `REAL_RESOURCE_ID`. None: returns nothing, and 02b
      creates the listing paused as before. Exactly one, `open`, whose stated
      `vcpu_count`, `ram_gb`, and `disk_gb` equal the target's `capacity`: pauses it
      unless already paused (`pause_listing`), reads it back paused and open
      (`get_listing`), and returns it. Several, or one `closed`, or one whose shape
      differs: fails naming each listing's id, status, and shape and the target's
      capacity, for an operator to recover. 02b records the adopted or created listing
      as `seller_listing_id` and logs which it did; 03b is unchanged. Nothing before 02b
      writes a listing, so a refused adoption leaves the stack as the previous run left
      it. (D2a)
      `listing_for_run`, pages of 200; any status other than `open` fails as `closed`
      does, and the failure says how an operator recovers. Correction: the registrations
      before 02b still reconcile, so a changed capacity rewrites the declaration and is
      refused here (`design.md`, D2a).
- [x] 7C.3 Unit, `test_real_vm_lane.py`, against a fake storefront client in the
      file's existing fakes' style: (a) the re-reservation's claim is `resource_id`
      plus `dimensions` equal to the target's capacity, with no quantity among its
      attributes; (b) no listing on the resource → nothing returned, no pause; (c)
      one open listing of the target's shape, unpaused → paused and returned; (d) the
      same already paused → returned, no second pause; (e) a closed one, (f) two, and
      (g) one whose disk differs → fail naming the listings and the capacity, nothing
      paused; (h) listings on other resources are ignored; (i) a listing found only on
      a later page is still found. Mutation checks: restoring the attributes-only claim
      fails (a); dropping the shape comparison fails (g); dropping the status check
      fails (e). (D2a)
      Unit, 10 new cases over `FakeStorefront`, plus 02b's body recording an adopted
      listing; each mutation fails as planned. That the stored `listing_resource` keeps
      the created counts was read, not tested; 8.3 is its live use.
- [x] 7C.4 Verification: `make -C e2e-tests test-unit` (unit); `make test`; `make
      check-change CHANGE=prove-real-vm-provisioning`. No dependency or lock changes, so
      no packaging check is owed beyond `make test`'s.
      End-to-end: `e2e_vm_real_provisioning`, in no lane, through 8.2 and 8.3 against a
      real host; no pipeline lane runs it, and the mock lanes' drivers and stages are
      untouched, so their results are no evidence for this section. No CI workflow is
      owed.
      Unit 303 passed; `make test` and `make check-change` passed.

## 7D. A deal waits for its own dispatch, and recovery finds it

Delivers D4's "Finding this deal's dispatch" and its recovery rule: 08b reads this run's
fulfillment however many runs the listing has served, and a run that fails after its
settlement was accepted never leaves a guest unreported, so 8.3 (a rerun passes) can
hold. Planned after 8.3's run at 7C's revision found both. Confined to the e2e package:
no published image or chart changes.

Files: `e2e-tests/tests/e2e/roles/scenarios/vms/compute_deal_driver.py`
(`VmDealDriverBase.settle_dispatched`, shared with the mock VM lane);
`e2e-tests/tests/e2e/roles/helpers/compute_deal_stages.py` only if 08b must take the
mark before it settles; `e2e-tests/tests/e2e/roles/scenarios/vms/real_compute_deal_driver.py`
(`tear_down_after_failure`); `e2e-tests/tests/unit/test_real_vm_lane.py`, and the unit
module that covers the shared VM driver or 08b (`test_compute_deal_stages.py` or a new
one beside it).

- [x] 7D.1 08b's dispatch wait is this deal's: `settle_dispatched` waits for
      `provision/job_submitted` filtered by the deal's `negotiation_id` and counted from a
      `since_id` mark taken before settlement is submitted (read with `get_events`, as
      11b reads its mark), keeping the listing filter. Where the mark is taken — in 08b
      before `settle_evm`, or in a driver method 08b calls first — is the
      implementer's, recorded in the note; bare metal's driver is untouched. (D4,
      "Finding this deal's dispatch")
      The mark is taken in 08b before `settle_evm` by `latest_stage_event_id`
      (`helpers/compute_deal.py`), scoped to the negotiation and read across every page;
      the negotiation filter is what excludes another deal's event. Correction to
      "bare metal's driver is untouched": the mark reaches the driver as
      `settle_dispatched(…, events_since=…)` on `ComputeDealDriver`, which bare metal's
      driver accepts and ignores, and the bare-metal lane's 08b now reads the event log.
- [x] 7D.2 Recovery finds an accepted settlement's fulfillment:
      `tear_down_after_failure`, where neither the deal's state nor the settle status
      names a fulfillment, reads the settle status; a status the storefront reports as
      accepted (`provisioning` or a later status — read the settle status model for the
      set) waits within a named bound for this negotiation's `job_submitted` and reads
      the status again; where it still names none, it raises naming the escrow, the
      negotiation, the settle status, and the host. Only a status that is not accepted
      logs "nothing to tear down" and returns. With a fulfillment found, recovery goes
      on as today. (D4, "When the run fails")
      `RealVmComputeDealDriver.dispatched_fulfillment`, within `DISPATCH_BOUND_SECONDS`
      (60). Written to fail closed: `UNDISPATCHED_SETTLE_STATUSES` is `refunding` alone,
      and a 404 settle status is waited on like an accepted one. What failing closed
      costs is in `design.md`, D4 "When the run fails".
- [x] 7D.3 Unit tests at the lowest level that proves each (`docs/development/TESTING.md`,
      unit): (a) with an earlier `job_submitted` for the same listing but another
      negotiation already in the fake event log, `settle_dispatched` does not return on
      it — it waits for this deal's event and returns this run's fulfillment; (b) the
      wait passes this deal's `negotiation_id` and a mark taken before settlement;
      (c) recovery with an accepted status naming no fulfillment, whose
      `job_submitted` then arrives and whose status then names it, tears the guest
      down as `test_a_create_still_in_flight_is_settled_then_torn_down` does; (d) the
      same status that never names one raises naming the escrow, negotiation, status,
      and host; (e) a status that is not accepted still returns with nothing torn down
      (the existing test, its status made explicit). Mutation checks, each run and
      reverted: dropping the negotiation filter fails (a); restoring the
      return-on-no-fulfillment fails (d).
      Unit, `e2e-tests/tests/unit/test_vm_deal_dispatch.py` (4 cases, over a fake
      event log filtering as the storefront's query does) for (a) and (b);
      `test_real_vm_lane.py` (5 new, 1 reworked, over a fake settlement) for (c)–(e) and
      the 404 cases. Each mutation fails as planned. The fakes stand in for the
      storefront's filtering and settle status, read from its source; 8.3 is the live
      check that the filter finds the event.
- [x] 7D.4 Verification: `make -C e2e-tests test-unit` (unit); `make test`; `make
      check-change CHANGE=prove-real-vm-provisioning`. No dependency or lock changes, so
      no packaging check is owed beyond `make test`'s.
      End-to-end: `e2e_vm_real_provisioning`, in no lane, through 8.2 and 8.3 against a
      real host. The shared `settle_dispatched` also runs in the mock VM scenarios that
      use the VM driver, `e2e_deal` (`test_full_deal.py`) and
      `e2e_non_erc20_settlement` (`test_non_erc20_settlement.py`): their pipeline result
      is evidence that the narrower wait still finds a single run's event there. No CI
      workflow is owed.
      Unit 312 passed; `make test`, `make check-packaging`, and `make check-change`
      passed. Correction: `e2e_non_erc20_settlement` settles in its own body and is no
      evidence; the shared 08b runs in `e2e_deal` and `e2e_bare_metal_mock_deal`, whose
      pipeline results are (9.8).

## 8. Live verification [log]

Requires a prepared, GPU-less, nested-virtualization KVM host and a deployed stack the
owner provides (`design.md`, "Implementation cadence"). Each item states its acceptance;
the owner supplies the output, free of addresses, project, cluster, namespace, host
names, and private paths, and it is checked against the acceptance here. Record the
public revision of this branch the run used.

- [x] 8.1 **[log]** Host preparation with the default image setup and `gpu_passthrough`
      left `auto`, on a GPU-less host. Supplied: the play recap; `/proc/cmdline` before
      and after; `/sys/module/kvm_intel/parameters/nested` (or `kvm_amd`); `ls -l
      /dev/kvm`; whether `gpu-detection.service` exists. Acceptance: preparation
      succeeds; the kernel command line is unchanged; nested virtualization is on and
      `/dev/kvm` exists; no GPU-detection service is installed; no golden-image step ran.
      (D9)
      Correction: the unit is `gpu-detect.service`; the evidence checks both names.
      At `8638567c8`, from its published provisioning image, `vm-setup.yaml` with no
      extra variables, on a GPU-less x86-64 Ubuntu 24.04 cloud instance with nested
      virtualization (owner-supplied, sanitized), each point holds: `failed=0
      unreachable=0`; kernel command line byte-identical across the reboot; `nested` `Y`
      and `/dev/kvm` present; no GPU-detection unit; no golden-image task; the GPU
      decision `GPU present: False`, `gpu_passthrough: auto`, passthrough skipped. Not
      shown: the host type already had nested virtualization, and D9a's refusals cannot
      fire on a capable host (they rest on 3.6). The run's `ignored=1` was the `restart
      sshd` handler naming a unit Ubuntu 24.04 lacks, which led to 7A (D9d). Host
      preparation's code differs at the head only by 7A, which 8.4 shows, so the
      acceptance stands for `3dee66930`.
- [x] 8.2 **[log]** The scenario: `make -C e2e-tests test-module
      MODULE=e2e_vm_real_provisioning ACTIVE_PROFILES=local,real-vm-target` against the
      provided stack. Supplied: pytest's summary and per-stage results; the VM-execution
      check's reported executor; the create and teardown jobs' terminal statuses; the
      logged host-key fingerprint; the access probes' values against the negotiated
      shape; the unrelated key's refusal; the `list_vms` result; the post-teardown
      refusal. Acceptance: every stage passes and none skips; the values match the
      requirement's scenarios "A real deal is delivered", "An unrelated key is
      refused", and "Teardown removes the VM and its access". (D4, D7)
      Earlier runs, owner-supplied and sanitized, each against a fresh stack of its
      revision's published images and an empty host registry: at `fa27649fe` the create
      succeeded but delivery failed on the codec's port (7B, D4b); at `f52f07973` 36
      passed and 11b's re-reservation was refused (7C, D2a); at `cb05d625f` 37 passed.
      Acceptance met by run 4: a clean checkout of `3dee66930` (sections 1–7D) against a
      fresh, unmocked stack of `f52f07973`'s published images and chart — identical to
      the head outside `openspec/` and `e2e-tests/` — an empty host registry, and a
      fresh GPU-less nested-KVM host prepared at `f52f07973` (`failed=0 ignored=0`). 37
      passed, none skipped or failed: 00e1 `offering_mode='vm' mocked=False`; 00f2 the
      target registered; 02b created its listing; 08b `dispatching`; 08b3's create and
      11a3's teardown jobs `succeeded` on the target host; 09a `active`; 09d connected
      as the delivered user at the host's address and forwarded port, logged the
      host-key fingerprint, and probed `7 / 27.41 / 160` against the sold `7 / 28 / 160`
      (memory 2.1% short, within 5%); 09e `Permission denied (publickey,password)`; 11b
      re-reserved the released capacity; 11c listed `[]`; 11d `Connection timed out`.
      5.8 and 6.12 came after; 11d's reason meets 5.8's rule unchanged.
- [x] 8.3 **[log]** A second run of the scenario against the same stack. Acceptance: it
      passes, the host's registration being reconciled rather than duplicated. (D2)
      Earlier reruns: at `f52f07973` 02b's create was refused because the first run's
      listing still held its publication source (7C, D2a); at `cb05d625f` 02b adopted
      the listing and 08b read the previous run's dispatch event (7D, D4), and recovery
      left that run's guest unreported, which the infra side removed by replacing the
      host. Acceptance met by run 3: `3dee66930`, straight after 8.2's run 4 against the
      same stack and host, 37 passed: 00f1 and 00f2 reconciled the registration (one
      host, one bucket after both runs); 02b logged run 4's listing "an earlier run's,
      adopted paused"; 08b recorded this run's own fulfillment; every later stage passed
      as in run 4, with a new guest's fingerprint. After both runs the service held four
      reservations, all `released`, and jobs `create`, `vm_remove`, and `list` twice
      each, all `succeeded`. Not shown, since neither run failed: the failure recovery
      (6.8, 7D.2), which rests on its unit tests; 03b's registry read is vacuous on an
      adopted listing, which pausing does not unpublish.
- [x] 8.4 **[log]** Host preparation re-run, as in 8.1, at a public revision of this
      branch that includes section 7A, on the same kind of host. Supplied: the play
      recap and the handler's result from the log. Acceptance: the recap shows
      `failed=0` and `ignored=0`; the handler restarts the OS family's SSH unit without
      error; 8.1's other acceptance points still hold. (D9d)
      At `fa27649fe`, its published image (ansible-core 2.19), on a fresh host of 8.1's
      kind (owner-supplied, sanitized): `failed=0 unreachable=0 ignored=0`; `restart
      sshd` `changed` after the reboot; 8.1's other points hold. The host of 8.2's run 4
      was prepared at `f52f07973` with the same result. Host preparation's code is
      identical at `fa27649fe`, `f52f07973`, and `3dee66930`, so 8.4 holds for the head.
      Section 8 changes no code; `e2e_vm_real_provisioning`, run by hand, is its
      evidence, and no pipeline lane selects it.

## 9. Closeout

The eleven parts of `openspec/README.md#plan-closeout-requirements`, in order.

- [x] 9.1 **Comment hygiene.** Run `make check-comment-hygiene`; any finding, or a
      comment the change added that narrates history, returns the change to
      implementation.
      `make check-comment-hygiene`: passed. The comments the change added, read from
      its diff against `dev`, describe current behaviour; none names the review,
      migration, or change that introduced it.
- [x] 9.2 **Import placement.** Confirm the imports sections 1–6 added are module-level
      or carry a recorded reason; one that should move returns the change to
      implementation.
      Every import the change added is module-level. The one indented `import` in its
      diff is inside the fake `ssh` script `test_ssh_access.py` writes out as text, not
      an import of the test module.
- [x] 9.3 **Documentation compliance.** Re-check each decision's destination below
      against `openspec/README.md`'s placement table.
      Subsystem behaviour goes to the `test-compatibility` and `physical-provisioning`
      specifications through the deltas; testing practice to `TESTING.md`; the operator
      procedure to `VALIDATION_RUNBOOK.md`; the host kit's options to its README; the
      goal's state to `ROADMAP.md`; D10 to the index; D4b and D9d to their code's own
      comments. `ARCHITECTURE.md`: no change, since no layer, authority, or major flow
      changes. No companion `architecture.md`: D9b's rationale is short enough for its
      requirement, and `physical-provisioning`'s "Host preparation cannot cost the
      machine" still holds, since presence gating carries no new reboot-applied
      binding. `e2e-tests/README.md`'s real-lane section was checked against the module
      and holds.
- [x] 9.4 **Narrative compression.** Shorten completed-task notes to final behaviour,
      evidence, and destinations; move debugging narrative and declined suggestions into
      `design.md` first.
      Notes compressed. Moved first to `design.md`: what failing closed costs (D4,
      "When the run fails"), a changed capacity's effect on adoption (D2a), what was left
      as found, the owner's in-guest observations, and the declined suggestions
      ("Implementation notes"). The live runs' causes were already D4b, D2a, D9d, and D4
      "Finding this deal's dispatch". Each live run's revision and result stays in
      section 8.
- [x] 9.5 **Roadmap currency.** `docs/development/ROADMAP.md` Goal 1: remove the gap row
      "No end-to-end scenario provisions for real…" and say in the current state that a
      VM scenario provisions a GPU-less VM on a real host from an operator's machine and
      runs in no lane. The relay-backed gap stays unowned beside
      `relay-vm-access-without-a-dashboard`.
      Done; the relay-backed row adds that the scenario's access mode makes a
      relay-backed run additive.
- [x] 9.6 **Campaign index currency.** This change's row in
      `openspec/changes/README.md` ("Reach hosts and VMs that have no inbound route");
      `make check-change-index`.
      Status `in closeout`, its notes rewritten to the live and pipeline evidence; the
      campaign graph is unchanged and no other row moved. `make check-change-index`:
      passed.
- [x] 9.7 **Packaging.** `make check-packaging`; `make check-architecture-change
      CHANGE=prove-real-vm-provisioning`.
      `make check-packaging`: passed. `make check-architecture-change`: the change owns
      no architecture row. The change touched nothing under `.agents/`, `.claude/`, or
      `.codex/`, so `make check-agent-skills` is not owed.
- [x] 9.8 **End-to-end pipeline.** Record the pipeline run validating `HEAD`: the VM and
      bare-metal lanes (`e2e_deal`, `e2e_listing_shapes`, `e2e_bare_metal_mock_deal`)
      passing over the split stages, and `e2e_vm_real_provisioning` in no lane. The real
      lane's evidence is section 8's.
      Run 41119590777 (`reviews/62-validation.md`) at `a8d4b4a60`, the pre-closeout
      commit, which closeout's documentation-only commit carries unchanged: success.
      e2e-vm 145 passed (`e2e_deal` and `e2e_listing_shapes` among them, not itemised);
      e2e-bare-metal 65 passed, 3 skipped (`e2e_bare_metal_mock_deal`); e2e-apicredits 1
      passed, 3 skipped. `e2e_vm_real_provisioning` ran in no lane. No section owed a CI
      workflow. The validation's Helm part was waived by the owner, so it is
      inconclusive on that part only.
- [x] 9.9 **Promotion.** Write: `docs/development/TESTING.md` — under "#### The
      canonical compute deal", shared stages and mock gates as separate stages with a
      mock-only driver part; a new subsection under "### 4. System Integration Tests
      (End-to-End)" for the real-provisioning lane (its target section, how it is run,
      what it proves and does not, that it is in no lane);
      `docs/development/VALIDATION_RUNBOOK.md` §21–26 rewritten as the lane's manual
      counterpart for an operator-provided host, against the signed admin API and the D9
      defaults, with §17–20's references to it checked;
      `domains/vms/provisioning/iac/README.md` — the scratch default, `gpu_passthrough`,
      and the virtualization requirement. The `test-compatibility` and
      `physical-provisioning` specifications are written by the archive (9.11).
      `docs/development/ARCHITECTURE.md` has no change, as the proposal records. Complete
      the design-promotion record in `design.md`.
      Amended during section 1: the canonical-deal diagrams under
      `docs/development/diagrams/` (`e2e-compute-deal`, `e2e-settle-zoom`,
      `e2e-stage-discipline`, `.drawio` and their `.svg` exports) and TESTING.md's
      "One part, zoomed in" are redrawn with the mock gates as mock-lane stages.
      Amended during section 6: the real-lane subsection says the lane waits for real
      jobs by reading their status within a named bound, where the stage discipline
      otherwise waits only on a request a stage made, and that its failure recovery
      expires only its own deal's lease.
      Amended at the D9d replanning: D9d has no permanent destination; it repairs a
      handler to do what it already claimed, and the reason the unit name follows the OS
      family is the handler's own comment (7A.1). The design-promotion record says so.
      Amended at the D4b replanning: D4b has no permanent destination either; it repairs
      the codec to deliver what a direct create already promised, and why the relay's
      port is gated is the codec's own comment (7B.1). The design-promotion record says
      so.
      Amended at the D2a replanning: TESTING.md's real-lane subsection says a rerun
      against the same stack reconciles the lane's registrations and adopts its open
      listing, since a publication source backs one listing for good, and fails naming
      the listings it cannot adopt. The re-reservation's claim shape is the driver's own
      comment (7C.1). The design-promotion record names both.
      Amended during section 7D: TESTING.md's real-lane subsection says 08b waits for
      the deal's own dispatch event, by its negotiation and from a mark taken before
      settling, since an adopted listing logs earlier deals' events; and that recovery
      takes any settlement the storefront records, or whose dispatch it logs within a
      bound, as having dispatched a fulfillment unless its status shows a refund begun
      before delivery, failing naming the escrow and negotiation where the fulfillment
      cannot be found. The design-promotion record names D4's two paragraphs.
      Written: `TESTING.md` ("The canonical compute deal": mock gates as mock-lane stages
      on a `MockGates` part, the split, the preflight before settlement, the stage-set
      checks; "One part, zoomed in"; the bare-metal paragraph's pointer; "The
      real-provisioning lane", with every amendment above); the three diagrams, `.drawio`
      and `.svg` (both the drawn text and the source each `.svg` embeds);
      `VALIDATION_RUNBOOK.md` §21–26 as the scenario's operator procedure (provide,
      prepare with the D9 defaults, run provisioning for real, describe the target, run,
      restore), the scenario doing the registration through the signed admin API, with
      §17's overview and variables and §19's registration sentence brought into line;
      the design-promotion record; and `domains/vms/provisioning/iac/README.md` (§2's
      parameters and notes: the scratch default, the virtualization requirement and
      `--virt-type kvm`, presence-gated passthrough and `gpu_passthrough`; the
      architecture bullets; the parameter reference; the passthrough tag example), with
      the owner's permission for this run to edit under `domains/`.
- [x] 9.10 **Documentation citations.** `make check-doc-citations
      CHANGE=prove-real-vm-provisioning`; `openspec validate prove-real-vm-provisioning
      --strict`.
      `make check-change` (citations, strict validation with the pinned validator,
      comment hygiene, agent skills, task list, index): passed, after the example
      profile's citation was reworded so the checker no longer reads it as the ignored
      file.
- [x] 9.11 **Archival.** `openspec archive prove-real-vm-provisioning -y`, merging both
      spec deltas.
      Neither permanent spec carried the deltas' requirements, so both merge (no
      `--skip-specs`): `test-compatibility` (one modified, two added) and
      `physical-provisioning` (one modified, two added).
