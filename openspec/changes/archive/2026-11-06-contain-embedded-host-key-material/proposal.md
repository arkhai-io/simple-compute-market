## Why

Secret material on the provisioning service's execution path should not outlive
the operation that needs it, and when it cannot be used, the failure should say
why.

A host may hold its own SSH key, protected at rest by the `ssh` codec and
decrypted for one operation. That path works: a host is registered with its own
key through `POST /api/v1/hosts` with `secrets` or the INI import's `embedded`
mode, every decrypted key file is created owner-only and removed on every ending
of a run, and so is the Ansible variables file. Under Helm, which mounts a single
key file, it is the only way to give a host a credential of its own. An
independently operated host never needs the shared key's private half; per-host
keys answer a smaller blast radius, per-host revocation, and a host operator who
supplies the keypair.

Two gaps remain.

1. **Ansible keeps an unredacted log by default.** The packaged `ansible.cfg`
   the service runs under sets `log_path = ./ansible.log`, so every real
   playbook run and connectivity check appends its full output — including facts
   a role prints by design — to a file in the provisioning container that lasts
   as long as the container. The runner already captures that output, redacts
   it, and keeps it as the job's logs, so the file adds only an unredacted copy.
   It is written on the service, never on a managed host: its readers are
   whoever can read the container, not buyers.

2. **A protected key that cannot be decrypted fails without a reason.** A key
   protected under another `ssh_decryption_key` — after a rotation, or a restore
   into another deployment — raises an exception with an empty message. A job
   records `Internal error: `, the connectivity check answers a server error
   rather than a result, and readiness reports every embedded key present
   without trying it, so the service reads ready while every job against the
   host fails.

## What Changes

- **The packaged Ansible configuration names no log file.** An operator's own
  `ansible_cfg` may still name one; the service does not override it, and the
  operator handbook says that such a log receives unredacted output.
- **The connectivity check's result is redacted**, as a job's logs already are.
- **A protected key that cannot be decrypted is named.** The `ssh` codec, given
  the host's id, raises a typed error naming the host's key and how to recover,
  carrying no ciphertext. A job fails with that message and is not retried; the
  connectivity check answers the host unreachable with it as the reason.
- **Readiness checks embedded keys.** The host authority gains an internal read
  of the enabled hosts with their protected envelopes, which readiness takes in
  place of the public listing. The Ansible readiness component decrypts each
  enabled host's protected key in memory, and reports a key that fails as not
  ready, naming the host. It reads each `ssh` host as execution does, so a
  host whose stored connection execution refuses, such as one still at `ssh`
  version 1, is reported not ready too. "Connection secrets stay protected" is
  modified to admit this check.
- **The documents describing per-host keys as missing are corrected**: the
  roadmap's gap row, and the relay campaign's prerequisite edge, paragraph, and
  the relay row's note. The relay change's task 2A.7, its design paragraph on
  the variables file, and its handoff note are revised to the requirement the
  existing handling meets.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `physical-provisioning`: Ansible output is kept only redacted unless an
  operator configures otherwise, and a protected key that cannot be decrypted is
  named at dispatch, at the connectivity check, and in readiness. "Connection
  secrets stay protected" admits in-memory decryption for readiness and the host
  authority's internal reads for execution and readiness. "Execution readiness
  is reported in system status" has the Ansible component refuse a stored
  connection exactly as execution refuses it.

## Non-Goals

- Do not generate per-host keypairs, and do not decide who does. Producing a
  keypair for a host and placing its public half in that host's
  `authorized_keys` is host preparation, outside this repository.
- Do not remove the shared-key path. A host registered with a key path keeps
  working unchanged.
- Do not change the encryption scheme or the key that protects stored material.
- Do not restrict what an operator's own Ansible configuration or playbooks
  write, on the service or on a host.
- Do not change the layout of the existing transient files: they are already
  owner-only, uniquely named, and removed on every ending (design D3).

## Compatibility

**Behaviour.** `/app/ansible.log` stops being written under the packaged
configuration; a profile naming its own `ansible_cfg` is unaffected. A job
against a host whose key cannot be decrypted already failed unretried; its error
now names the cause. A connectivity check of such a host answers a result rather
than a server error. The `ansible` status component reports not ready for such a
host where it reported ready, and for an enabled host still stored at an `ssh`
version execution refuses.

**Wire.** The readiness detail keeps its fields and is published as schema
version 2: `exists` for an embedded key says whether it decrypts, and a host
whose stored connection execution refuses has no `ssh_keys` entry. Version 1 is
no longer produced; no production code reads the detail, which status carries
opaquely. No API contract changes.

**State.** Nothing to migrate. No schema change, and no stored value is
reinterpreted.

**Residue.** A container that ran real playbooks before this change holds an
`ansible.log` in its working directory until it restarts; the next pod rollout
removes it.

## Dependencies and Related Changes

- `relay-vm-access-without-a-dashboard` task 2A.7 asked this change for the
  variables file's lifetime, in a directory the operation owns. The permanent
  requirement it serves is met by the existing handling, and the directory is
  rejected (design D3, D6), so neither change depends on the other. This
  change's closeout revises 2A.7 and its design paragraph and handoff note to
  the requirement met, and corrects the relay row and campaign; ticking 2A.7
  stays with the relay change's closeout.
- `bare-metal-mock-provisioned-deal` (archived) moved the execution path into the
  Ansible distribution and gave decrypted key files and the variables file their
  current owner-only, always-removed handling.

## Impact

- Code: the Ansible distribution (`provisioning/compute/ansible`) — its packaged
  `ansible.cfg`, the `ssh` codec, the connectivity probe, and the readiness
  component; the host authority (`provisioning/compute`), which gains an
  internal `execution_hosts` read; and the provisioning service's composition
  root, which hands readiness the codec and that read.
- Tests: unit tests in the distribution and the compute family kit, and an
  integration test in the provisioning service through the canonical client.
- Documentation: `physical-provisioning` specification, operator handbook,
  roadmap, the change index, and the relay change's task 2A.7 and its design.

## Permanent documentation impact

- [x] Existing subsystem specification: `openspec/specs/physical-provisioning/spec.md` — Ansible output kept only redacted by default; a protected key that cannot be decrypted is named
- [x] `docs/operator-handbook.md` — an operator `ansible_cfg` naming a log file receives unredacted output; recovering from a key that cannot be decrypted
- [x] `docs/development/ROADMAP.md` — Goal 1's per-host-key gap row removed and its current state amended
- [x] `openspec/changes/README.md` — the relay campaign's prerequisite edge, paragraph, and the relay row's note on task 2A.7
- [x] `openspec/changes/relay-vm-access-without-a-dashboard/` — task 2A.7, its design paragraph on the variables file, and its handoff note revised to the requirement the existing handling meets
- [ ] `docs/development/ARCHITECTURE.md` — no repository-wide shape change

### Knowledge to promote

- D1: no permanent destination — it sets this change's scope, which the index row and the promoted requirements carry.
- D2: the packaged configuration names no log file, an operator's own configuration is not overridden, and the connectivity check's result is redacted → `openspec/specs/physical-provisioning/spec.md`; configuring a log and what it receives → `docs/operator-handbook.md`
- D3: no permanent destination — it keeps the existing layout, which "Connection secrets stay protected" already governs; its revisit trigger stays in this change's design.
- D4: a protected key that cannot be decrypted is named at dispatch and at the connectivity check, unretried → `openspec/specs/physical-provisioning/spec.md`; recovering from it → `docs/operator-handbook.md`
- D5: readiness checks that each enabled host's embedded key decrypts, through the host authority's internal `execution_hosts` read, and refuses a stored connection exactly as execution does → `openspec/specs/physical-provisioning/spec.md`
- D6: task 2A.7's requirement met by the existing variables-file handling; no prerequisite edge → `openspec/changes/README.md` (the relay row and campaign) and `openspec/changes/relay-vm-access-without-a-dashboard/` (2A.7, its design paragraph, and its handoff note)
- D7: per-host keys are registered through the host API and diagnosed when unusable → `docs/development/ROADMAP.md` (Goal 1)
- D8: the two added requirements and the modified "Connection secrets stay protected" and "Execution readiness is reported in system status" → `openspec/specs/physical-provisioning/spec.md`
