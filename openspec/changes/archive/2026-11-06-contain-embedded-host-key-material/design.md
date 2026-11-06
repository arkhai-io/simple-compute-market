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

- No unredacted copy of Ansible output is kept by default, and the connectivity
  check returns its output redacted.
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

The connectivity check's result is the other place Ansible output leaves the
service, and it is redacted too (10 F3). `check_connectivity_with_inventory`
passes the `detail` it returns through `redact_ansible_output`, with the generic
secret fields, since a probe runs no domain's playbook: both the output of
`ansible -m ping` and the text of an exception running it. The redactor replaces
the value of a `password` field, an SSH identity-file argument, and an `sshpass`
password, and nothing else, so SSH's diagnostic text survives. That is the
whole of the promise: a probe's inventory names a key only by the path of a
transient file and carries no domain's variables, so no other secret reaches
its output (35 F1).

Rejected: forcing `ANSIBLE_LOG_PATH=/dev/null` into every Ansible subprocess,
which overrides an operator's deliberate configuration; a per-run log removed
when the run ends, a copy of output the runner already captures that nothing
reads; keeping the default log with documentation, which keeps an
unredacted copy by default against this change's premise; and narrowing the
promise to the log file alone, leaving the connectivity check's result raw,
which keeps one Ansible output surface unredacted for no saving worth having.

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

`SshConnectionCodec.decrypt_private_key(ciphertext, *, host_id)` raises a typed
error, exported by the distribution, for every cause — a key protected under
another key or malformed ciphertext, both of which Fernet reports as
`InvalidToken`, and no key configured, which it reports as a key-format
`ValueError` (10 F2). The codec catches both and raises the typed error, which
carries `host_id` as an attribute. Its message names the host's protected key as
unreadable under the configured `ssh_decryption_key` and how to recover (restore
the key it was protected under, or submit the host's private key again), and
carries no ciphertext or key material. The connection envelope holds no host id,
so the caller passes it; the codec uses it only for the error. Every caller —
the runner's `write_inventory`, which the job path and the probe share, and
readiness (D5) — has the host in hand, so the job, the probe, and readiness
report one text for one failure.

Implementation refined two points. The codec checks for an unconfigured key
itself, before Fernet, so that cause's message says no `ssh_decryption_key` is
configured and names both recoveries that work there: configuring the key the
host's key was protected under, or configuring a key and submitting the host's
private key again. Without some key a private key cannot be submitted, since the
codec's `build` refuses it, but any configured key protects a new submission
(42 F2). And catching `InvalidToken` imports
`cryptography.fernet`, so the distribution declares `cryptography` as a runtime
dependency; it was already in every lock that installs the distribution. The
alternative, `market_config` raising an error of its own, would widen the change
into `kit/config` for no difference a caller sees.

A job lets it propagate, as relay execution lets `RelayUnusableAtExecutionError`
propagate: the job engine records it with its message and never retries it,
since a retry meets the same configuration. The connectivity probe catches it
and answers `reachable=False` with the message as its detail, keeping the
route's rule that a host's state is a result rather than a refusal.

Rejected: leaving `Internal error: ` as the whole diagnosis; having the probe
refuse with 422, which would keep configuration faults apart from reachability
but gives a caller polling connectivity an error instead of a result for a host
it can address; and a host-neutral error each caller wraps with the host id,
which keeps host identity out of the codec but composes one diagnosis in three
places that can drift apart.

### D5 — Readiness checks that each enabled host's embedded key decrypts

The Ansible readiness component receives the `ssh` codec from composition and
decrypts each enabled host's protected key in memory, never to a file, discarding
the plaintext at once. A key that fails reports `exists: false`, documented for
an embedded key as "decrypts under the configured key", and adds a not-ready
reason naming the host. As with a missing key file, it counts once any Ansible
executor is real, since mocked executors need no keys. The detail keeps its
fields and is published as schema version 2 (27 F1): `exists` for an embedded
key no longer means present, and a host whose connection execution refuses has
no entry, so a version-1 reader's meaning no longer holds, and
`docs/development/RELEASING.md`, "Versioning policy", forbids changing a
versioned contract in place. No production code reads the detail (status
carries it opaquely, and tests outside the distribution read only its model or
its Ansible version), and before 1.0 the release introducing version 2 stops
producing version 1. Rejected: keeping version 1 because only a value range widens,
which the release rule does not allow and which ignores the dropped entries;
and keeping `exists` meaning present with decryption reported only in the
reasons, which keeps the misstatement this decision removes.

The public host listing carries protected values by scheme only, so it gives
readiness nothing to decrypt (10 F1). The host authority gains an internal read,
`execution_hosts(enabled_only=True) -> list[ExecutionHost]`, beside `lookup`:
the enabled hosts in one query, ordered by `host_id`, each with its full
connection envelope. No route exposes it, and every ordinary read stays
redacted. The composition root passes it to readiness in place of the public
listing, so readiness reads one consistent snapshot through one input: key paths
from each envelope's public fields, and embedded keys from its protected values.

- If the read raises, the component reports the registry unreadable, as today.
- A key that does not decrypt, whatever the cause (D4's typed error), marks only
  that host's entry `exists: false` with a reason naming the host; every other
  host is reported as it would be without it.
- An enabled-host list that is empty is ready when the other checks pass.
- A host of a connection kind other than `ssh` is skipped: no Ansible executor
  reaches it.
- Each `ssh` host is read through the runner's `inventory_target`, the function
  execution renders a host from, so readiness refuses exactly the connections
  execution refuses (19 F1). The specification keeps a host stored at a version
  the codec no longer serves, such as `ssh` version 1, until it is submitted
  again, and execution refuses it before any inventory is written; validation at
  submission does not reach it. A host `inventory_target` refuses adds a
  not-ready reason naming the host and carrying the refusal, and is left out of
  `ssh_keys`, since its key reference was never read at a served version. This
  holds for a key file as for an embedded key: a version-1 host whose key file
  exists reads ready today while every job against it is refused.
- A served `ssh` connection names a key file or holds a `private_key` protected
  value, since `inventory_target` refuses one naming neither.

Readiness exists to say whether a job can run, and it already reads key files
from disk to say so; the plaintext stays within the codec and memory for the
length of one decryption. "Connection secrets stay protected" permits
decryption only for execution and keeps protected values out of every host read
today, so the change modifies it to admit this check and the authority's
internal reads (D8).

Rejected: composing `lookup` with the public listing at the composition root,
which leaves the authority's interface unchanged but reads each embedded host
twice and must define a host that disappears between the reads; checking only
that keys decrypt and recording that a stored connection at an unserved version
can leave the component ready, narrower but ready while jobs against that host
are refused; checking the version in readiness with a rule of its own, which
can drift from the one execution applies; leaving
embedded keys reported present without trying them, which
misstates the one thing readiness answers for this case; verifying without
decrypting, impossible because Fernet carries no key id and a stored key
fingerprint would be a persistence change; and documenting `exists` as
unverified, honest but still ready while jobs fail.

### D6 — The relay change's task 2A.7 is revised to the requirement the existing handling meets

The relay change hands this change the variables file's lifetime: owner-only,
removed when the operation ends, and in a directory the operation owns. The
first two hold (`write_extra_vars` creates the file `O_EXCL` at `0600`, and the
executor's `finally` removes it, proven by `test_no_file_outlives_its_run`), and
they are what the permanent requirement asks: the variables file has "the same
lifetime and access restrictions as other decrypted secret material on the
execution path". D3 rejects the third. This change records no dependency.

Task 2A.7's own words demand the directory, so ticking it as written would
record unbuilt work as done (10 F5). This change's closeout revises the relay
change's commitment openly instead: it rewrites 2A.7 to state what it requires
and what holds — the variables file created owner-only and `O_EXCL`, and removed
on every ending of the run, meeting `physical-provisioning`'s requirement — with
a note that a per-operation directory was weighed and rejected in this change's
D3, and D3's revisit trigger. It rewrites to match the relay design's paragraph
on the resolved variables file and its handoff note naming this change as owner
of 2A.7, and applies the same correction to the two other places the relay
change states this change's earlier role: its design-promotion row saying the
per-host-key fix is owned here, and its sequencing paragraph calling this change
a practical prerequisite of its section 8. It also corrects the relay row's Notes, removes the campaign graph edge
naming this change as a prerequisite of that change's live verification, and
rewrites the campaign paragraph that says this change is what allows an
independently prepared host to be registered. Ticking 2A.7 stays with the relay
change's own closeout, since it is one of that change's decision gates.

Rejected: building the per-operation directory, which reopens D3 for no failure
anyone can name; ticking 2A.7 as written, which records a directory nobody
built; recording a dependency, which would gate the relay change's closeout on
work this change does not do; and leaving the rows as they are, which keeps them
false.

### D7 — The roadmap's per-host-key gap is removed

Goal 1's gap row saying a host prepared by another party cannot be registered
with its own credential is false: such a host can be, and after D4 and D5 a key
that cannot be used is named. Closeout removes the row and adds to Goal 1's
current state that a host may be registered with its own key material through
the host API, decrypted only for the operation that uses it, and that a key that
cannot be decrypted is named at dispatch, at the connectivity check, and in
readiness.

Rejected: rewriting the row as a narrower gap, since none remains; leaving it.

### D8 — The specification gains two requirements, modifies two, and drops the change's earlier ones

The change's earlier requirements are dropped: decrypted key material's lifetime
is already "Connection secrets stay protected", and the inventory-placeholder
requirement governs a renderer that no longer exists. Two requirements are added
to `physical-provisioning`: Ansible output is kept only redacted unless an
operator configures otherwise (D2), and a protected key that cannot be decrypted
is named rather than hidden (D4, D5).

"Connection secrets stay protected" is modified (10 F4). As it stands it lets a
codec decrypt only "just in time for execution" and keeps a protected value out
of every host-authority read, so readiness decrypting on a status read and
`execution_hosts` returning envelopes would contradict it once the delta is
archived. The modification widens exactly two clauses: a codec may also decrypt
in memory to check that a protected value decrypts when the executor's readiness
is reported, the plaintext discarded at once and never written to storage; and
the host authority returns a protected envelope only through its internal reads
for execution and readiness, never on an API read, log, or error surface. Every
other guarantee and both existing scenarios stand, and a scenario is added for
the readiness check.

"Execution readiness is reported in system status" is modified too (19 F1): the
Ansible component refuses an enabled `ssh` host's stored connection exactly as
execution refuses it, reporting itself not ready naming the host once any
Ansible executor is real, and skips a host of another connection kind. Its text
otherwise stands, both existing scenarios with it, and a scenario is added for a
host stored at an unserved version.

Rejected: adding the new requirements beside the old one unmodified, which
leaves two normative rules that disagree on when a key may be decrypted.

## Implementation cadence

One round, one session, then closeout. The round covers the packaged
configuration's log line and its test; the codec's `host_id` keyword, its
typed error, and its unit tests for every cause, including that no ciphertext
reaches the message; the probe's handling of it, and the redaction of its result
with a unit test planting a secret in Ansible's output; the host authority's
`execution_hosts` read and its test; readiness's switch to that read, its
reading of each `ssh` host through `inventory_target` with a unit test for a
host stored at version 1, its decryption check, its per-host failure
reporting, and its wiring at the
composition root; and one integration test through the canonical client in
which a host protected under another key fails its job unretried with the
message, answers its connectivity check unreachable with the reason, and makes
the `ansible` component not ready. The operator handbook, roadmap, and index
edits, and the revision of the relay change's 2A.7 (D6), are closeout's
promotion.

Two tests start a stand-in `ansible` `/bin/sh` script first on `PATH`: the
distribution's connectivity-redaction unit test, and the service's application
integration test of the connectivity route's redaction. `TESTING.md` would place
a real subprocess at integration and mock the runner in application integration;
both were kept as planned, beside the distribution's existing real-subprocess
streaming test, since the distribution has no integration suite, and the
implementation review raised no finding on them.

The change bumps `arkhai-compute-provisioning` to 0.26.0 (the new
`execution_hosts` read), `arkhai-compute-provisioning-ansible` to 0.8.0 (the
incompatible `decrypt_private_key` and `ansible_readiness_component`
signatures), and `arkhai-compute-provisioning-service` to 0.24.0 (its readiness
reports differently), under `docs/development/RELEASING.md`'s versioning policy.

## Risks / Trade-offs

- An operator who relied on `/app/ansible.log` without configuring it loses it;
  the job's redacted logs remain, and the handbook says how to configure a log.
- Readiness now decrypts each enabled embedded key on every status read: a
  Fernet decryption per host, with plaintext in memory briefly.
- One host whose key cannot be decrypted makes the `ansible` component not
  ready, as one missing key file already does.
- An enabled host still stored at `ssh` version 1 makes the `ansible`
  component not ready where it read ready; jobs against it were already
  refused, and the reason says to submit it again at version 2.

## Open Questions

None.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 — the change covers the secret-lifetime gaps that remain | no permanent destination; the index row and the promoted requirements carry its scope |
| D2 — the packaged configuration names no log file, an operator's own is not overridden, and the connectivity result is redacted with the generic fields | `openspec/specs/physical-provisioning/spec.md#requirement-ansible-output-is-kept-only-redacted-unless-an-operator-configures-otherwise`, by the archive; `docs/operator-handbook.md#ansible-configuration` |
| D3 — the existing transient files keep their layout | no permanent destination; `openspec/specs/physical-provisioning/spec.md#requirement-connection-secrets-stay-protected` governs the layout, and the revisit trigger stays in this design and in the relay change's revised 2A.7 |
| D4 — a protected key that cannot be decrypted is named at dispatch and at the probe | `openspec/specs/physical-provisioning/spec.md#requirement-a-protected-key-that-cannot-be-decrypted-is-named-not-hidden`, by the archive; `docs/operator-handbook.md#a-hosts-protected-key-no-longer-decrypts` |
| D5 — readiness reads hosts through `execution_hosts`, decrypts embedded keys in memory, and refuses a stored connection as execution does; detail schema version 2 | `openspec/specs/physical-provisioning/spec.md#requirement-execution-readiness-is-reported-in-system-status` and `#requirement-connection-secrets-stay-protected`, by the archive, the former also stating the detail's kind and schema version 2 and their meanings (42 F1); `docs/operator-handbook.md#a-hosts-protected-key-no-longer-decrypts` and `#host-definitions` (the version-2 rule) |
| D6 — relay task 2A.7's requirement is met by the existing variables-file handling; no prerequisite edge | `openspec/changes/README.md` (the relay row's Notes, the campaign graph, its introduction and its paragraph on this change); `openspec/changes/relay-vm-access-without-a-dashboard/tasks.md` (2A.7, the implementation-progress handoff, the promotion row, the sequencing paragraph, and a correction note on 11.5) and `design.md` (the resolved variables file paragraph) |
| D7 — per-host keys are registered through the host API and diagnosed when unusable | `docs/development/ROADMAP.md#goal-1--consolidate-physical-resource-authority-in-the-provisioning-service` (gap row removed, current state amended) |
| D8 — two added and two modified requirements | `openspec/specs/physical-provisioning/spec.md`, by the archive |

No `architecture.md`, `docs/development/ARCHITECTURE.md` or
`openspec/specs/README.md` change is owed: the change adds no repository-wide
shape, authority boundary or capability, and `physical-provisioning` has no
`index.md`.
