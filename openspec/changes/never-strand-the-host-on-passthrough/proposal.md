## Why

`roles/vm-setup/tasks/gpu-passthrough.yml` can render a rented host permanently
unreachable, with no way to recover it in band. It has already done so once.

The task *"Get all devices in NVIDIA GPU IOMMU groups"* walks
`/sys/kernel/iommu_groups/<group>/devices/*` for every group containing a GPU,
resolves **every member** to a `vendor:device` pair, and concatenates all of
them into `vfio_device_ids_combined`. That value is written onto the kernel
command line as `vfio-pci.ids=`, `update-grub` runs, and the role's final task
reboots the host.

Nothing between those steps asks what the group members are. A group containing
the GPU and the onboard network controllers yields a command line instructing
the kernel to bind the network controllers to a stub driver at boot. On the
boot where `vfio-pci` wins its race against the real driver, the host has no
network path.

Four distinct defects produce that outcome:

1. **No device-class filter.** Network controllers, storage controllers, and
   USB controllers are bound identically to GPU functions. The role has no
   notion that some devices are load-bearing for the host.
2. **`vfio-pci.ids` is vendor-scoped, not slot-scoped.** Listing `14e4:165f`
   because one port sits in the GPU's group claims *every* device with that
   ID in the machine, including ports in unrelated groups. One group's contents
   cost the host all onboard networking.
3. **PCI bridges are included in the bind list.** Bridges are not passed
   through and are not endpoints; binding one to `vfio-pci` is meaningless. The
   presence of a bridge ID in a rendered command line is direct evidence the
   list is assembled without regard to what the devices are.
4. **Binding happens at boot, so failure is unrecoverable.** A bind that goes
   wrong in the kernel command line produces an unreachable machine. The same
   bind attempted after boot produces a running, reachable machine with an
   unavailable GPU.

The observed incident also disqualifies the obvious mitigation. A boot-success
watchdog with automatic rollback was in place, detected the missing network
interface, and reverted correctly — into a prior command line that already
carried the same `vfio-pci.ids` NIC entries. That configuration had never been
correct; it had been winning a driver race. The rollback delivered the host into
an unobserved failure at the moment it most needed a reliable one.

No in-band failsafe survives this failure class. A reverse tunnel, a second
`sshd` on another port, a non-`sshd` shell service, and a periodic self-heal
loop all require a network interface the host no longer has.

## What Changes

- **A read-only passthrough audit, runnable standalone.** Enumerates IOMMU
  groups, resolves each device's address, class, and bound driver, identifies
  which devices carry the host's default route and root filesystem, and
  classifies every GPU as bindable or not with a stated reason. Changes
  nothing, so it is safe to run first on a newly rented machine.
- **Preflight refusal.** The audit runs before any configuration is written. A
  GPU whose group contains a device the host depends on is reported and
  skipped; other GPUs in viable groups proceed. An absent or disabled IOMMU
  fails closed rather than reading as "no conflicts found".
- **Bind by PCI address, never by vendor ID.** `driver_override` per device
  replaces `vfio-pci.ids` on the kernel command line, so a binding decision
  applies to the slot it was made about.
- **Bind after boot rather than during it.** A systemd unit applies overrides
  once userspace is up, ordered before `libvirtd`. A failed bind leaves a
  reachable host with an unavailable GPU instead of an unreachable host.
- **A rescue boot entry that contends for nothing.** Permanently installed,
  never regenerated from current state, and recognised by the bind unit as an
  instruction to do nothing. This is the rollback target — chosen because it
  cannot fail, not because it worked last time.
- **The reboot is scoped to IOMMU enablement only.** `intel_iommu=on` /
  `amd_iommu=on` genuinely requires a reboot and binds no device, so it cannot
  strand the host. Every device-binding decision takes effect without one.
- **Host GPU drivers are not installed, and `nouveau` is blacklisted.** This
  removes the circular dependency in which a driver holding the GPU forces a
  reboot to release it.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `physical-provisioning`: host preparation reports GPU passthrough viability
  and refuses bindings that would strand the host.

## Non-Goals

- Do not enable passthrough for a GPU sharing an IOMMU group with a
  host-critical device. There is no safe way to do this on such hardware; the
  correct outcome is an accurate report that the GPU is unavailable.
- Do not apply an ACS override patch. It is an out-of-tree kernel patch that
  works by asserting isolation the hardware does not provide, and its failure
  mode is silent cross-device DMA rather than a refused bind.
- Do not add an in-band recovery path for a host that has lost its network
  interface. None exists; this change prevents the state rather than recovering
  from it.
- Do not change VM creation, GPU attachment to a running VM, or MIG handling.
  This change is about which devices are bound on the host and when.
- Do not manage out-of-band console access. It remains the last resort and
  belongs in an operations runbook.

## Compatibility

**Hosts already prepared by this role.** A host carrying a command-line
`vfio-pci.ids` continues to boot as it does today; this change does not
retroactively rewrite it. Re-running the role on such a host migrates it to
address-scoped runtime binding and removes the command-line list. Whether that
migration is safe to perform remotely depends on the host's group topology,
which the audit reports before anything is written.

**Hosts with clean topology.** A GPU in a group containing only its own
functions binds as before, by a different mechanism, with the same result.

**Hosts with unsafe topology.** These currently appear to succeed and then fail
at the next reboot. After this change they report a skipped GPU and remain
reachable. That is a behavioural change in the direction of accuracy: capacity
that was never usable stops being claimed.

**Capacity reporting.** A host whose GPUs are all unbindable prepares
successfully with zero passthrough-capable cards. Any consumer inferring GPU
capacity from host preparation succeeding rather than from what the audit
reports will now be wrong in a way it previously was not — worth confirming
against the capacity path during planning.

## Dependencies and Related Changes

- Independent of `add-host-ssh-port` and
  `relay-vm-access-without-a-dashboard`. It touches the passthrough tasks only
  and shares no code with either.
- It should land **before** either is exercised against real hardware. Both of
  those changes are verified by provisioning a VM on a rented host, and the
  role that prepares that host is the one that can strand it.
- `capacity-resource-administration` declares sellable capacity. A GPU the
  audit reports as unbindable is not sellable capacity, and the relationship
  between the two is worth confirming rather than assuming.

## Impact

- A rented host cannot be stranded by its own preparation.
- GPU passthrough viability becomes an observable property of a machine,
  reported before money is spent proving it the expensive way.
- A failed binding degrades to reduced capacity rather than a lost machine.
- The audit is runnable read-only against a freshly rented node, so hardware
  suitability is established in minutes rather than after a full preparation
  run and a reboot.

## Permanent documentation impact

- [x] Existing subsystem specification: `openspec/specs/physical-provisioning/spec.md` — passthrough viability is audited, refused when unsafe, and applied without a reboot
- [x] Existing capability architecture: `openspec/specs/physical-provisioning/architecture.md` — why binding is address-scoped and runtime-applied, and why a rescue state must be non-contending rather than previous
- [ ] `docs/development/ARCHITECTURE.md` — no repository-wide shape change
- [ ] `docs/development/ROADMAP.md` — disposition recorded at closeout

### Knowledge to promote

- No configuration change that can remove the host's network path may require a
  reboot to take effect or to be undone →
  `openspec/specs/physical-provisioning/architecture.md`
- A rollback target must be a state that cannot fail, not the most recent state
  that has not yet failed →
  `openspec/specs/physical-provisioning/architecture.md`
- Device binding is scoped to a PCI address, never to a vendor/device ID →
  `openspec/specs/physical-provisioning/spec.md`
- An absent or disabled IOMMU fails closed →
  `openspec/specs/physical-provisioning/spec.md`
- A GPU sharing an IOMMU group with a host-critical device is reported
  unavailable rather than bound →
  `openspec/specs/physical-provisioning/spec.md`
