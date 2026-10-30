# Design: Prove real VM provisioning end to end

## Context

Designed against `dev` at `1f157a17d6022bef06c41233c082060ff3ed7198`.

**Every VM scenario is mock-bound.** `Stage00e_ProvisioningMockMode`
(`e2e-tests/tests/e2e/roles/helpers/compute_deal_stages.py`) asserts
`execution.mocked`. The VM drivers arm mock rules through the `/test/*` routes, which
the provisioning service mounts only when `ACTIVE_PROFILES` contains `mock`
(`provisioning/compute/service/src/compute_provisioning_service/main.py`, "Test
controller — only mounted when mock profile is active"). Delivery is asserted as
non-empty `tenant_credentials`; no scenario connects to a VM.

**What survives outside the mock profile.** The job gates (`pause_before_result`,
held in `provisioning/compute/src/compute_provisioning/jobs/executor_mock.py`) and
`/test/jobs/{wait,drain}` do not. The module-level worker holds and explicit advances
do: fulfillment-convergence pause and `advance_fulfillment_convergence_cycle`, the
lease-watchdog pause, lease truncation through the site, and the storefront loop
holds, all on the ordinary admin client
(`provisioning/compute/client/src/compute_provisioning_client/client.py`;
`e2e-tests/tests/e2e/roles/helpers/compute_deal.py`). Job state is readable through
`get_job`, `get_job_credentials`, and `get_job_logs`.

**The shared stages.** `compute_deal_stages.py` defines the canonical deal once; each
lane subclasses its stages with empty bodies and supplies differences through
fixtures and `ComputeDealDriver`. Five stages call mock-only driver hooks: 07
(`arm_create_gate`), 08c (`evaluate_create_job`, returning `MockJobEvaluation`), 09a
(`release_create_gate` and a drain), 10a (`arm_teardown_gate`), and 11b
(`release_teardown_gate`).

**Registration is the scenario's.** `scenarios/vms/host_registry.py` registers the
pool, the executor host (idempotently), and the capacity declaration through the
admin APIs; its module docstring records why all three must exist.

**GPU-less shapes in the helpers.** `capacity_source_for`
(`scenarios/vms/conftest.py`) reads `resource["gpu_model"]` unconditionally and the
VM drivers hard-code `gpu_count: 1`. The only GPU-less coverage is
`test_listing_shapes.py`'s `kvm-shapes-cpu`.

**Configuration.** The e2e settings load `config.yml` and one `config-<profile>.yml`
per `ACTIVE_PROFILES` entry from `CONFIG_DIRECTORY`, then `ARKHAI_*` variables
(`e2e-tests/src/e2e_harness/settings.py`, `kit/config/src/market_config/dynaconf_bootstrap.py`).
A profile file placed in the config directory is picked up with no loader change.
`provisioning/compute/service/src/compute_provisioning_service/config/config-local.yml.example`
is the precedent for a committed example beside an ignored local file.

**Host preparation.** `domains/vms/provisioning/iac/ansible/playbooks/host-kit/vm-setup.yaml`
runs, in order: system packages, the passthrough audit, GPU passthrough, the rescue
boot entry, KVM setup, KVM network, security hardening, SSH keys, the VM tunnel
client (only with `frp_server_addr`), the golden build (only for `golden`), the
GPU-detection service, and an unconditional reboot. It defaults `vm_image_type` to
`golden`; market fulfillment defaults to `scratch`
(`domains/vms/provisioning/adapter/src/vm_provisioning_adapter/models/fulfillment_model.py`).
`kvm-setup.yml` checks for `vmx`/`svm` with `ignore_errors` and enables nested
virtualization only if found; `/dev/kvm` is reported, never asserted; `vm-create.yml`
passes no `--virt-type`.

**Access.** Delivered access is `ssh -i <key> -p <port> user@addr`, with `addr` the
host's `public_host` or `ssh_host` and `port` the DNAT port the create job reports
(`domains/vms/provisioning/adapter/src/vm_provisioning_adapter/codec.py`). The guest
reboots once from cloud-init after first boot. The VM domain does not deliver the
guest's host key. The only scenario that opens SSH today is
`scenarios/bare_metal/test_bare_metal_deal.py`, by `subprocess`.

**Dead material.** The e2e package's own nested `e2e.yml` workflow is never run (GitHub reads
only the repository root's workflows). `e2e-tests/README.md` documents
`e2e-mock-happy`/`e2e-mock-failure`, which do not exist.
`docs/development/VALIDATION_RUNBOOK.md` §21–26 describes a manual real-host proof
whose raw calls predate signed admin principals.

## Goals and non-goals

Goals: a scenario that proves, against a real KVM host, that a GPU-less VM deal is
provisioned by the real Ansible path, reachable by its buyer with the delivered access
and the negotiated key while an unrelated public key is refused, and removed with its
access ended when the lease expires;
host preparation that fails closed on a host that cannot run KVM and leaves a
GPU-less host's boot configuration alone.

Non-goals are in `proposal.md`.

## Decisions

### D1. The target is a typed settings section in an ignored profile file

The scenario reads its target from a `REAL_VM_TARGET` section of the e2e settings,
loaded from `config-real-vm-target.yml` in the e2e config directory when the run selects the
`real-vm-target` profile (`ACTIVE_PROFILES=local,real-vm-target`). An environment
owner renders that file and places it in the config directory. The repository
commits `config-real-vm-target.yml.example`, carrying obviously fictitious values,
and ignores `config-real-vm-target.yml`.

```yaml
# Example values only — documentation addresses and fictitious names. An environment
# owner renders the real file; never commit it.
REAL_VM_TARGET:
  version: 1
  host:
    host_id: example-kvm-1
    ssh_host: 192.0.2.10        # RFC 5737 documentation address
    ssh_user: provisioner
    ssh_port: 22
    ssh_key_path: /run/secrets/example-host-key   # where the service reads its key; never the key
    public_host: 192.0.2.10
    capacity: {vcpu_count: 7, ram_gb: 28, disk_gb: 160}
  access: {mode: direct}
```

Version 1 describes exactly one host, as a mapping rather than a list: the scenario
deals once on one shape, and a list would document a selection the format does not
have. Serving several hosts is a later version's, with its own selection rule.

`ssh_key_path` is where the provisioning service reads the key it reaches this host
with — a path in the service's filesystem, which whoever deploys the stack arranges
together with the key (D3). It is not key material, and the SSH connection the host
is registered with names its key by it.

`capacity` is what the host **sells** — its hardware less whatever the environment
owner reserves for the host itself — not the hardware. Its keys are the VM capacity
dimensions every VM lane declares, `vcpu_count`, `ram_gb` (GiB), and `disk_gb`, each
a positive integer and all three required. It is registered as the declaration's
`capacity` unchanged, and the listing shape is derived from it by
`capacity_source_for` (`cpu.count`, `memory.gib`, `storage.gib`, with no GPU family;
D6), so the one deal takes everything the host sells and the shape checks (D7)
compare the guest against it. Rendering hardware totals would ask for a guest holding
all of the host's memory and disk.

The scenario validates the section with a typed model before any stage runs and
before anything is written to the stack, fixture setup included (10 F5): a
missing or misspelled field fails with a message naming it rather than falling back
to a default, an unknown `version` is refused rather than interpreted, and
`access.mode` is an enum whose version 1 admits only `direct`. The model's fields are
the format's documentation. The section never carries the host's private key: the
provisioning service already holds the key it reaches hosts with. Should a later
field need secret material, the file is written owner-only and the `.example` shows
where such a field sits with a fictitious value. Without the profile the scenario
skips, naming the profile it needs.

Rejected: a JSON descriptor with its own schema and an environment variable naming
its path (a second configuration mechanism beside dynaconf for one scenario);
`ARKHAI_*` variables alone (flat, unvalidated, silent defaults on a typo); an include
hook for a file outside the config directory (unnecessary once the file is placed in
the directory).

### D2. The scenario registers its own supply

From the target, the scenario registers a pool stating a GPU-less listing shape, the
executor host, and its one capacity declaration, through the `host_registry.py`
helpers. The deployment seeds no host inventory. Convention: the VM lane already
registers everything it reads.

`register_e2e_host` takes an optional SSH connection. The mock lanes omit it and keep
today's placeholder, which nothing connects to. The real lane passes the connection
built from the target (`ssh_host`, `ssh_user`, `ssh_port`, `public_host`,
`ssh_key_path`). A host that already exists has its connection replaced when it
differs (`HostUpdate.connection`), not only its pool reconciled, so a stack surviving
an earlier run never sends the create to a stale address; and the registered host's
public connection is checked against the target before any deal stage runs.

The VM scenarios' module-autouse `_ensure_provisioning_host_registered` registers a
stub `kvm1` host for the mock lanes. The real module overrides it with a fixture of
the same name that registers nothing, so the only host the real lane writes is the
target's (10 F5). Its setup fixtures depend on the validated target (D1) and the
VM-execution check (D4a), so a run without its profile, with a malformed target, or
against a mocked service writes nothing to the stack.

The registrations follow the VM scenario convention: they are left in place, and the
next run's registration reconciles them (10 F6). Pools are disabled, never deleted,
hosts are disabled, never deleted, and the site has no operation that retracts a
declaration; idempotency here is that a rerun reconciles, not that a run removes.

### D3. The scenario's credentials are the local profile's

The scenario signs as the principals of the `local` profile and reaches services on
its forwarded ports. Whoever deploys the stack it runs against supplies matching
identities and the provisioning service's host key; the scenario receives neither.

### D4. Determinism without job gates

The real lane keeps every hold and explicit advance that exists outside the mock
profile: convergence and the lease watchdog are held for the module, and each
transition the lane asserts is triggered by a stage. Where a mock lane releases a job
gate and drains, the real lane polls `get_job` until the job is terminal, bounded by
a named timeout sized for a real create (cloud image fetch, guest install, the
cloud-init reboot), then advances. It asserts what mocks cannot prove: the service's
VM execution is not mocked, the create and teardown jobs ran and succeeded, the
buyer's access works, the VM no longer exists on the host once its capacity is
released, and access has ended. Intermediate states the mock lanes prove under their
gates are left to them.

**Finding the jobs.** The fulfillment path surfaces no executor job id, so the real
lane correlates through the fulfillment's `capacity_reservation_id`, which the status
08b reads carries, and the operator job list filtered by it
(`list_jobs(capacity_reservation_id=…)`):

- The create-job poll lists the reservation's jobs and requires exactly one, on the
  target host; it polls that job to terminal, requires `succeeded`, and records its
  id, which 09c then also checks the lease's `create_job_id` equals, and the guest's
  `vm_name` from its result.
- The teardown-job poll, once teardown is dispatched, lists the reservation's jobs
  and requires exactly one besides the create job, on the target host, and polls it
  the same way.
- No match fails naming the reservation and the fulfillment's state; several
  matches fail listing them; a failed job fails with its error and its
  `get_job_logs` output; a timeout fails with the job's last status and its logs.

**Observing the guest's absence (10 F2).** A succeeded teardown job reports what the
playbook did, and a refused connection is as consistent with a running guest whose
forward or key was removed; neither shows the guest gone. Once the teardown job has
succeeded, the lane submits a host-scoped `list_vms` job on the target host through
the VM operator client, polls it within the same bound, and requires a succeeded job
with a well-formed list in which the recorded `vm_name` is absent. A failed list job
or a missing list fails the check. The refused delivered access stays a separate
assertion: it proves access ended, not that the guest is gone.

**When the run fails (10 F6).** A failure after the create leaves a guest on a real
host, and every later stage, 10a and 11b among them, skips on its missing
prerequisite. A finalizer in the real module, when the run dispatched a fulfillment
and its own teardown did not complete, truncates this deal's lease through the site
and advances the held workers, so the provisioning service tears the guest down
through its own lease lifecycle; the test layer reimplements no teardown. It then
looks for the teardown job and the guest's absence as above, and where it cannot
confirm removal — no lease because the fulfillment never reached `active`, a failed or
timed-out teardown, the guest still listed — it fails the run naming the fulfillment,
reservation, create and teardown job ids, guest name, and host, for an operator to
recover by hand. Only then are the module's worker holds released. The real module
never uses `release_reserved_resources`: `admin_release_reservations` is fleet-wide,
and would return the host's capacity to the market while its guest still runs.

Where the existing operator interface proves insufficient for a check the lane
needs, the provisioning service may gain an operation for it; the job list is the
starting mechanism, not a limit.

Rejected: job gates in real mode under a dedicated profile (a test hook in the real
executor's path, a new authority surface to keep impossible under production
configuration, and the gated job still runs for minutes); asserting the gated
intermediate states opportunistically (conditional assertions that read as
coverage).

### D4a. Shared stages split at their mock gates

Each shared stage that calls a mock gate — 07, 09a, 10a, 11b — is split at the gate.
Its gate-free part stays shared; its gate part becomes a mock-only stage named for
what it does: 07 becomes the on-chain escrow stage plus a create-gate arm; 09a a
create release-and-drain plus the shared advance to `active`; 10a a teardown-gate
arm plus the shared expiry; 11b a teardown release-and-drain plus the shared
completion and release. 08c, whose assertions are about the mock rule, becomes
mock-only. The real lane inserts its own create-job and teardown-job polls (D4) where
the mock lanes release. `Stage00e_ProvisioningMockMode` stays mock-only.

The real lane's own first check reads `execution.executors` and requires the entry for
offering mode `vm` with `mocked=false`; an absent or mocked entry fails naming the
reported executors, before any registration or deal mutation (10 F3). It cannot invert
00e: `execution.mocked` is true only when every composed executor is the mock, so a
service with a real bare-metal executor and a mocked VM one reports `false`. A
per-mode entry suffices because the VM bundle composes one executor for every VM
action (`build_vm_adapter_bundle`), so create, list, and teardown are mocked or real
together.

08b and 11a stay shared. Neither calls a gate, and the states they assert —
`dispatching` after settlement, `tearing_down` after the dispatching cycle — hold
because convergence is held for the module and only a stage's explicit advance
observes a provider's outcome; a real job finishing moves neither. 08b's message
says the fulfillment is dispatched and not yet converged.

08b submits settlement, so it must still skip when the preflight before it fails
(10 F1). Its prerequisite becomes a readiness field, `_settle_preflight_passed`,
written by the stage immediately before it in every lane, in place of the mock-only
`_provision_job_evaluated`: in the mock lanes 08c writes it once its assertions pass,
which keeps today's failure path; in the real lane a real-only preflight after 08a
writes it once the settlement preview's chosen host (`_evaluate_settle_host_id`) is
the target's `host_id`, so the deal cannot settle onto another registered host. Each
lane has one producer of the field and 08b consumes it, as the stage unit tests
require.

The resulting orders:

- **Mock lanes:** 07 escrow → create-gate arm → 07b → 08a → 08c → 08b → create
  release-and-drain → 09a advance to `active` → 09b → 09c → teardown-gate arm → 10a
  expiry → 10b → 11a → teardown release-and-drain → 11b completion and release.
- **Real lane:** the same shared stages, with its VM-execution check in place of 00e,
  its settlement preflight between 08a and 08b, a create-job poll between 08b and
  09a, the SSH access stages (D7) after 09c, a teardown-job poll between 11a and 11b,
  and the VM-gone (`list_vms`) and access-ended checks after 11b.

The gate methods (`create_rule_id`, `teardown_rule_id`, `arm_*`, `release_*`,
`evaluate_create_job`) move from `ComputeDealDriver` to a `MockGates` part that only
the VM and bare-metal mock drivers implement. Both mock lanes list the new mock-only
stages where the split stages were, so their coverage and order are unchanged. The
real VM driver implements `ComputeDealDriver` alone.

Rejected: generalising the gate hooks into semantic ones (`hold_create`,
`complete_create`) that the real driver answers with a no-op hold. A real-lane run
would then report a gate stage as passed when nothing was held, and a shared stage's
assertion would hold under one driver and be vacuous under another.

### D4b. A direct-access create reports the port it forwarded

Settled by the owner after live verification 8.2's first run; another design review
waived. The VM adapter's result codec (`build_result_payload` in
`domains/vms/provisioning/adapter/src/vm_provisioning_adapter/codec.py`) replaced the
port it parsed from the playbook's output with the relay block's `remote_port` whenever
that value was truthy. `vm-create.yml` reports the relay block on every create, and with
no relay it reports `enabled: false` and `remote_port: "N/A"`, so a direct-access
create's forwarded port became `"N/A"`, `create_evidence` could not read it as a port,
and the create reported no delivery evidence: the fulfillment failed though the guest
was running and reachable. The mock lanes never interpret playbook output, and the
codec's unit fixtures were hand-built payloads without the relay block the playbook
emits, so nothing caught it.

The relay's `remote_port` replaces the access port only when the playbook reports the
relay enabled — the same rule `create_evidence` already applies to a relayed guest — and
the value is a port number; otherwise the port parsed from the output stands. The codec
is tested against the fact shape `vm-create.yml` actually emits, through the executor,
with the relay disabled.

Rejected: removing the replacement (the relay branch of the evidence already reads the
relay's port, but what a relayed create reports as its `ssh_port` would change on a path
no lane runs live); changing the playbook to omit the relay block or report nulls when
there is no relay (two fact blocks change, and the codec would still mis-read any
`"N/A"` placeholder).

### D5. Placement and invocation

A marker, `e2e_vm_real_provisioning`, registered in `e2e-tests/pyproject.toml` and in
no default lane, on a module `scenarios/vms/test_real_provisioning_deal.py` with a
real VM driver. It runs from an operator's machine against forwarded services through
the existing `make -C e2e-tests test-module MODULE=e2e_vm_real_provisioning
ACTIVE_PROFILES=local,real-vm-target`. Convention: `e2e_bare_metal_deal`, which is in
no lane and skips without its configuration.

### D6. GPU-less shapes in the e2e helpers

`capacity_source_for` and the VM drivers read GPU fields only when the shape carries
them. The real lane's shape and declaration come from the target's `capacity`. The
mock lanes keep their GPU shapes. Convention: `test_listing_shapes.py`
`kvm-shapes-cpu`.

### D7. What the scenario proves over SSH

- **What a connection proves.** With the delivered command, `ssh … true` succeeds;
  `id -un` is the delivered user; `nproc` equals the negotiated `vcpu_count`;
  `MemTotal` is within a named tolerance of the negotiated `ram_gb` in GiB; the root
  disk is at least the negotiated `disk_gb`; and a second, unrelated key is refused. The tolerance
  starts strict and is loosened only on evidence.
- **What the refused key proves (10 F4).** That the delivered account's
  `authorized_keys` admits the negotiated key and not an arbitrary one — not that
  the negotiated key is the only way in. The scratch guest also enables password
  authentication and root login and carries root and tenant passwords, which
  `BatchMode=yes` never tries; this scenario neither exercises nor claims anything
  about them. Making guest access key-only is a product change to what delivery
  promises, not part of proving the current path.
- **Keys.** The scenario generates an ed25519 key pair per run, owner-only, with the
  `cryptography` package, and negotiates its public half.
- **Host key.** Trust on first use per run: `StrictHostKeyChecking=accept-new`
  against a run-scoped `known_hosts`, reused by every later connection in the run, so
  a host swapped mid-run fails; the fingerprint is logged. Pinning needs the VM
  domain to deliver the guest's host key and is a product follow-up.
- **Client.** The system `ssh`, with `BatchMode=yes` and `ConnectTimeout`, retried
  within a bounded window to absorb the cloud-init reboot, behind one domain-neutral
  helper, `e2e-tests/tests/e2e/roles/helpers/ssh_access.py`. A bare-metal access
  helper exists on an unmerged branch; whichever lands second converges on one
  helper.
- **After teardown,** the same helper asserts the connection fails, refused or timed
  out, within a bound.

Rejected: reachability only (proves a VM, not the VM sold); `asyncssh` (a new
dependency and a departure from precedent, worth revisiting only when the scenario
runs in a pod); `StrictHostKeyChecking=no`.

### D8. Direct access only; the relay-backed lane is a follow-up

This change proves direct access through the host's DNAT. The real driver and the
target treat the access mode as a parameter, so relay-backed access is additive. A
relay-backed real lane is the next change in this area: it takes the roadmap's
unowned gap that no end-to-end lane runs a relay-backed pool, and its run is the live
evidence `relay-vm-access-without-a-dashboard` needs to close.

### D9. Host preparation fails closed and leaves GPU-less hosts' boot alone

- **9a. Hardware virtualization is required.** Host preparation fails, naming the
  cause, when the CPU exposes no `vmx`/`svm` or `/dev/kvm` is absent after the KVM
  modules load. VM creation passes `--virt-type kvm`, so a create never falls back to
  software emulation. Rejected: asserting in preparation only (misses a host that
  loses KVM later); leaving it (an operator without nested virtualization gets a late,
  unrelated failure).
- **9b. Passthrough boot configuration follows GPU presence; binding follows the
  audit.** An operator variable, `gpu_passthrough: auto | enabled | disabled`
  (default `auto`), forces either way; any other value fails preparation, naming the
  value. Under `auto` the rule has two phases (01 F5):
  - *Presence decides the boot configuration.* Preparation reads PCI class and
    vendor from sysfs, which needs no IOMMU, and a display or 3D controller (`0300`,
    `0302`) from a vendor whose GPUs the market passes through — NVIDIA (`10de`) or
    AMD (`1002`) — is GPU presence. Presence runs the GPU passthrough configuration
    (the IOMMU kernel arguments among it), the rescue boot entry, and the
    GPU-detection service.
  - *The audit decides binding.* Binding still happens only after the reboot, from
    an assessable audit's bindable addresses, exactly as before. It runs only
    where the passthrough configuration ran (found in implementation): binding
    writes its list into a directory the configuration creates and applies it
    through the `vfio-bind` unit the configuration installs, so on a host
    prepared without it the bind phase would fail preparation rather than bind
    nothing. Skipping the configuration, under `auto` without a GPU or under
    `disabled`, does not undo an earlier one: a unit an earlier preparation
    enabled stays enabled.

  The audit cannot be the boot gate: with the IOMMU disabled it reports nothing
  assessable and no GPUs, and enabling the IOMMU is one of the gated steps, so a GPU
  host whose IOMMU starts disabled would never be prepared. Presence cannot be class
  alone: a server's BMC display controller and the emulated VGA of most KVM cloud
  instances are class `0300`, so a class test would change the boot of exactly the
  GPU-less hosts this rule spares. A listed-vendor card the operator did not mean to
  pass through gets the IOMMU arguments, as every host does today; an unlisted
  vendor is treated as GPU-less until the operator sets `enabled`. A host that gains
  GPUs later re-runs preparation, as binding them requires anyway. Rejected: an
  explicit variable defaulting to enabled (a GPU-less host gets boot changes unless
  someone remembers); leaving it (boot changes on every GPU-less host the market can
  now sell); `auto` keyed to the audit with `enabled` required for a GPU host whose
  IOMMU starts disabled (moves a step onto the operators of exactly the hosts the
  market sells).
- **9c. Host preparation defaults to the scratch image**, the image market
  fulfillment creates from. The golden image becomes an explicit choice, and the
  documentation that states the default is updated with it.
- **9d. The SSH hardening is applied by restarting the daemon's own unit** (settled by
  the owner after live verification 8.1; another design review waived). Preparation's
  `restart sshd` handler, notified when the hardening block is written to
  `sshd_config`, named a unit Ubuntu 24.04 does not have (`ssh.service` there) and
  ignored its own failure. In 8.1's run the preparation reboot, tagged `always`,
  restarted the daemon first, so nothing was lost; on a host whose configuration
  changes without that reboot the hardening would silently not take effect. The
  handler restarts the unit the host's OS family names — `ssh` for the Debian family,
  `sshd` otherwise, the `ansible_os_family` idiom the provisioning roles already use —
  and a failure fails preparation. Rejected: a static `ssh` (breaks the non-Debian
  hosts the role does not otherwise exclude); keeping `ignore_errors` (the defect is
  that a failed restart went unnoticed); tracking it as an issue (the owner chose to
  fix it here, since the run that found it is this change's). The golden image's
  Packer cloud-init template (`roles/vm-setup/templates/user-data.j2`) also restarts
  `sshd`, but only the golden build renders it — scratch guests take their cloud-init
  from `vm-create.yml`, which already tries `ssh` then `sshd` — so it stays with the
  golden image under D10, noted on `fix-golden-image-config`.

### D10. The golden image is out of scope

Scratch needs only outbound network access from the host. The golden path needs a
service-account key file activated on the host, an object-storage bucket, Packer on
the host, golden settings in the service, and a way for a market deal to select it,
which has not been confirmed to exist. What the golden image is for — given that
scratch already fetches over the network and golden adds a storage dependency — is
to be re-evaluated by `fix-golden-image-config` before its configuration is fixed.

### D11. Dead material

The e2e package's nested `e2e.yml` workflow is deleted; the README's nonexistent targets
are removed; `VALIDATION_RUNBOOK.md` §21–26 is rewritten as the manual counterpart of
the real lane, against the current signed admin API and the D9 defaults, for an
operator-provided host. The dead markers `mock_provisioning*`, `roles_*`, and
`roles_cli_*` and unrelated Makefile cleanup are out of scope.

### Implementation cadence

Two rounds, one session each.

- **Round 1 — everything the mock lanes and unit tests can prove:** the D4a stage
  split and `MockGates`; GPU-less helper support (D6); the D9 host preparation and
  VM creation changes with their IaC tests; the target settings model, `.example`,
  and ignore rule (D1); the SSH helper and its unit tests (D7).
- **Round 2 — the real lane:** the real driver and scenario module (D2, D4, D5, D7),
  marker registration, and the D11 documentation; then, added after 8.1's run, the
  D9d handler fix, ahead of the remaining live verification and a re-run of host
  preparation that shows it; then, added after 8.2's first run, the D4b codec fix,
  ahead of the scenario's runs. Its validation is a run against a
  real host; the evidence recorded here is the scenario's result, the access checks'
  output, and the teardown checks, with no environment identifiers.

Round 2's real-host run cannot be part of the pipeline or of a change validation:
validation runs the lanes and the Helm namespace, where the real lane has no target
and skips. Round 2 therefore ends with a live-verification section in the
`[log]` form `relay-vm-access-without-a-dashboard` and
`never-strand-the-host-on-passthrough` use: each item states its acceptance, and the
owner supplies the run's output, already free of addresses, project, cluster,
namespace, and host names, for checking against it here. Until it is supplied the
change is `blocked in implementation` on that external input. The pipeline's result
is evidence for round 2 only in that every lane still passes and the real lane skips
naming its profile.

## Risks and trade-offs

- **The real lane is not in the pipeline.** It runs only when someone provides a
  host, so it can rot. Its marker, the `.example`, and the runbook keep the run
  reproducible; moving it into the scenario pod is named later work.
- **Timing bounds.** A real create's duration depends on the host and the network.
  The poll bound is a named constant and a timeout reports the job's logs rather than
  only the elapsed time.
- **Shape tolerance.** Guest memory reporting varies with kernel and image; a
  tolerance too tight fails spuriously. It starts strict as a named constant.
- **The stage split touches both mock lanes.** Their stage lists change shape while
  their coverage must not; round 1 is validated by both lanes passing unchanged in
  outcome.
- **Interaction with `never-strand-the-host-on-passthrough`.** Its tasks now run only
  on a host with an NVIDIA or AMD GPU present, whether or not its IOMMU is enabled
  yet, and binding still follows its audit, so its live verification on such a host
  is unaffected.
- **The vendor allow-list.** Presence names the vendors whose GPUs the market passes
  through. A new vendor's cards are treated as GPU-less until the list gains it or
  the operator sets `enabled`.

## Open Questions

None.
