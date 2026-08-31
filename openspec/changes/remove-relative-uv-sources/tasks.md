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
