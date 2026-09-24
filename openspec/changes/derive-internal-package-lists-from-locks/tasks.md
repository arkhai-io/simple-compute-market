# Tasks — derive internal package lists from locks

## 1. Flag script

- [ ] 1.1 Add a new script, `internal_package_flags.py <uv.lock> --form reinit|refresh`,
  standard library only, selecting the packages a lock resolves from a local wheel
  registry (a filesystem path, relative or absolute).
- [ ] 1.2 Unit tests: relative and absolute registry paths selected; public-index,
  editable, path, and the project itself excluded; stable output order; both forms.

## 2. Makefiles

- [ ] 2.1 Replace the package list in each of the 34 `reinit` targets with the
  derived flags, evaluated in the recipe's shell.
- [ ] 2.2 Confirm each project's `make reinit` installs the same set as before.

## 3. Dockerfiles

- [ ] 3.1 In each of the 7 Dockerfiles with a `--refresh-package` list, copy the
  script into the builder and derive the flags after the registry-path rewrite.
- [ ] 3.2 Confirm each builder stage has Python 3.11 or later.
- [ ] 3.3 Build each image and confirm its import checks pass.

## 4. Check

- [ ] 4.1 Rewrite `scripts/check_reinit.py` to fail when a project whose lock
  installs internal wheels lists packages by hand in its `reinit` target or in a
  Dockerfile that copies `.dist`.
- [ ] 4.2 Tests for the rewritten check, including a Dockerfile list.

## 5. Documentation and promotion

- [ ] 5.1 Update `AGENTS.md`'s `check-reinit` rule and
  `docs/development/ARCHITECTURE.md` (build, packaging, and initialization).
- [ ] 5.2 Promote the requirement into `openspec/specs/deployment-state/spec.md` and
  fold the stray "Internal wheel development contract" section into
  `## Requirements`.

## 6. Validation

- [ ] 6.1 `make test`, `make check-reinit`, and the e2e pipeline pass.
