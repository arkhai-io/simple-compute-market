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

## Capacity Preparation Interfaces

The `capacity` namespace prepares and inspects artifacts for the finite VM/G1
capacity contract, whose Q1-Q8 rows assign substantive agent ownership. It has
exactly seven commands—`validate`, `hash`,
`evaluate`, `finding`, `issue-plan`, `cancel`, and `cleanup`—and intentionally
has no `run` or `execute` command.

These commands do not launch Codex agents, perform quickstart actions, issue
market or wallet requests, access a cloud or host, provision a VM, exercise
KVM/Ansible/GPU hardware, cancel or clean live work, query GitHub, or mutate
Git or GitHub. Passing them is harness-contract evidence only. It is not Q0,
Reference B1, or Q1-Q8 execution, real-infrastructure evidence,
system-capacity evidence, or capacity qualification. Scenario declarations for
real KVM/Ansible and one whole GPU describe an external execution contract;
validation does not perform or prove those actions.

| Command | Current behavior | Exit behavior |
|---|---|---|
| `capacity validate SCENARIO` | Validate one finite VM/G1 scenario and emit its ID/hash context. | `0` valid; `2` invalid or unavailable input. |
| `capacity hash SCENARIO` | Validate and emit the canonical SHA-256 scenario identity. | `0` valid; `2` invalid or unavailable input. |
| `capacity evaluate RESULT --scenario SCENARIO CONTEXT` | Validate a supplied sanitized result, bind it to explicit context, and derive classifications and findings. | `0` no findings; `1` findings; `2` invalid input or context. |
| `capacity finding FINDING --scenario SCENARIO CONTEXT` | Validate and render a supplied finding bound to scenario/run context; it does not derive a finding from a result. | `0` valid; `2` invalid input or context. |
| `capacity issue-plan RESULT --scenario SCENARIO CONTEXT` | Re-evaluate the original sanitized result and derive every issue decision; a caller-authored evaluation is not accepted as authority. | `0` valid plan, suppression, or withholding; `2` invalid input or context. |
| `capacity cancel ...` | With global `--dry-run`, emit a deterministic cancellation key/packet; otherwise validate an external context-bound receipt. It never performs cancellation. | `0` plan or positive receipt; `1` negative receipt; `2` invalid input or context. |
| `capacity cleanup ...` | With global `--dry-run`, emit a deterministic cleanup key/packet; otherwise validate an external context-bound receipt. It never performs cleanup. | `0` plan or zero-residue receipt; `1` negative receipt; `2` invalid input or context. |

Adapter-selection errors use exit `3`. Ordinary argument-parser usage errors
use exit `2`; once a capacity handler is dispatched, stdout is one compact,
key-sorted JSON line with this envelope:

```json
{
  "schema_version": 1,
  "command": "capacity.evaluate",
  "status": "ok",
  "context": {},
  "result": {},
  "error": null
}
```

The displayed JSON is expanded for readability. Actual command output is one
line. Status is `ok`, `findings`, `negative-evidence`, or `error`. Error
envelopes do not echo rejected input paths or private values.

### Scenario and result inspection

This Bash example validates, hashes, and evaluates one supplied sanitized
result. `RESULT` is a caller-chosen path; `.scm-local/capacity/` is only an
illustrative location. During preparation, the result must come from a
mock/fake external runner. The public commands neither produce nor persist it.

```bash
SCENARIO=tools/issue-discovery/config/capacity/b2-g1-contention.json
RESULT=.scm-local/capacity/run-001/result.json
PUBLIC_BRANCH="$(git branch --show-current)"
PUBLIC_SHA="$(git rev-parse HEAD)"

CAPACITY_CONTEXT=(
  --repository arkhai-io/simple-compute-market
  --branch "$PUBLIC_BRANCH"
  --sha "$PUBLIC_SHA"
  --run-id run-001
  --timeout-seconds 900
  --adapter market=mock
)

./scripts/issue-discovery capacity validate "$SCENARIO"
./scripts/issue-discovery capacity hash "$SCENARIO"
./scripts/issue-discovery capacity evaluate \
  "$RESULT" \
  --scenario "$SCENARIO" \
  "${CAPACITY_CONTEXT[@]}"
```

Context rules are closed and fail-safe:

- `--repository` is exactly the public SCM repository.
- `--branch` is a canonical, unqualified, non-default public working branch;
  `dev`, `main`, `origin/...`, `refs/...`, pseudo-refs, and malformed Git ref
  shapes are rejected.
- `--sha` is exactly 40 lowercase hexadecimal characters.
- `--run-id` is a sanitized identifier of at most 120 characters, and
  `--timeout-seconds` is from 1 through 86400.
- Result repository, branch, SHA, run ID, timeout, scenario ID, and scenario
  hash must agree with the supplied context.
- At least one `--adapter KIND=MODE` is required for `evaluate`, `finding`,
  `issue-plan`, `cancel`, and `cleanup`.
- Adapter kinds are exactly `market`, `wallet`, `cloud`, `host`,
  `provisioning`, and `github-mutation`; modes are exactly `mock`, `fake`, and
  `dry-run`.
- Duplicate kinds, unknown values, and every `live` mode exit `3` before a
  scenario, result, finding, issue snapshot, proposal, or receipt file is
  read.

The finite scenarios are Q0, controller-driven Reference B1, and Q1-Q8. They
scale substantive buyers before adding distinct sellers, keep every deal a VM,
use one physical whole-GPU fence, prohibit retries, and require zero-residue
cleanup. Q5 represents serialized reuse by one persistent buyer. G2, non-VM,
unknown, and adaptive/unbounded inputs are rejected.

### Mocked GitHub planning

`issue-plan` consumes the original sanitized result and derives its evaluation
and complete finding set. The issue snapshot is caller-supplied JSON; the
command never queries GitHub.

```bash
ISSUES_SNAPSHOT=.scm-local/capacity/run-001/issues.json

./scripts/issue-discovery capacity issue-plan \
  "$RESULT" \
  --scenario "$SCENARIO" \
  --issues-snapshot "$ISSUES_SNAPSHOT" \
  --repository arkhai-io/simple-compute-market \
  --branch "$PUBLIC_BRANCH" \
  --sha "$PUBLIC_SHA" \
  --run-id run-001 \
  --timeout-seconds 900 \
  --adapter github-mutation=dry-run
```

A snapshot is required only when evaluation yields at least one
publication-eligible finding. It is not read for a clean result, expected
scarcity, or findings wholly withheld because cleanup is unproven. The
top-level decision is `no-action` for a successful result with no expected
scarcity. Per-finding plans
deterministically select `create`, `no-op`, `update`, `reopen`, or `withhold`;
exact expected scarcity returns `suppressed`. Every per-finding issue plan has
`dry_run: true`, and all operations are inert data.

The minimum snapshot shape is:

```json
[
  {
    "number": 17,
    "state": "OPEN",
    "body": "Existing issue body",
    "comments": [
      {"body": "Existing comment"}
    ]
  }
]
```

`number`, `state`, and `body` are required; `comments` is optional. Matching
uses machine-readable scope and occurrence markers in issue bodies or comments,
not title text.

Optional fix selection requires both `--fix-proposal` and
`--fix-fingerprint`. A proposal has this exact shape:

```json
{
  "schema_version": 1,
  "ownership": "public-harness",
  "summary": "Correct the bounded capacity result adapter.",
  "paths": [
    "tools/issue-discovery/src/issue_discovery/runner.py"
  ]
}
```

```bash
./scripts/issue-discovery capacity issue-plan \
  "$RESULT" \
  --scenario "$SCENARIO" \
  --issues-snapshot "$ISSUES_SNAPSHOT" \
  --fix-proposal proposal.json \
  --fix-fingerprint "$FINGERPRINT" \
  --repository arkhai-io/simple-compute-market \
  --branch "$PUBLIC_BRANCH" \
  --sha "$PUBLIC_SHA" \
  --run-id run-001 \
  --timeout-seconds 900 \
  --adapter github-mutation=dry-run
```

Only a cleanup-proven `harness-defect` and allowlisted public harness paths
qualify. The candidate uses exact `fix/<fingerprint>` head naming and the
supplied working branch as its base, with `draft: true`, `auto_merge: false`,
and `executed: false`. Any emitted `git` or `gh` argument arrays are candidate
data and are not invoked.

This is distinct from the pre-existing `issue create` command documented
below. That ordinary command can call authenticated `gh issue create` after
operator review. Capacity preparation never calls that path.

### Cancellation and cleanup receipts

The public commands implement a two-phase contract. First, dry-run mode emits
the deterministic idempotency key:

```bash
./scripts/issue-discovery --dry-run capacity cancel \
  --scenario "$SCENARIO" \
  --termination timeout \
  "${CAPACITY_CONTEXT[@]}"

./scripts/issue-discovery --dry-run capacity cleanup \
  --scenario "$SCENARIO" \
  --termination timeout \
  "${CAPACITY_CONTEXT[@]}"
```

Valid terminations are `completed`, `timeout`, `cancelled`, `partial-launch`,
`role-failure`, and `controller-failure`.

A separately authorized external runner may perform the represented operation
and return a sanitized receipt envelope. That envelope is bound to the exact
operation, idempotency key, public repository/branch/SHA, scenario ID/hash,
run ID/timeout, normalized adapters, and termination. Re-running the command
without global `--dry-run` and with `--receipt RECEIPT.json` validates and
renders a bounded summary of the external evidence; it persists nothing, and
the public result still reports `executed: false`.

A successful cancellation receipt envelope has this shape (substitute the
exact values and key emitted by the dry-run command):

```json
{
  "schema_version": 1,
  "operation": "cancel",
  "idempotency_key": "<dry-run-idempotency-key>",
  "public_context": {
    "repository": "arkhai-io/simple-compute-market",
    "branch": "<working-branch>",
    "sha": "<40-character-public-sha>"
  },
  "scenario": {
    "id": "q2-b2-s1-g1",
    "sha256": "<scenario-sha256>"
  },
  "run": {
    "run_id": "run-001",
    "timeout_seconds": 900
  },
  "adapters": {
    "market": "mock"
  },
  "termination": "timeout",
  "receipt": {
    "attempted": true,
    "status": "succeeded",
    "failure": null
  }
}
```

Validate it without performing cancellation:

```bash
./scripts/issue-discovery capacity cancel \
  --scenario "$SCENARIO" \
  --termination timeout \
  --receipt cancel-receipt.json \
  "${CAPACITY_CONTEXT[@]}"
```

A cleanup envelope uses `operation: cleanup`; its inner receipt additionally
contains `zero_residue`. Successful cleanup requires `attempted: true`,
`status: succeeded`, `zero_residue: true`, and `failure: null`.

A receipt is forbidden in dry-run mode and required outside dry-run mode.
Cross-run, cross-adapter, cross-operation, and other context replay is
rejected. A failed or not-attempted cleanup receipt is valid negative evidence:
the cleanup command exits `1` and cannot establish zero residue. When the same
typed state is incorporated into a capacity result, evaluation retains a
cleanup-failure finding rather than hiding it.

### Privacy and validation responsibility

Only bounded public assertions may enter capacity output. A supplied result
may carry opaque reservation and fulfillment values solely so evaluation can
check correlation; evaluation and findings never emit them. Finding and output
validation rejects private refs, filesystem paths, raw executor identities,
accounts, wallets, credentials and tokens, SSH identities, network and host
identities, URLs, and raw-log/control text. Raw evidence remains with the
external runner; public findings retain only correlation states and sanitized
summaries.

The default repository Tests workflow currently excludes
`tools/issue-discovery`. Run its locked suite explicitly when changing this
tool:

```bash
cd tools/issue-discovery
uv --no-config run pytest -q
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

The create command only files candidates marked `ready_to_file` unless `--force` is supplied. Real issue creation checks the body against the configured redaction rules and searches open GitHub issue titles for the candidate fingerprint before calling `gh issue create`. If a duplicate exists, it prints the existing URL and exits without creating a new issue.

The create command uses `gh issue create` from the repository root selected by the wrapper or `--repo-root`, so it requires the GitHub CLI to be installed and authenticated for that repository.

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
