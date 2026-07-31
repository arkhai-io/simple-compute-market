# Issue Discovery

The issue-discovery harness is for finding local and clean-machine failures, not hiding them. The strict workflow runs the repo as-is, records evidence, and produces issue candidates from any failures it observes.

## Commands

Run the strict local workflow from the repo root:

```bash
./scripts/issue-discovery strict
```

Preview the selected phases without executing them:

```bash
./scripts/issue-discovery --dry-run strict
```

Continue with explicit workarounds after strict mode finds a blocker:

```bash
./scripts/issue-discovery continue --with redis_no_host_port
./scripts/issue-discovery continue --with storefront_volume_chown
./scripts/issue-discovery continue --with cleanup_fixed_docker_names
./scripts/issue-discovery continue --with skip_known_stale_seller_layer
./scripts/issue-discovery continue --with redis_no_host_port --with storefront_volume_chown
```

Run a narrower diagnostic profile:

```bash
./scripts/issue-discovery profile fresh-volumes
./scripts/issue-discovery profile host-redis-conflict
```

Inspect the clean-room discovery ladder without starting a VM:

```bash
./scripts/issue-discovery clean-room plan local-vm
./scripts/issue-discovery clean-room script local-vm
```

## Strict Versus Continue

Strict mode does not apply hidden fixes. It verifies prerequisites, builds the repo, runs code-level tests, starts the compose stack in mock provisioning mode, checks readiness, registers the mock `kvm1` host, runs marker suites, runs the full integration sweep, and tears down compose.

Continuation mode records that one or more workarounds were used before continuing. Later evidence in that run depends on those workarounds and should be interpreted that way. Use continuation runs to discover the next failure after a known blocker, not to redefine strict success.

Some workarounds define a `start_phase`, so continuations can resume at the affected build or runtime phase instead of rerunning unrelated earlier phases. When a resumed phase depends on an earlier phase that was not rerun, the runner records that dependency as `assumed_passed` in `phases.jsonl` and in the manifest's `assumed_passed_phases`.

## Loop Until Done

The intended workflow is a failure-harvest loop:

1. Run strict mode first and capture the first blocker without applying hidden fixes.
2. Review the issue candidates and file actionable issues for real failures.
3. Continue with the smallest explicit workaround needed to move past that blocker.
4. Repeat the process until the configured sequence stops revealing new actionable failures.
5. After issues are fixed, return to strict mode on a clean state and verify the workarounds are no longer needed.

Clean-room sequences encode this loop in YAML. The current `local-vm` sequence runs strict mode first, then stacked continuations for the known local build, Redis port, and storefront volume-ownership blockers. Each step records its own run artifacts, and the clean-room status file records which steps failed or passed.

## Artifacts

Runs write to:

```text
.scm-local/issue-discovery/runs/<run-id>/
```

Important files:

- `manifest.json`: run identity, selected phases, phase scope, status, workaround context.
- `phases.jsonl`: ordered phase outcomes, failed commands, log paths, and classifier hints.
- `commands/<phase>/<command>.*`: stdout, stderr, and command metadata.
- `collectors.jsonl`: collector outcomes and evidence paths.
- `context/git-status.txt`: source tree state for the run.
- `context/tool-versions.txt`: host tool versions.
- `docker/`, `health/`: compose and service diagnostics when collected.
- `issue-candidates/candidates.jsonl`: generated issue metadata.
- `issue-candidates/*.md`: Markdown bodies suitable for GitHub issues.

Classifier hints are only used when the collected evidence matches the known fingerprint. If no known fingerprint matches, the harness generates a generic phase/command issue candidate instead of guessing a root cause.

Generated run outputs are intentionally under `.scm-local/` and are not committed.

## Issue Filing

List issue candidates for a run:

```bash
./scripts/issue-discovery issue list .scm-local/issue-discovery/runs/<run-id>
```

Show a candidate body:

```bash
./scripts/issue-discovery issue show .scm-local/issue-discovery/runs/<run-id> <fingerprint>
```

Preview GitHub issue creation:

```bash
./scripts/issue-discovery issue create .scm-local/issue-discovery/runs/<run-id> <fingerprint> --dry-run
```

Create the issue after reviewing the body:

```bash
./scripts/issue-discovery issue create .scm-local/issue-discovery/runs/<run-id> <fingerprint>
```

The create command only files candidates marked `ready_to_file` unless `--force` is supplied. Real issue creation checks the body against the configured redaction rules and explicitly searches open GitHub issue titles for the candidate fingerprint before calling `gh issue create`. If a duplicate exists, it prints the existing URL and exits without creating a new issue; a previously closed issue does not suppress a newly reproduced failure.

The create command uses `gh issue create` from the repository root selected by the wrapper or `--repo-root`, so it requires the GitHub CLI to be installed and authenticated for that repository.

These commands retain the legacy phase/command candidate workflow. A
schema-v2 capacity finding has a separate immutable ingest and replay path and
is deliberately rejected by `issue create`, `issue transition`, and
`issue propose-fix`; see [Capacity Finding Handoff](#capacity-finding-handoff).

## Marker Suites And Full Sweep

Marker suites are useful because they isolate roles and scenarios quickly. Marker deselection is expected in those runs because each marker intentionally selects only part of the integration suite.

The full unfiltered integration sweep still matters because it catches tests that are not covered by a marker command and exposes order or shared-state problems across the complete suite.

## Clean Ubuntu Bootstrap

On a fresh Ubuntu host, run:

```bash
sudo ./scripts/bootstrap-clean-host-ubuntu.sh run
```

The bootstrap installs host prerequisites, including Docker, Compose plugin, `make`, `git`, `curl`, `jq`, `python3`, `uv`, and ZeroTier. It then runs `./scripts/issue-discovery strict` from the checkout by default.

Set `SCM_CLEAN_ROOM_SEQUENCE` when the bootstrap should run a YAML-backed clean-room sequence instead of a single validation command. The bootstrap asks the issue-discovery CLI to render the sequence script, writes it under `.scm-local/clean-room/`, and runs it. The default clean-room status file is `.scm-local/clean-room/step-status.tsv`.

Useful modes:

```bash
./scripts/bootstrap-clean-host-ubuntu.sh check
SCM_BOOTSTRAP_SKIP_ZEROTIER=1 ./scripts/bootstrap-clean-host-ubuntu.sh check
sudo SCM_RUN_VALIDATION=0 ./scripts/bootstrap-clean-host-ubuntu.sh run
sudo SCM_CLEAN_ROOM_SEQUENCE=local-vm ./scripts/bootstrap-clean-host-ubuntu.sh run
sudo SCM_VALIDATION_COMMAND='./scripts/issue-discovery profile fresh-volumes' ./scripts/bootstrap-clean-host-ubuntu.sh run
```

## Multipass Clean Room

For a local disposable Ubuntu VM:

```bash
./scripts/clean-room/multipass-run.sh --dry-run
./scripts/clean-room/multipass-run.sh
```

The wrapper creates a Multipass VM, transfers the current branch as a git bundle, runs the clean Ubuntu bootstrap inside the VM with `SCM_CLEAN_ROOM_SEQUENCE=local-vm` by default, fetches `.scm-local/` artifacts back under `.scm-local/clean-room-runs/<vm-name>/`, and deletes the VM unless `KEEP_VM=1` is set.

The git bundle is staged under `scm-clean-room-transfer/` by default. This directory is intentionally not dot-prefixed because snap-confined Multipass can fail to read bundles from `/tmp` or hidden home paths.

Common overrides:

```bash
SCM_MULTIPASS_IMAGE=24.04 \
SCM_MULTIPASS_CPUS=6 \
SCM_MULTIPASS_MEMORY=12G \
SCM_CLEAN_ROOM_SEQUENCE=local-vm \
SCM_MULTIPASS_TRANSFER_DIR=scm-clean-room-transfer \
./scripts/clean-room/multipass-run.sh
```

Use `./scripts/clean-room/multipass-run.sh --dry-run` before launching the VM. It prints the VM settings and the exact clean-room sequence that will run, without requiring Multipass to be installed.

## Public VM Capacity Authority

The public capacity contract is under
`tools/issue-discovery/config/capacity/`:

- `scenarios/` contains mode-neutral schema-v2 VM shapes;
- `profiles/g1-v2.json` freezes qualification and measured progression;
- `profile-stages/b1-s1-g1-mock.json` is a standalone preparatory mock stage;
- `findings/example.json` is sanitized illustrative finding-v2 data.

Current scenarios are VM-only, use real KVM and Ansible, require whole-device
GPU passthrough, and give every request a retry budget of zero. The current
profile admits exactly one independently assignable GPU. Offered listings are
market choices, not additional physical GPUs. G2 is not current authority.

The seven pre-Q0 profile stages are, in order:

1. `observer-probe`;
2. `b1-s1-g1-reference`;
3. `b1-s1-g1-qualification`;
4. `b2-s1-g1-qualification`;
5. `serialized-reuse-a-qualification`;
6. `serialized-reuse-b-qualification`;
7. `b2-s2-g1-qualification`.

The probe is `readiness`/`none`; the deterministic reference is
`real-reference`/`controller-driven`; the five qualification rows are
`real-qualification`/`agent-triggered`. The separate standalone mock is
`mock`/`agent-triggered` and cannot claim real provisioning or capacity.

Resolve authority from an exact 40-character SCM commit and a known
repository-relative path. Hash operations discover the validated authority;
validation operations require the caller to repeat the expected values:

```bash
SCM_REF="$(git rev-parse HEAD)"
SCENARIO=tools/issue-discovery/config/capacity/scenarios/b2-s1-g1.json
PROFILE=tools/issue-discovery/config/capacity/profiles/g1-v2.json

./scripts/issue-discovery capacity scenario-sha256 \
  "$SCENARIO" --scm-ref "$SCM_REF"
./scripts/issue-discovery capacity scenario-validate \
  "$SCENARIO" --scm-ref "$SCM_REF" --expected-sha256 <scenario-sha256>

./scripts/issue-discovery capacity profile-sha256 \
  "$PROFILE" --scm-ref "$SCM_REF"
./scripts/issue-discovery capacity profile-validate \
  "$PROFILE" --scm-ref "$SCM_REF" \
  --expected-sha256 <profile-canonical-sha256> \
  --expected-raw-sha256 <profile-raw-sha256>

./scripts/issue-discovery capacity profile-stage-sha256 \
  b2-s1-g1-qualification --scm-ref "$SCM_REF"
./scripts/issue-discovery capacity profile-stage-validate \
  b2-s1-g1-qualification --scm-ref "$SCM_REF" \
  --expected-sha256 <profile-stage-sha256> \
  --expected-registry-sha256 <profile-canonical-sha256> \
  --expected-registry-raw-sha256 <profile-raw-sha256>
```

Scenario hash output is the canonical digest. Profile and stage operations
return deterministic one-line JSON containing their complete validated public
semantics, pinned path/ref, and applicable canonical/raw digests. A stage
response also contains the resolved scenario or explicit null. Private
orchestration consumes these outputs; it does not import the public Python
package or copy the public validation policy.

Canonical SHA-256 uses UTF-8 JSON with recursively sorted keys, compact
separators, non-finite values rejected, and exactly one trailing newline.
Pinned resolution also rejects traversal, symlinks, non-regular or untracked
paths, wrong Git object modes, and worktree bytes that differ from the selected
commit.

## Portable Role, Action, and Outcome Evidence

The remaining `capacity` subcommands validate and canonical-hash the portable
evaluation policy, reference policy, role plans and receipts, concurrency
policy, oracle authority, frozen actions, action results, actor set, mock
capture, independently observed capacity results, serialized reuse, and buyer
frontier. Run:

```bash
./scripts/issue-discovery capacity --help
./scripts/issue-discovery capacity <subcommand> --help
```

for each exact path-only dependency list.

A buyer, seller, host operator, or independent observer counts only from a
substantive receipt bound to its pinned instructions, prepared authority, and
action/result evidence. The deterministic controller is not a counted
observer. `action-capture` is a preparation-only, one-shot mock adapter; real
actions are authenticated and invoked by private infrastructure. Offered buyer
count is reported separately from request-processing, simultaneous
fulfillment, provisioning queue/service, correctness, and load-generator
frontiers.

## Capacity Finding Handoff

Private orchestration exports one sanitized finding-v2 occurrence only after it
can reconstruct the exact validated capacity result, verify terminal
correlations, complete teardown, prove zero active residue, and restore the
baseline. The producer supplies a unique `finding_id`; SCM derives the stable
`capacity-<sha256>` defect fingerprint from closed public defect semantics.
Result, occurrence, ref, evidence, prose, cleanup, and readiness values do not
alter that stable identity.

The only classification/destination mappings are:

| Classification | Destination | Working branch | Upstream |
| --- | --- | --- | --- |
| `public-product` | `simple-compute-market` | `feat/issue-discovery-harness` | `dev` |
| `public-harness` | `simple-compute-market` | `feat/issue-discovery-harness` | `dev` |
| `private-orchestration` | `compute-market-internal-infra` | `tools/agent-orchestration-scratch` | `main` |
| `environment-provider` | `compute-market-internal-infra` | `tools/agent-orchestration-scratch` | `main` |

Evidence paths are UTF-8 regular files strictly below one explicit immutable
`evidence/` root. Each file is at most 1 MiB and the occurrence total is at
most 4 MiB. Public validation rejects credential signatures, prohibited
private field names and portable patterns, project/wallet/host/GPU identity
patterns, traversal or symlinks, byte drift, JSON/YAML/CommonMark encoding
evasions, unsafe Unicode, and evidence that names harness-managed outputs.
Private infrastructure must additionally reject its runtime exact private
values before export; public SCM does not claim that environment-specific
denylist.

Validate or ingest using the exact context required to rebuild the result:

```bash
./scripts/issue-discovery capacity finding-validate \
  <finding.json> <result-context.json> \
  --evaluation-policy <evaluation-policy.json> \
  --expected-scm-ref <40-character-scm-ref> \
  --destination-repo-root <exact-destination-worktree> \
  --evidence-root <immutable-evidence-root>

./scripts/issue-discovery capacity finding-ingest \
  <run-dir> <finding.json> <result-context.json> \
  --evaluation-policy <evaluation-policy.json> \
  --expected-scm-ref <40-character-scm-ref> \
  --destination-repo-root <exact-destination-worktree>
```

Reuse and seller findings also pass the applicable predecessor, reuse-baseline,
buyer-frontier, ordered buyer-result, and ordered prior-seller contexts shown
by `finding-ingest --help`.

Ingest is local and preparation-only. It uses the run directory as both the
explicit evidence root and immutable occurrence store, with current-user-owned
0700 directories, 0600 files, descriptor-rooted reads/writes, two
compliant-writer locks, append-only source/index/lifecycle ledgers,
authenticated crash recovery, and one final replay snapshot. Identical reingest
is a no-op; changed bytes or authority under the same ID fail.

`issue list` and `issue show` may inspect the generated capacity-v2 candidate.
The legacy `issue create`, `issue transition`, and `issue propose-fix` commands
reject capacity v2 before any write, subprocess, or GitHub access. Credentialed
issue/update/reopen and fix-PR mutation belongs to the separate guarded
publication capability; local readiness or a marker-free payload does not
grant it.

Historical finding/scenario schema v1 remains interpretable only at the exact
Git commit that defined it. Current validators never reinterpret v1 as v2.
