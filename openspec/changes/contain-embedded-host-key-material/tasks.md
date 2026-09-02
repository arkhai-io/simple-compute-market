# Implementation Tasks

Paths are relative to the repository root.

Two packages: the VM provisioning adapter holds both renderers, and the
provisioning service holds the tests that exercise them. Nothing here needs a
live host — the encryption round trip, the file lifetime, and the inventory text
are all observable in process.

Section 1 makes decrypted material owned; section 2 makes the renderers honest.
Either order works, but 1 before 2 means the sentinel is removed from a code
path that already cleans up after itself.

## 1. Own the decrypted key material

- [ ] 1.1 Write the inventory and its companion key files into one directory
      created per invocation, in `write_inventory` in
      `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/ansible_service.py`,
      rather than into the shared temporary directory. Return the directory so
      cleanup is a single removal of something the writer owns outright.
- [ ] 1.1a Return the directory rather than the list of paths. Returning paths
      also works and is a smaller change, but it preserves the property that
      caused the defect: the number of files a caller must remember to remove
      is a function of the hosts passed in. Both current callers would be
      correct on the day of the change; the third is the problem.
- [ ] 1.2 Remove the directory in `check_connectivity` in
      `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/host_operations_service.py`,
      which currently unlinks only the inventory file, and in the job path in
      `ansible_service.py`, which currently unlinks only the vars file.
- [ ] 1.2a Do the removal in a `finally`, not on the success path. A failed
      authentication is the case most likely to leave key material behind and
      the case most likely to be retried, so it is the case that must be
      covered. Both call sites already have a `finally` for their existing
      artifact.
- [ ] 1.3 Keep the per-invocation nonce in the directory name. It is what keeps
      two concurrent operations against one host apart, and moving separation
      from the file name to the directory name does not remove the need for it.
- [ ] 1.4 Keep the `0400` mode on the key file. The containing directory should
      be owner-only as well, so a decrypted key is not readable through a
      directory listing by another process in the container.
- [ ] 1.5 Correct the `write_inventory` docstring. It currently says companion
      files are deleted when the caller removes the inventory file's parent
      directory. That parent is the process-wide temporary directory, so a
      caller following the instruction would delete other tenants' files — the
      instruction is not merely unfollowed, it is unfollowable.
- [ ] 1.6 State the invariant in a comment where the material is written:
      decrypted key material exists only for the operation that needs it, and
      every path that writes it removes it including failing paths. The
      invariant belongs in the comment; the change that introduced it does not.

**Validation:** `make test` in `domains/vms/provisioning` and
`provisioning/compute/service`.

## 2. Make the renderers honest

- [ ] 2.1 Resolve the `__embedded_key_<name>__` sentinel in
      `render_inventory_ini` in
      `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/host_service.py`.
      Its docstring says `write_inventory` substitutes it; `write_inventory`
      builds its own text from the host rows and never sees it, so nothing
      substitutes anything.
- [ ] 2.1a Have the renderer refuse rather than write files. A function
      returning a string cannot make a key exist, and making it write files
      would give decrypted material a second owner — which is exactly what
      section 1 exists to prevent. Refusing, or emitting a value that is
      visibly not a key path and documented as such, keeps one owner.
- [ ] 2.1b Check every caller before changing the signature. Today they are
      tests and a human-readable listing, none of which authenticates; confirm
      that rather than assuming it, because a caller that does authenticate
      changes the answer to 2.1a.
- [ ] 2.2 Correct the two docstrings that describe the substitution, in
      `host_service.py` and `ansible_service.py`.
- [ ] 2.3 Keep the existing must-not-drift comments accurate. They warn that a
      host connecting differently depending on which renderer produced its
      inventory is a defect visible on only one path — which is what happened
      here. The comment should say what each renderer is for, so the next
      reader can tell which one to use.

**Validation:** `make test` in `domains/vms/provisioning` and
`provisioning/compute/service`.

## 3. Tests

- [ ] 3.1 A connectivity check against an embedded host: a readable key file
      exists during the operation, and no decrypted material survives it.
      Assert on the filesystem, not on a mock, since the defect is a file that
      outlives a call.
- [ ] 3.2 The same when the operation raises. This is the test that fails today
      in spirit and the one that must not regress.
- [ ] 3.3 The same for the job path, which cleans up a different artifact and
      would otherwise be assumed to share the connectivity path's behaviour.
- [ ] 3.4 Two overlapping operations against one host neither read nor remove
      each other's material.
- [ ] 3.5 A key-path host writes no key material at all and its inventory names
      the configured path.
- [ ] 3.6 No inventory produced by either renderer contains an unresolvable
      placeholder in the key-file position. Assert against the rendered text
      for both renderers in one test, so the two cannot drift apart again
      without failing.
- [ ] 3.7 A decrypt failure — wrong key, corrupt ciphertext — leaves no
      partially written key file behind.

**Validation:** `make test` in `domains/vms/provisioning` and
`provisioning/compute/service`.

## 4. Closeout

- [ ] 4.1 **Comment hygiene.** `make check-comment-hygiene` from the repository
      root, then read the touched files for what the target cannot catch.
- [ ] 4.2 **Import placement.** `write_inventory` and `get_decrypted_key_value`
      both import `decrypt_key` and `tempfile` inside the function. Check each
      for a real reason to stay local — attempt the move and read the actual
      failure rather than assuming a cycle — and move the ones that have none.
      Verify with `make test`, not a syntax check.
- [ ] 4.3 **Documentation compliance.** Re-read `openspec/README.md`'s
      placement rules and apply them directly.
- [ ] 4.4 **Narrative compression.** Shorten completed-task notes to final
      behaviour, material evidence, and unresolved work.
- [ ] 4.5 **Roadmap currency.** This change has no roadmap impact: no goal's
      current state changes, and the shared-key limitation it makes answerable
      is not a roadmap goal today. Recorded as a disposition rather than
      omitted, so an absent roadmap edit is a decision rather than an open
      question at review.
- [ ] 4.6 **Promotion.**

| Accepted decision | Permanent location |
|---|---|
| Decrypted host key material exists only for the operation that needs it, and every path that writes it removes it including failing paths | `openspec/specs/physical-provisioning/spec.md` |
| A host may hold its own encrypted key material; hosts registered without it use the deployment's shared key | `openspec/specs/physical-provisioning/spec.md` |
| A rendered inventory names a usable key location or states that it cannot represent the host | `openspec/specs/physical-provisioning/spec.md` |
| Decrypted material has one owner, which is why the string-returning renderer refuses rather than writing files | `openspec/specs/physical-provisioning/architecture.md` |

## Sequencing against the sibling changes

Independent of `relay-vm-access-without-a-dashboard`; either may land first.
They touch one file in common, `ansible_service.py`, in different functions.

A practical prerequisite for that change's section 8 whenever the rented host's
operator supplies its own SSH key rather than accepting the deployment's shared
one — which is the ordinary case for hardware this repository does not prepare.

## Implementation progress

Not started. The design is settled; the two defects and their evidence are
recorded in `proposal.md`.

## Validation evidence

| Suite | Baseline |
|---|---|
| `make test` unit, `provisioning/compute/service` | 522 passed |
| `make test` integration | 196 passed |
| `make test`, `domains/vms/provisioning/iac` | 52 passed |

Baselines measured on the delivered tree before any work in this change. No
suite here needs Ansible or a live host.
