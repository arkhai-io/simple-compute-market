# Change Workflow Specification

## Purpose

Define how an OpenSpec change is worked with agent skills: the phases it moves
through and the owner's gates between them, its review records and their findings,
triage and the intervention ledger, implementation one section per fresh session,
validation as an observation of a committed slice, the guarded push of a change's
branch, and agent skills that every supported harness loads from one source.

## Requirements

## Evidence

- Contributor guide to each step, the review directory, and the ledger:
  `docs/agents/change-workflow.md`; rationale: `architecture.md`.
- Leaf skills: `.agents/skills/change-design/`, `change-plan/`, `change-review/`,
  `change-triage/`, `change-implement/`, `change-validate/`, `change-closeout/`, and
  `change-archive-cleanup/`, linked for each harness and held by
  `make check-agent-skills` (`scripts/check_agent_skills.py`).
- Review records: `make review` (`scripts/run_change_review.py`); finding a change
  by name, active or archived: `scripts/find_change.py`.
- Validation: `make validate-local` and `make validate-helm`
  (`scripts/validate_slice.py`); run selection for the validated commit:
  `scripts/fetch-e2e-logs.py`; the push guard: `make check-push-ready` and
  `make push-branch` (`scripts/check_push_ready.py`).
- Reading a round: `make round-view` and `make round-done` (`scripts/round_view.py`).
- Index edits checked: `make check-change-index` (`scripts/check_change_index.py`).
- The post-compaction hook: `.claude/settings.json` and
  `scripts/post_compaction_context.py`.
- Tests for each script under `scripts/tests/`.

The skills are instructions to an agent; that a session follows them is shown by the
sessions that ran them, not by a test.
