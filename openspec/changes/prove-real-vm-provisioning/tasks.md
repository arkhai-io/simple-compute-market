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
      Done; the drivers' bodies are unchanged, only their docstrings name both parts.
      A marker base, `MockLaneStage`, identifies the mock-lane stages in source.
- [x] 1.2 Split each gated stage at its gate, as D4a names them: 07 into the shared
      on-chain escrow stage and a mock-only create-gate arm; 09a into a mock-only create
      release-and-drain and the shared advance to `active`; 10a into a mock-only
      teardown-gate arm and the shared expiry; 11b into a mock-only teardown
      release-and-drain and the shared completion and release. 08c becomes mock-only and
      `Stage00e_ProvisioningMockMode` stays mock-only. Mock-only stages take the driver
      as `MockGates`; shared stages take it as `ComputeDealDriver`. Each new class name
      says what the stage does. (D4a)
      Shared: `Stage07_OnChainEscrow`, `Stage09a_FulfillmentConvergesToActive`,
      `Stage10a_LeaseExpirySetup` (test renamed `test_10a_expire_lease`),
      `Stage11b_TeardownCompletion`. Mock-lane: `Stage07a_ArmCreateGate`,
      `Stage08b2_ReleaseCreateGateAndDrain`, `Stage09c2_ArmTeardownGate`,
      `Stage11a2_ReleaseTeardownGateAndDrain`, plus 00e and 08c. Beyond the plan, so
      that a real lane can run every shared stage: 00e's output field
      `_provisioning_mock_mode` became the lane-neutral `_provisioning_execution_confirmed`
      (00f1 and 07 require it; section 6's VM-execution check writes it), and the VM
      buyer-CLI scenarios, which declare their own stages, keep `_provisioning_mock_mode`
      on VM's `DealState`. Two more readiness fields follow 08b's pattern so a failed
      release or poll skips its dependent rather than letting it fail:
      `_create_job_completed` (08b2 → 09a) and `_teardown_job_completed` (11a2 → 11b);
      the arms write `provisioning_gate_armed` and `_teardown_gate_armed`, which the
      releases require.
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
      The stages module defines every stage in the mock-lane order, so a mock lane
      declares them all in definition order; VM's 09a2 and 09bb and bare metal's own
      stages sit where they did. That the order and assertions match the lanes'
      before the split was checked by hand against the planning commit, not by a
      test: the unit test holds the lanes to the new definition order. One step
      moved: 11b's stage-event mark is now taken after teardown's release and
      drain, which is sound because convergence and the lease watchdog are held.
      09c2's arm takes 10a's prerequisites, as the arm did inside 10a.
- [x] 1.5 Unit (`test_compute_deal_stages.py`, `stage_sources.py`):
      `test_every_compute_state_field_is_consumed_after_it_is_produced` passes with the
      new field; a new test fails if any shared stage's source references a `MockGates`
      member or the mock test client; a new test that 08b skips when
      `_settle_preflight_passed` is unset; the existing stage-list tests are updated for
      the new classes in both lanes. (D4a; scenarios "A mock lane holds a job", "A real
      lane runs the canonical deal")
      Unit, `e2e-tests/tests/unit/test_compute_deal_stages.py`: the stage-list test now
      requires a mock lane to declare every stage in definition order;
      `test_no_shared_stage_touches_a_mock_gate` (a `MockGates` member or
      `provisioning_test_client` named as an attribute, argument, or name, or the
      `MockGates` name, in a shared stage's own source — a gate reached through a
      helper the stage calls, or through another attribute such as a driver's
      `vm_rules`, is beyond it); `test_each_stage_takes_the_driver_part_its_kind_may_use` (annotations);
      `test_the_shared_driver_part_names_no_mock_gate`;
      `test_settlement_skips_until_the_preflight_before_it_passes` calls 08b's body
      with mocks and asserts the skip names the field and nothing was settled. The
      gate check was confirmed to fail by temporarily adding a gate call to shared
      09a. `stage_sources.py` needed no change.
- [x] 1.6 Verification: `make -C e2e-tests test-unit`; `make test`.
      End-to-end: `e2e_deal` (VM lane) and `e2e_bare_metal_mock_deal` (bare-metal
      lane) run the reordered stages; their outcome must be unchanged, so the
      validation pipeline's result for both lanes is this section's evidence.
      `make -C e2e-tests test-unit`: 176 passed (unit). `make test`: passed. No
      end-to-end run was made here: the pipeline's run of the lanes, which
      validation dispatches, is this section's end-to-end evidence that the
      outcome is unchanged. Markers confirmed: `e2e_deal` and
      `e2e_bare_metal_mock_deal` run the split stages; `e2e_deal_buyer_cli` and
      `e2e_buy` (VM lane) are touched only by `_provisioning_mock_mode` moving to
      VM's `DealState`, which keeps their behaviour. No CI workflow beyond the
      pipeline is owed.
      Handoff: `TESTING.md` ("The canonical compute deal", "One part, zoomed in")
      and the diagrams `docs/development/diagrams/e2e-settle-zoom.drawio` (settle
      requires "the gate is armed"), `e2e-compute-deal.drawio`, and
      `e2e-stage-discipline.drawio` still draw gates inside shared parts; 9.9's
      promotion owes them (amended there). The stage-set unit test's
      field-consumption test is held to the mock lanes: section 6's real lane
      produces none of the gate fields, so its row needs a lane-scoped variant
      (fields it produces are consumed) rather than `COMPUTE_FIELDS`.

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
      stays in the VM `conftest.py`, which a unit test imports without trouble. Two
      behaviours change for inputs no caller passes: a resource naming `gpu_model`
      without `gpu_count` used to publish one GPU and now publishes none, and one
      naming `gpu_count` without `gpu_model` used to raise `KeyError` and now yields
      a GPU-less shape; every caller states both.
- [x] 2.2 The VM driver's provision terms and required attributes name GPU fields only
      when its shape carries them; the mock lanes keep their GPU shapes, so their terms
      are unchanged. (D6)
      The VM driver's provision terms name no GPU field already. Its re-reservation
      claim is built by `claim_attributes` (`host_registry.py`), which requires
      `gpu_count` only of a GPU shape; the mock driver's shape is always its GPU
      constants (`E2E_DEAL_GPU_MODEL`, `E2E_DEAL_GPU_COUNT`), so its claim
      (`{"resource_id": …, "gpu_count": 1}`) and its count assertion are unchanged.
      No test drives the driver's re-reservation; only the helper is unit-tested.
      Handoff: `resource_gpus` and `claim_attributes` are there for section 6's real
      driver to build its GPU-less shape and claim from the target's capacity.
- [x] 2.3 Unit: a GPU-less resource (`vcpu_count: 7, ram_gb: 28, disk_gb: 160`) yields
      a shape with no `gpu` family and those three dimensions; a GPU resource yields the
      same shape as before; a resource with `gpu_count: 0` yields no `gpu` family. (D6)
      Unit, `e2e-tests/tests/unit/test_vm_shapes.py`: the GPU-less case; two GPU
      cases (one GPU with CPU, four GPUs with memory and storage), whose expected
      shapes were checked against the previous function by reading it; `gpu_count:
      0`; the predicate (model alone, count alone, both); and `claim_attributes`
      with and without GPUs.
- [x] 2.4 Verification: `make -C e2e-tests test-unit`; `make test`.
      End-to-end: `e2e_deal`, `e2e_listing_shapes` — unchanged in outcome.
      `make -C e2e-tests test-unit`: 182 passed (unit). `make test`: passed (before
      the review fixes, which touched only e2e-tests code the unit suite reran).
      `make check-packaging`: passed. No end-to-end run here; the pipeline's VM lane
      is the evidence that outcomes are unchanged. Markers
      corrected: `capacity_source_for` is called by `e2e_deal`,
      `e2e_deal_buyer_cli`, `e2e_buy`, `multi_registry`, `e2e_non_erc20_settlement`,
      and `e2e_compute_dynamic_listings`, all with GPU resources, so their shapes
      are unchanged; `e2e_listing_shapes` does not call it and is unaffected. No
      CI workflow beyond the pipeline is owed.

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
      Every golden step (`system-packages.yml`'s gcloud and Packer installs,
      `golden-image-build.yml`) is already conditioned on `vm_image_type == "golden"`.
- [x] 3.2 Validate `gpu_passthrough` (`auto`, `enabled`, `disabled`; default `auto`) as
      the role's first task, failing with the value named before anything on the host
      changes. (D9b; scenario "The override names an unknown value")
      An `assert` in `main.yml`, tagged `always` so a tag-limited run still makes
      it; the default is in `defaults/main.yml`.
- [x] 3.3 Fail before any host mutation when `/proc/cpuinfo` shows neither `vmx` nor
      `svm`, as a read-only precondition at the start of the role, replacing
      `kvm-setup.yml`'s `ignore_errors` check; after the KVM modules load in
      `kvm-setup.yml`, fail when `/dev/kvm` is absent. Both messages say hardware
      virtualization is unavailable and why. (D9a; scenario "A host without
      virtualization extensions")
      The probe (`grep -qwE '(vmx|svm)'`, `changed_when: false`) and its `fail` are
      the second and third tasks of `main.yml`, tagged `always`. `kvm-setup.yml`'s
      nested-virtualization tasks no longer test the probe's result, since the
      role cannot reach them without it.
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
      `tasks/gpu-presence.yml` sets `gpu_present` and `gpu_passthrough_configured`;
      its include and its `apply` are tagged `always`. Correction to "binding is
      unchanged": the `gpu-bind.yml` include now carries the same condition.
      Ungated, it would fail every GPU-less host: its bind-list `copy` writes into
      `/etc/vfio-bind`, which only `gpu-passthrough.yml` creates (the unit restart
      and enable are already skipped when nothing is bindable), contradicting the
      scenario "A host has no GPU" ("preparation otherwise completes"). Where
      passthrough is configured, binding is still exactly what the post-reboot
      audit finds bindable. Skipping configuration does not undo an earlier one:
      on a host an earlier preparation configured, an enabled `vfio-bind` unit
      stays enabled and its list replays at the reboot. Recorded in `design.md`
      D9b, the `physical-provisioning` delta ("attempted only where this
      configuration is applied"), and the proposal's Impact list. The play's
      closing notes and the audit's report say whether passthrough applies; the
      reboot stays unconditional, its message no longer naming the IOMMU.
- [x] 3.5 Pass `--virt-type kvm` on every `virt-install` invocation in the
      `vm-management` role, the GPU retry path included, and fail a create before
      `virt-install` when `/dev/kvm` is absent, naming KVM as unavailable. (D9a;
      scenario "KVM disappears after preparation")
      Nine invocations across `vm-create.yml` (4), `gpu-virt-install-retry.yml`,
      `gpu-virt-install-multi.yml` (2), and `gpu-virt-install-multi-retry.yml` (2).
      The KVM check is `vm-create.yml`'s first two tasks, delegated to the target
      host, before anything is created for the guest.
- [x] 3.6 Unit: structural tests that `vm-setup.yaml`'s default is `scratch`; that the
      override check and the virtualization precondition precede every task that
      changes the host; that the three passthrough includes carry the D9b condition;
      that every `virt-install` command in the role names `--virt-type kvm`; and that
      the create checks `/dev/kvm` before `virt-install`. Presence, through
      `shell_harness.py` over a fake sysfs: an NVIDIA `0300` and an AMD `0302` device are
      presence; an ASPEED BMC (`1a03`, `0300`), a QEMU emulated VGA (`1234`, `0300`),
      and a host with no display device are not. (D9)
      Unit, `test_ansible_structure.py` (`TestHostPreparationFailsClosed`): the
      scratch default; the override check, the CPU probe, and its refusal as
      `main.yml`'s tasks 0–2, tagged `always`, before the first include; the four
      gated includes (gpu-bind included) after the presence include, whose own
      and `apply` tags are `always`; the decision expression read verbatim; the
      default `auto`; and `kvm-setup.yml`'s `/dev/kvm` check after its last
      `modprobe`. The decision expression is checked as text, not evaluated: the
      project's tests run without Ansible or Jinja, and that a tag-limited run
      behaves is read from the tags, not run. Unit, `test_vm_management_contracts.py`
      (`VmCreationRequestsKvmTests`): every line naming `virt-install` as a
      command word, outside comments and task names, is `virt-install \` followed
      by `--virt-type kvm \`; the KVM stat and refusal are `vm-create.yml`'s first
      two tasks. Unit, `test_gpu_presence.py`: the five listed cases, plus no PCI
      devices, an NVIDIA audio function alone (not a GPU), a GPU beside a BMC, and
      a `bash -n` parse.
- [x] 3.7 Verification: `make -C domains/vms/provisioning/iac validate` (inventory,
      playbook syntax, tests); `make test`.
      End-to-end: none in the pipeline — the mock profile runs no playbook. Section 8's
      live run exercises 3.1, 3.3, 3.4, and 3.5 on a GPU-less host.
      `make test-provisioning-iac` (the IaC suite, unit): 82 passed, before and
      after the review fixes. `make test`: passed (before the review fixes, which
      touched only the IaC project's YAML wording and tests, rerun above). `make
      check-packaging`: passed. Not run: `validate`'s inventory and `--syntax-check` parts — Ansible
      is not installed in this environment, and running `make -C` on the IaC
      directory was refused here; no CI workflow runs them either. End-to-end
      markers confirmed: none. No CI workflow beyond the pipeline is owed.

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
      `e2e-tests/src/e2e_harness/real_vm_target.py`: `RealVmTarget` (frozen pydantic
      models, `extra="forbid"`; counts strict positive integers, so a string or a
      boolean is refused; text fields non-empty; `ssh_port` 1–65535; `AccessMode =
      Literal["direct"]`); `load_real_vm_target(settings)` returns the target or
      `TargetNotConfigured(reason)`, and raises `TargetInvalid` whose message names
      each field as `REAL_VM_TARGET.<path>`. The version is checked first, as an
      `int` (so `true` and `1.0` are refused), so a newer section is refused for its
      version alone. "Not configured" means the settings hold no section at all —
      the profile unselected, or selected with its file missing (the loader skips a
      missing include) or naming no `REAL_VM_TARGET`, which the reason says; an
      empty section is refused as invalid. Declared `pydantic>=2.0` (previously only
      transitive) and relocked; the lock gains the dependency and its specifier.
      The root `.dockerignore` excludes the real profile file in the e2e config directory,
      since the e2e image copies the whole config directory and an operator's
      checkout holds the rendered file.
- [x] 4.2 Commit `config-real-vm-target.yml.example` in the D1 shape with RFC 5737
      addresses and fictitious names, and a header saying it is an example, that an
      environment owner renders the real file, and that the real file is never
      committed. (D1)
      Committed in `e2e-tests/config/`; its `.example` suffix keeps the settings
      loader from reading it as a profile.
- [x] 4.3 Ignore `config-real-vm-target.yml` in `e2e-tests/.gitignore`. (D1)
- [x] 4.4 Unit (`test_real_vm_target.py`): the example loads and validates; a missing
      field, a misspelled field, and an unknown nested field each fail naming the field;
      version 2 is refused; `access.mode: relay` is refused; a zero or negative
      capacity is refused; an absent section yields "not configured" naming the profile
      and file. (scenarios "A field is misspelled", "A newer target reaches an older
      reader", "Relay access is requested under version 1")
      Unit, `e2e-tests/tests/unit/test_real_vm_target.py` (31 cases): the example,
      copied as `config-real-vm-target.yml` into a temporary config directory
      beside the repository's `config.yml` and `config-local.yml`, loads through
      the harness's bootstrap (`_load_bootstrap` with `CONFIG_DIRECTORY` and
      `ACTIVE_PROFILES=local,real-vm-target`) with the `local` settings still
      present, and validates; under `local` alone, and with the profile selected
      but its file absent, there is no target; an empty section loaded the same
      way is refused. The listed refusals each assert the field's
      `REAL_VM_TARGET.<path>` in the message, plus a missing `access`, an unknown
      top-level field, versions 0, `"1"`, `true`, `1.0`, an explicit null, and a
      removed key, a string or fractional capacity, and a section that is not a
      mapping; these pass the section as a plain mapping, not through the loader.
- [x] 4.5 Verification: `make -C e2e-tests test-unit`; `git check-ignore -v` on the
      real profile file's path in the e2e config directory names the rule; `make test`; `make
      check-packaging` when 4.1 declared a dependency.
      End-to-end: none until section 6.
      `make -C e2e-tests test-unit`: 213 passed (unit). `git check-ignore -v` on the
      real profile file's path names `e2e-tests/.gitignore:18`; the `.example` is
      not ignored. `make lock`, then `make check-packaging`: passed. `make test`:
      passed, before and after the review fixes.
      End-to-end markers confirmed: none. No CI workflow beyond the pipeline is
      owed.

## 5. SSH access helper

Delivers the domain-neutral helper the real lane proves access with (D7).

Files: a new `e2e-tests/tests/e2e/roles/helpers/ssh_access.py`; a new
`e2e-tests/tests/unit/test_ssh_access.py`; `e2e-tests/pyproject.toml` (declare
`cryptography` if it is not declared).

- [x] 5.1 Generate an ed25519 key pair per run with `cryptography` into an owner-only
      temporary directory, returning the private key's path and the OpenSSH public
      line; the directory is removed when the run ends. (D7, "Keys")
      `e2e-tests/tests/e2e/roles/helpers/ssh_access.py`: `ssh_session()` yields an
      `SshSession` over a `0700` temporary directory and removes it on exit;
      `new_key(name)` writes the private key `0600` (`O_EXCL`) and returns an
      `SshKey(private_key, public_line)`. Declared `cryptography>=42.0`
      (previously only transitive) and relocked.
- [x] 5.2 Run a command over SSH with the system `ssh`: `BatchMode=yes`,
      `ConnectTimeout`, `IdentitiesOnly=yes` (so only the given key is offered, which
      the refused-key check depends on), `StrictHostKeyChecking=accept-new`, and a
      run-scoped `UserKnownHostsFile`; retry connection failures within a named bound to
      absorb the guest's cloud-init reboot; log the host-key fingerprint on first
      contact; fail when a later connection presents another host key. (D7, "Client",
      "Host key")
      `SshSession.run(endpoint, key, command)`. Beyond the listed options, so the
      result does not depend on the operator's machine: `-F /dev/null`,
      `IdentityAgent=none`, `GlobalKnownHostsFile=/dev/null`, and
      `HashKnownHosts=no` (so the fingerprint can be read from the run's
      `known_hosts`). Any `ssh` failure (exit 255) is retried within
      `CONNECT_RETRY_SECONDS` (600) every `RETRY_INTERVAL_SECONDS` (5), which
      covers both a guest not yet listening and one not yet holding the key; a
      changed host key raises `HostKeyChanged` at once; a command failing once
      connected is not retried. An attempt that outlives `attempt_seconds` (70)
      counts as a connection failure. The fingerprint is the unpadded base64 SHA256
      of the trusted key's blob, the form `ssh-keygen -l` prints; that equivalence
      is read, not checked against `ssh-keygen`. The clock, the sleep, the attempt
      timeout, and the `ssh` executable are constructor parameters.
- [x] 5.3 Assert a connection is refused, or times out, within a named bound — used both
      for the unrelated key and for access after teardown. (D7)
      `SshSession.assert_refused(endpoint, key, bound=REFUSAL_BOUND_SECONDS)` (120):
      returns the refusal's reason on the first `ssh` failure; a connection still
      accepted when the bound closes fails. It is for access after teardown, where
      unreachable is the expected outcome. For the unrelated key, a timeout would
      prove nothing about the key, so `assert_key_refused(endpoint, key)` (added
      beyond the plan) requires the host to answer `Permission denied`, retrying
      an unreachable host within the connect window and failing at its end, and
      failing at once if the key is accepted. Section 6 should use it for 6.6's
      refused key. Left as is: after teardown, a host presenting another key on
      the forwarded port raises `HostKeyChanged` rather than counting as refused.
- [x] 5.4 Probes returning the remote user (`id -un`), vCPU count (`nproc`), memory in
      GiB from `MemTotal`, and the root disk's size in GiB, with the memory tolerance a
      named constant that starts strict. (D7, "What a connection proves")
      `SshSession.probe` runs one labelled command and returns a `GuestShape`. The
      root disk is the whole device holding `/` (its partition's parent, through
      `findmnt` and `lsblk`), since the partition and filesystem are smaller than the
      disk the guest was given. `MEMORY_SHORTFALL_TOLERANCE = 0.05`;
      `memory_within_tolerance(memory_gib, ram_gb)` admits up to 5% below and
      nothing above.
- [x] 5.5 Unit (`test_ssh_access.py`) with a fake `ssh` on `PATH`: the argv carries every
      option in 5.2 and only the given identity; connection failures are retried until
      success and fail at the bound; a changed host key fails; refusal and timeout are
      reported as refused; probe output is parsed, including `MemTotal` in kB; the key
      directory is owner-only and gone afterwards. (D7)
      Unit, `e2e-tests/tests/unit/test_ssh_access.py` (24 cases): the fake `ssh` is an
      executable the session is given by path rather than found on `PATH`; it records
      each argv, answers from a plan, and writes or refuses `known_hosts` entries as
      `accept-new` does, printing the refusal OpenSSH prints — that real `ssh` prints
      it is OpenSSH's behaviour, read, not tested. Covered as listed (every 5.2
      option, `HashKnownHosts` included), plus a fake clock (no test waits on
      retries), a failing command not retried, the first fingerprint logged and its
      form, an attempt hanging past its timeout (half a second of real time)
      retried by `run` and counted as refused by `assert_refused`, refusal after
      access was briefly still accepted, `assert_key_refused`'s three outcomes,
      four malformed probe outputs, and a `bash -n` parse of the probe command. The
      host keys are generated per test run. These tests cross a subprocess
      boundary to the fake from the unit directory: the e2e package has no
      integration tier, and the IaC suite's shell harness does the same. The
      probe command is not run anywhere here; section 8's live run is its first
      execution.
- [x] 5.6 Verification: `make -C e2e-tests test-unit`; `make test`; `make
      check-packaging` when 5.x declared a dependency.
      End-to-end: none until section 6.
      `make -C e2e-tests test-unit`: 238 passed (unit). `make lock`, then `make
      check-packaging`: passed. `make test`: passed (before the review fixes,
      which touched only the helper and its test; the unit suite reran).
      End-to-end markers confirmed: none. No CI workflow beyond the pipeline is
      owed. Handoff: the helper is not yet used by any scenario; section 6 builds
      an `SshEndpoint` from the delivered access, negotiates
      `new_key("buyer").public_line`, checks `GuestShape` against the target's
      capacity with `memory_within_tolerance`, refuses `new_key("unrelated")` with
      `assert_key_refused`, and after teardown calls `assert_refused` with the
      buyer key. The fake-ssh fixture in the test is local to it; a real-lane
      unit test needing one can lift it into a shared helper.
- [x] 5.7 Round-1 triage fix (25 F1): `assert_refused` must see the refusal by the time
      its bound closes, and 5.3's "returns the refusal's reason on the first `ssh`
      failure" overshot it by up to one attempt plus a retry interval.
      `ssh_access.py`: `assert_refused` starts no attempt once the bound has passed,
      caps each attempt's timeout at the time left, fails a refusal that returns after
      the bound, and fails an attempt cut short by the bound that runs out of time
      (that shows only that the connection had not finished); a full-length attempt's
      timeout still counts as refused. `run` and `assert_key_refused` keep full-length
      attempts — their window bounds when the last attempt starts, since cutting a
      connected command short would fail it for a reason unrelated to connecting —
      and every retry sleep stops at the window's end (`_pause`, never negative).
      `_attempt` returns `None` when it runs out of time.
      Unit, `test_ssh_access.py` (29 cases): the fake's plan steps can declare
      `elapse`, simulated seconds the attempt takes, which the fake clock adds, so an
      attempt runs past a deadline without the test waiting. New: no refusal attempt
      starts after the bound; a refusal returned after the bound fails; an attempt cut
      short by the bound (half a second of real time) is not a refusal; `run`'s and
      `assert_key_refused`'s sleeps stop at the window. Each fails on the code before
      the fix (reasoned from it, not run).
      `make -C e2e-tests test-unit`: 243 passed (unit). `make test`: passed.
      `make check-packaging`: passed. `make check-comment-hygiene`: passed.
      Fresh-context check of the diff: no blocking defect. Fixed: a retry sleep
      could go negative where an attempt cut short returned after the bound (clamped
      in `_pause`); a timing-dependent call count in the cut-short test (removed);
      `_attempt`'s docstring now says a timeout means the host answered and the
      connection did not finish. Declined: a full-length timeout whose kill overhead
      lands milliseconds past the bound fails as "only after" — consistent with the
      bound as stated; `bound <= 0` fails without an attempt — no caller passes one.
- [x] 5.8 Round triage fix (53 F1): `assert_refused` counted an attempt that ran its
      full time out as refused. `ssh` gives up within its `ConnectTimeout` when nothing
      answers, so such an attempt shows something answered and stayed connected, and
      after teardown that is what 11d must catch. 5.3's "refused, or times out", 5.5's
      "counted as refused by `assert_refused`", 5.7's "a full-length attempt's timeout
      still counts as refused", and D7's "refused or timed out" now read as `ssh`'s own
      failure: refused, or its `ConnectTimeout` expiring (exit 255).
      `ssh_access.py`: only an `ssh` failure is a refusal. An attempt that runs out of
      time, full-length or cut short, is retried within the bound like an accepted
      connection, and the check fails when the bound closes, "not shown to refuse" when
      the last attempt had not finished, "still accepted" otherwise. The other 5.7 rules
      hold. The live runs' 11d reasons were `ssh`'s own `Connection timed out` (8.2,
      8.3), so they meet the rule unchanged.
      Unit, `test_ssh_access.py` (32 cases): the combined hang test split in two, `run`
      retrying a hang and `assert_refused` retrying one and returning the refusal that
      follows; new: a hang lasting to the bound fails as not shown, and a hang then an
      accepted connection fails as still accepted. The first two fail on the code
      before the fix (reasoned from it, not run). `make -C e2e-tests test-unit`: 315
      passed (unit). `make test`: passed. `make check-packaging`: passed. `make
      check-change`: passed. No dependency change. End-to-end: none; 11d runs only
      by hand against a real host (section 8), and the fix needs no rerun as above.
      Fresh-context check of the diff: no blocking defect. Fixed: the failure message
      and docstring claimed a cut-short attempt was still connected, which only a
      full-length one shows; no test covered a hang then an accepted connection
      (added). Left: the hang tests wait half a second of real time per attempt, as
      5.5 records.

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
      `host_registry.py`: a connection differs when its kind, version, or any public
      field the submission states differs (a stored connection also carries its
      kind's defaults); `provision_e2e_executor` passes `connection` through. Unit,
      `e2e-tests/tests/unit/test_real_vm_lane.py`, over a fake registry: the four
      listed cases, and a host registered with another port is not the target.
- [x] 6.2 A real VM driver implementing `ComputeDealDriver` alone: supply from the
      validated target (a pool stating the GPU-less listing shape derived from
      `capacity`, the host with its connection, one declaration with `capacity`
      unchanged); provision terms carrying the run's public key (5.1); delivery
      assertions that read the delivered access; the lease view as the VM driver reads
      it. Access mode is a parameter it reads from the target. (D2, D6, D8)
      `scenarios/vms/real_compute_deal_driver.py`: `RealVmComputeDealDriver` on a new
      `VmDealDriverBase` in `compute_deal_driver.py`, which now holds what both VM
      drivers supply alike (settle response, delivery, settlement selection, lease
      view, release) and no gate; the mock driver adds its gates on it, unchanged in
      behaviour. Fixed ids `compute-e2e-real-pool` and `compute-e2e-real-001`, so a
      rerun reconciles them (the site's declaration write is an upsert). The pool's
      shape is the listing's own `capacity_source_for` shape, passed in. The
      delivered access is the settle status's `connection_details` (host, port,
      user), and its host must be the target's `public_host` under `direct` access.
      Beyond the plan: the shared `DealLease.resource_consumed` read only the site's
      GPU mirror, which a GPU-less declaration does not state (`value` and
      `available_units` are null), so 10b would have failed; it now falls back to
      the declared and available dimension maps when the mirror is absent, unchanged
      for a GPU declaration (unit, both cases). 11b's re-reservation claims the whole
      capacity (`resource_id` and the three dimensions), so a reservation coming
      back shows all of it released.
- [x] 6.3 The module, marker `e2e_vm_real_provisioning`: skips naming the profile and
      file when the target is not configured; overrides
      `_ensure_provisioning_host_registered` with a fixture that registers nothing; its
      setup fixtures depend on the validated target and on a first real-only stage that
      reads `execution.executors` and requires the `vm` entry with `mocked=false`,
      failing with the reported executors otherwise, so nothing is written to the stack
      before both pass; it then checks the registered host's public connection against
      the target before any deal stage. (D1, D2, D4a; scenarios "No target is present",
      "The service's VM execution is mocked")
      `scenarios/vms/test_real_provisioning_deal.py`. Correction: the holds pause the
      shared services when pytest sets them up, before any stage runs, so a stage
      cannot precede them. The check is therefore a module fixture,
      `real_vm_execution` (on `real_vm_target`, which skips or raises
      `TargetInvalid`), listed first in `usefixtures`, before the holds; stage 00e1
      makes the same check (`vm_executor_is_real`) to record it in the results and
      write `_provisioning_execution_confirmed`. That the target and the check are set
      up before every hold is pinned from pytest's setup plan (unit,
      `test_scenario_cleanup_order.py`); the mocked-service path has not been run
      against a stack. 00f2 reads the registered host back
      and requires its pool, enablement, and whole public connection to be the
      target's. The module also declares its own listing stages (02b create paused,
      03b resume and registry read) for a GPU-less offer of the whole capacity, and
      its own 09a2 over `step_listing_reconciliation`, extracted unchanged from the
      mock deal's 09a2 into `scenarios/vms/conftest.py`, which the mock deal now
      calls too; it omits the mock deal's 03a and 09bb. Its state is
      `RealVmDealState` (`_target_host_confirmed`, `create_job_id`, `vm_name`,
      `delivered_access`, `_guest_absent`).
- [x] 6.4 A real-only settlement preflight between 08a and 08b that writes
      `_settle_preflight_passed` only when the preview's chosen host
      (`_evaluate_settle_host_id`) is the target's `host_id`. (D4a; scenario "The
      settlement preview chooses another host")
      Stage 08a2. Unit: its body run with the target, both outcomes.
- [x] 6.5 A create-job poll between 08b and 09a: list the fulfillment reservation's jobs
      (`list_jobs(capacity_reservation_id=…)`), require exactly one, on the target host;
      poll it to terminal within a named bound; require `succeeded`; record its id and the
      guest's `vm_name`. No match, several matches, failure, and timeout each fail with
      D4's named diagnostics and the job's logs. A real-only stage after 09c checks the
      lease's `create_job_id` equals the recorded id. (D4, "Finding the jobs")
      Stage 08b3 over `JobWatch` (`JOB_BOUND_SECONDS` 1800, polled every 10 s, the
      last sleep stopping at the bound; clock and sleep injected); the reservation is
      read from the fulfillment's status, and the guest from the create result's
      `detail.vm_name`. Stage 09c3 checks the lease.
- [x] 6.6 SSH access stages after 09c, with the section 5 helper and the delivered
      access: the delivered user, `nproc` equal to `vcpu_count`, memory within tolerance
      of `ram_gb`, root disk at least `disk_gb`; then an unrelated generated key refused
      for the delivered user. (D7; scenarios "A real deal is delivered", "An unrelated
      key is refused")
      Stages 09d (probe; logs the endpoint, the host key's fingerprint, the shape, and
      the capacity) and 09e (`assert_key_refused`). The key pair and known hosts live
      in a module `ssh_session`; the buyer key is negotiated in the provision terms
      and the settlement preview.
- [x] 6.7 A teardown-job poll between 11a and 11b (exactly one job besides the create
      job, on the target host, polled as in 6.5); after 11b, a `list_vms` job on the
      target host through the VM operator client, polled within the bound, requiring a
      succeeded, well-formed list without the recorded `vm_name`; then the delivered
      access refused within its bound. (D4, "Observing the guest's absence"; scenario
      "Teardown removes the VM and its access")
      Stages 11a3, 11c, and 11d. The list is read from the result's `ansible_result`
      (the playbook's `vm_list_data`), not its top-level `vms`, which the VM codec
      omits when no guest is listed; well-formed is `result_kind` `vm_list`, action
      `list`, status `success`, and `vms` a list of entries each naming a guest.
- [x] 6.8 A module finalizer, when a fulfillment was dispatched and the lane's own
      teardown did not complete: truncate this deal's lease through the site and advance
      the held workers; look for the teardown job and the guest's absence as in 6.7;
      fail naming fulfillment, reservation, create and teardown job ids, guest, and host
      where removal is not confirmed; then release the module's holds. The module never
      calls `release_reserved_resources`. (D4, "When the run fails"; scenario "The run
      fails with a guest on the host")
      `recover_failed_run`, listed after the holds, acts when settlement was
      submitted (`_settle_preflight_passed`) and `_guest_absent` is not set — keyed
      to submission because 08b records `fulfillment_id` only after its own
      assertions, while the create already runs — through
      `RealVmComputeDealDriver.tear_down_after_failure`: the fulfillment from the
      state or else the settle status (none: nothing dispatched, nothing done); a
      create still `dispatching` is waited for and converged to `active`, since
      release waits for an in-flight create (`ReleaseAction.CREATE_IN_FLIGHT`) and
      convergence is held; an `active` lease whose end is still ahead is truncated
      (one 10a already back-dated is not, since the site refuses a later end); the
      watchdog is stepped where no release has begun; convergence advanced to
      `tearing_down` only from `teardown_dispatch_pending`; the teardown job waited
      for; `torn_down` and a watchdog step; then the list check. Unit,
      `test_real_vm_lane.py`, over a stateful fake of the service's convergence and
      watchdog steps: an in-flight create recovered with no recorded fulfillment, a
      back-dated lease not truncated again, a guest still listed failing naming
      fulfillment, reservation, both jobs, guest, and host, and no fulfillment
      dispatched. Whether the real service's steps move as the fake's do is shown
      only by a failing live run. A settlement refused at 08b reports a spurious
      "recover it by hand" where its settle status cannot be read.
- [x] 6.9 Register the marker in `e2e-tests/pyproject.toml` and in no lane variable of
      `e2e-tests/Makefile`; the module's stage list follows D4a's real-lane order.
      (D5)
      The Makefile's lane comment says the marker is in no lane and why.
- [x] 6.10 Unit: job correlation (exactly one, none, several, a failed job, a timeout)
      and the `list_vms` absence check against fake clients; the preflight's host
      comparison; a stage-list test that the real module runs every shared stage in
      D4a's real-lane order and no mock-only stage. (D4, D4a)
      Unit, `test_real_vm_lane.py`: correlation as listed plus a job on another host
      and the teardown found besides the create; the list check (absent, empty,
      present, five malformed lists, a failed list job); `vm_executor_is_real`
      (real beside a mocked bare-metal one; mocked, absent, none); the delivered
      endpoint and three incomplete ones; the create's guest name. Unit,
      `test_compute_deal_stages.py`: the real lane's row joins the generic checks
      (state base, prerequisites produced earlier, reads produced first, one
      producer per field, own stages using declared fields); a test pins the real
      lane's whole order (`REAL_LANE_ORDER`) and that it runs every shared stage in
      definition order and no mock-lane stage; and a lane-scoped consumption test
      (every field it produces is read by a later stage or the module's recovery
      fixture). Unit, `test_scenario_cleanup_order.py`: the real module's holds are
      released after its other cleanup (the existing check); it takes
      `ensure_storefront_resumed` and `recover_failed_run` in place of the lane
      cleanup, never `release_reserved_resources`, and sets up its target and
      execution check before any hold. Not unit-tested: the driver's composition of
      these (`create_job`, `teardown_job`, `delivered_access`'s address check, the
      re-reservation claim), and the stored connection view 00f2 compares against,
      which the fake registry builds by hand from the SSH kind's model.
      Correction to 6.7: 11d requires `_teardown_job_completed`, not 11c's
      `_guest_absent`, so access ending is asserted whether or not the guest is
      still listed.
- [x] 6.11 Verification: `make -C e2e-tests test-unit`; `make test`; `make -C e2e-tests
      test-module MODULE=e2e_vm_real_provisioning ACTIVE_PROFILES=local` with no stack
      running skips naming the profile and file.
      End-to-end: `e2e_vm_real_provisioning` is in no lane; the pipeline's lanes must
      still pass. Live evidence is section 8.
      `make -C e2e-tests test-unit`: 293 passed (unit). `make -C e2e-tests
      test-module MODULE=e2e_vm_real_provisioning ACTIVE_PROFILES=local` with no
      stack: 37 skipped, each naming the `real-vm-target` profile and
      `config-real-vm-target.yml`, none erroring at setup. `make test`: passed
      (before the review fixes, which touched only e2e-tests files the unit suite
      reran). `make check-packaging`: passed. `make check-change`: passed.
      Fresh-context check of the diff: no blocking defect. Fixed: recovery could not
      remove a guest whose create was still in flight, re-truncated a lease 10a had
      back-dated, depended on a field 08b writes last, and looked the create job up
      after the teardown existed; 11d skipped when 11c failed; the shared state's
      `_supply_seeded` docstring; the setup order pinned by a test. Owed at 9.9:
      TESTING.md's real-lane subsection says the lane waits on real jobs by polling
      within a bound, the one wait D4 adds to the stage discipline. End-to-end markers
      confirmed: `e2e_deal` runs the reworked mock driver (its non-gate parts moved
      to the base) and the extracted 09a2; every VM lane module is touched by the
      `register_e2e_host` and `DealLease` changes, unchanged for their inputs; the
      pipeline's VM lane is that evidence. `e2e_vm_real_provisioning` runs in no
      lane. No CI workflow beyond the pipeline is owed.
      Handoff, unproven until section 8's live run: the storefront accepting an
      explicit GPU-less listing through `create_listing` (the GPU-less deal so far
      ran only through a publication-derived listing); the admin re-reservation
      with dimension attributes; a real teardown finishing inside the watchdog's
      300 s grace after 10a's one-minute back-date (10a to 11b, on the host); and the
      probe command's first execution.
- [x] 6.12 Round triage fix (53 F2): the comment on `provision_terms`'s negotiated key
      in `real_compute_deal_driver.py` said it is "the only one that can pass", the
      claim D7 narrowed (10 F4). It now says the access checks show that the key
      negotiated here was installed. Checks as 5.8's.

## 7. Dead e2e material

Delivers D11's removals and the e2e package's own run instructions (D11, D5).

Files: the e2e package's nested `e2e.yml` workflow (deleted); `e2e-tests/README.md`.

- [x] 7.1 Delete the e2e package's nested `e2e.yml` workflow, and the directory if it is
      left empty. (D11)
      Deleted with `git rm`; it was the directory's only file, so the directory is
      gone. The mentions of its path in `proposal.md`, `design.md`, and here were
      reworded, since a citation of a path that no longer exists is a blocking
      defect.
- [x] 7.2 Remove `e2e-mock-happy`/`e2e-mock-failure` from `e2e-tests/README.md`, and add
      how to run `e2e_vm_real_provisioning`: copy the example profile, render or fill the
      real file, forward the stack's services to the `local` ports, run the module with
      `ACTIVE_PROFILES=local,real-vm-target`. (D5, D11)
      The mock-provisioning section, which also ran the dead `mock_provisioning_happy`
      marker, is replaced by a short "End-to-end lanes" note and a "Real VM
      provisioning" section: what the scenario proves, why it is in no lane, the
      prepared GPU-less host, the three steps, and the skip and failure behaviour.
      Beyond the plan: the "CI/CD" section described the deleted workflow
      (a staging profile, a 02:00 nightly, report artefacts); it now points to the
      root `E2E` workflow and `TESTING.md`.
- [x] 7.3 Verification: no tracked file references the deleted workflow or the removed
      targets; `make check-doc-citations CHANGE=prove-real-vm-provisioning` reports
      nothing for them.
      End-to-end: none.
      A repository search (`e2e-tests/\.github`, `e2e-mock-happy`, `e2e-mock-failure`)
      finds them only in this change's own documents, where the workflow is no longer
      named by path; the archived changes' references are to the root workflow, which
      remains. `make check-doc-citations CHANGE=prove-real-vm-provisioning`: passed
      after the rewording (before it, it reported two mentions of the deleted file).
      That check reads only the change's documents and only paths with a file suffix,
      so the proposal's directory mention was found by the fresh-context review, and
      the README's two relative links (the root workflow and TESTING.md's section 4
      anchor) were checked by hand. `make test`: passed. End-to-end markers: none. No
      CI workflow is owed. Fresh-context check: fixed the README's lane description
      (a lane replaces its stack and leaves it running; `PROVISIONING_MODE` decides
      the profile), its copy step's wording, the proposal's directory citation, and
      these notes.

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
      The name is kept; the unit is `"{{ 'ssh' if ansible_os_family == 'Debian' else
      'sshd' }}"`. The fact is there: `vm-setup.yaml`, the only playbook using the
      role, gathers facts (Ansible's default), and the handler runs only in its play.
- [x] 7A.2 Unit, `test_ansible_structure.py`: the handler names `ssh` for the Debian
      family and `sshd` otherwise through `ansible_os_family`, and has no
      `ignore_errors`; every `notify` of it in the role resolves to a handler that
      exists; no task or handler in `roles/vm-setup` restarts a unit literally named
      `sshd` outside that expression (the golden-only `templates/` and `files/` are
      excluded and say so in the test). Mutation check: restoring `ignore_errors` or the
      literal `sshd` fails the test. (D9d)
      Unit, `TestSshRestartHandler` (4 cases): the handler's `systemd` name is the
      expression read verbatim (as text — the suite runs without Ansible or Jinja, so
      neither branch is evaluated, and an equivalent spelling such as
      `ansible_facts['os_family']` would fail it), its state `restarted`, and it has
      neither `ignore_errors` nor `failed_when`; every `notify` in the role's tasks and
      handlers, blocks and list notifies included, names a handler (or a `listen`);
      every task whose module's `path` or `dest` is `/etc/ssh/sshd_config` notifies
      the restart, and there is one; no `systemd`/`systemd_service`/`service` task
      or handler, under any collection prefix, names `sshd` in its mapping-form
      arguments, and no `shell`/`command`/`raw` line (string, `cmd`, or `argv`)
      hands `systemctl`, `service`, or `invoke-rc.d` a unit named `sshd`, whatever
      its action or flags, within one command of the line. Not covered: free-form
      module arguments (`name=sshd`) and arguments under `args:`; a command split by
      a backslash continuation; a `script` task's file; a unit named through a
      variable; a write to `sshd_config` by a shell command, or to a drop-in under
      `sshd_config.d/` (none is written). Correction to the plan's wording: `templates/` is not wholly
      golden-only (the tunnel client, vfio-bind, and rescue entry templates are
      not); the test reads only what the role runs, tasks and handlers, and its
      comment says the one template restarting `sshd`, `user-data.j2`, is rendered
      only by the golden build. Mutation checks, each run and reverted:
      `ignore_errors: yes` restored fails the handler case; the literal `sshd`
      restored fails it and the literal case; a notify of a missing handler and a
      `systemctl restart sshd.service` shell task fail the notify and literal cases;
      the hardening's notify removed fails the `sshd_config` case; and an
      `ansible.builtin.command` `argv` of `systemctl --no-block restart fail2ban
      sshd` fails the literal case.
- [x] 7A.3 Verification: `make test-provisioning-iac` (the IaC suite, unit); `make
      test`.
      End-to-end: none in the pipeline — the mock profile runs no playbook. 8.4's live
      re-run of host preparation exercises it.
      `make test-provisioning-iac` (unit): 86 passed. `make test`: passed (before the
      fresh-context fixes, which touched only the handler's comment and the IaC test,
      rerun above). `make check-packaging`: passed. `make check-change`: passed. Not
      run: `validate`'s inventory and `--syntax-check` parts, as in 3.7 (no Ansible
      here). End-to-end markers confirmed: none. No CI workflow is owed.
      Fresh-context check: no guidance break. Fixed: `check-packaging` unrecorded;
      the literal-`sshd` scan missed flags, several units, `invoke-rc.d`,
      collection-prefixed modules, and `argv`; the notify check did not tie the
      restart to the `sshd_config` write; the handler's comment now says it usually
      runs after the reboot and matters on a run that skips it. Declined: merging
      `_flatten` into `walk`, which collects findings rather than tasks. A second
      check: no blocking defect; fixed the comment's claim that a run flushing
      handlers before the reboot depends on the restart (the reboot still follows),
      "Ubuntu 24.04 has no `sshd` unit" (true of a default install, where
      `ssh.service` is socket-activated and its alias absent), the literal case's
      name (it flags any action, not only restarts), the handler case's tolerance of
      a collection prefix, and the list of what is not covered.
      Handoff for 8.4: the handler runs only when the hardening block changes
      `sshd_config`, so a re-run on the host 8.1 prepared shows `ignored=0`
      vacuously; 8.4 needs a host whose `sshd_config` lacks the block (a fresh
      instance). The playbooks run from the provisioning service's image, so the
      run needs an image built from a revision containing this section, as 8.1 used
      one built from `8638567c8`.

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
      `_relay_reported(payload)` gates it; a new `_is_port` accepts an `int`, or its
      ASCII decimal text (surrounding whitespace allowed), in 1–65535, and refuses a
      `bool`. The replaced value keeps the type the playbook printed, as before.
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
      Unit, `test_vm_codec.py`: (a) `test_a_disabled_relay_keeps_the_forwarded_port`,
      `enabled` as `False` and `"False"`, `remote_port` as `"N/A"` and, beyond the
      plan, a port number, so the enabled gate is pinned on its own; (b) the existing
      test, its block now `enabled: True` with a `relay_addr` (the playbook emits no
      `subdomain`, which it carried); (c)
      `test_an_enabled_relay_without_a_port_keeps_the_forwarded_port` over `"N/A"`,
      `""`, `"0"`, `"65536"`, `"40001x"`, a non-ASCII digit, `True`, `4.5`, and
      `None`; (d) `test_a_direct_create_reports_the_port_it_forwarded` and (e)
      `test_a_relayed_create_reports_the_relay_and_its_leased_port`, both through
      `AnsibleJobExecutor` with a stand-in runner (`_executed`, now shared with the
      existing executor test), over output built by `_create_fact_output`: the
      provided-key `vm_creation_data` fact of `vm-create.yml` field for field,
      printed as `json-output.yml` prints it under the YAML result format both
      `ansible.cfg` files select — the `debug: var:` task as bare YAML, then the
      `to_nice_json` string as a `msg: |-` block — so the codec reads it through
      `extract_vm_fact`'s `msg` fallback, as it reads a real run's (test (d) asserts
      the output has no `"vm_creation_data":` key for the named-fact branch to take).
      They are unit tests of the codec through its executor seam, not runs of the
      playbook: the fact's shape and its printing were read from `vm-create.yml`,
      `json-output.yml`, and the `ansible.cfg` files, not captured from Ansible.
      Assumed, as ansible-core 2.19's native templating renders them (the version
      8.4's image ran; the image's pin also admits 2.17 and 2.18, whose rendering was
      not checked): `enabled` prints as a JSON boolean (the codec accepts either
      form, and (a) covers both), and a leased `remote_port` as an integer, which
      (e) pins in the detail. Mutation checks, each run and
      reverted: the unconditional replacement restored fails (a)'s four cases, (c)'s
      seven non-empty non-port values, and (d), rerun after the printed form was
      corrected; the enabled gate kept and the port test replaced by the old
      truthiness test fails (c)'s seven; the port test kept and the enabled gate
      dropped fails (a)'s two port-valued cases. `""` and `None` pass under each of
      these, since the old truthiness test skipped them too.
- [x] 7B.3 Verification: `make test-provisioning-adapter` (the adapter's suite, unit);
      `make test`; `make check-packaging`.
      End-to-end: none in the pipeline — the mock lanes never interpret playbook
      output. 8.2's and 8.3's runs exercise it against a real host.
      `make test-provisioning-adapter` (unit): 273 passed, before and after the
      fresh-context fixes. `make test`: passed (before those fixes, which touched only
      the codec's comment and the adapter's test, rerun above). `make
      check-packaging`: passed. `make check-change`: passed. Fresh-context check: no
      layering, packaging, test-level, or placement break; the codec correct against
      the buyer-key create fact (the generated-key fact's block it does not read; see
      the handoff). Fixed: (d) and (e) printed the fact as JSON, which took
      `extract_fact`'s named-fact branch, while the YAML result format the
      `ansible.cfg` files select makes a real run's fact read from its `msg` block;
      the fixture's `gpu` block lacked three of the fact's fields, so "field for
      field" was false; `design.md` D4b said the mock lanes never interpret playbook
      output; a mutation's wording; the codec comment now names the buyer-key fact,
      since the generated-key fact names its block `relay`; the codec comment's
      wrapping. A second check found the fixture's output takes the codec's real
      parsing path and the mutation counts right; fixed: this note's claim about
      both facts, the undisclosed integer `remote_port` assumption, and 8.2's note.
      Declined: calling `VmAnsibleCodec.interpret` directly in (d) and (e) rather than
      through the executor — the plan names the executor seam, the existing executor
      test uses it, and the stand-in runner keeps it a unit test.
      End-to-end markers, correcting the plan's "the mock lanes never interpret
      playbook output" above: the mock lanes' create output does pass through this codec (the
      mock executor's output is parsed by the adapter's real result path), and the
      VM scenarios' mock create facts (`compute_deal_driver.py`'s
      `_CREATE_RESULT_STDOUT` and its copies in `e2e_deal_buyer_cli`, `e2e_buy`,
      `e2e_listing_shapes`, and `e2e_non_erc20_settlement`) carry `"frp":
      {"enabled": false}` with no `remote_port`, which neither the old rule nor the
      new one replaces the port from. Those lanes are therefore unchanged in outcome
      and are no evidence for this section;
      `e2e_vm_real_provisioning`, in no lane, is, through 8.2 and 8.3. No CI
      workflow is owed.
      Handoff: the generated-key create fact (`vm-create.yml`, the variant used when
      no buyer key is given) names its relay block `relay`, not `frp`, so the codec
      reads no relay from it and such a relayed create reports no evidence. The
      market always negotiates a buyer key, so the real lane never takes that
      variant; left as it is, outside D4b, for the relay-backed follow-up to weigh.

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
      As planned. That the site reads a claim's `dimensions` as its quantity request
      and matches every other key against the resource was read from
      `kit/site/src/market_site/ledger.py`, not run here; 8.2 is its first live use.
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
      `listing_for_run` on the driver, over `storefront_admin_client`: pages of 200
      (the storefront's largest; a short page ends the read), selecting listings whose
      `listing_resource.resource_id` is `REAL_RESOURCE_ID`; adoption requires one
      listing, `status` `open`, whose `vcpu_count`, `ram_gb`, and `disk_gb` equal the
      target's capacity. Any other status fails as `closed` does. The failure names
      each listing's id, status, paused flag, and stated shape, and the capacity, and
      says closing a listing does not free its source: rerun with the target the
      listing was made for, or against a fresh stack. 02b adopts or creates and logs
      which. Correction to "a refused adoption leaves the stack as the previous run
      left it": that holds of listings; 00f1, before 02b, still reconciles the host's
      connection and the declaration's capacity (D2), so a target whose capacity
      changed between runs has its declaration rewritten and its old listing refused,
      and only the old target or a fresh stack recovers it.
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
      Unit, `test_real_vm_lane.py` (10 new cases): (a) the claim is exactly
      `resource_id` and `dimensions` equal to the target's capacity; (b)–(i) as
      listed, over `FakeStorefront` (paged `list_listings`, `pause_listing`,
      `get_listing` over `storefront_client.models.ListingSummary` rows), (e)–(g)
      asserting the message names the capacity and each listing's id, status,
      paused flag, and shape, and that nothing was paused; (i) puts the listing at
      201st behind 200 on another resource and asserts the reads `(200, 0)`,
      `(200, 200)`. Beyond the plan: 02b's body, called with the fakes, records an
      adopted listing and calls no `create_listing`; 02b's create path is not
      unit-tested. Mutation checks, each run and reverted: the attributes-only claim
      restored fails (a); the shape comparison dropped fails (g); the status check
      dropped fails (e). That the storefront's stored `listing_resource` keeps the
      `resource_id` and the three counts the listing was created with is read from
      the create path, not tested; 8.3 is its first live use.
- [x] 7C.4 Verification: `make -C e2e-tests test-unit` (unit); `make test`; `make
      check-change CHANGE=prove-real-vm-provisioning`. No dependency or lock changes, so
      no packaging check is owed beyond `make test`'s.
      End-to-end: `e2e_vm_real_provisioning`, in no lane, through 8.2 and 8.3 against a
      real host; no pipeline lane runs it, and the mock lanes' drivers and stages are
      untouched, so their results are no evidence for this section. No CI workflow is
      owed.
      `make -C e2e-tests test-unit` (unit): 303 passed, before and after the
      fresh-context fixes. `make test`: passed (before those fixes, which touched only
      the driver's failure message and comments, 02b's docstring, and the unit test,
      rerun above). `make check-change`: passed. End-to-end markers confirmed: only
      `e2e_vm_real_provisioning`, which runs in no lane. No CI workflow is owed.
      Fresh-context check: no layering, import, packaging, test-level, or comment
      break; the paging, the shape comparison, and the message correct. Fixed: the
      message assertion passed without naming the capacity in two of three cases (it
      now matches the capacity and each listing's id, status, paused flag, and shape);
      a redundant claim assertion and a duplicated capacity literal; 02b's docstring
      stated the refusal too narrowly; the message names how an operator recovers;
      the page constant's comment; the 7C.2 correction above.
      Handoff for 8.2 and 8.3: the fix stays within `e2e-tests/`, so the runs need a
      checkout of a public revision including this section against a fresh stack of
      `f52f07973`'s published images and chart. A fresh stack's 02b creates its
      listing; the rerun's 02b should log the earlier run's listing adopted.

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
      The mark is taken in 08b, before `settle_evm`, by a new helper
      `latest_stage_event_id(client, negotiation_id=…)` in `helpers/compute_deal.py`:
      the id of the latest stage event naming the deal's negotiation, read page by page
      through the storefront's `truncated` flag (11b's own mark reads one page of 500
      only; left as it is). The mark is scoped to the negotiation, the same filter the
      wait applies, so it is a few events rather than the whole log; it therefore
      passes over nothing of another deal's on its own — the negotiation filter does
      that, and the mark excludes only this negotiation's earlier events, of which
      none is a `job_submitted` — and the protocol's docstring says a driver waiting
      from it must filter by the same negotiation. 08b now takes the
      `storefront_admin_client` fixture, which every lane running it provides (11b
      already takes it). Correction to "bare metal's driver is untouched": the mark
      reaches the driver as a keyword, `settle_dispatched(…, events_since=…)`, on
      `ComputeDealDriver`, so bare metal's `settle_dispatched` accepts it and its
      docstring says it goes unused (its fulfillment exists when settle returns).
      Its driver's behaviour is unchanged, but the bare-metal lane's 08b now makes the
      signed read of the storefront's event log for the mark, which no unit test runs
      against bare metal's storefront. The other route, a `ComputeDealState`
      field 08b writes and the driver reads, fails the mock lanes'
      `test_every_compute_state_field_is_consumed_after_it_is_produced`, which counts
      only stages' reads, and a driver method 08b calls first would have needed a bare
      metal body too.
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
      (60, the driver's `dispatch_bound`), waiting through the storefront client's own
      `wait_for_stage_event` (negotiation filter, no mark: only this settlement logs
      that negotiation's `job_submitted`) and catching its `TimeoutError` so the status
      is read again either way. Read from the VM storefront (`load_vm_settlement_job`,
      looked up by this lane's escrow uid), settle status reports the delivery record
      merged over the escrow row where a delivery is recorded (inserted `provisioning`,
      then `ready`, `failed`, or `refunded`), else the escrow row alone (inserted
      `provisioning` by the settle path before it checks the settlement's evidence, so
      a settlement refused there also reads `provisioning`; or `refunding`, inserted by
      a refund begun before any escrow row; later `refunded`), else 404. (Its refund
      evidence branch is keyed by negotiation id, which this lane's reference is not.)
      The rule is written the other way from the plan's wording, so it fails closed:
      `UNDISPATCHED_SETTLE_STATUSES` is `refunding` alone, the one status that shows no
      delivery was recorded, and every other status, one added later included, is
      taken as accepted. A 404 is a settlement the storefront holds no record of yet:
      recovery waits for the deal's `job_submitted` as for an accepted status, since a
      submission that failed on the client's side may still be being recorded, and
      returns with nothing to tear down only where none comes within the bound and the
      status is still unrecorded; where the event came, an unrecorded or
      fulfillment-less status fails. That removes the spurious "recover it by hand"
      6.8 noted for a settlement refused at 08b, at the cost of a wait of the bound.
      The cost of failing closed, each a wait of the bound and then a failure asking an
      operator to look though nothing was dispatched: a settlement refused at the
      evidence check (`provisioning`); one refunded before delivery once the refund
      completes (`refunded`); a delivery that failed before the provisioning service
      began a fulfillment (`failed`, no fulfillment); and a delivery scheduled to start
      later than the bound. The escrow and negotiation join the recovery failure's
      named fields for every failure, not only this one.
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
      Unit, a new `e2e-tests/tests/unit/test_vm_deal_dispatch.py` (4 cases), over
      `FakeEventLog`, a fake of the storefront's stage-event log that filters reads and
      waits as the storefront's query does (after `since_id`, oldest first, every
      filter given) and logs its "arriving" events when a wait first finds nothing,
      and a settle status naming the fulfillment once this deal's event is logged:
      (a) `VmDealDriverBase.settle_dispatched` called with `events_since=0`, so the
      negotiation filter alone is under test; (b) 08b's body run with the base driver,
      asserting the mark is read before `settle_evm` and the wait after it, with the
      listing, the negotiation, and the mark (the latest event of this negotiation, past
      an earlier deal's), and the fulfillment recorded is this deal's; beyond the plan,
      the mark read past two full pages, and a deal with no event marked 0. Unit,
      `test_real_vm_lane.py` (5 new cases, 1 reworked), over `FakeSettlement`, a settle
      status and `job_submitted` wait whose status names the fulfillment once the event
      has come, or answers 404 as a `StorefrontClientError` until it has: (c) the wait
      is for `job_submitted` under `negotiation-1`, then the guest torn down to
      `torn_down` and `released`; (d) the failure names `'0xescrow'`,
      `'negotiation-1'`, the status, and the host, and nothing was listed, for
      `provisioning` and, beyond the plan, for a status recovery does not know; (e)
      status `refunding` returns with no wait, no truncation, and no list, and, beyond
      the plan, a 404 with no dispatch returns after one wait with no truncation;
      beyond the plan, a 404 whose dispatch is then logged is torn down. The existing
      `test_settlement_skips_until_the_preflight_before_it_passes` passes the new
      fixture. Mutation checks, each run and reverted: the negotiation filter dropped
      fails (a) and (b); the return on no fulfillment restored (`if True:`) fails (c)
      and both cases of (d); a return at once on a 404 fails the late-recorded 404 case
      and (e)'s 404 case. The fakes stand in for the storefront's filtering, read
      from its `stage_events` query and the client's `wait_for_stage_event`, and for
      its settle status, read from the VM storefront's settle controller and payment
      repository; none is run against them. 8.3 is the live check that the filter
      finds the event; the recovery paths run live only on a failing run.
- [x] 7D.4 Verification: `make -C e2e-tests test-unit` (unit); `make test`; `make
      check-change CHANGE=prove-real-vm-provisioning`. No dependency or lock changes, so
      no packaging check is owed beyond `make test`'s.
      End-to-end: `e2e_vm_real_provisioning`, in no lane, through 8.2 and 8.3 against a
      real host. The shared `settle_dispatched` also runs in the mock VM scenarios that
      use the VM driver, `e2e_deal` (`test_full_deal.py`) and
      `e2e_non_erc20_settlement` (`test_non_erc20_settlement.py`): their pipeline result
      is evidence that the narrower wait still finds a single run's event there. No CI
      workflow is owed.
      `make -C e2e-tests test-unit` (unit): 312 passed (309 before the fresh-context
      fixes). `make test`: passed, before and after both checks' fixes. `make check-packaging`: passed (run though no lock
      changed, as `AGENTS.md` requires). `make check-change`: passed. End-to-end
      markers, correcting the plan: `e2e_non_erc20_settlement` does not use the VM
      driver's wait — it settles and waits by listing in its own body, unchanged here
      — so it is no evidence. The shared 08b, with its mark and the new keyword, runs
      in `e2e_deal` (the VM driver's narrower wait) and `e2e_bare_metal_mock_deal`
      (bare metal's driver, ignoring the mark, but its 08b making the new event-log
      read); their pipeline results are evidence that one run's settlement still finds
      its dispatch and that the mark's read works against both storefronts.
      `e2e_vm_real_provisioning` is the evidence for the rerun, through 8.3. No CI
      workflow is owed.
      Fresh-context check: no layering, import, test-level, comment-hygiene, or
      public-repository break. Fixed: the comments on the mark said it alone made the
      awaited event this settlement's, where it counts only the negotiation's events
      and the negotiation filter does that work; the accepted-status allow-list failed
      open for a status the storefront adds later (now `UNDISPATCHED_SETTLE_STATUSES`,
      failing closed); a 404 settle status raised a spurious recovery failure; a
      garbled sentence in the real module's docstring; `check-packaging` unrun; these
      notes' claims that an escrow row's `provisioning` shows acceptance and that bare
      metal is unchanged. A second check: no guidance break; fixed: a 404 taken at
      once as not accepted could pass over a guest whose settle response was lost
      while the storefront was still recording it (now waited for, as above); these
      notes' account of where `refunding` comes from and of what failing closed costs;
      the 9.9 sentence below, now amended into 9.9 itself, as sections 1 and 6 did.
      Declined: matching the 404's detail text as well as its status — the wait now
      covers a 404 from elsewhere too. Declined: amending the `test-compatibility`
      delta in this section — its recovery requirement ("after a fulfillment is
      dispatched", failing "naming the fulfillment, reservation, jobs, guest, and
      host") still holds of the behaviour, since an accepted settlement has dispatched
      one and the failure names those fields and more; whether the delta gains a
      scenario for an accepted settlement whose fulfillment is not yet named is the
      triage's to weigh, as a plan change. Owed at 9.9 (amended there): TESTING.md's
      real-lane subsection says the dispatch wait is the deal's own, and how recovery
      finds an accepted settlement's fulfillment.
      Handoff for 8.2 and 8.3: the fix stays within `e2e-tests/`, so the runs need a
      checkout of a public revision including this section against a fresh stack of
      `f52f07973`'s published images and chart and a freshly prepared host. The
      rerun's 08b should pass with the earlier run's listing adopted; the recovery
      paths this section adds run only on a failing run.

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
      Correction: the unit the playbook installs is `gpu-detect.service`
      (`roles/vm-setup/tasks/gpu-detection-service.yml`); `gpu-detection.service` is
      the task file's name, not a unit's. The evidence checks both names.
      Revision: `8638567c8` (sections 1–7), from its published provisioning image,
      `vm-setup.yaml` with no extra variables, on a GPU-less x86-64 Ubuntu 24.04 cloud
      instance with nested virtualization. Owner-supplied, sanitized. Against the
      acceptance, each holds:
      - preparation succeeds: recap `failed=0 unreachable=0`, `ignored=1` (below);
      - kernel command line byte-identical before and after preparation's reboot;
      - after the reboot `kvm_intel`'s `nested` is `Y` and `/dev/kvm` exists
        (`crw-rw---- root kvm 10, 232`);
      - no GPU-detection unit under either name, before or after;
      - no golden-image, Packer, or image-build task among the log's task headers.
      The GPU decision shows D9b on a GPU-less host: `GPU present: False`,
      `gpu_passthrough: auto`, the play's note that passthrough boot configuration and
      binding were skipped and the boot configuration left as it is, and the audit
      reporting IOMMU disabled, not assessable, no GPUs.
      What the run does not show: the host type loads `kvm_intel` with nested on at
      boot, so `nested` and `/dev/kvm` were already present before preparation; the run
      shows preparation keeps them through its reboot, not that `kvm-setup.yml` enables
      them. D9a's two refusals (no `vmx`/`svm`; `/dev/kvm` absent after the modules
      load) cannot fire on a capable host and rest on 3.6's structural tests.
      The ignored failure is the `restart sshd` handler (`roles/vm-setup/handlers/main.yml`,
      `ignore_errors: yes`, notified by `security-hardening.yml`), which this change
      did not touch: on Ubuntu 24.04 the unit is `ssh.service` and Ansible finds no
      `sshd`. It runs after preparation's reboot, which is tagged `always`, so the
      reboot had already started the daemon with the hardened configuration; a change
      to that configuration on a host that is not rebooted would not be applied.
      Every point of the acceptance holds on this evidence. The task is left
      unchecked only because section 8 returns to planning before it is committed
      (below); it is checked when the section is.
      Returned to planning: the owner decided the handler is fixed in this change, a
      fix outside the design's decisions and the plan's tasks. The fix this session
      proposed: the handler restarts the unit the host's OS names (`ssh` on the
      Debian family, `sshd` elsewhere) and no longer ignores its failure, with a
      structural test in `domains/vms/provisioning/iac/tests/`. Left to planning:
      where the task sits (section 8 is evidence only), whether 8.1 is re-run to show
      the recap with `ignored=0`, and whether the guest's cloud-init template
      (`roles/vm-setup/templates/user-data.j2`, `systemctl restart sshd`), which
      the owner did not rule on, is in scope; the proposal's Impact list names
      neither file. Nothing of the fix is implemented. 8.2 and 8.3 still await the
      owner-supplied scenario runs.
      Planned: the fix is section 7A (D9d), shown by 8.4's re-run. The template is
      rendered only by the golden image build — scratch guests' cloud-init is written
      by `vm-create.yml`, which already tries `ssh` then `sshd` — so the owner left it
      out of scope with the golden image (D10), noted on `fix-golden-image-config`'s
      row. The Impact list now names the handler.
      Checked with the section at `3dee66930`. Host preparation's code there differs
      from `8638567c8`'s only by 7A's handler and its test (`git diff --stat 8638567c8
      3dee66930 -- domains/vms/provisioning/iac`), which 8.4 shows, so 8.1's acceptance
      still stands for the head.
- [x] 8.2 **[log]** The scenario: `make -C e2e-tests test-module
      MODULE=e2e_vm_real_provisioning ACTIVE_PROFILES=local,real-vm-target` against the
      provided stack. Supplied: pytest's summary and per-stage results; the VM-execution
      check's reported executor; the create and teardown jobs' terminal statuses; the
      logged host-key fingerprint; the access probes' values against the negotiated
      shape; the unrelated key's refusal; the `list_vms` result; the post-teardown
      refusal. Acceptance: every stage passes and none skips; the values match the
      requirement's scenarios "A real deal is delivered", "An unrelated key is
      refused", and "Teardown removes the VM and its access". (D4, D7)
      Run 1, owner-supplied and sanitized: revision `fa27649fe` (sections 1–7A), its
      published images and chart, provisioning unmocked, an empty host registry, the
      scenario run from a clean checkout of the same revision. Stages 00 to 08b3
      passed: 00e1 reported `offering_mode='vm' mocked=False`; the host registered
      as the target; listing, negotiation, escrow, and settlement completed; 08b3's
      create job succeeded on the target host with a running guest and its DNAT
      forward. 09a failed: the fulfillment went `failed`
      (`provider_reported_failure`, "the create job succeeded without usable
      delivery evidence"), every later stage skipped on its prerequisite, and the
      module's recovery reported the lease `RELEASE_FAILED` with the guest possibly
      left on the host (the infra side cleaned the host; the stack is replaced for the
      next run). Acceptance not met.
      Cause, an application defect read from the source at that revision and the
      job's stored result: the playbook reports an `frp` block even with FRP
      disabled (`enabled: False`, `remote_port: "N/A"`), and the VM adapter's
      `build_result_payload` (`domains/vms/provisioning/adapter/src/vm_provisioning_adapter/codec.py`)
      copies any truthy `frp.remote_port` over the `ssh_port` parsed from the
      playbook, so the stored detail's `ssh_port` is `"N/A"`; `create_evidence`
      takes the direct branch (the job leased no relay) and `int("N/A")` raises
      inside its `try`, so it returns `None`. A direct-access create can therefore
      never report delivery evidence. The mock lanes never interpret playbook
      output, so no lane exercised it. The run itself showed the real lane's
      pre-delivery half working against a real host and the failure path's
      reporting; the recovery could not tear the guest down, since no lease reached
      `active` (D4, "When the run fails", names that case for an operator).
      Returned to planning: the owner's decision, relayed by the infra-side
      coordinator and confirmed by the return, is that the codec defect is fixed in
      this change, as 7A was — a fix outside the design's decisions and the
      proposal's Impact list. The relayed fix shape: `frp.remote_port` replaces
      `ssh_port` only when FRP is enabled and the value is a port number; an adapter
      unit test of a direct-forwarding create whose output carries a disabled `frp`
      block yields evidence with the parsed port. Left to planning: the section, the
      design record (as D9d), and whether a spec delta or the proposal's Impact list
      changes.
      Nothing of the fix is implemented. After it is pushed, the infra side
      republishes, deploys a fresh stack, re-prepares a fresh host, and runs the
      scenario twice for 8.2 and 8.3.
      Planned: the fix is section 7B (D4b), the owner choosing that the relay's port
      replaces the access port only when the relay is enabled and the value is a port,
      and waiving another design review. No spec delta: "A real deal is delivered"
      already requires delivery. The Impact list now names the codec. 8.2 is met by a
      run at a public revision that includes 7B.
      Correction, found implementing 7B: the mock lanes' create output does pass
      through the codec, but their facts' relay block is disabled and names no port,
      which the old rule passed over; that, not an uninterpreted output, is why no
      lane exercised the defect (7B.3).
      Run 2, owner-supplied and sanitized: revision `f52f07973` (sections 1–7B), its
      published images and chart, provisioning unmocked, an empty host registry, a
      freshly created and prepared GPU-less nested-KVM host (preparation at this
      revision `failed=0 ignored=0`, the SSH restart handler `changed`), the scenario
      run from a clean checkout of the same revision. 36 passed, 1 failed (11b).
      Against the acceptance:
      - 00e1 reported `offering_mode='vm' mocked=False`;
      - 08b3's create job and 11a3's teardown job both `succeeded` on the target
        host; the only other job the run caused is 11c's `list`;
      - 09d connected with the negotiated key as the delivered user at the host's
        address and forwarded port, logged the guest's host-key fingerprint
        (`SHA256:…`), and probed `vcpu_count=7, memory_gib=27.41,
        root_disk_gib=160.0` against the sold `7 / 28 / 160`: vCPUs equal, memory
        2.1% short (within the 5% tolerance), disk equal — so 7B's direct-access
        evidence reached delivery;
      - 09e: the unrelated key refused with `Permission denied (publickey,password)`;
      - 11c: the guest gone from the host, which lists `[]`;
      - 11d: the delivered access timed out after teardown.
      Every scenario of "A real deal is delivered", "An unrelated key is refused", and
      "Teardown removes the VM and its access" is shown, but the acceptance ("every
      stage passes") is not met: 11b failed after the release itself completed (the
      reservation `released`, the resource `torn_down`, the bucket back at `7 / 28 /
      160`, and 11b's own checks before the re-reservation passed). Its
      re-reservation returned 409 "no available capacity matched the claim".
      Cause, from the source: `RealVmComputeDealDriver.reserve_released_capacity`
      (`real_compute_deal_driver.py`) sends `required_attributes={"resource_id": …,
      **self.capacity}`, so `vcpu_count`, `ram_gb`, and `disk_gb` are matched as
      resource attributes, which the declaration states only as capacity dimensions
      (its attributes are the region and SLA); `admin_reserve_capacity` takes only
      `required_attributes`. 6.2's note chose this claim, and 6.11's handoff listed
      "the admin re-reservation with dimension attributes" as unproven until this run.
      The mock VM driver claims `resource_id` and `gpu_count`, which its GPU
      declaration does carry as attributes, and bare metal claims `gpu_model`.
      Observed by the owner from inside the guest between 09e and 10a, outside any
      stage: the instance metadata service gave the guest no service-account token,
      and the forwarded port answered only the host's allowed sources. Not acceptance
      points; recorded as context.
      Returned to planning: the owner decided, relayed by the infra-side coordinator,
      that this defect and 8.3's are fixed in this change, as 7A and 7B were. Left to
      planning: the section (the coordinator suggests 7C), the claim 11b's
      re-reservation makes of a GPU-less declaration (what it can pin through
      attributes alone, and how it shows the whole capacity came back — 11b's
      checks before it already read the bucket's dimensions), and whether either fix
      needs a design record as D4b did. Nothing of the fixes is implemented. If they
      stay within `e2e-tests/`, the infra side deploys a fresh stack at `f52f07973`
      with no republish and runs 8.2 and 8.3 from a checkout of the new head.
      Planned: the fix is section 7C (D2a, "The re-reservation's claim"): 11b claims
      the resource as its attribute and the sold capacity as `dimensions`, the shape the
      storefront's admin reserve already accepts for a GPU-less listing; the owner
      waived another design review. It stays within `e2e-tests/`, so 8.2 is met by a run
      from a checkout of a public revision that includes 7C against a fresh stack of
      `f52f07973`'s published images and chart.
      Run 3, owner-supplied and sanitized: the scenario from a clean checkout of
      `cb05d625f` (sections 1–7C) against a freshly deployed, unmocked stack of
      `f52f07973`'s published images and chart (7C changed only `e2e-tests/`, so the
      deployed code is the same), an empty host registry, and the host prepared at
      `f52f07973` (`failed=0 ignored=0`). 37 passed, none skipped or failed. Against
      the acceptance:
      - 00e1 reported `offering_mode='vm' mocked=False`; 00f2 the host registered as
        the target;
      - 08b3's create job and 11a3's teardown job `succeeded` on the target host; the
        only other job the run caused is 11c's `list`;
      - 09a converged the fulfillment to `active`;
      - 09d connected as the delivered user at the host's address and forwarded port,
        logged the guest's host-key fingerprint (`SHA256:…`), and probed
        `vcpu_count=7, memory_gib=27.41, root_disk_gib=160.0` against the sold `7 / 28
        / 160` (memory 2.1% short, within the 5% tolerance);
      - 09e: the unrelated key refused with `Permission denied (publickey,password)`;
      - 11b passed: the released capacity was reserved again under 7C's claim;
      - 11c: the guest gone from the host, which lists `[]`;
      - 11d: the delivered access timed out after teardown.
      Every stage passes and none skips, and the values match "A real deal is
      delivered", "An unrelated key is refused", and "Teardown removes the VM and its
      access": acceptance met at `cb05d625f`. Left unchecked because section 8 returns
      to planning before it is committed (8.3); the infra side runs 8.2 again at the
      fix's revision, so both runs are at the final revision.
      Planned: 8.2 is met by the first of 8.3's two runs at a revision that includes
      7D (8.3, "Planned").
      Run 4, owner-supplied and sanitized: the scenario from a clean checkout of
      `3dee66930` (sections 1–7D) against a freshly deployed, unmocked stack of
      `f52f07973`'s published images and chart, an empty host registry, and a GPU-less
      nested-KVM host freshly created and prepared at `f52f07973` (`failed=0 ignored=0`,
      the SSH restart handler `changed`). Outside `openspec/` and `e2e-tests/` the two
      revisions are identical (`git diff --stat f52f07973 3dee66930` over the rest of
      the tree is empty), so the deployed code is the head's. 37 passed, none skipped
      or failed (553 deselected). Against the acceptance:
      - 00e1 reported `offering_mode='vm' mocked=False`; 00f2 the host registered as
        the target; 02b created its listing paused on the fresh stack;
      - 08b recorded the fulfillment `dispatching`; 08b3's create job `succeeded` on
        the target host and reported the guest; 09a converged the fulfillment to
        `active`;
      - 09d connected as the delivered user at the host's address and forwarded port,
        logged the guest's host-key fingerprint (`SHA256:…`), and probed `vcpu_count=7,
        memory_gib=27.41, root_disk_gib=160.0` against the sold `7 / 28 / 160` (vCPUs
        and disk equal, memory 2.1% short, within the 5% tolerance);
      - 09e: the unrelated key refused with `Permission denied (publickey,password)`;
      - 11a3's teardown job `succeeded` on the target host; 11b passed, the released
        capacity reserved again under 7C's claim;
      - 11c: the guest gone from the host, which lists `[]`;
      - 11d: the delivered access timed out after teardown (`Connection timed out`).
      Every stage passes and none skips, and the values match "A real deal is
      delivered", "An unrelated key is refused", and "Teardown removes the VM and its
      access": acceptance met at `3dee66930`, the head this section is committed on.
- [x] 8.3 **[log]** A second run of the scenario against the same stack. Acceptance: it
      passes, the host's registration being reconciled rather than duplicated. (D2)
      Run 1, owner-supplied and sanitized: the same revision, stack, and host as
      8.2's run 2, straight after it. 11 passed, 1 failed, 25 skipped. 00f1 and 00f2
      passed: the run found the host registered with the target's connection and went
      on, so the registration was reconciled, not duplicated. 02b failed: creating the
      listing returned 409 "this publication source is already bound to another
      listing". Run 2's listing had been reopened when its capacity was released
      (`capacity_released` named it among `reopened_listing_ids`) and republished, so
      it still holds the publication source — the listing shape derived from the same
      `capacity` — that this run's identical listing would bind; every later stage
      skipped on its prerequisite. Acceptance not met. D2 makes the pool, host, and
      declaration reconcile on a rerun but says nothing of the listing, and the module
      leaves its listing open; the mock lanes never meet this, since each lane run
      replaces its stack. Returned to planning with 8.2's defect (above): left to
      planning, and possibly to a design record extending D2, is whether a rerun
      reuses the open listing on its source or the module closes its listing when it
      ends (a closed listing then no longer holding the source would need checking),
      and what a run interrupted before that cleanup leaves for the next.
      Planned: section 7C (D2a). A listing's binding is unique across open and closed
      listings and survives a close, so closing at the end would not free the source;
      the owner chose that a rerun adopts the one open listing on the scenario's
      resource when its shape matches the target, and fails naming the listings
      otherwise, and waived another design review. 8.3 is met by a second run, straight
      after 8.2's, against the same stack.
      Run 2, owner-supplied and sanitized: `cb05d625f`, straight after 8.2's run 3,
      against the same stack and host. 21 passed, 1 failed, 15 skipped. 00f1 and 00f2
      passed (the registration reconciled, not duplicated) and 02b adopted run 3's
      listing — 7C's adoption holds live. 08b failed: "fulfillment_id absent from
      settle status after job_submitted event", the settle status `provisioning`;
      every later stage skipped. Acceptance not met.
      Cause, read from the source at `cb05d625f`: `VmDealDriverBase.settle_dispatched`
      (`scenarios/vms/compute_deal_driver.py`) waits for the storefront's
      `provision/job_submitted` stage event filtered only by `listing_id`, with no
      `since_id` mark. With the listing adopted, the previous run's `job_submitted` for
      the same listing is already in the event log, so the wait returns at once and the
      settle status is read before this run's fulfillment is recorded. The event also
      carries `negotiation_id` (`market_storefront/services/vm_fulfillment_service.py`,
      `_record_fulfillment_id`), which is unique to the run, and
      `wait_for_stage_event` already passes a `negotiation_id` filter, so filtering on
      this deal's negotiation, or a `since_id` mark taken before 08b settles, would
      wait for this run's own event. The fix is in the VM driver base, which the mock
      VM lane shares: its one negotiation per lane run makes either filter unchanged in
      outcome there.
      The other event and state waits the real lane makes, looked over for the same
      staleness on an adopted listing: 05b's and 06b's negotiation events are
      filtered by this run's `negotiation_id`; 11b's release event waits after a
      `since_id` mark; 09b's `closed` listing is this run's, since 02b adopts only an
      open one; the lease view reads reservations by negotiation. One check is vacuous
      on adoption, not stale: 03b's registry read finds the listing already published
      by the previous run, since pausing does not unpublish; 03b's own advance,
      resume answering `published`, still holds, and 04a reads the same registry.
      A second gap the run showed: run 2's settlement had dispatched a real create
      (`succeeded`, reservation `leased`, lease ending about an hour later), yet the
      module's recovery tore nothing down and raised nothing (the summary has no
      teardown error; the recovery's own log line was not supplied). Read from the
      source, the one path that does so: 08b recorded no `fulfillment_id`, so
      `tear_down_after_failure` read it from the settle status, which by then still
      named none, and returned "nothing to tear down" — so a settlement answered
      `provisioning` can still leave its guest on the host silently. The infra side is
      removing that guest by replacing the host. Whether recovery waits for this
      negotiation's `job_submitted` within a bound before concluding nothing was
      dispatched, and fails naming the escrow and negotiation where none arrives, is
      left to planning beside the 08b fix.
      Returned to planning: the owner decided, relayed by the infra-side coordinator,
      that the 08b defect is fixed in this change, as 7A, 7B, and 7C were (the
      coordinator suggests a section 7D). Nothing of the fix is implemented. If it
      stays within `e2e-tests/`, the infra side prepares a fresh host, deploys a fresh
      stack at `f52f07973` with no republish, and runs the scenario twice from the new
      head, for 8.2 and 8.3 both at the final revision.
      Planned: section 7D (D4, "Finding this deal's dispatch" and the recovery rule
      under "When the run fails"): 08b waits for this deal's own `job_submitted`, and
      recovery finds an accepted settlement's fulfillment or fails naming it. It stays
      within `e2e-tests/`, so 8.2 and 8.3 are met by two runs, straight after one
      another, from a checkout of a public revision that includes 7D against a fresh
      stack of `f52f07973`'s published images and chart and a freshly prepared host.
      Run 3, owner-supplied and sanitized: `3dee66930`, straight after 8.2's run 4,
      against the same stack and host. 37 passed, none skipped or failed. Against the
      acceptance:
      - 00f1 declared the supply and refreshed the storefront's projection, and 00f2
        found the host registered as the target; after both runs the provisioning
        service holds one host and one capacity bucket, so the registration was
        reconciled, not duplicated (D2);
      - 02b logged run 4's listing, by its id, as "an earlier run's, adopted paused"
        (D2a);
      - 08b passed on the adopted listing, where run 2 at `cb05d625f` failed, recording
        this run's own fulfillment `dispatching` (D4, 7D); the evidence logs no event
        id, so that the wait passes over the earlier deal's `job_submitted` rests on
        7D.3(a)'s unit test;
      - every later stage passed as in run 4: 08b3's create and 11a3's teardown jobs
        `succeeded`, 09a `active`, 09d the same `7 / 27.41 / 160` probe against `7 / 28
        / 160` with a different host-key fingerprint (a new guest), 09e the unrelated
        key refused, 11b, 11c's host listing `[]`, and 11d's access no longer
        connecting.
      After both runs the service's records: four reservations, all `released` (the two
      deals and their two 11b re-reservations); jobs `create` ×2, `vm_remove` ×2, and
      `list` ×2, all `succeeded`; nothing running or leased. Neither run left a guest or
      a reservation behind, and each caused exactly the three jobs it asserts.
      Acceptance met at `3dee66930`. Not shown by these runs, since neither failed: the
      module's failure recovery (6.8, and 7D's accepted-settlement path), which rests on
      its unit tests. 03b's registry read is vacuous on the adopted listing, as run 2's
      note says; its resume answering `published` holds.
- [x] 8.4 **[log]** Host preparation re-run, as in 8.1, at a public revision of this
      branch that includes section 7A, on the same kind of host. Supplied: the play
      recap and the handler's result from the log. Acceptance: the recap shows
      `failed=0` and `ignored=0`; the handler restarts the OS family's SSH unit without
      error; 8.1's other acceptance points still hold. (D9d)
      Revision: `fa27649fe` (sections 1–7A), from its published provisioning image
      (ansible-core 2.19), `vm-setup.yaml` with no extra variables, on a freshly
      created host of 8.1's kind (GPU-less x86-64 Ubuntu 24.04 cloud instance with
      nested virtualization), so the hardening `blockinfile` changed `sshd_config`
      and notified the handler. Owner-supplied, sanitized. Against the acceptance,
      each holds:
      - recap `failed=0 unreachable=0 ignored=0`; no task or handler failed or was
        ignored anywhere in the log;
      - `RUNNING HANDLER [restart sshd]` reports `changed` without error, the play's
        last handler, after the reboot task; the log records the result, not the
        resolved unit name, which on this Debian-family host the expression makes
        `ssh`;
      - kernel command line byte-identical before and after preparation's reboot;
      - after the reboot `kvm_intel`'s `nested` is `Y` and `/dev/kvm` exists;
      - no GPU-detection unit under either name, before or after;
      - none of the log's task headers names a golden-image, Packer, or image-build
        task; the GPU decision reads `GPU present: False`, `gpu_passthrough: auto`,
        and passthrough boot configuration and binding skipped.
      As in 8.1, the host type already had nested virtualization and `/dev/kvm`
      before preparation. Acceptance met. Left unchecked only because section 8
      returns to planning before it is committed (8.2); checked when the section is.
      When the fix 8.2 found is implemented, the infra side re-prepares a fresh host
      at that revision, which gives the handler another run; 8.4 does not need it.
      That run came: the host of 8.2's run 4 and 8.3's run 3, freshly created, was
      prepared at `f52f07973` with `failed=0 ignored=0` and the handler `changed`
      (owner-supplied). Host preparation's code is the same at `fa27649fe`, `f52f07973`,
      and `3dee66930` (`git diff --stat` over `domains/vms/provisioning/iac` is empty
      from `fa27649fe` to each of the other two), so 8.4 holds for the head.
      Section 8, at its commit: every item meets its acceptance on owner-supplied,
      sanitized evidence, each run's revision recorded above; the earlier, failing runs
      stay recorded as they led to 7A–7D. The section changes no code. End-to-end
      markers: `e2e_vm_real_provisioning`, run by hand against a real host, is the
      section's evidence; no pipeline lane selects it, so the pipeline's result is no
      evidence for this section. No CI workflow is owed.
      Handoff: implementation's sections are all complete. Section 9, the closeout,
      comes after this round's validation, review, and triage, then the pre-closeout
      review and its triage and the merge of the branch the change lands on
      (`docs/agents/change-workflow.md`). 9.8's pipeline run is the mock lanes'; the
      real lane's evidence is this section's.

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
- [ ] 9.10 **Documentation citations.** `make check-doc-citations
      CHANGE=prove-real-vm-provisioning`; `openspec validate prove-real-vm-provisioning
      --strict`.
- [ ] 9.11 **Archival.** `openspec archive prove-real-vm-provisioning -y`, merging both
      spec deltas.
