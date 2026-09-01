# Implementation Tasks

Every path below is relative to `domains/vms/provisioning/iac/`.

Validation commands are the ones this project actually uses: `make validate`
(inventory parse, playbook syntax check, tests) and `make test`
(`uv run pytest tests -q`). Ansible is not available in the authoring
environment, so any task whose only validation is `make validate` is disclosed
as unrun until an operator supplies its output.

Live evidence is supplied by the operator as terminal output and verified here
against the acceptance stated in each task. A task marked **[log]** is not
complete on the strength of the code being written; it is complete when the
supplied output shows what the task says it must.

## 1. Audit — read-only, standalone

- [x] 1.1 Add `ansible/roles/vm-setup/tasks/passthrough-audit.yml`. Read-only:
      no `copy`, no `lineinfile`, no `command` that mutates, no handler
      notification. It resolves, for every PCI device:
      address and `vendor:device` (`lspci -Dnnk`), class code, currently bound
      driver (`/sys/bus/pci/devices/<addr>/driver`), and IOMMU group
      (`/sys/kernel/iommu_groups/<n>/devices/`).
- [x] 1.2 Identify the host-critical devices in the same task file: the PCI
      address behind the default route (`ip -o route get 1.1.1.1` → interface →
      `readlink /sys/class/net/<if>/device`) and the address behind the root
      filesystem (`findmnt -no SOURCE /` → parent block device → its PCI
      parent). Resolve both to addresses, not to IDs — the identification must
      survive two devices sharing a `vendor:device`.
- [x] 1.3 Classify each GPU group. Bindable when every member is the GPU
      function (`0300`/`0302`), a companion function at the same PCI device
      number (`0403` audio, `0c03` USB, `0c80` serial bus), or a PCI bridge
      (`0604`) that is not itself bound. Not bindable when any member is a
      network controller, a storage controller, a USB controller at a different
      device number, or either address from 1.2. Record a per-device reason,
      not a single verdict.
- [x] 1.4 Fail closed on IOMMU state. Empty `/sys/class/iommu/` or an empty
      `/sys/kernel/iommu_groups/` yields an explicit "IOMMU not enabled, cannot
      assess" outcome distinct from "assessed, no conflicts". These are the two
      states the current role's `nvidia_iommu_groups.stdout != ""` guards
      conflate, and they mean opposite things.
- [x] 1.5 Emit a structured audit fact — per GPU: address, model, group number,
      group members with class and driver, bindable true/false, reason. This is
      the value every later task reads and the artifact the operator sends back.
- [x] 1.6 Add `ansible/playbooks/host-kit/passthrough-audit.yaml` targeting
      `kvm_hosts`, including only the audit task file. This is what runs first
      against a newly rented machine, before anything writes to it.
- [x] 1.7 Register the new playbook in `Makefile`'s `validate-playbooks` target
      alongside the existing four syntax checks.

**Validation:** `make validate`.

## 2. Audit behaviour under test

The suite already exercises real shell out of task files with faked binaries
(`tests/shell_harness.py`, used by `tests/test_gpu_attachment_discovery.py`).
The audit's logic is shell and belongs under the same harness; a substring
assertion cannot prove a classifier classifies.

- [x] 2.1 Add `tests/test_passthrough_audit.py` using `extract_between`,
      `fake_binaries`, and `run_bash`. Fake `lspci`, `ip`, `findmnt`, `lsblk`,
      and a temporary sysfs tree for `/sys/kernel/iommu_groups` and
      `/sys/bus/pci/devices`.
- [x] 2.2 Cover, each as its own case: GPU with audio function only → bindable;
      GPU with a network controller → not bindable, naming the network device;
      GPU with a bridge → bindable, bridge excluded from the bind list; GPU
      alone in its group → bindable; two GPUs, one clean group and one dirty →
      one bindable and one not, independently.
- [x] 2.3 Cover the incident's exact topology as a named regression case: GPU
      plus two Broadcom NICs plus an ASPEED bridge and VGA, with one NIC
      carrying the default route. Assert not bindable, and assert no rendered
      artifact contains the NIC's `vendor:device`.
- [x] 2.4 Cover fail-closed: empty `/sys/class/iommu/` produces "cannot
      assess" and never produces an empty-and-therefore-clean bind list.
- [x] 2.5 Cover host-critical identification with several interfaces present,
      only one of which holds the default route.

**Validation:** `make test`. Runnable in the authoring environment; results
reported rather than deferred.

## 3. Address-scoped binding, applied after boot

- [x] 3.1 Rewrite `ansible/roles/vm-setup/tasks/gpu-passthrough.yml` to consume
      the audit fact and act only on GPUs it reports bindable. Remove the
      device-ID accumulation: the `vfio_device_ids_combined` fact, the tasks
      that build it (*"Get all devices in NVIDIA GPU IOMMU groups"*, its AMD
      counterpart, and the verification tasks that echo group contents), and
      both consumers below.
- [x] 3.2 Remove `vfio-pci.ids=` and `vfio-pci.disable_vga=1` from the GRUB
      command-line edit. The IOMMU token (`intel_iommu=on` / `amd_iommu=on`)
      stays: it binds no device and cannot strand the host.
- [x] 3.3 Remove the vendor-ID list from `/etc/modprobe.d/vfio.conf`. The task
      *"Bind all IOMMU group devices to VFIO-PCI"* writes
      `options vfio-pci ids=... disable_vga=1` — a second copy of the same
      unsafe list, in a second location, which must go with the first. Deleting
      only the command-line copy leaves the machine binding by ID.
- [x] 3.4 Keep `/etc/modules-load.d/vfio.conf`. Loading `vfio_pci` binds
      nothing on its own once no `ids=` is supplied, and the module must be
      present before an override is applied.
- [x] 3.5 Add `ansible/roles/vm-setup/templates/vfio-bind.sh.j2` and
      `vfio-bind.service.j2`. The unit is `Type=oneshot`,
      `RemainAfterExit=yes`, `After=systemd-modules-load.service`,
      `Before=libvirtd.service`, with no `Requires=` or `BindsTo=`. For each
      address in the bind list the script writes `vfio-pci` to
      `driver_override`, unbinds the current driver if one is bound, and
      triggers `drivers_probe`. It reads its address list from a file rendered
      by the role, so re-running the role changes data rather than code.
- [x] 3.6 Make the script a no-op when `/proc/cmdline` carries the rescue
      token. This is what makes the rescue entry inert without a second
      initramfs.
- [x] 3.7 Bind failure must fail the unit and leave the host running. No
      `ignore_errors` on the apply task, and no reboot triggered by a bind
      outcome.
- [x] 3.8 Confirm the existing `blacklist-nvidia.conf` task and the existing
      `update-initramfs -u -k all` task remain, and that the blacklist is
      written whenever any GPU is bindable rather than only when
      `nvidia_gpu_id` is set. The blacklist is what makes the unbind in 3.5
      uncontested; the initramfs rebuild is what makes the blacklist take
      effect. Both already exist — verified in the current tree — so this task
      is a check against regression, not new work.

**Validation:** `make validate`; disclosed as unrun until an operator supplies
`ansible-playbook --syntax-check` output.

## 4. Rescue boot entry

- [x] 4.1 Add `ansible/roles/vm-setup/tasks/rescue-boot-entry.yml` installing a
      custom GRUB entry under `/etc/grub.d/`: same kernel and initramfs as the
      default, IOMMU token retained, plus the rescue token from 3.6.
- [x] 4.2 The entry is written once and never regenerated from current state.
      Its correctness must not depend on what the machine's configuration
      happened to be when it was created — that dependency is the defect the
      incident exposed, and rendering it from the live command line would
      reintroduce it exactly.
- [x] 4.3 Set `GRUB_DEFAULT=saved` and leave the normal entry as default.
      Selecting the rescue entry is an operator action from the console, not an
      automatic fallback: with binding moved to runtime there is no longer a
      boot outcome that needs one, and an automatic reverter is the mechanism
      that delivered the incident host into a coin flip.
- [x] 4.4 Include the rescue entry's title and selection procedure in the audit
      output from 1.5, so an operator reaching a console knows what to pick
      without repository access.

**Validation:** `make validate`; disclosed as unrun.

## 5. Wire into the role, and keep the reboot honest

- [x] 5.1 Include `passthrough-audit.yml` from
      `ansible/roles/vm-setup/tasks/main.yml` ahead of `gpu-passthrough.yml`,
      tagged so it runs under `host_setup` and can also be run alone.
- [x] 5.2 Include `rescue-boot-entry.yml` after `gpu-passthrough.yml`.
- [x] 5.3 Confirm the role's closing reboot is now reachable only for the IOMMU
      command-line change, and state in a comment on that task what it is and
      is not permitted to carry. A reboot that only enables the IOMMU cannot
      strand the host; a reboot that also applies a binding can, and the
      comment is what stops the second being reintroduced.

## 5a. Sequencing: bind after the reboot, persist after verification

Added after review found that installing an *enabled* unit and then rebooting
put the first application of an unverified bind list inside the boot path — the
hazard the change exists to remove, one level up.

- [x] 5a.1 Split `gpu-passthrough.yml` to phase one only: boot configuration,
      no bind list, no `systemctl start`, no `enabled: yes`.
- [x] 5a.2 Add `ansible/roles/vm-setup/tasks/gpu-bind.yml` as phase two,
      included from `main.yml` **after** the reboot task.
- [x] 5a.3 Re-run the audit in phase two. An IOMMU disabled in firmware exposes
      no groups, so a pre-reboot audit cannot classify anything; re-auditing is
      what makes a first preparation converge in one pass.
- [x] 5a.4 Assert before binding that the bind list contains neither the route
      device nor the root device, so one classifier defect cannot strand a host.
- [x] 5a.5 Apply with `systemctl start`, confirm every audited address reports
      `vfio-pci`, and confirm the route device's driver is unchanged.
- [x] 5a.6 Enable the unit last, only after those confirmations.
- [x] 5a.7 Scope the host GPU driver blacklist to hosts where every detected GPU
      is bindable. `modprobe` blacklists a module, not a device, so applying it
      while the audit deliberately left a card on its own driver strands that
      card for the host too.
- [x] 5a.8 Cover the sequencing in `tests/test_ansible_structure.py`: phase one
      binds nothing and writes no bind list; apply precedes verification
      precedes enable; the pre-bind assertion names both critical devices;
      `gpu-bind.yml` runs after the reboot in `main.yml`; the unit is not
      ordered after the target that wants it; the blacklist is conditional.
- [x] 5.4 Report skipped GPUs prominently in the role's closing debug output —
      count, address, and reason. A host prepared with zero bindable cards must
      not read as a fully successful preparation.

**Validation:** `make validate`; disclosed as unrun.

## 6. Decision gate — capacity reporting

- [x] 6.1 Trace whether anything infers GPU capacity from host preparation
      succeeding rather than from an explicit count: the capacity check job in
      `ansible/roles/vm-management/tasks/`, `gpu-detection-service.yml`, and the
      capacity administration path named by `capacity-resource-administration`.
- [x] 6.2 **Decide and record** in `design.md` whether an unbindable GPU must be
      excluded from declared capacity by this change, or whether that belongs to
      the capacity change. Record the reasoning and the revisit trigger. This is
      a gate, not an instruction: both answers are open, and 6.3 executes
      whichever is chosen.
- [x] 6.3 Implement the decision from 6.2, or record explicitly that no code
      change follows from it.

**Validation:** whichever focused test the decision implies; `make test`.

## 7. Live verification [log]

Requires a rented node. Each item states the acceptance; the supplied output is
checked against it here.

- [ ] 7.1 **[log]** Audit run read-only against the node before anything is
      written. Supplied: `lspci -Dnnk`, the `/sys/kernel/iommu_groups` tree with
      bound drivers, `ip -o route get 1.1.1.1`, `findmnt -no SOURCE /`,
      `/proc/cmdline`, `ls /sys/class/iommu/`. Acceptance: the audit's
      per-GPU verdict is reproducible from the raw output by hand, and the raw
      output shows the node unchanged. If any GPU shares a group with a
      host-critical device, this is where the session stops and the direction is
      reconsidered — that is a successful outcome of this task, not a failure.
- [ ] 7.2 **[log]** Role run with binding applied. Supplied:
      `systemctl status vfio-bind`, `journalctl -u vfio-bind`,
      `lspci -Dnnk` for the GPU addresses, `ip -o route get 1.1.1.1`.
      Acceptance: bound GPUs show `vfio-pci`, the route-holding interface is
      unchanged and on its normal driver, and the host answered throughout.
- [ ] 7.3 **[log]** Deliberate bind failure — an address in the list that does
      not exist. Supplied: unit status and `journalctl`. Acceptance: the unit
      fails, `libvirtd` still starts, the host stays reachable.
- [ ] 7.4 **[log]** Reboot after the IOMMU change. Supplied: `/proc/cmdline`,
      `ls /sys/kernel/iommu_groups | wc -l`, and evidence the host came back.
      Acceptance: groups exist, no `vfio-pci.ids` on the command line, host
      reachable.
- [ ] 7.5 **[log]** Rescue entry booted from the console. Supplied:
      `/proc/cmdline`, `lspci -Dnnk` for the GPU addresses, `systemctl status
      vfio-bind`. Acceptance: rescue token present, GPUs on their normal
      drivers or unbound, the unit a no-op rather than a failure.
- [ ] 7.6 **[log]** A guest receives a bound card. Supplied: the guest's
      `lspci -nnk` and `nvidia-smi`. Acceptance: the card is present in the
      guest and its driver is bound there. This is the session's card-access
      goal; this change is its precondition, not its substitute.
- [ ] 7.7 **[log]** Confirm out-of-band console access on the specific hardware,
      including whether it survives `vfio-pci` claiming an onboard VGA function
      if one is in a bound group. Acceptance: a console session is demonstrated.
      Records the answer to the second open question; does not block 7.1–7.6.

## 8. Closeout

- [x] 8.1 **Comment hygiene.** Run `make check-comment-hygiene` from the
      repository root and resolve every match. Then read the new shell,
      templates, and task files directly for the fuzzier violations the target
      cannot catch — references to the incident, to this change, to a review, or
      to what the code used to do. The rationale that belongs in the code is the
      invariant ("binding is address-scoped so a vendor ID cannot capture an
      unrelated device"), never the history.
- [x] 8.2 **Import placement.** Applies to `tests/test_passthrough_audit.py`
      only; the rest of this change is YAML, shell, and templates. Check each
      import the file adds for a real reason to be local before moving it, and
      verify any move against `make test` rather than a syntax check.
- [x] 8.3 **Documentation compliance.** Re-check this change's accepted
      decisions against `openspec/README.md`'s placement rules directly.
      Normative behaviour to `spec.md`; the reasoning about why binding is
      address-scoped and runtime-applied, and why a rescue state must be
      non-contending rather than previous, to `architecture.md`.
- [x] 8.4 **Narrative compression.** Shorten completed-task notes to final
      behaviour, material evidence, and unresolved work. Move alternatives and
      debugging narrative into `design.md` first — this step deletes
      duplication, not information.
- [ ] 8.5 **Roadmap currency.** No roadmap goal in
      `docs/development/ROADMAP.md` currently covers reaching or preparing
      rented hosts. Decide explicitly whether one is warranted now that three
      changes serve it, and record the disposition either way so an absent edit
      is a deliberate finding.
- [ ] 8.6 **Promotion.** Complete the design-promotion record:

| Accepted decision | Permanent location | State |
|---|---|---|
| No configuration change that can remove the host's network path may require a reboot to take effect or to be undone | `openspec/specs/physical-provisioning/architecture.md` | Applied |
| A rollback target must be a state that cannot fail, not the most recent state that has not yet failed | `openspec/specs/physical-provisioning/architecture.md` | Applied |
| A binding is not persisted across reboots until applied and verified on that machine | `openspec/specs/physical-provisioning/spec.md` | Applied |
| Device binding is scoped to a PCI address, never a vendor/device ID | `openspec/specs/physical-provisioning/spec.md` | Applied |
| An absent or disabled IOMMU fails closed | `openspec/specs/physical-provisioning/spec.md` | Applied |
| A GPU sharing an IOMMU group with a host-critical device is reported unavailable rather than bound | `openspec/specs/physical-provisioning/spec.md` | Applied |
| Declared GPU capacity counts assignable devices, not present ones | `openspec/specs/physical-provisioning/spec.md` | Applied |
| ACS override is rejected, and why | `openspec/specs/physical-provisioning/architecture.md` | Applied |
| The blacklist is all-or-nothing, so it applies only when every GPU is bindable | `design.md` — implementation rationale, not a permanent contract | Recorded |

## Out of scope, observed

Neither is touched by this change; both are recorded so the observation is not
lost, and each is its own decision.

`ansible/roles/vm-setup/backup/original-main.yml` is a tracked backup copy of a
task file.

`make validate-inventory` parses `ansible/inventory/hosts`, which is gitignored
and therefore absent from any fresh checkout. Ansible emits "Unable to parse ...
as an inventory source", falls back to implicit localhost, and exits zero, so
the target reports success while validating nothing. Pointing it at
`ansible/inventory/hosts.example` — the file the repository actually ships —
would make it meaningful, but it is shared tooling for every playbook in this
project and the change belongs to whoever owns that target rather than being
folded in here.

## Implementation notes

Recorded at implementation; compressed at closeout.

**Sections 1–2 — audit.** `passthrough-audit.yml` classifies from sysfs
(`class`, `vendor`, `device`, `driver` symlink, `kernel/iommu_groups`) rather
than by parsing `lspci`, so there is no output format to absorb and the
classifier is exercisable against a fixture tree through `SYSFS_ROOT`. `lspci`
supplies a human-readable model only, and its absence degrades the report
rather than the verdict — covered by a test.

**Section 3 — binding.** The unsafe list was written in two places, not one:
the GRUB command line and `options vfio-pci ids=` in
`/etc/modprobe.d/vfio.conf`. Both are removed, and because neither removal
affects a machine that already carries them, the role also strips a stale
command-line list and deletes the modprobe file. `vfio-bind.service` is
`Before=libvirtd.service` with no `Requires=` or `BindsTo=`, so a failed bind
costs a device rather than virtualization; asserted by test.

**Section 4 — rescue entry.** Builds its command line from a fixed minimal set
rather than inheriting `GRUB_CMDLINE_LINUX_DEFAULT`, which on a host carrying a
stale `vfio-pci.ids` would reproduce the state the entry exists to escape.
Asserted by test against non-comment lines.

**Section 6 — decision gate.** The host capacity check counted every NVIDIA or
AMD card present. Deliberately skipping cards in unsafe groups makes that an
over-report, so the count and GPU details now report `vfio-pci`-bound cards.
Reasoning and scope boundary against `capacity-resource-administration`
recorded in `design.md`.

**Sections 7 and 8.5 remain open.** Live verification needs rented hardware;
the roadmap-currency disposition is deliberately deferred to closeout so it can
be decided once for all three changes rather than three times.

## Validation evidence

Run against a clean copy of the baseline with this change applied, not against
a working tree.

| Command | Where | Result |
|---|---|---|
| `make test` (`uv run pytest tests -q`) | authoring env | **52 passed** — 11 pre-existing, 41 added |
| `make check-comment-hygiene` | authoring env, repository root | **OK**, no matches outside `openspec/` |
| YAML parse of every new and modified task, defaults, and playbook file | authoring env | **OK** (6 files) |
| `bash -n` over both shell templates with Jinja expressions substituted | authoring env | **OK** (2 files) |
| `make validate-playbooks` | operator, `domains/vms/provisioning/iac` | **passed** — all five playbooks, including `host-kit/passthrough-audit.yaml` |
| `make validate-inventory` | operator, `domains/vms/provisioning/iac` | **passed vacuously** — see below |

Baseline suite before this change: 11 passed. No pre-existing test changed.

**What `validate-playbooks` did and did not cover.** It confirmed all five
playbooks parse, and — because `vm-setup.yaml` uses `roles:`, which is a static
import — that the role's `tasks/main.yml` parses. It did **not** parse the task
files that main.yml reaches, because all nine of those are `include_tasks`,
which Ansible resolves at run time rather than at parse time. Most of this
change lives in those files.

That gap is closed two ways. `host-kit/passthrough-audit.yaml` now uses
`import_tasks`, so `--syntax-check` reaches `passthrough-audit.yml`. And
`tests/test_ansible_structure.py` validates every task file in every role
structurally — one module per task, real keywords, named tasks, includes
pointing at files that exist — without needing Ansible installed, so the
coverage does not depend on an operator having it.

**Test dependencies.** `test_ansible_structure.py` parses YAML directly, so
`pyyaml` is declared in this project's dev dependency group and `uv.lock` is
regenerated. Validating the role's structure without Ansible installed is the
point of that file; the YAML parser is the cost of it. Verified by running
`make test` itself rather than a bare `pytest`, so the check exercises the
project's own dependency resolution rather than whatever the authoring
environment happens to have.

**`validate-inventory` passes without validating anything.** The target parses
`ansible/inventory/hosts`, which is gitignored and absent from a fresh
checkout; Ansible warns and exits zero. It is pre-existing, unrelated to this
change, and reported rather than fixed here — see the observation below.
