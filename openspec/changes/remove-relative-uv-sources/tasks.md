## 1. Inventory and guard

- [ ] 1.1 Confirm the exact internal path sources and lock entries in the API-credit domain, both provisioning adapters, compute contract, and compute service projects.
- [ ] 1.2 Add a repository check that rejects internal parent/sibling path sources while allowing external index selectors.

## 2. Wheel-only project cutovers

- [ ] 2.1 Add/repair build and reinit targets for `provisioning/compute` and its service with explicit wheel ordering/reinstall.
- [ ] 2.2 Add/repair targets for VM and bare-metal provisioning adapters and rebuild their prerequisites.
- [ ] 2.3 Cut over the API-credit domain and all five affected locks without unrelated dependency drift.
- [ ] 2.4 Verify clean-environment install, tests, wheel contents, and no source-tree import leakage for each project.
- [ ] 2.5 Close the wider `reinit` gap this change's second bullet already owns. Inventoried
      2026-08-13 against `e91767a3`: 16 of 33 projects with a `pyproject.toml` have no
      `reinit` target. Eleven have a Makefile without one — `core`,
      `core/registry-client`, `core/storefront-client`,
      `domains/apicredits/middleware/python`, `domains/vms/provisioning/iac`,
      `kit/alkahest`, `kit/identity`, `kit/policy`, `kit/resource-pools`, `kit/site`,
      `kit/site-client`. Five have no Makefile at all —
      `domains/bare_metal/provisioning/adapter`, `domains/vms/domain`,
      `domains/vms/provisioning/client`, `provisioning/compute`,
      `tools/issue-discovery`.

      Decide which are owed a target rather than adding sixteen. A project with no
      virtual environment to maintain does not need one, and at least two absences look
      deliberate: `tools/issue-discovery` is isolated behind `uv --no-config` on purpose,
      and several Makefile-less projects may be wheel-only libraries. The absence follows
      no convention worth preserving — `kit/config` and `kit/fulfillment` define `reinit`
      while their six siblings do not — so the decision is per project, on whether an
      environment exists to refresh, not by directory.

      `kit/policy` is out of scope here: `restore-issue-discovery-thin-runner` adds its
      target because a repaired phase invokes it. Skip it and avoid the collision.

## 3. Documentation and validation

- [ ] 3.1 Correct `docs/development/RELEASING.md` and any conflicting local-development guidance.
- [ ] 3.2 Run packaging checks, affected suites, full path-source scan, and strict OpenSpec validation.
- [ ] 3.3 Promote the accepted rule to `openspec/specs/deployment-state/spec.md` and rationale to `architecture.md`, recording destinations in `design.md` before archive.

## 4. `rl` extra resolution (found 2026-08-12, not yet planned)

- [ ] 4.1 Make `make reinit` resolvable in `domains/vms/storefront`. It currently fails on
      every host because `uv` resolves the `rl` extra across all declared environments and
      no `torch` satisfies the darwin/arm64 split. Two candidate fixes were tried and each
      moved the failure rather than removing it; see `design.md`, "Found from adjacent
      work". Decide the owning question first — whether the `pytorch-cpu` index selector
      should be scoped, whether `rl` belongs in the default resolution, or whether
      `requires-python` should narrow — rather than iterating on markers. Regenerating
      `domains/vms/storefront/uv.lock` is part of whichever fix is chosen.
- [ ] 4.2 Bound `dynaconf` below 3.3 in the five distributions that declare it, with the
      reason at the declaration: `settings.set` on a list key merges from 3.3 and replaces
      before it. Sequenced after 4.1 rather than beside it — the bound invalidates each
      `uv.lock`, and re-locking is what 4.1 unblocks. State the scope honestly when writing
      the comment: the demonstrated breakage is in test helpers overriding a list-valued
      setting, not in production config layering, so a later audit of list-valued `set`
      calls can lift it deliberately.
      Files: `domains/vms/storefront/pyproject.toml`,
      `domains/apicredits/storefront/pyproject.toml`,
      `domains/apicredits/service/pyproject.toml`,
      `provisioning/compute/service/pyproject.toml`, `e2e-tests/pyproject.toml`, and each
      project's lock.
