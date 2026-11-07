## Why

No end-to-end scenario has ever provisioned a VM for real. Every VM deal scenario
asserts that the provisioning service answered from its mock profile
(`Stage00e_ProvisioningMockMode`), drives its jobs through the mock-only `/test/*`
routes, and checks only that delivered credentials are non-empty; none opens a
connection to what was provisioned. The Ansible path that creates, reaches, and
tears down a VM on a KVM host is therefore unverified by any test, and a defect in
it — a playbook that cannot run on the host, a delivered address nobody can reach, a
teardown that leaves the guest running — surfaces only on a seller's machine.

GPU-optional compute shapes made a VM shape without GPUs sellable end to end. That
makes an ordinary cloud instance with nested virtualization a valid KVM host, and
removes the last practical obstacle to proving the real path against a real host.

Three further defects stand in the way of doing so:

1. Host preparation does not require hardware virtualization. `kvm-setup.yml` greps
   for `vmx`/`svm` with `ignore_errors`, and VM creation names no virtualization
   type, so a host without KVM completes preparation and every VM on it either falls
   back to software emulation or fails late with an unrelated error.
2. Host preparation applies GPU-passthrough boot configuration to every host — the
   IOMMU kernel arguments, vfio module loading, an initramfs rebuild, the rescue boot
   entry, and the GPU-detection service — whether or not the passthrough audit found
   anything to pass through. On a GPU-less host the boot configuration of a machine
   reachable only over SSH is changed for no purpose.
3. Host preparation defaults to the golden-image path, which needs object storage,
   a service-account key, and Packer, while market fulfillment creates VMs from
   scratch. Preparing a host for the VMs the market actually creates requires
   overriding the default.

The e2e helpers also cannot describe a GPU-less shape (`capacity_source_for` reads
`gpu_model` unconditionally), and the repository carries a live-environment workflow
nested inside the e2e package's own directory, which GitHub never runs.

## What Changes

- A real-provisioning VM scenario, `e2e_vm_real_provisioning`, in no default lane. It
  reads a target description — the one host to provision on, its capacity, and the
  access mode to expect — from a typed settings section an environment owner renders
  into an ignored profile file, registers the pool, host, and GPU-less capacity
  declaration itself, runs the canonical compute deal through to an active lease,
  proves the buyer's SSH access with the negotiated key and the refusal of an
  unrelated one, expires the lease, and proves the VM is gone from the host's VM list
  and access has ended. A failed run truncates its lease so the guest is torn down.
- The canonical deal's shared stages split at their mock gates, so the real lane
  subclasses every stage it can and the mock lanes' stage lists name their mock-only
  stages explicitly. The mock gates move off the shared driver protocol onto one only
  mock drivers implement.
- A domain-neutral SSH access helper for scenarios, and GPU-less shape support in
  the VM e2e helpers.
- Host preparation refuses a host without hardware virtualization, and VM creation
  pins KVM. GPU-passthrough boot configuration is applied only to a host with a GPU
  from a vendor whose GPUs are passed through, whether or not its IOMMU is enabled
  yet, with an explicit operator override; binding still follows the passthrough
  audit. Host preparation defaults to the scratch image.
- The dead nested workflow and the README's nonexistent targets are removed; the
  manual live-validation runbook is rewritten as the scenario's manual counterpart.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `test-compatibility`: the canonical deal's shared stages are shared with a
  real-provisioning lane; a real-provisioning VM scenario and its target
  description.
- `physical-provisioning`: hardware virtualization is required by host preparation
  and VM creation; passthrough boot configuration follows GPU presence and binding
  follows the audit; host preparation's default image.

## Non-Goals

- Relay-backed (FRP) delivery in the real lane. The access mode is a parameter of
  the real driver and of the target description so it can be added, and the
  relay-backed lane is a named follow-up; this change proves direct access only.
- Running the real lane in the end-to-end pipeline or from the in-cluster scenario
  pod. It runs from an operator's machine against forwarded services; packaging it
  for the scenario pod (an SSH client in the e2e image) is later work.
- Host preparation as a provisioning-service capability. Preparation stays an
  operator step.
- The golden-image path. `fix-golden-image-config` owns its configuration and is to
  re-evaluate what the golden image is for.
- Host-key pinning for delivered VM access. The VM domain does not deliver the
  guest's host key; the scenario trusts on first use within one run.
- Retiring the other dead e2e markers or unrelated Makefile cleanup.

## Impact

- `e2e-tests/`: shared stage split, a `MockGates` driver part, the real VM driver and
  scenario module, the target settings model, the `.example` profile and its ignore
  rule, the SSH helper, GPU-less helper support, marker registration, README.
- `domains/vms/provisioning/iac/ansible/`: `vm-setup.yaml` default,
  `roles/vm-setup/defaults/main.yml`, `roles/vm-setup/tasks/{main,kvm-setup}.yml`
  and a new `gpu-presence.yml` (the passthrough includes, binding's among them, are
  conditioned in `main.yml`; the audit's report wording), the `restart sshd` handler
  in `roles/vm-setup/handlers/main.yml`, the `vm-management` role's `vm-create.yml`
  and `gpu-virt-install-*.yml`, and their IaC tests.
- `domains/vms/provisioning/adapter/`: the result codec's choice of a direct-access
  create's port (`codec.py`, `build_result_payload`) and its unit tests.
- `docs/development/TESTING.md`, `docs/development/VALIDATION_RUNBOOK.md`, host-kit
  and seller documentation that states the preparation default.
- No wire, persistence, chart, or image change. Existing mock lanes keep their
  coverage; GPU hosts keep their passthrough behaviour.

## Dependencies and Related Changes

- `never-strand-the-host-on-passthrough` (blocked in closeout) wrote the audit and
  the passthrough tasks this change gates. Its GPU path is unchanged, so its live
  verification remains valid; its gated tasks now run only on a host with an NVIDIA
  or AMD GPU present, and binding still follows its audit.
- `relay-vm-access-without-a-dashboard` (blocked in closeout) needs a prepared host
  and a deployed relay for its live verification. The relay-backed follow-up to this
  change is how that evidence is produced.
- `fix-golden-image-config` owns the golden-image path this change stops defaulting
  to.
- No dependency gates this change.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The real-provisioning lane, its target description, how it is run, and what it
  proves → `docs/development/TESTING.md` and `openspec/specs/test-compatibility/spec.md`.
- Shared stages split at mock gates; mock gates are a separate driver part →
  `openspec/specs/test-compatibility/spec.md`.
- Hardware virtualization required; passthrough boot configuration follows GPU
  presence and binding follows the audit; scratch default → `openspec/specs/physical-provisioning/spec.md`, with the
  operator procedure in `docs/development/VALIDATION_RUNBOOK.md`.
- Goal 1 gap "no end-to-end lane provisions for real" closes →
  `docs/development/ROADMAP.md`.
