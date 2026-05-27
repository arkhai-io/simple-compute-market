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

- `manifest.json`: run identity, selected phases, status, workaround context.
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

Common overrides:

```bash
SCM_MULTIPASS_IMAGE=24.04 \
SCM_MULTIPASS_CPUS=6 \
SCM_MULTIPASS_MEMORY=12G \
SCM_CLEAN_ROOM_SEQUENCE=local-vm \
./scripts/clean-room/multipass-run.sh
```

Use `./scripts/clean-room/multipass-run.sh --dry-run` before launching the VM. It prints the VM settings and the exact clean-room sequence that will run, without requiring Multipass to be installed.
