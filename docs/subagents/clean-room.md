# Clean Room Audit

## Goal

Judge whether a fresh operator could stand up and validate the stack from repo docs alone.

## Inputs

- `docs/standup/overview.md`
- `docs/deployment-input-checklist.md`
- every stand-up doc under `docs/standup/`

## Procedure

1. Follow the docs in order as a clean-room operator would.
2. Treat external credentials and infrastructure access as available, but no tribal knowledge.
3. Flag every place where the operator must infer missing information.
4. Do not assume prior chat context.

## Output Contract

- final yes/no judgment for clean-room stand-up
- file/line references for every gap
- blockers
- missing commands, env files, or verification steps
