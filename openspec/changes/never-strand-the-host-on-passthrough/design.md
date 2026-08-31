# Design

## The failure, precisely

An IOMMU group is the hardware's unit of DMA isolation. Devices in one group
can reach each other's memory, so the kernel will only hand a device to a guest
if *every* device in its group is handed over with it. That is a property of
the board's PCIe topology and cannot be configured away.

On the affected machine, the GPU at `01:00.0` sits in a group that also
contains the onboard Broadcom network controllers (`14e4:165f`, a BCM5720) and
ASPEED devices (`1a03:1150` bridge, `1a03:2000` VGA — a BMC signature). Passing
the GPU therefore requires passing the NICs. The role computed exactly that and
wrote it to the kernel command line.

Two drivers then contended for the NICs at every boot: `tg3`, which the kernel
loads for Broadcom Ethernet, and `vfio-pci`, instructed by `vfio-pci.ids=` to
claim the same IDs. Which one wins depends on module load order, and nothing
in the configuration determined it. While `tg3` won, the host had networking
and the GPU was not actually passthrough-capable — the configuration was
failing silently in the safe direction. On the boot where `vfio-pci` won, the
host had no network interface.

The watchdog behaved correctly. It detected the missing interface and reverted
to the previous command line. The previous command line contained the same
`vfio-pci.ids` entries, because the unsafe configuration had been installed
some time earlier and had simply been winning the race. Rollback returned the
host to a coin flip, and it came up tails.

## Four defects, separately

**Device class is never consulted.** The task assembling `vfio_device_ids_combined`
iterates group members and records each `vendor:device` with no filter. A NIC
and a GPU audio function are indistinguishable to it.

**`vfio-pci.ids` is vendor-scoped.** The parameter matches by ID, so every
device presenting `14e4:165f` anywhere in the machine is claimed — including
ports in groups the role never looked at. The blast radius of one group's
contents is the whole machine.

**Bridges are in the list.** `1a03:1150` is a PCI bridge. Bridges are not
endpoints and are not assigned to guests; a bridge appears in a group as the
group's own upstream port. Its presence in `vfio-pci.ids` is direct evidence
the list is assembled without regard to what the devices are, and binding it
is at best a no-op.

**Binding is a boot-time decision.** The kernel command line takes effect
before userspace, so a wrong decision produces an unreachable machine with no
opportunity to observe or correct it. The same decision made after boot
produces a running machine and a failed operation.

## The principle this change installs

> No configuration change that can remove the host's network path may require a
> reboot to take effect, or a reboot to be undone.

Everything below follows from it. IOMMU enablement is exempt because it binds
no device — it only makes groups exist. Every decision about *which devices go
to guests* moves out of the boot path.

## Preflight audit

Read-only, standalone-runnable, and the first thing executed against a newly
rented machine. It answers one question per GPU: can this card be bound without
taking something the host needs?

For each device it resolves:

| Fact | Source |
|---|---|
| PCI address, vendor:device, class code | `lspci -Dnnk` |
| Currently bound driver | `/sys/bus/pci/devices/<addr>/driver` |
| IOMMU group | `/sys/kernel/iommu_groups/<n>/devices/` |
| Carries the default route | `ip -o route get 1.1.1.1` → interface → `readlink /sys/class/net/<if>/device` |
| Carries the root filesystem | `findmnt -no SOURCE /` → parent block device → its PCI parent |

A GPU's group is **bindable** when every member is one of:

- the GPU function itself (class `0300` VGA or `0302` 3D controller);
- a companion function of the same card — audio (`0403`), and on Turing and
  later the USB controller (`0c03`) and serial bus controller (`0c80`) behind
  the card's USB-C port. These share the GPU's PCI device number and are bound
  alongside it;
- a PCI bridge (`0604`) that is the group's upstream port and is not itself
  bound.

It is **not bindable** when any member is a network controller, a storage
controller, a USB controller not belonging to the card, or any device
identified as carrying the default route or the root filesystem. The reason is
reported per device, not as a single verdict, so an operator can see which
device blocked the group.

**IOMMU state is checked first and fails closed.** If `/sys/class/iommu/` is
empty or `/sys/kernel/iommu_groups/` has no entries, the machine has no working
IOMMU and the group data is absent rather than clean. The current role's guards
key on `nvidia_iommu_groups.stdout != ""`, so an empty result skips the binding
work quietly; it must instead be an explicit "IOMMU not enabled, cannot assess"
outcome, distinct from "assessed and found no conflicts". Those two states look
identical downstream today and mean opposite things.

## Address-scoped binding, applied at runtime

`vfio-pci.ids` is replaced by `driver_override`, which is a per-device
attribute in sysfs:

```
echo vfio-pci > /sys/bus/pci/devices/0000:01:00.0/driver_override
echo 0000:01:00.0 > /sys/bus/pci/devices/0000:01:00.0/driver/unbind
echo 0000:01:00.0 > /sys/bus/pci/drivers_probe
```

The override names one address. There is no race, because nothing else is
being instructed to claim anything: `tg3` binds the NICs normally and is never
told otherwise. `driverctl set-override 0000:01:00.0 vfio-pci` is the packaged
equivalent and persists the override via udev; whether to depend on the
`driverctl` package or write the sysfs sequence directly is an implementation
choice, not a design one.

A systemd unit applies the overrides after boot, ordered `Before=libvirtd.service`
so the devices are in place before anything tries to use them. If a bind fails
— the device is held by something, the address moved, the card is absent — the
unit fails, the host is up and reachable, and the failure is a log line.

Blacklisting `nouveau` and not installing a host NVIDIA driver removes the
circular dependency that previously forced a reboot to release the card. With
no driver holding the GPU, the unbind step is uncontested. The host does not
need a GPU driver: for passthrough the card belongs to the guest, and the
driver belongs there too. The consequence is that `gpu-detection-service.yml`'s
`nvidia-smi` MIG branch cannot run on such a host, which is already true today
and should be stated rather than left as a silent no-op.

## The rescue state

The incident proves that "the previous configuration" is not a safe rollback
target. The previous configuration was unsafe and undetected. Any mechanism
that reverts to recent state inherits whatever was wrong with it, and does so
at the moment reliability matters most.

The rollback target is instead a permanently installed GRUB entry that is never
regenerated from current state and contends for nothing: same kernel, same
initramfs, IOMMU enabled, and one additional command-line token the bind unit
recognises as an instruction to apply no overrides at all. Booting it yields a
host with all devices on their normal drivers and no passthrough. That state
cannot lose the network to a binding decision, because it makes none.

Its correctness does not depend on history, on what was installed before, or on
whether anyone observed the last boot succeed. That is the property "previous
configuration" lacked.

With binding moved to runtime, the rescue entry is a second line of defence
rather than the primary one — a wrong binding no longer requires a reboot to
survive. It stays because the IOMMU command-line change still requires one
reboot, and because a kernel or initramfs problem introduced by an unrelated
package update is exactly the case where having a known-inert entry already
present is worth more than being able to construct one.

## Alternatives considered

**Fix the race with `softdep tg3 pre: vfio-pci` and vfio in the initramfs.**
This is the conventional remedy and it works: `vfio-pci` would deterministically
win. On this hardware that means deterministically losing the NICs on every
boot instead of some boots. The nondeterminism was never the problem — it was
the only reason the machine worked at all. Determinism without a class filter
converts an intermittent failure into a permanent one.

**ACS override patch.** An out-of-tree kernel patch that makes the kernel split
groups the hardware does not isolate. It would allow the GPU to be passed
without the NICs, by asserting an isolation property that is false. The failure
mode is a guest able to reach host memory through peer-to-peer DMA, which is
silent. Rejected: this is a marketplace renting isolation to strangers, and the
whole point of the group is the guarantee being overridden.

**Move the GPU to a different physical slot.** Genuinely effective — group
membership follows topology, and a different root port often yields a clean
group. Not available on rented hardware we do not physically touch. Worth
recording as the answer for owned hardware.

**Keep boot-time binding and add a watchdog.** Already tried, already failed,
for the reason above. A watchdog is a recovery mechanism and this change is
about not needing one.

**Audit only, without changing the binding mechanism.** Cheaper, and it would
have prevented this specific incident. It leaves boot-time binding in place, so
the next defect in the bind list is still unrecoverable. The audit prevents the
known failure; runtime binding prevents the class.

## Verification

No hardware with an IOMMU is available in the session environment, so
everything below is intended evidence rather than results. Logs are expected
from the operator for the live items.

Verifiable from source and focused tests, using captured `sysfs` and `lspci`
fixtures:

- A group containing GPU plus audio function classifies bindable.
- A group containing GPU plus a network controller classifies unbindable, and
  names the network device as the reason.
- A group containing GPU plus a bridge classifies bindable, and the bridge is
  excluded from the bind list.
- An empty `/sys/class/iommu/` produces "cannot assess", distinct from "no
  conflicts".
- The device carrying the default route is identified correctly when several
  network interfaces exist.
- No rendered artifact contains `vfio-pci.ids`.

Needs real hardware, verified from supplied logs:

- The audit run read-only against the rented node, before anything is written —
  the first thing executed on it. Expected output: `lspci -Dnnk`, the
  `/sys/kernel/iommu_groups` tree with bound drivers, `ip -o route get 1.1.1.1`,
  and `/proc/cmdline`.
- A bind applied at runtime, with the host remaining reachable throughout.
- A deliberately failed bind leaving the host reachable.
- The rescue entry booting to a host with all devices on normal drivers.
- A guest actually receiving the card — the session's card-access goal, which
  this change is a precondition for rather than a substitute for.

## Open questions

**Does an unbindable GPU affect declared capacity, and where?** A host whose
cards are all unbindable prepares successfully and has zero passthrough
capacity. Whether that is reported, and whether any consumer currently infers
GPU capacity from successful preparation rather than from an explicit count,
needs checking against the capacity administration path before planning.
Recording it here rather than assuming the audit's output has no downstream
consumer.

**Does the rented node's BMC console survive `vfio-pci` claiming the ASPEED
VGA?** On the affected machine `1a03:2000` was in the bind list. The BMC is a
separate service processor and normally retains its own network path, so remote
console access should survive losing the VGA function — but "normally" is
carrying weight, and if the console is the documented last resort its
availability should be confirmed on the specific hardware rather than assumed.
This is an operations question, answerable once a node is rented, and it does
not block implementation.
