# Design

## Context

The provisioning service holds secret material on its execution path in three
places: a host's embedded private key, protected at rest by the `ssh` codec and
decrypted for one operation; the Ansible variables file, which may carry a relay
admission token or image credentials; and whatever Ansible writes on its own
account. The question this change answers is whether any of it outlives the
operation that needs it, and whether a failure to use it says why.

Most of that already holds. The Ansible distribution's runner
(`provisioning/compute/ansible/src/compute_provisioning_ansible/runner.py`)
writes each decrypted key into a uuid-named file created `O_EXCL` with mode
`0600`, made read-only once written, and returns a `MaterializedInventory` that
owns the inventory and every key file. The job executor removes it, and the
variables file `write_extra_vars` creates owner-only, in a `finally` that covers
success, failure, timeout, and cancellation; the connectivity probe uses it as a
context manager; a write that fails part way removes what it wrote. The
permanent specification already requires this ("Connection secrets stay
protected", and the relay token's "same lifetime and access restrictions"). The
only renderer of an inventory Ansible runs is `AnsibleRunner.write_inventory`.

What does not hold:

- **Ansible's own log.** The service exports `ANSIBLE_CONFIG` pointing at the
  distribution's packaged `ansible.cfg` unless the profile's `ansible_cfg` names
  another, and the packaged file sets `log_path = ./ansible.log`. The service's
  working directory is writable, so every real playbook run and connectivity
  check appends its full, unredacted output — including facts a role prints by
  design — to a file in the provisioning container that lasts as long as the
  container. The file is written on the Ansible controller, the service, never
  on a managed host, so its readers are whoever can read the container's
  filesystem, not buyers. The runner already captures the same output, redacts
  it, and keeps it as the job's logs.
- **A protected key that cannot be decrypted.** A key protected under another
  `ssh_decryption_key` (after a rotation or a restore into another deployment)
  raises `InvalidToken`, whose message is empty; with no key configured, Fernet's
  own key-format error. A job records `Internal error: ` and nothing more; the
  connectivity route answers a server error rather than a result; and readiness
  reports every embedded key as present without trying it, so the `ansible`
  component reads ready while every job against the host fails.

Per-host key material itself works: a host is registered with its own key
through `POST /api/v1/hosts` with `secrets` or the INI import's `embedded` mode,
and under Helm, which mounts one key file, that is the only per-host credential.
An independently operated host never needs the shared key's private half, only
its public half; per-host keys answer a smaller blast radius for one compromised
key, per-host revocation, and a host operator who supplies the keypair.

## Goals / Non-Goals

**Goals:**

- No unredacted copy of Ansible output is kept by default.
- A protected key that cannot be decrypted is named — at dispatch, at the
  connectivity check, and in readiness — with how to recover, and without
  revealing ciphertext or key material.
- The documents that describe per-host keys as missing, and this change as a
  prerequisite of relay verification, describe what is true.

**Non-Goals:**

- Generating per-host keypairs, or deciding who does.
- Removing the shared-key path.
- Changing the encryption scheme or the key that protects stored material.
- Restricting what an operator's own Ansible configuration or playbooks write.
- Changing how the existing transient files are laid out (D3).

## Decisions

### D1 — The change covers the secret-lifetime gaps that remain on the execution path

The defects this change was opened for — decrypted key files never removed, and
a second renderer emitting a key placeholder nothing replaced — were removed
when the execution path moved into the Ansible distribution, and both of its
first requirements are either already permanent or govern code that no longer
exists. The change keeps its purpose and applies it to what remains: the default
Ansible log (D2), and a protected key that cannot be decrypted (D4, D5), with
the documentation that misstates the current system corrected (D6, D7).

Rejected: retiring the change as delivered elsewhere, which would leave a live
leak and an undiagnosable failure, both small and understood and in this
change's area, as unowned gaps; and retiring it while opening a new change for
the log, which pays a second design, review, and closeout for the same package
and requirement. The name stays: renaming would ripple through the index, the
roadmap, and other changes' references for no gain in meaning.

### D2 — The packaged Ansible configuration names no log file

`log_path` is removed from the distribution's packaged `ansible.cfg`, so under
the service's default configuration Ansible writes no log file and a run's
output is kept only as the job's redacted logs. An operator whose profile's
`ansible_cfg` names a configuration of their own gets whatever it states,
including a log file; the service does not override it, and the operator
handbook says how to configure one and that it receives unredacted output.

The service owns its defaults, and its default is what writes the file today.
An operator may supply their own playbooks through a pool's `playbook_path` and
must not be mechanically prevented from logging their runs; `log_path` is a
service-wide configuration setting rather than a pool's, so the operator's own
configuration is where that choice belongs.

Rejected: forcing `ANSIBLE_LOG_PATH=/dev/null` into every Ansible subprocess,
which overrides an operator's deliberate configuration; a per-run log removed
when the run ends, a copy of output the runner already captures that nothing
reads; and keeping the default log with documentation, which keeps an
unredacted copy by default against this change's premise.

### D3 — The existing transient files keep their layout

The inventory, decrypted key files, and variables file stay uuid-named,
owner-only files in the process temporary directory: `MaterializedInventory`
owns the inventory and keys, and the executor owns the variables file. Each is
created `O_EXCL`, so a name collision fails rather than overwrites, and each is
removed on every ending of a run, which tests prove.

Rejected: one owner-only directory per run removed with a single action, which
would satisfy the relay change's wording literally, hide host ids from a listing
by another user in a single-user container, and give the files one owner, but
fixes no failure anyone can name and touches six code sites and four fixtures;
and folding the variables file into the inventory's owner object, a tidy-up that
couples the runner's inventory to the codec's variables. Revisit when a third
secret file per run is added — a per-run `known_hosts`, for instance, if SSH
host-key checking is enabled — or if the provisioning container is ever shared
with another user.

### D4 — A protected key that cannot be decrypted is named at dispatch and at the probe

`SshConnectionCodec.decrypt_private_key` raises a typed error, exported by the
distribution, for both causes — a key protected under another key, and no key
configured. Its message names the host's protected key as unreadable under the
configured `ssh_decryption_key` and how to recover (restore the key it was
protected under, or submit the host's private key again), and carries no
ciphertext or key material.

A job lets it propagate, as relay execution lets `RelayUnusableAtExecutionError`
propagate: the job engine records it with its message and never retries it,
since a retry meets the same configuration. The connectivity probe catches it
and answers `reachable=False` with the message as its detail, keeping the
route's rule that a host's state is a result rather than a refusal.

Rejected: leaving `Internal error: ` as the whole diagnosis; and having the probe
refuse with 422, which would keep configuration faults apart from reachability
but gives a caller polling connectivity an error instead of a result for a host
it can address.

### D5 — Readiness checks that each enabled host's embedded key decrypts

The Ansible readiness component receives the `ssh` codec from composition and
decrypts each enabled host's protected key in memory, never to a file, discarding
the plaintext at once. A key that fails reports `exists: false`, documented for
an embedded key as "decrypts under the configured key", and adds a not-ready
reason naming the host. As with a missing key file, it counts once any Ansible
executor is real, since mocked executors need no keys. The detail keeps its
fields and its schema version 1: only the documented meaning of `exists` for an
embedded key widens, and a reader already handles `false` for a key file.

Readiness exists to say whether a job can run, and it already reads key files
from disk to say so; the plaintext stays within the codec and memory for the
length of one decryption, inside what "Connection secrets stay protected"
permits.

Rejected: leaving embedded keys reported present without trying them, which
misstates the one thing readiness answers for this case; verifying without
decrypting, impossible because Fernet carries no key id and a stored key
fingerprint would be a persistence change; and documenting `exists` as
unverified, honest but still ready while jobs fail.

### D6 — The relay change's task 2A.7 is met by the existing variables-file handling

The relay change hands this change the variables file's lifetime: owner-only,
removed when the operation ends, and in a directory the operation owns. The
first two hold (`write_extra_vars` creates the file `O_EXCL` at `0600`, and the
executor's `finally` removes it, proven by `test_no_file_outlives_its_run`); D3
rejects the third. This change records no dependency. Its closeout corrects the
relay row's Notes to say so, removes the campaign graph edge naming this change
as a prerequisite of that change's live verification, and rewrites the campaign
paragraph that says this change is what allows an independently prepared host
to be registered. The relay change ticks 2A.7 in its own closeout.

Rejected: recording a dependency, which would gate the relay change's closeout
on work this change does not do; and leaving the rows as they are, which keeps
them false.

### D7 — The roadmap's per-host-key gap is removed

Goal 1's gap row saying a host prepared by another party cannot be registered
with its own credential is false: such a host can be, and after D4 and D5 a key
that cannot be used is named. Closeout removes the row and adds to Goal 1's
current state that a host may be registered with its own key material through
the host API, decrypted only for the operation that uses it, and that a key that
cannot be decrypted is named at dispatch, at the connectivity check, and in
readiness.

Rejected: rewriting the row as a narrower gap, since none remains; leaving it.

### D8 — The specification gains two requirements and drops the change's earlier ones

The change's earlier requirements are dropped: decrypted key material's lifetime
is already "Connection secrets stay protected", and the inventory-placeholder
requirement governs a renderer that no longer exists. Two requirements are added
to `physical-provisioning`: Ansible output is kept only redacted unless an
operator configures otherwise (D2), and a protected key that cannot be decrypted
is named rather than hidden (D4, D5). Adding them rather than modifying the
existing requirement keeps the new behaviour under headings of its own without
restating that requirement.

## Implementation cadence

One round, one session, then closeout. The round covers the packaged
configuration's log line and its test; the codec's typed error and its unit
tests for both causes, including that no ciphertext reaches the message; the
probe's handling of it; readiness's decryption check and its wiring at the
composition root; and one integration test through the canonical client in
which a host protected under another key fails its job unretried with the
message, answers its connectivity check unreachable with the reason, and makes
the `ansible` component not ready. The operator handbook, roadmap, and index
edits are closeout's promotion.

## Risks / Trade-offs

- An operator who relied on `/app/ansible.log` without configuring it loses it;
  the job's redacted logs remain, and the handbook says how to configure a log.
- Readiness now decrypts each enabled embedded key on every status read: a
  Fernet decryption per host, with plaintext in memory briefly.
- One host whose key cannot be decrypted makes the `ansible` component not
  ready, as one missing key file already does.

## Open Questions

None.
