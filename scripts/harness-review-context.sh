#!/usr/bin/env bash
# Resolve the current state a harness review or planning session needs.
#
# Pinned SHAs in planning documents go stale — `dev` in particular advances
# through ordinary work. This resolves the same facts live, so a session starts
# from what the repository says now.
#
# Output is public and safe to paste anywhere. This script deliberately reports
# only this repository; anything about a separate private repository belongs to
# that repository's own copy and must not be reported here.
#
# Three questions this answers that ref ancestry alone cannot:
#   1. Is a given capability PRESENT on dev, regardless of which branch it came
#      from? Ancestry answers "was this branch merged", which is a different
#      question and has been misread as this one.
#   2. Where did the harness code on dev come from, and is that commit reachable
#      from a harness branch?
#   3. Do dev's permanent documents cite paths dev does not contain? An orphan
#      cross-reference is how excluded work gets silently inherited.
#
# Read-only. Fetches and reads refs, writes one file under /tmp. Creates no
# branch, moves no ref, mutates nothing.
set -euo pipefail

OUT_DIR="${HARNESS_CONTEXT_DIR:-/tmp/harness-review-context}"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/scm-context.md"

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
git rev-parse --git-dir >/dev/null 2>&1 || die "not a git repository"
[ -d openspec/changes ] && [ -d domains/vms ] \
  || die "not the application repository — expected openspec/ and domains/vms/"

printf 'fetching...\n' >&2
git fetch --quiet --prune origin || printf 'warning: fetch failed; reporting cached refs\n' >&2

sha()     { git rev-parse --short=12 "$1" 2>/dev/null || echo MISSING; }
full()    { git rev-parse "$1" 2>/dev/null || echo MISSING; }
dated()   { git log -1 --format='%cd' --date=short "$1" 2>/dev/null || echo '-'; }

# grep -c prints 0 AND exits 1 on no match. `|| echo 0` therefore emits a
# second 0 — the defect that made an earlier task table unreadable.
count()   { printf '%s\n' "$1" | grep -c "$2" || true; }

exists()  { git cat-file -e "$1" 2>/dev/null && echo yes || echo no; }
grepref() { git show "$1" 2>/dev/null | grep -qiE "$2" && echo yes || echo no; }

# Relationship of $1 to $2, distinguishing equality from strict containment.
relation() {
    local a="$1" b="$2"
    git rev-parse --verify --quiet "$a" >/dev/null || { echo missing; return; }
    git rev-parse --verify --quiet "$b" >/dev/null || { echo missing; return; }
    if [ "$(full "$a")" = "$(full "$b")" ]; then echo equal; return; fi
    if git merge-base --is-ancestor "$a" "$b" 2>/dev/null; then echo "contained in $b"; return; fi
    if git merge-base --is-ancestor "$b" "$a" 2>/dev/null; then echo "contains $b"; return; fi
    echo diverged
}

{
    cat <<HEADER
# SCM (public) review context

Generated $(date -u +%Y-%m-%dT%H:%M:%SZ). Public — safe to share.

The review issue's SHAs are stale by design; these are current.

## Implementation cutoff

\`origin/dev\` is the sole public product and inherited implementation authority.
Pin the full SHA before starting, and re-pin if the session spans a day.

| ref | full sha | last commit |
|---|---|---|
| \`origin/dev\` | \`$(full origin/dev)\` | $(dated origin/dev) |
HEADER

    # --- branch ancestry, clearly labelled as ancestry ----------------------
    printf '\n## Harness branches — merge relationship to dev\n\n'
    printf '| branch | sha | relationship to `origin/dev` |\n|---|---|---|\n'
    for b in $(git for-each-ref --format='%(refname:short)' 'refs/remotes/origin/**' \
                | grep -iE 'harness|issue-discovery|agent' | grep -v 'origin/HEAD' | sort); do
        printf '| `%s` | `%s` | %s |\n' "$b" "$(sha "$b")" "$(relation "$b" origin/dev)"
    done
    cat <<'NOTE'

This table answers **was this branch merged**, which is not the same question as
**is its work present on dev**. A branch can be unmerged while the capability it
carries is on dev by other means, and a merged branch can have had work reverted
since. Read the content inventory below before concluding anything about
inherited authority.
NOTE

    # --- content inventory: the question ancestry cannot answer -------------
    printf '\n## Harness content actually present on dev\n\n'
    printf '| capability marker | on `origin/dev` |\n|---|---|\n'
    printf '| base tool `tools/issue-discovery/README.md` | %s |\n' \
        "$(exists origin/dev:tools/issue-discovery/README.md)"
    printf '| base tool python files | %s |\n' \
        "$(git ls-tree -r --name-only origin/dev tools/issue-discovery 2>/dev/null | grep -c '\.py$' || true)"
    printf '| capacity module `src/issue_discovery/capacity.py` | %s |\n' \
        "$(exists origin/dev:tools/issue-discovery/src/issue_discovery/capacity.py)"
    printf '| capacity scenario schema | %s |\n' \
        "$(exists origin/dev:tools/issue-discovery/schemas/capacity-scenario.schema.json)"
    printf '| capacity finding schema | %s |\n' \
        "$(exists origin/dev:tools/issue-discovery/schemas/capacity-finding.schema.json)"
    printf '| capacity scenario fixtures | %s file(s) |\n' \
        "$(git ls-tree -r --name-only origin/dev tools/issue-discovery/config/capacity 2>/dev/null | grep -c . || true)"
    printf '| capacity tests `tests/test_capacity.py` | %s |\n' \
        "$(exists origin/dev:tools/issue-discovery/tests/test_capacity.py)"
    printf '| spec requirement (agent-driven capacity) | %s |\n' \
        "$(grepref origin/dev:openspec/specs/test-compatibility/spec.md 'agent-driven .*capacity|finite and non-executing')"
    printf '| `ISSUE_DISCOVERY.md` privacy/validation section | %s |\n' \
        "$(grepref origin/dev:docs/development/ISSUE_DISCOVERY.md 'privacy and validation')"
    printf '| `TESTING.md` harness jurisdiction section | %s |\n' \
        "$(grepref origin/dev:docs/development/TESTING.md 'agent-driven capacity harness')"
    printf '| make target invoking the harness | %s |\n' \
        "$(grepref origin/dev:Makefile 'issue-discovery')"

    # --- provenance of what IS on dev --------------------------------------
    printf '\n## Provenance of the harness code on dev\n\n'
    if [ "$(exists origin/dev:tools/issue-discovery/README.md)" = yes ]; then
        intro="$(git log --format='%H' --diff-filter=A --reverse origin/dev -- tools/issue-discovery 2>/dev/null | head -1 || true)"
        if [ -n "${intro:-}" ]; then
            printf -- '- introduced by `%s` (%s) — %s\n' \
                "$(git rev-parse --short=12 "$intro")" \
                "$(git log -1 --format='%cd' --date=short "$intro")" \
                "$(git log -1 --format='%s' "$intro")"
            printf -- '- refs containing that commit:\n'
            git branch -r --contains "$intro" 2>/dev/null | sed 's/^/    - /' || printf '    - (none resolvable)\n'
        else
            printf -- '- introducing commit not resolvable in this clone (shallow?)\n'
        fi
        printf -- '- last touched by `%s` (%s)\n' \
            "$(git log -1 --format='%h' origin/dev -- tools/issue-discovery)" \
            "$(git log -1 --format='%cd' --date=short origin/dev -- tools/issue-discovery)"
    else
        printf -- '- `tools/issue-discovery/` is not on dev; no provenance to report\n'
    fi
    printf -- '\nIf the introducing commit is reachable from a harness branch, the base tool\n'
    printf 'is inherited authority under the cutoff rule. If it was authored on `dev`,\n'
    printf 'the harness branches are excluded provenance in full.\n'

    # --- orphan cross-references in permanent documents --------------------
    printf '\n## Permanent documents referencing paths dev does not contain\n\n'
    orphans=0
    for doc in docs/development/TESTING.md docs/development/ARCHITECTURE.md \
               docs/development/ISSUE_DISCOVERY.md openspec/README.md; do
        [ "$(exists "origin/dev:$doc")" = yes ] || continue
        for p in $(git show "origin/dev:$doc" 2>/dev/null \
                    | grep -oE '(openspec|docs|tools|scripts|e2e-tests)/[A-Za-z0-9_./-]+\.(md|py|json|ya?ml|sh)' \
                    | sort -u); do
            if [ "$(exists "origin/dev:$p")" = no ]; then
                printf -- '- `%s` cites `%s`, which is not on dev\n' "$doc" "$p"
                orphans=$((orphans + 1))
            fi
        done
    done
    [ "$orphans" -eq 0 ] && printf -- '- none found\n'
    printf -- '\nA permanent document describing behavior dev does not implement is how\n'
    printf 'excluded work gets inherited without a decision. Each hit needs an explicit\n'
    printf 'disposition: remove it, or open the change that makes it true.\n'

    # --- change inventory, keyword-free ------------------------------------
    printf '\n## OpenSpec changes touching the harness or the e2e path\n\n'
    printf '| change | done | open | mentions harness | carries findings doc |\n|---|---|---|---|---|\n'
    for c in $(git ls-tree --name-only origin/dev openspec/changes/ | sed 's|/$||;s|.*/||' | sort -u); do
        t="openspec/changes/$c/tasks.md"
        [ "$(exists "origin/dev:$t")" = yes ] || continue
        body="$(git show "origin/dev:$t" 2>/dev/null || true)"
        blob="$(git ls-tree -r --name-only origin/dev "openspec/changes/$c" 2>/dev/null || true)"
        # Select on content, not on a name keyword: a change qualifies if it
        # names the harness or the e2e path anywhere in its own directory.
        hay="$(git grep -h -iE 'issue-discovery|issue_discovery|harness|e2e' "origin/dev" -- "openspec/changes/$c" 2>/dev/null || true)"
        [ -n "$hay" ] || continue
        mh=no; printf '%s' "$hay" | grep -qiE 'issue-discovery|issue_discovery|harness' && mh=yes
        fd="$(printf '%s\n' "$blob" | grep -icE 'findings|inventory' || true)"
        printf '| `%s` | %s | %s | %s | %s |\n' "$c" \
            "$(count "$body" '^- \[x\]')" "$(count "$body" '^- \[ \]')" "$mh" "$fd"
    done
    printf '\nA change with open tasks is unstarted or in flight; one with none is\n'
    printf 'complete but not archived until `openspec archive` runs.\n'

    printf '\n## Unarchived findings documents\n\n'
    found=0
    for f in $(git ls-tree -r --name-only origin/dev openspec/changes 2>/dev/null \
                | grep -v '^openspec/changes/archive/' \
                | grep -iE 'findings|ledger' || true); do
        printf -- '- `%s`\n' "$f"; found=1
    done
    [ "$found" -eq 0 ] && printf -- '- none\n'


printf '\n---\n\nRegenerate with `bash scripts/harness-review-context.sh`. Nothing here is\n'
printf 'authority: the reviewed plan is. This only says what the repository\n'
printf 'currently contains.\n'
} > "$OUT"

printf 'wrote %s\n' "$OUT"
printf '\n--- summary ---\n'
sed -n '/^## Harness content actually present on dev/,/^## Provenance/p' "$OUT" 2>/dev/null | head -16
