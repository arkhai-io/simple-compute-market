#!/usr/bin/env bash
# Drive the E2E workflow from a terminal.
#
# The E2E suite runs nightly and on demand, and its evidence lands in two
# different places: the pytest output is in the job's step log, while the
# `docker compose logs` capture is a separate `e2e-logs` artifact. Diagnosing a
# failure usually needs both, and fetching them through the web UI is slow enough
# that people skip the compose logs — which is where the cause of an inventory or
# startup failure normally is.
#
# Requires the GitHub CLI, authenticated: `gh auth login`.
set -euo pipefail

WORKFLOW="e2e.yml"
ARTIFACT="e2e-logs"
OUT_DIR="${E2E_LOG_DIR:-.e2e-logs}"

die() { printf 'error: %s\n' "$*" >&2; exit 1; }

require_gh() {
    command -v gh >/dev/null 2>&1 || die "GitHub CLI not found — install gh and run 'gh auth login'"
    gh auth status >/dev/null 2>&1 || die "gh is not authenticated — run 'gh auth login'"
}

gh_version() { gh --version 2>/dev/null | head -1; }

# Reported when a subcommand rejects a flag: the flags this script uses have
# appeared at different gh releases, and the version is the first thing needed to
# tell "unsupported here" from "wrong arguments".
unsupported() {
    printf 'note: %s\n' "$1" >&2
    printf '      gh: %s\n' "$(gh_version)" >&2
}

current_branch() {
    git rev-parse --abbrev-ref HEAD 2>/dev/null || die "not a git repository"
}

# The workflow dispatches against a ref the remote knows about, so an unpushed
# branch would silently run someone else's code. Refuse instead.
require_pushed() {
    local branch="$1"
    git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1 \
        || die "branch '$branch' is not on origin — push it before dispatching"
    local local_sha remote_sha
    local_sha="$(git rev-parse HEAD)"
    remote_sha="$(git ls-remote origin "refs/heads/$branch" | cut -f1)"
    if [ "$local_sha" != "$remote_sha" ]; then
        printf 'warning: local HEAD %s differs from origin/%s %s\n' \
            "${local_sha:0:8}" "$branch" "${remote_sha:0:8}" >&2
        printf '         the run will use the pushed commit, not your working tree\n' >&2
    fi
}

# Filtered client-side rather than with `gh run list --branch`: that flag is
# absent from older gh releases, while `--json`/`--jq` are present in every
# version that has `run list` at all.
latest_run_id() {
    local branch="$1"
    gh run list --workflow "$WORKFLOW" --limit 30 \
        --json databaseId,headBranch \
        --jq "[.[] | select(.headBranch == \"$branch\")] | .[0].databaseId // empty" \
        2>/dev/null
}

list_runs() {
    local branch="$1"
    gh run list --workflow "$WORKFLOW" --limit 30 \
        --json databaseId,headBranch,status,conclusion,createdAt,displayTitle \
        --jq "[.[] | select(.headBranch == \"$branch\")] | .[:5][]
              | \"\(.databaseId)  \(.status)/\(.conclusion // \"-\")  \(.createdAt)  \(.displayTitle)\"" \
        2>/dev/null
}

cmd_dispatch() {
    require_gh
    local branch; branch="$(current_branch)"
    require_pushed "$branch"
    printf 'dispatching %s on %s\n' "$WORKFLOW" "$branch"
    gh workflow run "$WORKFLOW" --ref "$branch"
    # The run is not queryable the instant dispatch returns, and the dispatch has
    # already succeeded by this point — a failed id lookup must not fail the
    # command and imply nothing was queued.
    sleep 5
    local run_id; run_id="$(latest_run_id "$branch" || true)"
    if [ -n "$run_id" ]; then
        printf 'run %s: %s\n' "$run_id" \
            "$(gh run view "$run_id" --json url --jq .url 2>/dev/null || echo '(url unavailable)')"
    else
        printf 'dispatched; the run is not queryable yet — try: make e2e-status\n'
    fi
}

cmd_watch() {
    require_gh
    local branch; branch="$(current_branch)"
    local run_id; run_id="$(latest_run_id "$branch")"
    [ -n "$run_id" ] || die "no $WORKFLOW run found for branch '$branch'"
    if ! gh run watch "$run_id" --exit-status 2>/dev/null; then
        local status
        status="$(gh run view "$run_id" --json status,conclusion \
            --jq '"\(.status)/\(.conclusion // "-")"' 2>/dev/null || echo unknown)"
        if [ "$status" = "unknown" ]; then
            unsupported "'gh run watch --exit-status' failed; poll with: make e2e-status"
            return 1
        fi
        # `--exit-status` makes watch exit non-zero on a failed run, which is the
        # intended signal rather than an error in this script.
        printf 'run %s finished: %s\n' "$run_id" "$status"
        case "$status" in *"/success") return 0 ;; *) return 1 ;; esac
    fi
}

cmd_status() {
    require_gh
    local branch; branch="$(current_branch)"
    local rows; rows="$(list_runs "$branch")"
    if [ -z "$rows" ]; then
        printf 'no %s runs found for branch %s\n' "$WORKFLOW" "$branch"
        return 0
    fi
    printf 'RUN ID      STATUS/RESULT        CREATED               TITLE\n'
    printf '%s\n' "$rows"
}

# Both halves of the evidence, named so it is obvious which is which.
cmd_logs() {
    require_gh
    local branch; branch="$(current_branch)"
    local run_id="${1:-}"
    [ -n "$run_id" ] || run_id="$(latest_run_id "$branch")"
    [ -n "$run_id" ] || die "no $WORKFLOW run found for branch '$branch'"

    local dest="$OUT_DIR/$run_id"
    mkdir -p "$dest"

    printf 'run %s (%s)\n' "$run_id" "$branch"

    # Artifact first: it carries the scenario output and the stack logs, and is a
    # far smaller fetch than a 90-minute job's step log.
    if ! gh run download "$run_id" --name "$ARTIFACT" --dir "$dest" 2>/dev/null; then
        printf 'note: no %s artifact for run %s — it may predate the artifact, or\n' \
            "$ARTIFACT" "$run_id" >&2
        printf '      the stack failed before collecting; using the step log instead\n' >&2
    fi

    # Fetched when the artifact lacks the scenario output — older runs, or a job
    # that died before the tee flushed.
    if [ ! -s "$dest/scenario-output.txt" ]; then
        gh run view "$run_id" --log > "$dest/steps.txt" 2>/dev/null \
            || gh run view "$run_id" --log-failed > "$dest/steps.txt" 2>/dev/null \
            || printf 'warning: could not fetch step log either\n' >&2
    fi

    printf '\nwrote:\n'
    find "$dest" -type f -printf '  %p (%s bytes)\n' 2>/dev/null \
        || find "$dest" -type f -exec ls -l {} \;

    # The two lines a reader wants first.
    local summary_src="$dest/scenario-output.txt"
    [ -s "$summary_src" ] || summary_src="$dest/steps.txt"
    if [ -s "$summary_src" ]; then
        printf '\npytest summary:\n'
        grep -oE '[0-9]+ (failed|passed|skipped|error)[a-z, ]*' "$summary_src" \
            | tail -4 | sed 's/^/  /' || true
        printf '\nfailing scenarios:\n'
        grep -oE 'FAILED tests/[^ ]*' "$summary_src" | sort -u | sed 's/^/  /' || true
    fi
}

usage() {
    cat <<'USAGE'
usage: scripts/e2e-ci.sh <command>

  dispatch      run the E2E workflow against the current branch on origin
  watch         follow the newest run for this branch until it finishes
  status        list recent runs for this branch
  logs [RUN_ID] download the step log and the compose-logs artifact

Output goes to .e2e-logs/<run-id>/ (override with E2E_LOG_DIR).
USAGE
}

case "${1:-}" in
    dispatch) shift; cmd_dispatch "$@" ;;
    watch)    shift; cmd_watch "$@" ;;
    status)   shift; cmd_status "$@" ;;
    logs)     shift; cmd_logs "$@" ;;
    ""|-h|--help) usage ;;
    *) usage; exit 2 ;;
esac
