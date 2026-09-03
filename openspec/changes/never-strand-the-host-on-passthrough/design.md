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

A systemd unit applies the overrides after boot, ordered
`After=systemd-modules-load.service` so `vfio-pci` exists and
`Before=libvirtd.service` so the devices are in place before anything tries to
use them. It declares no `Requires=` or `BindsTo=`: a failed bind must cost a
device, not virtualization. If a bind fails — the device is held by something,
the address moved, the card is absent — the unit fails, the host is up and
reachable, and the failure is a log line.

**Applying at runtime is necessary but not sufficient.** An *enabled* unit is
part of the boot path: every subsequent boot replays its bind list, and if that
list is wrong the host comes up, loses its network when the unit runs, and comes
up the same way again. Installing an enabled unit and then rebooting puts the
first application of an unverified bind list inside a boot nobody is watching —
the property this change set out to remove, reintroduced one level up.

So the work is split across the reboot:

| | Phase one, before the reboot | Phase two, after it |
|---|---|---|
| Changes | IOMMU parameter, module load, blacklists, initramfs, rescue entry | bind list, live apply, verification, enable |
| Binds a device | no | yes, with Ansible connected |
| Unit state | installed, disabled | enabled last, after verification |
| Worst case | a reboot that changes no device ownership | a failed task on a reachable host |

Phase two applies the bindings with `systemctl start`, confirms every audited
address reports `vfio-pci`, confirms the host's route device still holds the
driver it held beforehand, and only then enables the unit. A boot never replays
a list that has not been observed to work on that machine.

The reboot also earns its place beyond the IOMMU parameter. An IOMMU disabled in
firmware exposes no groups, so a pre-reboot audit reports "cannot assess" and
there is nothing to classify; the groups exist only on the far side. Re-running
the audit in phase two is what lets a first preparation converge in one pass
rather than silently requiring the operator to notice and run the role again — a
phase transition that was previously implicit and undocumented.

Phase two also asserts, immediately before binding, that the bind list contains
neither the route device nor the root device. The audit already refuses such a
group; the assertion costs nothing and means a single classifier defect cannot
strand a host, because both would have to fail the same way.

An automatic post-boot watchdog that disabled the unit when the host could not
reach the relay was considered and rejected. Its rollback target would be sound,
unlike the reverted command line that stranded a previous host, but it
reintroduces a self-modifying agent for a case the sequencing already covers: an
unverified list is never persisted, so no boot needs rescuing from one.

**The host GPU driver blacklist applies only when every GPU is bindable.**

`modprobe` blacklists a module, not a device, so the blacklist cannot be scoped
the way the binding is. On a host where the audit deliberately leaves one card
on its own driver -- because its IOMMU group contains something the host needs --
blanket-blacklisting the vendor's driver strands that card for the host as well.
That is a much broader effect than the per-address decision the audit just made,
and it contradicts it.

So the blacklist is applied only when the audit is assessable and every detected
GPU is bindable: when the host is genuinely dedicating its GPUs to guests. Its
absence does not prevent binding, because `driver_override` plus an unbind
succeeds whenever nothing holds the device open; the blacklist only removes the
race with a driver that would otherwise claim the card at boot. Where it is not
applied, a bind that fails because a driver still holds the card fails visibly
rather than silently.

The consequence either way is that `gpu-detection-service.yml`'s `nvidia-smi`
MIG branch cannot run on a host whose GPUs are all bound, which is already true
today and should be stated rather than left as a silent no-op.

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

*Resolved — capacity counts passthrough-capable cards, and this change closes
the gap it opens.*

The host capacity check counted GPUs with
`lspci -nn | grep -iE 'vga|3d|display' | grep -E '\[10de:|\[1002:'`: every
NVIDIA or AMD card present, whether or not it could be handed to a guest. While
the role bound every card it found, that count was approximately right. Once
cards in unsafe groups are deliberately skipped, it over-reports — the host
publishes capacity that no create job can satisfy, and the failure surfaces at
VM creation as a GPU attachment error rather than at the point the capacity was
claimed.

The discrepancy is created here, so it is closed here rather than deferred: the
count and the GPU details now report cards bound to `vfio-pci`, which is
exactly the set that can be attached to a guest. Only `.0` functions are
counted, preserving parity with the allocation logic in the same task, which
treats a card's audio and USB functions as bound alongside it rather than
separately allocatable.

This also reads correctly on a host prepared by the previous mechanism: a card
bound through a command-line `ids=` list is still `vfio-pci`-bound, so it still
counts. And it reads correctly between enabling the IOMMU and the reboot that
activates it — nothing is bound yet, the host reports zero, and that is true.

Whether declared *sellable* capacity, as opposed to this host-level count,
should also derive from the audit remains owned by
`capacity-resource-administration`. The relationship is now a narrow one: this
change makes the host-level number honest, and that change decides what is
published from it.

**Does the rented node's BMC console survive `vfio-pci` claiming the ASPEED
VGA?** On the affected machine `1a03:2000` was in the bind list. The BMC is a
separate service processor and normally retains its own network path, so remote
console access should survive losing the VGA function — but "normally" is
carrying weight, and if the console is the documented last resort its
availability should be confirmed on the specific hardware rather than assumed.
This is an operations question, answerable once a node is rented, and it does
not block implementation.
