# Session prompts

This folder holds the standing prompts used to open a session with an AI
agent working on this repository, one file per role. These are prompts
*about how to work*, not repository documentation — they should mostly
be short and should mostly point at `AGENTS.md`, `docs/development/ARCHITECTURE.md`,
`docs/development/TESTING.md`, and `openspec/README.md` rather than
restate them. If a prompt is duplicating content that already exists in
one of those files, that content probably belongs in the file, not the
prompt — duplicated rules drift out of sync with each other, which is
what happened to the tombstone convention before this folder existed.

- `implementation.md` — discuss → plan → implement sessions.
- `code-review.md` — sessions whose job is to review a change, not
  implement one (used with external review agents).

Update a prompt when the *role* changes, not when a repository rule
changes — repository rules belong in the guidance documents above and
should only need updating in one place.
