## 1. Inventory and guard

- [ ] 1.1 Confirm the exact internal path sources and lock entries in the API-credit domain, both provisioning adapters, compute contract, and compute service projects.
- [ ] 1.2 Add a repository check that rejects internal parent/sibling path sources while allowing external index selectors.

## 2. Wheel-only project cutovers

- [ ] 2.1 Add/repair build and reinit targets for `provisioning/compute` and its service with explicit wheel ordering/reinstall.
- [ ] 2.2 Add/repair targets for VM and bare-metal provisioning adapters and rebuild their prerequisites.
- [ ] 2.3 Cut over the API-credit domain and all five affected locks without unrelated dependency drift.
- [ ] 2.4 Verify clean-environment install, tests, wheel contents, and no source-tree import leakage for each project.

## 3. Documentation and validation

- [ ] 3.1 Correct `docs/development/RELEASING.md` and any conflicting local-development guidance.
- [ ] 3.2 Run packaging checks, affected suites, full path-source scan, and strict OpenSpec validation.
- [ ] 3.3 Promote the accepted rule to `openspec/specs/deployment-state/spec.md` and rationale to `architecture.md`, recording destinations in `design.md` before archive.
