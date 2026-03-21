# Local Stack Audit

## Goal

Audit the local developer stack path from checkout through local bring-up.

## Inputs

- repo checkout
- `README.md`
- `docker-compose.yml`
- local service READMEs

## Procedure

1. Read only the docs and files needed to bring up the local stack.
2. Verify the documented startup order, env samples, and exposed ports.
3. Identify every step that still depends on unstated assumptions.
4. Do not assume prior chat context.

## Output Contract

- summary of whether the local stack path is executable
- file/line references for every gap
- blockers
- missing commands, env files, or verification steps
