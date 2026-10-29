# Tasks

Planned against the design settled in `design.md` and advanced by
`reviews/10-design.triage.md`. Every task answers to a decision (D1–D11), a delta
requirement under `specs/`, or a repository obligation cited at the task:
`openspec/README.md#plan-closeout-requirements`, the task rules in
`openspec/config.yaml`, `docs/development/TESTING.md`'s level definitions, and
`AGENTS.md`'s package discipline.

Test levels follow `docs/development/TESTING.md`: unit (no stack); system (the
`e2e-tests` markers, run by the pipeline lanes). The IaC tests under
`domains/vms/provisioning/iac/tests/` are unit tests of the playbooks' structure and of
their shell logic against a fake filesystem.

Order: sections 1–5 deliver everything the mock lanes and unit tests can prove; sections
6–8 deliver the real lane, its documentation, and its live verification; section 9 is
the closeout. Section 6 needs sections 1, 2, 4, and 5. Section 8 is evidence the owner
supplies from a run against a real host (`design.md`, "Implementation cadence"); until it
is supplied the change is `blocked in implementation`. No dependency gates
implementation.

Permanent documentation — `TESTING.md`, the validation runbook, the IaC README, and the
roadmap — is written at closeout (9.9). Sections change code, tests, and the e2e
package's own README and example profile.

Public-repository discipline (`AGENTS.md`) applies to every task note and to the
section 8 evidence: no address, project, cluster, namespace, host name, or private
path.

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

- [ ] 1.1 Add a `MockGates` protocol beside `ComputeDealDriver` and move to it
      `create_rule_id`, `teardown_rule_id`, `arm_create_gate`, `release_create_gate`,
      `evaluate_create_job`, `arm_teardown_gate`, and `release_teardown_gate`. Both mock
      drivers (VM and bare metal) implement both protocols, unchanged in behaviour. The
      module docstring and `ComputeDealDriver`'s say a shared stage never uses
      `MockGates` and why (D4a: a gate hook answered by a no-op would make a shared
      assertion vacuous under one driver). (D4a)
- [ ] 1.2 Split each gated stage at its gate, as D4a names them: 07 into the shared
      on-chain escrow stage and a mock-only create-gate arm; 09a into a mock-only create
      release-and-drain and the shared advance to `active`; 10a into a mock-only
      teardown-gate arm and the shared expiry; 11b into a mock-only teardown
      release-and-drain and the shared completion and release. 08c becomes mock-only and
      `Stage00e_ProvisioningMockMode` stays mock-only. Mock-only stages take the driver
      as `MockGates`; shared stages take it as `ComputeDealDriver`. Each new class name
      says what the stage does. (D4a)
- [ ] 1.3 Replace 08b's prerequisite `_provision_job_evaluated` with a readiness field
      `_settle_preflight_passed` on `ComputeDealState`; 08c writes it once its
      assertions pass and no longer writes `_provision_job_evaluated` (remove the field
      if nothing else reads it). 08b's assertion message says the fulfillment is
      dispatched and not yet converged. 08b and 11a stay shared, unchanged otherwise.
      (D4a; scenario "The preflight before settlement fails")
- [ ] 1.4 List the new stages in both mock lane modules in the mock-lane order D4a
      gives, so each lane runs the same assertions in the same order as before.
      (D4a; scenario "A mock lane holds a job")
- [ ] 1.5 Unit (`test_compute_deal_stages.py`, `stage_sources.py`):
      `test_every_compute_state_field_is_consumed_after_it_is_produced` passes with the
      new field; a new test fails if any shared stage's source references a `MockGates`
      member or the mock test client; a new test that 08b skips when
      `_settle_preflight_passed` is unset; the existing stage-list tests are updated for
      the new classes in both lanes. (D4a; scenarios "A mock lane holds a job", "A real
      lane runs the canonical deal")
- [ ] 1.6 Verification: `make -C e2e-tests test-unit`; `make test`.
      End-to-end: `e2e_deal` (VM lane) and `e2e_bare_metal_mock_deal` (bare-metal
      lane) run the reordered stages; their outcome must be unchanged, so the
      validation pipeline's result for both lanes is this section's evidence.

## 2. GPU-less shapes in the VM helpers

Delivers capacity sources and provision terms that carry GPU fields only when the shape
does (D6; delta requirement "A real-provisioning VM scenario proves delivery on a real
host", "MUST be able to deal on a shape that declares no GPUs").

Files: `e2e-tests/tests/e2e/roles/scenarios/vms/conftest.py`,
`…/vms/compute_deal_driver.py`, `…/vms/host_registry.py`; a new unit test under
`e2e-tests/tests/unit/`.

- [ ] 2.1 `capacity_source_for` emits the GPU family only when the resource carries a
      positive `gpu_count` and a `gpu_model`, and otherwise emits `cpu.count`,
      `memory.gib`, and `storage.gib` from `vcpu_count`, `ram_gb`, and `disk_gb`. If the
      function cannot be imported by a unit test from the scenarios' `conftest.py`,
      move it into `host_registry.py` unchanged in behaviour and import it back.
      (D1, D6)
- [ ] 2.2 The VM driver's provision terms and required attributes name GPU fields only
      when its shape carries them; the mock lanes keep their GPU shapes, so their terms
      are unchanged. (D6)
- [ ] 2.3 Unit: a GPU-less resource (`vcpu_count: 7, ram_gb: 28, disk_gb: 160`) yields
      a shape with no `gpu` family and those three dimensions; a GPU resource yields the
      same shape as before; a resource with `gpu_count: 0` yields no `gpu` family. (D6)
- [ ] 2.4 Verification: `make -C e2e-tests test-unit`; `make test`.
      End-to-end: `e2e_deal`, `e2e_listing_shapes` — unchanged in outcome.

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

- [ ] 3.1 `vm-setup.yaml` defaults `vm_image_type` to `scratch`; `golden` stays
      selectable by `image_setup_type`. `single-tenant/vm-operations.yaml` is not
      changed: the service always passes the image setup type. (D9c; scenarios "A host
      is prepared without options", "The operator names the golden image")
- [ ] 3.2 Validate `gpu_passthrough` (`auto`, `enabled`, `disabled`; default `auto`) as
      the role's first task, failing with the value named before anything on the host
      changes. (D9b; scenario "The override names an unknown value")
- [ ] 3.3 Fail before any host mutation when `/proc/cpuinfo` shows neither `vmx` nor
      `svm`, as a read-only precondition at the start of the role, replacing
      `kvm-setup.yml`'s `ignore_errors` check; after the KVM modules load in
      `kvm-setup.yml`, fail when `/dev/kvm` is absent. Both messages say hardware
      virtualization is unavailable and why. (D9a; scenario "A host without
      virtualization extensions")
- [ ] 3.4 Add a GPU-presence task file that reads PCI class and vendor from sysfs,
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
- [ ] 3.5 Pass `--virt-type kvm` on every `virt-install` invocation in the
      `vm-management` role, the GPU retry path included, and fail a create before
      `virt-install` when `/dev/kvm` is absent, naming KVM as unavailable. (D9a;
      scenario "KVM disappears after preparation")
- [ ] 3.6 Unit: structural tests that `vm-setup.yaml`'s default is `scratch`; that the
      override check and the virtualization precondition precede every task that
      changes the host; that the three passthrough includes carry the D9b condition;
      that every `virt-install` command in the role names `--virt-type kvm`; and that
      the create checks `/dev/kvm` before `virt-install`. Presence, through
      `shell_harness.py` over a fake sysfs: an NVIDIA `0300` and an AMD `0302` device are
      presence; an ASPEED BMC (`1a03`, `0300`), a QEMU emulated VGA (`1234`, `0300`),
      and a host with no display device are not. (D9)
- [ ] 3.7 Verification: `make -C domains/vms/provisioning/iac validate` (inventory,
      playbook syntax, tests); `make test`.
      End-to-end: none in the pipeline — the mock profile runs no playbook. Section 8's
      live run exercises 3.1, 3.3, 3.4, and 3.5 on a GPU-less host.

## 4. The real-provisioning target description

Delivers the typed, versioned target section, its example, and its ignore rule (D1;
delta requirement "A real-provisioning target is a typed, versioned settings
section").

Files: a new `e2e-tests/src/e2e_harness/real_vm_target.py`;
the example profile `config-real-vm-target.yml.example` in `e2e-tests/config/`; `e2e-tests/.gitignore`;
`e2e-tests/tests/unit/test_real_vm_target.py`; `e2e-tests/pyproject.toml` when the
model needs a dependency not yet declared.

- [ ] 4.1 A typed model of `REAL_VM_TARGET` version 1: `version` exactly 1; one `host`
      mapping (`host_id`, `ssh_host`, `ssh_user`, `ssh_port`, `ssh_key_path`,
      `public_host`, `capacity` with `vcpu_count`, `ram_gb`, `disk_gb` each a positive
      integer, all required); `access.mode` admitting only `direct`; unknown fields
      refused at every level. A loader reads the section from the e2e settings and
      returns either the validated target or an explicit "not configured" result naming
      the `real-vm-target` profile and `config-real-vm-target.yml`; a present but
      invalid section raises an error naming the field. The model's field descriptions
      are the format's documentation. Declare any distribution the module imports that
      `e2e-tests/pyproject.toml` does not already declare. (D1)
- [ ] 4.2 Commit `config-real-vm-target.yml.example` in the D1 shape with RFC 5737
      addresses and fictitious names, and a header saying it is an example, that an
      environment owner renders the real file, and that the real file is never
      committed. (D1)
- [ ] 4.3 Ignore `config-real-vm-target.yml` in `e2e-tests/.gitignore`. (D1)
- [ ] 4.4 Unit (`test_real_vm_target.py`): the example loads and validates; a missing
      field, a misspelled field, and an unknown nested field each fail naming the field;
      version 2 is refused; `access.mode: relay` is refused; a zero or negative
      capacity is refused; an absent section yields "not configured" naming the profile
      and file. (scenarios "A field is misspelled", "A newer target reaches an older
      reader", "Relay access is requested under version 1")
- [ ] 4.5 Verification: `make -C e2e-tests test-unit`; `git check-ignore -v` on the
      real profile file's path in the e2e config directory names the rule; `make test`; `make
      check-packaging` when 4.1 declared a dependency.
      End-to-end: none until section 6.

## 5. SSH access helper

Delivers the domain-neutral helper the real lane proves access with (D7).

Files: a new `e2e-tests/tests/e2e/roles/helpers/ssh_access.py`; a new
`e2e-tests/tests/unit/test_ssh_access.py`; `e2e-tests/pyproject.toml` (declare
`cryptography` if it is not declared).

- [ ] 5.1 Generate an ed25519 key pair per run with `cryptography` into an owner-only
      temporary directory, returning the private key's path and the OpenSSH public
      line; the directory is removed when the run ends. (D7, "Keys")
- [ ] 5.2 Run a command over SSH with the system `ssh`: `BatchMode=yes`,
      `ConnectTimeout`, `IdentitiesOnly=yes` (so only the given key is offered, which
      the refused-key check depends on), `StrictHostKeyChecking=accept-new`, and a
      run-scoped `UserKnownHostsFile`; retry connection failures within a named bound to
      absorb the guest's cloud-init reboot; log the host-key fingerprint on first
      contact; fail when a later connection presents another host key. (D7, "Client",
      "Host key")
- [ ] 5.3 Assert a connection is refused, or times out, within a named bound — used both
      for the unrelated key and for access after teardown. (D7)
- [ ] 5.4 Probes returning the remote user (`id -un`), vCPU count (`nproc`), memory in
      GiB from `MemTotal`, and the root disk's size in GiB, with the memory tolerance a
      named constant that starts strict. (D7, "What a connection proves")
- [ ] 5.5 Unit (`test_ssh_access.py`) with a fake `ssh` on `PATH`: the argv carries every
      option in 5.2 and only the given identity; connection failures are retried until
      success and fail at the bound; a changed host key fails; refusal and timeout are
      reported as refused; probe output is parsed, including `MemTotal` in kB; the key
      directory is owner-only and gone afterwards. (D7)
- [ ] 5.6 Verification: `make -C e2e-tests test-unit`; `make test`; `make
      check-packaging` when 5.x declared a dependency.
      End-to-end: none until section 6.

## 6. The real-provisioning lane

Delivers the real VM driver and the `e2e_vm_real_provisioning` scenario (D2, D3, D4,
D4a's real stages, D5, D7, D8; delta requirement "A real-provisioning VM scenario
proves delivery on a real host" and its scenarios).

Files: `e2e-tests/tests/e2e/roles/scenarios/vms/host_registry.py`; new
`…/vms/real_compute_deal_driver.py` and `…/vms/test_real_provisioning_deal.py`;
`e2e-tests/pyproject.toml` (marker); unit tests under `e2e-tests/tests/unit/`.

- [ ] 6.1 `register_e2e_host` takes an optional SSH connection; when given, a new host is
      registered with it and an existing host whose connection differs has it replaced
      through `HostUpdate.connection`, besides the pool reconcile; without it, the mock
      lanes' placeholder is unchanged. Unit with a fake provisioning client: new host,
      unchanged host, changed connection replaced, no connection given. (D2)
- [ ] 6.2 A real VM driver implementing `ComputeDealDriver` alone: supply from the
      validated target (a pool stating the GPU-less listing shape derived from
      `capacity`, the host with its connection, one declaration with `capacity`
      unchanged); provision terms carrying the run's public key (5.1); delivery
      assertions that read the delivered access; the lease view as the VM driver reads
      it. Access mode is a parameter it reads from the target. (D2, D6, D8)
- [ ] 6.3 The module, marker `e2e_vm_real_provisioning`: skips naming the profile and
      file when the target is not configured; overrides
      `_ensure_provisioning_host_registered` with a fixture that registers nothing; its
      setup fixtures depend on the validated target and on a first real-only stage that
      reads `execution.executors` and requires the `vm` entry with `mocked=false`,
      failing with the reported executors otherwise, so nothing is written to the stack
      before both pass; it then checks the registered host's public connection against
      the target before any deal stage. (D1, D2, D4a; scenarios "No target is present",
      "The service's VM execution is mocked")
- [ ] 6.4 A real-only settlement preflight between 08a and 08b that writes
      `_settle_preflight_passed` only when the preview's chosen host
      (`_evaluate_settle_host_id`) is the target's `host_id`. (D4a; scenario "The
      settlement preview chooses another host")
- [ ] 6.5 A create-job poll between 08b and 09a: list the fulfillment reservation's jobs
      (`list_jobs(capacity_reservation_id=…)`), require exactly one, on the target host;
      poll it to terminal within a named bound; require `succeeded`; record its id and the
      guest's `vm_name`. No match, several matches, failure, and timeout each fail with
      D4's named diagnostics and the job's logs. A real-only stage after 09c checks the
      lease's `create_job_id` equals the recorded id. (D4, "Finding the jobs")
- [ ] 6.6 SSH access stages after 09c, with the section 5 helper and the delivered
      access: the delivered user, `nproc` equal to `vcpu_count`, memory within tolerance
      of `ram_gb`, root disk at least `disk_gb`; then an unrelated generated key refused
      for the delivered user. (D7; scenarios "A real deal is delivered", "An unrelated
      key is refused")
- [ ] 6.7 A teardown-job poll between 11a and 11b (exactly one job besides the create
      job, on the target host, polled as in 6.5); after 11b, a `list_vms` job on the
      target host through the VM operator client, polled within the bound, requiring a
      succeeded, well-formed list without the recorded `vm_name`; then the delivered
      access refused within its bound. (D4, "Observing the guest's absence"; scenario
      "Teardown removes the VM and its access")
- [ ] 6.8 A module finalizer, when a fulfillment was dispatched and the lane's own
      teardown did not complete: truncate this deal's lease through the site and advance
      the held workers; look for the teardown job and the guest's absence as in 6.7;
      fail naming fulfillment, reservation, create and teardown job ids, guest, and host
      where removal is not confirmed; then release the module's holds. The module never
      calls `release_reserved_resources`. (D4, "When the run fails"; scenario "The run
      fails with a guest on the host")
- [ ] 6.9 Register the marker in `e2e-tests/pyproject.toml` and in no lane variable of
      `e2e-tests/Makefile`; the module's stage list follows D4a's real-lane order.
      (D5)
- [ ] 6.10 Unit: job correlation (exactly one, none, several, a failed job, a timeout)
      and the `list_vms` absence check against fake clients; the preflight's host
      comparison; a stage-list test that the real module runs every shared stage in
      D4a's real-lane order and no mock-only stage. (D4, D4a)
- [ ] 6.11 Verification: `make -C e2e-tests test-unit`; `make test`; `make -C e2e-tests
      test-module MODULE=e2e_vm_real_provisioning ACTIVE_PROFILES=local` with no stack
      running skips naming the profile and file.
      End-to-end: `e2e_vm_real_provisioning` is in no lane; the pipeline's lanes must
      still pass. Live evidence is section 8.

## 7. Dead e2e material

Delivers D11's removals and the e2e package's own run instructions (D11, D5).

Files: `e2e-tests/.github/workflows/e2e.yml` (deleted); `e2e-tests/README.md`.

- [ ] 7.1 Delete `e2e-tests/.github/workflows/e2e.yml`, and the directory if it is left
      empty. (D11)
- [ ] 7.2 Remove `e2e-mock-happy`/`e2e-mock-failure` from `e2e-tests/README.md`, and add
      how to run `e2e_vm_real_provisioning`: copy the example profile, render or fill the
      real file, forward the stack's services to the `local` ports, run the module with
      `ACTIVE_PROFILES=local,real-vm-target`. (D5, D11)
- [ ] 7.3 Verification: no tracked file references the deleted workflow or the removed
      targets; `make check-doc-citations CHANGE=prove-real-vm-provisioning` reports
      nothing for them.
      End-to-end: none.

## 8. Live verification [log]

Requires a prepared, GPU-less, nested-virtualization KVM host and a deployed stack the
owner provides (`design.md`, "Implementation cadence"). Each item states its acceptance;
the owner supplies the output, free of addresses, project, cluster, namespace, host
names, and private paths, and it is checked against the acceptance here. Record the
public revision of this branch the run used.

- [ ] 8.1 **[log]** Host preparation with the default image setup and `gpu_passthrough`
      left `auto`, on a GPU-less host. Supplied: the play recap; `/proc/cmdline` before
      and after; `/sys/module/kvm_intel/parameters/nested` (or `kvm_amd`); `ls -l
      /dev/kvm`; whether `gpu-detection.service` exists. Acceptance: preparation
      succeeds; the kernel command line is unchanged; nested virtualization is on and
      `/dev/kvm` exists; no GPU-detection service is installed; no golden-image step ran.
      (D9)
- [ ] 8.2 **[log]** The scenario: `make -C e2e-tests test-module
      MODULE=e2e_vm_real_provisioning ACTIVE_PROFILES=local,real-vm-target` against the
      provided stack. Supplied: pytest's summary and per-stage results; the VM-execution
      check's reported executor; the create and teardown jobs' terminal statuses; the
      logged host-key fingerprint; the access probes' values against the negotiated
      shape; the unrelated key's refusal; the `list_vms` result; the post-teardown
      refusal. Acceptance: every stage passes and none skips; the values match the
      requirement's scenarios "A real deal is delivered", "An unrelated key is
      refused", and "Teardown removes the VM and its access". (D4, D7)
- [ ] 8.3 **[log]** A second run of the scenario against the same stack. Acceptance: it
      passes, the host's registration being reconciled rather than duplicated. (D2)

## 9. Closeout

The eleven parts of `openspec/README.md#plan-closeout-requirements`, in order.

- [ ] 9.1 **Comment hygiene.** Run `make check-comment-hygiene`; any finding, or a
      comment the change added that narrates history, returns the change to
      implementation.
- [ ] 9.2 **Import placement.** Confirm the imports sections 1–6 added are module-level
      or carry a recorded reason; one that should move returns the change to
      implementation.
- [ ] 9.3 **Documentation compliance.** Re-check each decision's destination below
      against `openspec/README.md`'s placement table.
- [ ] 9.4 **Narrative compression.** Shorten completed-task notes to final behaviour,
      evidence, and destinations; move debugging narrative and declined suggestions into
      `design.md` first.
- [ ] 9.5 **Roadmap currency.** `docs/development/ROADMAP.md` Goal 1: remove the gap row
      "No end-to-end scenario provisions for real…" and say in the current state that a
      VM scenario provisions a GPU-less VM on a real host from an operator's machine and
      runs in no lane. The relay-backed gap stays unowned beside
      `relay-vm-access-without-a-dashboard`.
- [ ] 9.6 **Campaign index currency.** This change's row in
      `openspec/changes/README.md` ("Reach hosts and VMs that have no inbound route");
      `make check-change-index`.
- [ ] 9.7 **Packaging.** `make check-packaging`; `make check-architecture-change
      CHANGE=prove-real-vm-provisioning`.
- [ ] 9.8 **End-to-end pipeline.** Record the pipeline run validating `HEAD`: the VM and
      bare-metal lanes (`e2e_deal`, `e2e_listing_shapes`, `e2e_bare_metal_mock_deal`)
      passing over the split stages, and `e2e_vm_real_provisioning` in no lane. The real
      lane's evidence is section 8's.
- [ ] 9.9 **Promotion.** Write: `docs/development/TESTING.md` — under "#### The
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
- [ ] 9.10 **Documentation citations.** `make check-doc-citations
      CHANGE=prove-real-vm-provisioning`; `openspec validate prove-real-vm-provisioning
      --strict`.
- [ ] 9.11 **Archival.** `openspec archive prove-real-vm-provisioning -y`, merging both
      spec deltas.
