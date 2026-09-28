# Tasks — converge Python packaging

Design is settled in `design.md` (D1–D16). This is the section outline by slice; the
file-level plan, per-section validation, and the closeout task defined in
`openspec/README.md#plan-closeout-requirements` are added at planning.

## Slice 1 — one way to build an environment

### 1. Converge the outlier images (D5)

- [ ] 1.1 `domains/apicredits/sample-app`, `provisioning/compute/service` (with
      `--extra adapters`), and `domains/bare_metal/storefront`: install dependencies
      from the committed lock, then the project's own wheel from `.dist`.
- [ ] 1.2 Build each image and confirm its import and health checks pass.

### 2. One Python version (D8)

- [ ] 2.1 Root `.python-version` declaring `3.13`; every Dockerfile `PYTHON_VERSION`
      default at `3.13`.

### 3. Shared script and its callers (D1–D4, D6, D7, D9)

- [ ] 3.1 `scripts/uv_project.py` with `reinit`, `image`, `install-wheel`, and `lock`,
      and its unit tests.
- [ ] 3.2 Every `reinit` target delegates to it; `--python` and `find-links`
      declarations removed.
- [ ] 3.3 Every Dockerfile that copies `.dist` installs through it from a mirrored
      layout with `--locked`, and installs its own wheel in the builder stage;
      `sed` lock rewrites, version literals, the VM storefront's runtime-stage wheel
      install, and `scripts/tests/test_storefront_image_pins.py` removed; the two
      ignore files admit the script.
- [ ] 3.4 Root `make lock`; `make review-locks` delegates to it.
- [ ] 3.5 Confirm each project's `reinit` installs the same set as before, apart from
      the deltas recorded in `design.md`.

### 4. Checks (D12, D13)

- [ ] 4.1 `check-uv-setup`, `check-locks`, `check-python-version`, and
      `make check-packaging`, with tests, including the continued-comment Makefile
      case, a same-version wheel that gained a requirement, a repository distribution
      resolved from an index, and a uv-produced lock with platform-marked and
      extra-scoped requirements that must pass.
- [ ] 4.2 Plan-closeout requirements, `AGENTS.md`, `docs/prompts/implementation.md`,
      and the closeout task of every active change whose closeout is incomplete name
      `make check-packaging`.

### 5. Documentation for slice 1 (D14, D15)

- [ ] 5.1 `docs/development/BUILD_AND_PACKAGING.md`, linked from `ARCHITECTURE.md`,
      `AGENTS.md`, and `openspec/README.md`.

## Slice 2 — one project layout

### 6. Flat import packages under `src/` (D10)

- [ ] 6.1 Move the six nested-import projects to `src/<package>` and rename every
      import, entry point, patch target, warning filter, and smoke import.
- [ ] 6.2 Remove `UV_NO_EDITABLE`, the CI `no_editable` flag, and `cache-keys`;
      update `docs/configuration.md`.

### 7. Versions and publication (D16)

- [ ] 7.1 Bump the minor version of every distribution whose wheel contents change,
      move every `==` pin on them, and relock with `make lock`.
- [ ] 7.2 Update `publish-pypi.yml` path filters to the moved directories and record
      the import migration in `docs/development/RELEASING.md`.

### 8. Relative sources (D11)

- [ ] 8.1 `domains/bare_metal/provisioning/adapter` resolves siblings from `.dist`.
- [ ] 8.2 Record in `remove-relative-uv-sources` that its open sections transferred
      here.

### 9. Layout check and documentation

- [ ] 9.1 `check-project-layout`, with tests, joins `make check-packaging`.
- [ ] 9.2 Layout sections of `BUILD_AND_PACKAGING.md`.

## Closeout

Defined at planning.
