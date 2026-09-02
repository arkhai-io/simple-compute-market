## Why

The host registry supports two ways of holding a host's SSH credential.
`ssh_key_type="path"` stores a filesystem path and the provisioner reads the key
from disk; `ssh_key_type="embedded"` stores the private key itself, encrypted at
rest with the profile's encryption key, and the provisioner decrypts it per run.

Only the first is in use. Every host is registered against a single keypair
mounted at a fixed path, so one private key reaches every host in an
environment, across all pools. That is acceptable while every host is operated
by the same party. It stops being acceptable at the first independently operated
host, because a key that opens every machine cannot be given to the operator of
one of them.

`embedded` is the mechanism that answers this, and it is nearly ready: the
registry encrypts on write, and the inventory writer decrypts and writes a
per-host key file for Ansible to use. Two defects stand in the way.

1. **Decrypted key files are never deleted.** The inventory writer writes one
   companion key file per embedded host into the process temporary directory at
   mode `0400`, collects their paths, logs how many it wrote, and discards the
   collection — the paths are not returned to the caller. Both callers clean up
   only the artifact they know about: the connectivity check unlinks the
   inventory file, and the job path unlinks the variables file. Neither can
   unlink a companion key file it was never told about.

   The result is that every connectivity check and every job against an embedded
   host leaves a decrypted private key on the container filesystem, accumulating
   one file per host per invocation for the lifetime of the pod. The docstring
   states the files are removed when the caller deletes the inventory file's
   parent directory, which is the shared temporary directory that no caller
   deletes and none should.

   This is latent rather than live: no host is registered as `embedded` today,
   so nothing is currently written. It becomes live with the first such host.

2. **The registry's inventory renderer emits an unresolvable placeholder.** For
   an embedded host it writes a sentinel in place of the key path and documents
   that the inventory writer substitutes it. The inventory writer does no
   substitution — it builds its own inventory text and never sees the sentinel.
   Any inventory produced by the renderer for an embedded host therefore names a
   key file that does not exist, and an Ansible run using it would fail
   authentication against a host that is reachable.

   No production path calls the renderer today, so this is dead code rather than
   a live fault. It is a trap: the two renderers carry comments insisting they
   must not drift, which invites a reader to trust that they have not.

## What Changes

- **Return the companion key paths from the inventory writer** so callers can
  remove them, and remove them on every path that writes an inventory —
  including the paths that fail.
- **Give the temporary key material a single owner.** Write the inventory and
  its companion keys into one per-invocation directory rather than into the
  shared temporary directory, so cleanup is one removal that cannot miss a file
  and cannot collide with a concurrent invocation.
- **Resolve the renderer's sentinel.** Either make the renderer produce an
  inventory that works for embedded hosts, or restrict it to what it can
  correctly express and say so. The sentinel does not survive in either case.
- **Correct the docstrings** that describe cleanup behaviour the code does not
  have.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `physical-provisioning`: the lifetime of decrypted host key material becomes a
  stated property of the execution path rather than an unstated consequence of
  where temporary files happen to be written.

## Non-Goals

- Do not generate per-host keypairs, and do not decide who does. Producing a
  keypair for a host and placing its public half in that host's
  `authorized_keys` is host preparation, outside this repository. This change
  makes the registry's existing per-host mechanism safe to use; it does not
  create a policy for using it.
- Do not remove the shared-key path. A host registered without its own key
  material keeps working unchanged, and that remains the right default for hosts
  the operator prepared.
- Do not change the encryption scheme or the key that protects stored material.

## Compatibility

**Behaviour.** No externally observable change. Hosts registered with a key path
are unaffected, and no host is registered with embedded material today, so there
is no population whose behaviour changes.

**State.** Nothing to migrate. No schema change, and no stored value is
reinterpreted.

**Residue.** A pod that has run against embedded hosts before this change holds
decrypted key files in its temporary directory. There are none today. Were there
any, they would not survive a pod restart, so no cleanup step is owed.

## Dependencies and Related Changes

- `relay-vm-access-without-a-dashboard` records the shared-key finding that
  motivates this change and takes no action on it. The two are independent:
  neither blocks the other, and either order works.
- Registering a host with its own key material is what makes this change
  observable. That registration is an operator action against a running service,
  not a code dependency.

## Impact

- A host operated by a party who should not hold the keys to every other host
  can be registered and driven.
- Decrypted private key material stops outliving the operation that needed it.
- A renderer that produces an inventory nobody can authenticate with stops being
  something a future caller can adopt by accident.

## Permanent documentation impact

- [x] Existing subsystem specification: `openspec/specs/physical-provisioning/spec.md` — host key material lifetime on the execution path
- [ ] `docs/development/ARCHITECTURE.md` — no repository-wide shape change
- [ ] `docs/development/ROADMAP.md` — no goal's current state changes; the shared-key limitation this enables an answer to is not a roadmap goal today

### Knowledge to promote

- Decrypted host key material exists only for the duration of the operation that
  needs it, and every path that writes it removes it, including failing paths →
  `openspec/specs/physical-provisioning/spec.md`
- A host may hold its own encrypted key material, and hosts registered without
  it use the deployment's shared key →
  `openspec/specs/physical-provisioning/spec.md`
