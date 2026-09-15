## 0. Branch, authority and baseline

- [x] 0.1 Pin the implementation base, confirm the remote base matches it, and confirm the base's repository instructions, OpenSpec guide and development documents are the governing versions.
- [x] 0.2 Record the accepted design, qualification gates, source disposition, exclusions and ownership in this change.
- [x] 0.3 Build the internal wheels into `.dist` with `make dist-ci`, then run the affected suites with the CI invocation: `kit/site`, `kit/fulfillment`, `kit/capacity-publication`, `provisioning/compute`, `provisioning/compute/service`, `domains/bare_metal`, `domains/bare_metal/provisioning/adapter` and `domains/vms/provisioning/iac`. Record each result, and every unrun suite with its reason, in the baseline ledger below.
  - **Status:** Done. See the baseline ledger. Two pre-existing failures were reproduced and are recorded there, not masked.
- [x] 0.4 Run strict OpenSpec validation for this change, whitespace checks and `make check-comment-hygiene`.
  - **Status:** Done. `openspec validate managed-bare-metal-lifecycle --strict` reports the change valid, `git diff --check` is clean, and `make check-comment-hygiene` finds no references. Every repository path cited by this change resolves on this branch.

## 1. Account, endpoint and trust hardening

- [x] 1.1 Add the bare-metal provisioning adapter test entrypoint (`Makefile` test target against `.dist`) and CI matrix coverage, following existing package conventions. Refresh the package's committed `uv.lock`: it no longer matches its own dependency declarations, so `uv run` re-locks it on every invocation.
  - **Status:** Done. The adapter has a `Makefile` test target, a `domains/Makefile` target and a CI matrix row, and its lock was refreshed. The IaC suite also gained a CI matrix row, with ansible-core pinned as a test-only dependency, so its rendering and reclaim tests run in routine CI.
- [x] 1.2 Port canonical lease-account admission into `domains/bare_metal/src/arkhai_bare_metal/`. Reject arbitrary or colliding account names before privileged execution, and carry the canonical account through storage, inventory and results.
  - **Status:** Done for admission. Grant and reclaim admit only the account derived from the lease's own settlement identity. Reclaim resolves exactly one identity from the request or the site reservation and refuses when there is none or more than one, and the leases API reports a refusal as 422 before any job is queued. **Not established here:** host-side ownership. The current grant task reuses an existing host account at the canonical name. Closing that is an M2 prerequisite: the generated tenant user database and the reserved-UID ownership check (2.1, 2.2) replace host-account creation.
- [x] 1.3 Separate the buyer SSH endpoint from the management endpoint from ingestion through the returned credentials.
  - **Status:** Done. `hosts.public_port` is carried through inventory parsing, seeding, the typed host API (an explicit null clears it and an omitted field leaves it unchanged, in both clients) and both inventory renderings. The access role returns the tenant endpoint, falling back to the management endpoint, as evaluated by Ansible itself.
- [x] 1.4 Port pinned provisioning SSH trust through `helm/charts/provisioning/`. Require strict trust for the managed profile, and test missing and changed host keys without live connections.
  - **Status:** Implemented; pending acceptance. `hostKeyPins` mounts an operator-managed known_hosts Secret read-only and names it to the service. A bare-metal access playbook is spawned with its trust carried as highest-precedence extra-vars, which no inventory variable, inherited environment setting or `ansible.cfg` value can override. They fix the connection plugin to `ansible.builtin.ssh` — pins are OpenSSH options, and paramiko or `local` would run the playbook with the pin ignored — together with both aliases of its host-key-checking option and the ssh/scp/sftp executables, and they carry `ansible_ssh_args` with the strict options first, so those win OpenSSH's first-value race. The strict options make the pinned file the only host-key source (`GlobalKnownHostsFile=/dev/null`, `KnownHostsCommand=/bin/true`, `VerifyHostKeyDNS=no`) and disable connection sharing (`ControlMaster=no`, `ControlPath=none`), so no master socket opened without them — by a VM playbook or at an inventory-named path — can carry a pinned connection. A legitimate ProxyCommand in inventory common args still applies. Because the enforced connection also governs tasks delegated to `localhost`, the role takes its timestamp on the controller without a connection. `provisioning/compute/service/tests/integration/test_bare_metal_connection_enforcement.py` runs the real playbook through the production spawn against a hostile inventory and environment — paramiko and `local` by short and qualified name, plugin-specific checking aliases, substitute executables, pre-set control sockets and added host-key sources — with a recording `ssh` that connects nowhere, and checks every command line the plugin built; a control shows the hostile selection does take effect on an unpinned spawn, and VM spawns keep Ansible's defaults. The spawn is refused when the path is unset, the file is missing or empty, the host has no registered management endpoint, or the file has no pin for that endpoint, and the job fails without contacting the host. The connection is also bound to that selected endpoint: the extra-vars fix `ansible_host`/`ansible_ssh_host` and `ansible_port`/`ansible_ssh_port` to it and the strict args fix `HostName`, so no inventory address or port, and no inherited or inventory `HostName`/`Port`/`HostKeyAlias`, can aim the action at a different host that merely happens to be pinned in the same file; a hostile `HostKeyAlias` for another pinned host fails closed because the connection still reaches the selected host, whose key cannot match another entry. `provisioning/compute/service/tests/integration/test_bare_metal_host_binding.py` pins both the selected endpoint and a decoy and drives the production spawn: the built connection targets the selected endpoint despite every decoy address, port and alias (offline, run by the implementer), and gated connection-level cases reach the selected live endpoint or fail closed while the pinned decoy is never contacted (parent runs those). **Changed-host-key rejection** is exercised end to end by `provisioning/compute/service/tests/integration/test_changed_host_key_rejection.py`: the same production spawn and plugin selection with the real OpenSSH client, against an in-process SSH protocol endpoint whose host key changes under one never-rebound listening socket. The endpoint performs a real key exchange, never authenticates anyone and never opens a session, and touches no account, key or configuration on the machine running it. Acceptance is asserted from both sides (`Permission denied (publickey)` in Ansible's result; key exchange completed and an authentication request seen at the endpoint), and a control without enforcement shows the same hostile known-hosts sources would accept the changed key. It is gated behind `ARKHAI_RUN_SSH_TRUST_HARNESS=1`. A reviewing operator executed both gated harnesses against real loopback SSH and observed 11 passed: the five changed-host-key cases and the six host-binding cases, including the connection-level selected-endpoint and fail-closed cases. That observation qualifies these local tests only. It is not tower qualification, not the M2 account-adoption work, and not physical sanitation or reboot verification, none of which has been performed. The implementer did not run them and claims no independent sign-off; acceptance rests with the bounded review in progress. The two routine checks that resolve options with `ssh -G` (`domains/vms/provisioning/iac/tests/test_ssh_trust_argv_precedence.py` and one case in `provisioning/compute/service/tests/unit/services/test_ansible_host_trust.py`) were not part of that run and remain unexecuted for this revision. The chart render tests are wired into `make -C helm test-chart-contracts`, `make test-deployment-packaging` and the CI deployment-contracts job; the implementer does not run that Helm-executing wiring, and a reviewing operator observed 12 passed through it. The normative rules are recorded in this change's `physical-provisioning` delta as "Managed bare-metal access reaches only the selected pinned endpoint" and "Absent or changed bare-metal host trust refuses before contact". Both harnesses run through one isolated fixture (`provisioning/compute/service/tests/integration/bare_metal_playbook.py` with `ssh_endpoint.py`): the client is handed an explicit fixture-owned `-F` configuration, because OpenSSH resolves `~` from the account database rather than from `HOME`, and that configuration neutralises agent, identity, forwarding, proxy and known-hosts settings the command line does not already fix; every command line is validated against a fixture destination allowlist before a connection starts, so a foreign destination or an identity outside the fixture is refused rather than attempted; the Ansible configuration and the child environment are fixture-owned and allowlisted rather than inherited, with hostile values supplied only as controlled fixture inputs; and each run owns its process group, ended and verified empty on success, timeout and cancellation alike. `provisioning/compute/service/tests/integration/test_bare_metal_playbook_isolation.py` asserts those properties offline, using synthetic sentinels for contamination and stalled and cancelled runs for descendant cleanup, and reads what the spawn left behind before that safety cleanup runs, so a fixture cannot repair a leak into a passing assertion. The run's process group is the receipt taken when its session is created, not a lookup on the leader's process id, which cannot be resolved once the leader has been reaped while its workers and their ssh clients are still running; the group is ended on timeout, on cancellation including during the final awaited log callback, and after successful and failed leader exits alike, and a group this service did not create is never signalled. Those paths are covered by `provisioning/compute/service/tests/unit/services/test_ansible_run_cleanup.py`, which uses disposable local processes and needs no SSH.
- [x] 1.5 Port registry credential validation with sanitized failures and truthful CLI failure reporting.
  - **Status:** Done. The registry client refuses a key it cannot send verbatim as a header, without trimming it and without echoing it. The bare-metal storefront sends an optional Secret-referenced write key, and sends no header when none is configured. Publish and close failures are reported by type and HTTP status only, and `publish` exits nonzero when any candidate failed. Shared consumers of the registry client (core storefront, core buyer) were re-run. The storefront chart's credential-reference render tests share the 1.4 chart wiring, and a reviewing operator observed them passing through it. The normative rule is recorded in this change's `storefront-publication` delta as "Registry write credentials are sanitized and publication failures are truthful".
- [x] 1.6 Replace suppressed account lock and delete failures in the access role with authoritative per-step results. A failed or unverifiable step never reports success.
  - **Status:** Implemented for reclaim; pending acceptance. Lock and delete failures fail the play, and each is followed by a read-back and an assertion. Deletion is verified against `/etc/passwd` itself — the local database the `user` module writes to, read with `slurp` — because a `getent` lookup maps an unavailable NSS backend to the same unsuccessful result as a genuinely absent account. Absence is certified only from a valid, unambiguous current snapshot (`domains/vms/provisioning/iac/ansible/roles/bare-metal-access/filter_plugins/passwd_database.py`): strictly decoded base64 and UTF-8, every record newline-terminated with seven fields, canonical in-range numeric UID and GID, portable non-numeric names with no NSS compatibility entries, no duplicate names, and a root record with UID and GID 0. Anything else — unreadable, empty, malformed, undecodable or ambiguous — fails the task instead of answering. The guarantee is bounded and stated as such: a snapshot truncated exactly after a complete record is indistinguishable from a database that legitimately ends there, so a syntactically valid root-only file is accepted. This establishes that the current authoritative database does not contain the account; it does not establish historical completeness. Preservation of the host's other accounts rests on the role mutating only the named tenant account and on the host preservation gates, which are retained. The normative rule is recorded in this change's `physical-provisioning` delta as "Bare-metal account operations report only verified outcomes". Lock verification keeps its shadow/passwd read-back. The result reports locked or deleted only from the verified read-back, plus a per-step record. The reader is tested directly with the exact bytes a host could return, and the real playbook is exercised under `ansible-playbook` with test-only module stand-ins returning those bytes, covering failed and unverifiable locks, a deleted account, a realistic distribution database, an account still present, an unreadable database, fifteen invalid databases and a failed key revocation. The grant path's existing-account reuse is the M2 prerequisite recorded under 1.2.

## 2. Managed tenant boundary and lease storage

- [x] 2.1 Render the per-lease socket, SSH service template, slice, generated runtime view and lease SSH daemon configuration from the access role. Unit-test the rendered directives and the absence of host-account creation.
  - **Status:** Implemented as rendering and composition only; pending review. The access role renders a lease generation's socket on the buyer port, an accept-per-connection `sshd -i` service instance, a slice holding every tenant process, a generated `/etc` view (passwd, group, shadow, nsswitch) and the lease daemon configuration. The tenant account exists only in that view: the grant path creates, adopts and alters no host account, and an account already present under the lease name refuses the grant before anything is changed, read from the host's own database through the same reader the reclaim path uses. Every access method the daemon serves — interactive shell, remote command and SFTP through `internal-sftp` — is served by that one instance inside that one view, and keys the tenant adds live inside the lease volume. The service instance runs with a read-only root, `/usr` bound read-only, `/usr/local` masked, private devices exposing only the qualified GPU nodes, private IPC, an invisible `/proc`, the lease network namespace, no new privileges, namespace creation and SUID/SGID execution refused, keyring and module/mount/reboot/swap system calls filtered, and swap and core dumps disabled at the slice.
  - **What this does not do.** Grant refuses, unconditionally. Path existence is not preparation: an ordinary or stale directory satisfies an existence check while proving nothing about mount ownership, encryption, lease generation, or namespace and preflight correctness. The role therefore stops before any privileged write whatever those observations return, and the refusal is not overridable by a variable, because a switch there would be an opt-in route back to exposing a tenant on an unverified host. It is removed by implementing the verifiers in 2.2-2.5, not by setting something. No receipt is issued and nothing is written. Rendering stays exercisable through the template tests, which render the artifacts directly with controlled inputs rather than through the production path. This branch is not deployed and nothing that worked is withdrawn: the previous grant path created a host account, which is the behaviour this milestone exists to remove. No usable rental is claimed.
  - **Boundary coherence.** The rendered artifacts are self-consistent rather than merely plausible: the daemon is told to read `/etc/ssh/sshd_config` and its host key at `/etc/ssh/lease_host_key`, which are the paths its own mount view supplies, and the tests resolve those paths through the unit's mounts rather than asserting that a flag appears in the file. Daemon diagnostics reach a provider-only file inside the lease volume because the daemon is given that file explicitly: a daemon told nothing logs through syslog, and the lease namespace carries no `/dev/log`, so a unit-level stderr setting on its own would lose the records rather than redirect them. The unit sets both, and they are not interchangeable — systemd opens the stderr file on the host side before the unit's mounts are applied, so it catches what the daemon writes before its own log file takes effect, such as a fatal configuration error, while the daemon's log file is resolved inside the namespace. The tests assert both routes and check that the daemon's path is reachable and writable through the unit's own mounts. Neither destination is the journal, which would publish one tenant's connection records to the host. Scratch comes from the volume over `/tmp` and `/var/tmp` instead of systemd's private directories, which are host-backed and whose removal on stop is not cryptographic destruction. Qualified GPU nodes are both bound into the private `/dev` and permitted by device policy, since allowing a node that is not present grants nothing. The generated tenant's password field is an invalid hash rather than the locked-account marker: under `UsePAM no` the daemon performs its own account admission, and a reviewing operator compared the two forms against a pinned OpenSSH 8.9, with the same generated key and the same configuration, over standard input with no listening socket and no external network — the locked marker was refused before key authentication, and the invalid hash was accepted. Principals that must never authenticate keep the locked marker.
  - **Evidence and its limits.** Directive support is checked by rendering the units and reading `systemd-analyze verify` output for unknown keys — its exit status is unusable, because systemd ignores an unrecognised directive and still exits zero, so the check reads the output and considers only the lines naming the rendered files. It is gated to a lane that must supply systemd 249: outside the lane it skips with that reason, and inside it a missing tool or a different version fails rather than passing quietly. It has been run on systemd 249 / Ubuntu 22.04, the version the profile targets, which is directive acceptance on a matching version, not evidence of behaviour on the qualification host; the CI job that supplies that version in a container has not yet executed. The lease daemon configuration is asserted structurally; no `sshd` is present where these tests were written, so it is not machine-parsed there. Nothing was activated, no connection was made and no privileged operation ran: the role tests execute the real playbook with recording module stand-ins. A reviewing operator ran the suite and observed 41 passed. The M2 gate — the checked GPU computation over renter SSH and hostile persistence probes on qualified hardware — is not met and is not claimed.
- [ ] 2.2 Implement LUKS2 lease storage with the sealed keyslot secret: counter checks, sealed-object attributes, parent Name verification, prepare journal and exclusive-writer rule, as specified in `design.md` D4.
  - **Implemented seam:** The root-private helper serializes authoritative state under one host/index lock, fences an unreleased generation, journals an attributable full-width counter increment, creates and revalidates a fixed-size single-keyslot LUKS2 file, and seals its 32-byte standard-input-only key through one same-process ESAPI custody lifetime. It verifies the recorded persistent parent Name and the sealed policy and attributes. Durable sealed public/private blobs are recovery material; TPM object and session handles are valid only in the executor lifetime that created them. Pending, live, close-pending and confirmed-closed transitions are fsynced, cleanup is checked and limited to handles returned by that executor, and an incomplete prior lifetime or any other ambiguity is quarantined without a stale flush, counter re-advance or destructive retry.
  - **Evidence:** The deterministic custody set reports `76 passed, 2 skipped`, and final bounded review accepts the simulator custody seam. A reviewing operator's disposable-software-TPM run completed preparation and prepared-state revalidation, preserved foreign transient, session, persistent and NV sentinels, recovered from durable blobs after an emulator restart without another counter advance, and observed revoked blobs refuse recovery. Five abrupt `os._exit(97)` checkpoints restarted with neither stale cleanup nor a repeated counter advance; `after-flush-session` covers the first trial-policy flush, not a separate post-unseal flush.
  - **Limits:** Deterministic fault tests establish the modeled failure propagation, not comprehensive real response-loss or physical-TPM fault injection. The revocation run establishes refusal and owned-resource closure, not an independently read counter value or an assertion of one exact TPM error code. The ordinary helper entrypoint and the `node_prepare_lease_storage` role action refuse before creating state or a secret, and access grant remains unconditionally refused until supervised execution and persistent-path controls are integrated. No mapping, mount, qualified-host device, physical TPM, provider-preservation, reboot, Windows, GPU, egress, complete recovery or release path is established. Tasks 2.3–2.6 and sections 3–6 remain open, so overall 2.2 stays unchecked.
- [ ] 2.3 Implement recovery after restart or reboot under the per-host lock (D5), with the lease window never written.
- [ ] 2.4 Implement persistent-path preflight and controls (D3) as prepare preconditions that fail closed.
- [ ] 2.5 Implement the lease egress namespace and dual-stack firewall table (D8), with prepare refusing on a mismatch.
- [ ] 2.6 Exercise custody, recovery, containment and egress on a designated disposable software TPM and VM:
  - attribute checks;
  - parent reproduction after a TPM restart;
  - an unclean TPM kill;
  - headroom refusal;
  - same-index recreation;
  - fresh-session negative unseal;
  - the pre-satisfied-session regression;
  - interrupted session creation: a helper stopped after creating a session and before recording its handle leaves a retained pending intent that blocks release completion until the qualified TPM restart closes the gap, and reconciliation flushes no TPM handle it cannot attribute to the lease;
  - prepare ambiguity;
  - retry fencing;
  - hostile persistence markers;
  - the dual-stack egress matrix.

## 3. One durable release path and quarantine

- [ ] 3.1 First regressions:
  - a failed reclaim step cannot emit success;
  - tenant-added keys and live sessions survive neither cancellation nor expiry;
  - partial prepare cleanup follows the release owner;
  - a stale result cannot affect a replacement lease;
  - an interrupted recovery helper's pending session intent keeps release incomplete; recorded handles alone never satisfy completion;
  - a missing bare-metal release delegate fails closed.
- [ ] 3.2 Implement the release sequence and completion conditions (D6) with durable, resumable step state and generation fencing.
- [ ] 3.3 Add site-authority quarantine eligibility across every offering-mode alias of the physical host. Force-release and retries must not clear it, and administrator recovery requires fresh verification (D7).

## 4. Lifecycle composition and restart safety

- [ ] 4.1 Trace reservation, commit, scheduling, provisioning, access, cancellation or expiry, teardown and capacity return through the real application, repositories, typed clients and workers, with a controlled executor boundary.
- [ ] 4.2 Persist the lease window and selected host once, and prove that restart at each step neither extends the lease nor selects another host.
- [ ] 4.3 Cover the direct-expiry versus fulfillment divergence, a missing capacity-release notification, and duplicate or delayed results, using the existing pause and advance-cycle controls.
- [ ] 4.4 Composition and migration regressions for accepted constraints, through the existing owners (`kit/site/src/market_site/{db,ledger}.py` for the ledger-owned `claim_attributes`, `kit/fulfillment/src/market_fulfillment/scheduler.py` for scheduling), with no second constraint record:
  - ledger-owned `claim_attributes` survive bare-metal scheduling, restart and recovery unchanged;
  - accepted hardware constraints admit only eligible hosts;
  - contradictory requests are refused before dispatch;
  - legacy `NULL` constraints stay distinct from explicitly empty constraints through migration.

  These support, and do not replace, the exact-host and generation fencing in D5 and D6.

## 5. Availability and confirmed relisting

- [ ] 5.1 First regressions:
  - failed initial full reconciliation;
  - failed ledger-reset reconciliation;
  - close failure while held;
  - a remote write accepted and then timed out;
  - a local-commit failure after remote success;
  - stale readback;
  - a reservation racing a reopen.
- [ ] 5.2 Advance capacity cursors only after acknowledged work succeeds, or persist a pending reconciliation. Confirm relisting through authenticated readback (D11), with VM and API-credit parity tests if a shared contract changes. Add `kit/capacity-publication` to the CI test matrix, which does not currently run it.

## 6. Lifecycle qualification and release preparation

- [ ] 6.1 Composed case: publish, acquire exclusively, grant access, cancel or expire, reclaim, release, confirmed relist, then a second tenant with no predecessor access or data.
- [ ] 6.2 The renter workload proof (D10) through the advertised buyer endpoint, with renter-requested release and deadline expiry tested separately.
- [ ] 6.3 Physical qualification gates 1–6 from `design.md` on a qualified host, each within an authorized operation boundary.
- [ ] 6.4 Rebuild every changed internal package, refresh target-compatible locks, and follow the coordinated migration procedure.

## Baseline ledger

Recorded by task 0.3. Suites run with `ACTIVE_PROFILES=mock COLUMNS=200 uv run --find-links <repo>/.dist --with pytest --with pytest-asyncio pytest -q` from each package directory after `make dist-ci`.

Local environment: uv 0.8.14 (CI pins 0.11.17) and a uv-selected CPython 3.13. `make dist-ci` exited 0.

| Package | Result |
|---|---|
| `kit/site` | 190 passed |
| `kit/fulfillment` | 165 passed |
| `kit/capacity-publication` | 20 passed. Not in the CI matrix; see task 5.2 |
| `provisioning/compute` | 129 passed, 1 failed: `tests/unit/test_contracts.py::test_every_bound_mutation_contract_is_reachable[provisioning_relay_create]` |
| `provisioning/compute/service` | 873 passed, 1 failed: `tests/unit/test_config.py::test_provisioning_bootstrap_dotenv_uses_environment_layer_without_dotenv_local`, also failing when run alone |
| `domains/bare_metal` | 75 passed |
| `domains/bare_metal/provisioning/adapter` | 2 passed. No package test target or CI entry; the run re-locked the package's stale `uv.lock`, which was restored afterwards; see task 1.1 |
| `domains/vms/provisioning/iac` | 65 passed |
| `kit/config` (`tests/unit/test_dynaconf_bootstrap.py`, diagnostic) | 6 passed |

**Failure diagnosis, so far.**

- The relay-create case reproduces deterministically at the exact base, and the source explains it: the test turns each route pattern into a request path by removing `/?`, but the relay collection pattern `/api/v1/relays/?$` also ends in `$`, so the generated path `/api/v1/relays$` matches no contract. The failing test and pattern are in relay administration and on no bare-metal lifecycle path. The failure is retained, not fixed, and reproduced unchanged after section 1's edits.
- The service bootstrap case expects Dynaconf's `.env` discovery to find a `.env` the test writes into its working directory. Dynaconf discovers `.env` through its own vendored dotenv loader, and its search starts at the pytest entrypoint's directory and walks upward before it reaches the working directory. In the environment that ran this baseline, a `.env` in the developer's home directory is therefore selected first, and the test's temporary `.env` is never read; a probe confirmed the selected path without reading the file. `kit/config`'s own bootstrap tests pass. The failure is identical before and after section 1's edits, which do not touch this path. It is environment-dependent, and a run without such a file has not been observed here.
- CI had recorded no run at this exact commit when the baseline was taken. Both classifications above rest on local exact-base reproduction and source analysis, not on a CI observation.

**Not run.**

- `domains/bare_metal/storefront` was not run in this baseline. It pins the hosted settlement client, whose locked distribution resolves from the public package index at the same digest the committed trust configuration signs; running it locally additionally requires building the hosted adapter wheel into `.dist`, as CI does. CI also verifies the signed release before use.
- End-to-end, live-host and payment suites are outside this change's baseline.

## Closeout

Per `openspec/README.md#plan-closeout-requirements`.

Section 1 is accepted and its closeout is recorded below. M2.2 documentation is
prepared for its pending acceptance review; the rest of sections 2–6 remains open.

- [x] **Comment hygiene.** `make check-comment-hygiene` passes, and the comments and docstrings section 1 adds or touches were read directly for provenance narration the target cannot catch.
- [x] **Import placement.** Section 1's imports are at module level. The one deliberate exception is the gated harness's endpoint import, which is local so routine collection never depends on a loopback SSH fixture; the reason is stated where it occurs.
- [x] **Documentation compliance.** Section 1's accepted rules are in the owning `openspec/specs/physical-provisioning/spec.md` and `openspec/specs/storefront-publication/spec.md`, with the rationale that does not fit a normative scenario in `openspec/specs/physical-provisioning/architecture.md`. The implemented M2.2 preparation seam and its current refusal boundary are now promoted to the physical-provisioning spec and architecture; managed activation, recovery, release, quarantine and relisting remain only in this change. `docs/development/ARCHITECTURE.md` is unchanged because no repository-wide flow changed.
- [x] **Narrative compression.** Section 1 notes state final behavior, the validation that backs it, and what remains.
- [x] **Roadmap currency.** No goal or gap row in `docs/development/ROADMAP.md` names this change; nothing is owed and that disposition is recorded here and in the design-promotion record.
- [x] **Campaign index currency.** This change's row in `openspec/changes/README.md` states section 1 accepted with its rules promoted and sections 2-6 not started; its campaign placement is unchanged.
- [x] **Promotion.** The design-promotion record in `design.md` names each promoted rule and its exact permanent location, and no production source references this change directory.

### M2.2 documentation closeout preparation

The task narrative now records only the current same-process custody mechanism,
the accepted simulator-seam evidence, and its limits. The implemented interface
is promoted to the physical-provisioning specification and architecture; no
activation, recovery, release or physical-qualification behavior is promoted.
The roadmap needs no change. The campaign index records section 1 and the 2.1
rendering checkpoint as accepted, the 2.2 simulator seam as verified with
overall integration pending, and every later stage as open. Exact-version
strict validation, citation checks, comment hygiene and whitespace validation
pass for these documentation edits. Overall 2.2 remains unchecked until its
supervision, persistent-path, production activation and recovery integration
gates are completed.

## Section 1 acceptance

Section 1 — account, endpoint and trust hardening — is accepted on the evidence below.
Acceptance is narrow: it covers the implemented admission, endpoint, pinned selected-host
trust, truthful registry and authoritative account-result behavior, exercised locally.

A reviewing operator executed the gated changed-host-key and host-binding harnesses
against real loopback SSH and observed 11 passed, and separately executed the combined
run-cleanup, fixture-isolation and gated harness suites against the corrected source and
observed 26 passed. The chart contract render tests were observed passing through their
Make target. Those are that operator's observations, recorded here as such.

Outstanding, and not covered by this acceptance: physical qualification on a real host;
sanitation, reboot and verification before capacity returns; managed-tenant activation,
lease-storage recovery and revocation integration, egress containment, quarantine and
confirmed relisting of sections 2-6; and the grant path's handling of a pre-existing host
account, recorded under task 1.2.
Two repository baseline failures are unchanged and unrelated to this work: a
`provisioning/compute` relay route-contract case and a `provisioning/compute/service`
dotenv discovery case, both diagnosed in the baseline ledger above.
