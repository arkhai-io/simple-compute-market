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

Continue with one explicit workaround after strict mode finds a blocker:

```bash
./scripts/issue-discovery continue --with redis_no_host_port
./scripts/issue-discovery continue --with storefront_volume_chown
./scripts/issue-discovery continue --with cleanup_fixed_docker_names
./scripts/issue-discovery continue --with skip_known_stale_seller_layer
```

Run a narrower diagnostic profile:

```bash
./scripts/issue-discovery profile fresh-volumes
./scripts/issue-discovery profile host-redis-conflict
```

## Strict Versus Continue

Strict mode does not apply hidden fixes. It verifies prerequisites, builds the repo, runs code-level tests, starts the compose stack in mock provisioning mode, checks readiness, registers the mock `kvm1` host, runs marker suites, runs the full integration sweep, and tears down compose.

Continuation mode records that a workaround was used before continuing. Later evidence in that run depends on the workaround and should be interpreted that way. Use continuation runs to discover the next failure after a known blocker, not to redefine strict success.

## Artifacts

Runs write to:

```text
.scm-local/issue-discovery/runs/<run-id>/
```

Important files:

- `manifest.json`: run identity, selected phases, status, workaround context.
- `phases.jsonl`: ordered phase outcomes, failed commands, log paths, classifiers.
- `commands/<phase>/<command>.*`: stdout, stderr, and command metadata.
- `collectors.jsonl`: collector outcomes and evidence paths.
- `context/git-status.txt`: source tree state for the run.
- `context/tool-versions.txt`: host tool versions.
- `docker/`, `health/`: compose and service diagnostics when collected.
- `issue-candidates/candidates.jsonl`: generated issue metadata.
- `issue-candidates/*.md`: Markdown bodies suitable for GitHub issues.

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

The create command uses `gh issue create`, so it requires the GitHub CLI to be installed and authenticated.

## Marker Suites And Full Sweep

Marker suites are useful because they isolate roles and scenarios quickly. Marker deselection is expected in those runs because each marker intentionally selects only part of the integration suite.

The full unfiltered integration sweep still matters because it catches tests that are not covered by a marker command and exposes order or shared-state problems across the complete suite.

## Clean Ubuntu Bootstrap

On a fresh Ubuntu host, run:

```bash
sudo ./scripts/bootstrap-clean-host-ubuntu.sh run
```

The bootstrap installs host prerequisites, including Docker, Compose plugin, `make`, `git`, `curl`, `jq`, `python3`, `uv`, and ZeroTier. It then runs `./scripts/issue-discovery strict` from the checkout by default.

Useful modes:

```bash
./scripts/bootstrap-clean-host-ubuntu.sh check
sudo SCM_RUN_VALIDATION=0 ./scripts/bootstrap-clean-host-ubuntu.sh run
sudo SCM_VALIDATION_COMMAND='./scripts/issue-discovery profile fresh-volumes' ./scripts/bootstrap-clean-host-ubuntu.sh run
```

## Multipass Clean Room

For a local disposable Ubuntu VM:

```bash
./scripts/clean-room/multipass-run.sh
```

The wrapper creates a Multipass VM, transfers the current branch as a git bundle, runs the clean Ubuntu bootstrap inside the VM, fetches issue-discovery artifacts back under `.scm-local/clean-room/`, and deletes the VM unless `KEEP_VM=1` is set.

Common overrides:

```bash
SCM_MULTIPASS_IMAGE=24.04 \
SCM_MULTIPASS_CPUS=6 \
SCM_MULTIPASS_MEMORY=12G \
SCM_VALIDATION_COMMAND='./scripts/issue-discovery profile fresh-volumes' \
./scripts/clean-room/multipass-run.sh
```
