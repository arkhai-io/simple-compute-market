## MODIFIED Requirements

### Requirement: Passthrough binding cannot strand a host

Host preparation MUST NOT render a machine unreachable. A device is assigned to guests by binding a PCI address, never a vendor/device identifier: an identifier matches every device presenting it anywhere in the machine, including devices in IOMMU groups no decision considered.

Passthrough viability MUST be audited before any binding is configured, and the audit MUST be read-only so it is safe to run against a machine nothing else has touched. A GPU whose IOMMU group contains a network controller, a storage controller, the device carrying the host's default route, or the device carrying its root filesystem MUST be reported unavailable rather than bound, because assigning it would require assigning that device with it.

An absent or disabled IOMMU MUST fail closed. "No groups because the IOMMU is disabled" and "groups assessed, no conflicts found" MUST be distinguishable outcomes, and only the second may result in a device being bound.

Bindings MUST be applied while an operator or automation holds a live connection to the host, and MUST NOT be persisted across reboots until they have been applied and verified on that machine. A reboot may enable the IOMMU, which claims no device; it MUST NOT carry a device binding that has not been verified.

Declared GPU capacity MUST count devices that can be assigned to a guest, not devices present, so a host does not publish capacity no fulfillment can satisfy.

Passthrough boot configuration — the IOMMU kernel arguments, passthrough module loading, the rescue boot entry, and GPU detection — MUST be applied only to a host on which a GPU is present, unless the operator explicitly enables or disables it for that host. Presence MUST be decided without the IOMMU, from each PCI device's class and vendor: a display or 3D controller from a vendor whose GPUs are passed through. The passthrough audit cannot decide it, because it assesses nothing until the IOMMU is enabled and enabling the IOMMU is part of this configuration; a display controller's class alone cannot either, because a server's management controller and a virtual machine's emulated display present it. Binding still follows only an assessable audit. A host with no GPU present has its boot configuration left as it was, because changing the boot of a machine reachable only over its network buys nothing and risks the machine. An override value other than enabling, disabling, or leaving the decision to presence MUST fail preparation, naming the value.

#### Scenario: A GPU shares its group with a host-critical device

- **WHEN** the audit finds a GPU whose IOMMU group contains the device carrying the host's default route
- **THEN** that GPU is reported unavailable with the blocking device named, no binding is configured for it, and any GPU in a clean group on the same host is still bindable

#### Scenario: The IOMMU is not enabled

- **WHEN** the audit runs on a host exposing no IOMMU groups
- **THEN** it reports that viability cannot be assessed, distinctly from reporting no conflicts, and no device is bound

#### Scenario: A binding is applied

- **WHEN** audited bindings are applied
- **THEN** they are applied with a live connection to the host, every audited address is confirmed bound, the device carrying the default route is confirmed to hold the driver it held beforehand, and only then is the binding made to persist across reboots

#### Scenario: A binding fails

- **WHEN** applying a binding fails
- **THEN** the failure is reported, the host remains running and reachable, virtualization remains available, and the affected device is not counted as capacity

#### Scenario: A host has no GPU

- **WHEN** host preparation runs on a host with no GPU present — including one whose only display controller is a management controller's or an emulated one — and the operator has not enabled passthrough
- **THEN** its kernel command line, module loading, and boot entries are unchanged, no GPU-detection service is installed, and preparation otherwise completes

#### Scenario: A GPU host's IOMMU starts disabled

- **WHEN** host preparation runs on a host with a GPU present whose IOMMU is not yet enabled, and the operator has not disabled passthrough
- **THEN** passthrough boot configuration is applied, enabling the IOMMU on the next boot, and no device is bound until an audit after that boot can assess it

#### Scenario: The operator forces passthrough configuration

- **WHEN** the operator enables or disables passthrough configuration for a host
- **THEN** preparation applies or skips it as instructed, whatever is present, and the audit's findings still decide which devices may be bound

#### Scenario: The override names an unknown value

- **WHEN** the operator's passthrough override is neither enabled, disabled, nor left to presence
- **THEN** preparation fails before changing the host, naming the value

## ADDED Requirements

### Requirement: VM hosts must provide hardware virtualization

Host preparation MUST fail, naming the cause, on a host whose CPU exposes no hardware virtualization extension or that has no KVM device once the KVM modules are loaded. VM creation MUST request KVM explicitly, so a VM is never created under software emulation on a host that has lost KVM since it was prepared.

#### Scenario: A host without virtualization extensions

- **WHEN** host preparation runs on a machine whose CPU exposes neither `vmx` nor `svm`, such as a cloud instance created without nested virtualization
- **THEN** preparation fails before configuring KVM networking or rebooting, with a message saying hardware virtualization is unavailable

#### Scenario: KVM disappears after preparation

- **WHEN** a create job runs on a prepared host whose KVM device is no longer present
- **THEN** the create fails reporting that KVM is unavailable, and no VM is left running under emulation

### Requirement: Host preparation defaults to the image VM creation uses

Host preparation MUST default to preparing a host for the image source VM creation defaults to, so a host prepared without options can serve the VMs market fulfillment creates. Preparing for a golden image MUST be an explicit choice.

#### Scenario: A host is prepared without options

- **WHEN** an operator runs host preparation without naming an image setup type
- **THEN** the host is prepared for scratch-image VMs, and no object-storage, service-account, or image-build step runs

#### Scenario: The operator names the golden image

- **WHEN** an operator runs host preparation naming the golden image setup type
- **THEN** the golden-image steps run as before
