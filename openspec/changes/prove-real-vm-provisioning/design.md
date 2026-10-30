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

**Dead material.** `e2e-tests/.github/workflows/e2e.yml` is never run (GitHub reads
only the repository root's workflows). `e2e-tests/README.md` documents
`e2e-mock-happy`/`e2e-mock-failure`, which do not exist.
`docs/development/VALIDATION_RUNBOOK.md` §21–26 describes a manual real-host proof
whose raw calls predate signed admin principals.

## Goals and non-goals

Goals: a scenario that proves, against a real KVM host, that a GPU-less VM deal is
provisioned by the real Ansible path, reachable by its buyer with the delivered
access and only with it, and removed with its access ended when the lease expires;
host preparation that fails closed on a host that cannot run KVM and leaves a
GPU-less host's boot configuration alone.

Non-goals are in `proposal.md`.

## Decisions

### D1. The target is a typed settings section in an ignored profile file

The scenario reads its target from a `REAL_VM_TARGET` section of the e2e settings,
loaded from `e2e-tests/config/config-real-vm-target.yml` when the run selects the
`real-vm-target` profile (`ACTIVE_PROFILES=local,real-vm-target`). An environment
owner renders that file and places it in the config directory. The repository
commits `config-real-vm-target.yml.example`, carrying obviously fictitious values,
and ignores `config-real-vm-target.yml`.

```yaml
# Example values only — documentation addresses and fictitious names. An environment
# owner renders the real file; never commit it.
REAL_VM_TARGET:
  version: 1
  hosts:
    - host_id: example-kvm-1
      ssh_host: 192.0.2.10        # RFC 5737 documentation address
      ssh_user: provisioner
      ssh_port: 22
      public_host: 192.0.2.10
      capacity: {cpu_count: 7, memory_gib: 28, disk_gib: 160}
  access: {mode: direct}
```

`capacity` is what the host **sells** — its hardware less whatever the environment
owner reserves for the host itself — not the hardware. It is the capacity declaration
the scenario registers, and the listing shape the scenario states equals it, so the
one deal takes everything the host sells and the shape checks (D7) compare the guest
against it. Rendering hardware totals would ask for a guest holding all of the host's
memory and disk.

The scenario validates the section with a typed model before any stage runs: a
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
executor host, and one capacity declaration per host, through the existing
`host_registry.py` helpers. The deployment seeds no host inventory. Convention: the
VM lane already registers everything it reads.

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
cloud-init reboot), then advances. It asserts what mocks cannot prove: the service is
not mocked, the create and teardown jobs ran and succeeded, the buyer's access
works, the VM no longer exists on the host once its capacity is released, and access
has ended. Intermediate states the mock lanes prove under their gates are left to
them.

Rejected: job gates in real mode under a dedicated profile (a test hook in the real
executor's path, a new authority surface to keep impossible under production
configuration, and the gated job still runs for minutes); asserting the gated
intermediate states opportunistically (conditional assertions that read as
coverage).

### D4a. Shared stages split at their mock gates

Each shared stage that calls a mock gate is split at the gate. Its gate-free part
stays shared; its gate part becomes a mock-only stage named for what it does (for
example, 07 becomes the on-chain escrow stage plus a create-gate stage; 09a becomes
a release-and-drain stage plus the shared advance to `active`). 08c and 11a, whose
assertions exist only under a gate, become mock-only. The real lane inserts its own
"poll the create job to terminal" and "poll the teardown job to terminal" stages
where the mock lanes release. `Stage00e_ProvisioningMockMode` stays mock-only and the
real lane adds its own not-mocked check.

The gate methods (`create_rule_id`, `teardown_rule_id`, `arm_*`, `release_*`,
`evaluate_create_job`) move from `ComputeDealDriver` to a `MockGates` part that only
the VM and bare-metal mock drivers implement. Both mock lanes list the new mock-only
stages where the split stages were, so their coverage and order are unchanged. The
real VM driver implements `ComputeDealDriver` alone.

Rejected: generalising the gate hooks into semantic ones (`hold_create`,
`complete_create`) that the real driver answers with a no-op hold. A real-lane run
would then report a gate stage as passed when nothing was held, and a shared stage's
assertion would hold under one driver and be vacuous under another.

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
  `id -un` is the delivered user; `nproc` equals the negotiated vCPU count;
  `MemTotal` is within a named tolerance of the negotiated memory; the root disk is
  at least the negotiated size; and a second, unrelated key is refused. The tolerance
  starts strict and is loosened only on evidence.
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
- **9b. Passthrough boot configuration follows the audit.** GPU passthrough
  configuration, the rescue boot entry, and the GPU-detection service run when the
  passthrough audit finds at least one candidate. An operator variable,
  `gpu_passthrough: auto | enabled | disabled` (default `auto`), forces either way. A
  host that gains GPUs later re-runs preparation, as binding them requires anyway. The
  GPU path is unchanged. Rejected: an explicit variable defaulting to enabled (a
  GPU-less host gets boot changes unless someone remembers); leaving it (boot changes
  on every GPU-less host the market can now sell).
- **9c. Host preparation defaults to the scratch image**, the image market
  fulfillment creates from. The golden image becomes an explicit choice, and the
  documentation that states the default is updated with it.

### D10. The golden image is out of scope

Scratch needs only outbound network access from the host. The golden path needs a
service-account key file activated on the host, an object-storage bucket, Packer on
the host, golden settings in the service, and a way for a market deal to select it,
which has not been confirmed to exist. What the golden image is for — given that
scratch already fetches over the network and golden adds a storage dependency — is
to be re-evaluated by `fix-golden-image-config` before its configuration is fixed.

### D11. Dead material

`e2e-tests/.github/workflows/e2e.yml` is deleted; the README's nonexistent targets
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
  marker registration, and the D11 documentation. Its validation is a run against a
  real host; the evidence recorded here is the scenario's result, the access checks'
  output, and the teardown checks, with no environment identifiers.

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
  when the audit finds a candidate. On a GPU host the audit does, so its live
  verification is unaffected.

## Open Questions

None.
