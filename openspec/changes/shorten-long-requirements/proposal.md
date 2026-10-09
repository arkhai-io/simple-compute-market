# Shorten long requirements

## Why

`@fission-ai/openspec` 1.14.1 (published 2026-10-05) warns on requirement text
over 500 characters, and `validate --strict` fails on that warning. Under it, 21
of the 22 permanent specs fail strict validation, as do active changes whose
delta requirements are long (`bare-metal-mock-provisioned-deal` has 19). The
repository pins the validator to 1.14.0 (`openspec/README.md`) so the gate keeps
meaning what it meant; this change does the restructuring the new rule asks for,
then moves the pin forward.

The rule is sound: a requirement that carries its examples and edge cases in its
statement is harder to read and to test than one stating a single behavior with
scenarios for the cases.

## What changes

- Each requirement over 500 characters in `openspec/specs/` is restructured by
  moving examples and edge cases into scenarios, or split into requirements that
  each state one behavior. Normative meaning does not change: every MUST and
  every scenario's outcome survives, in the requirement or a scenario.
- The pin in `openspec/README.md` moves to the validator release that introduced
  the rule (or a later one), and the change gates on `validate --all --strict`
  passing under it.
- Active changes' delta requirements are not restructured here: each owns its
  deltas and restructures them at its own closeout, before promotion.

## Out of scope

- Any behavior change. A requirement whose restructuring would change its
  meaning is recorded as a finding for the capability's owner, not rewritten.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The restructured requirements, in each `openspec/specs/<capability>/spec.md`.
- The validator pin, in `openspec/README.md`.
