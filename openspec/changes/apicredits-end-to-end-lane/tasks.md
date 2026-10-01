# Tasks — API-credit end-to-end lane

Design phase; not planned. Loop holding follows `bare-metal-mock-provisioned-deal`,
which builds the API-credit lane; the integration tests have no blocking dependency.

## 1. Design

- [x] 1.1 **Decision gate.** Decide whether API credits runs in its own lane. Decided:
      its own pipeline job, not inside the VM lane. Building it migrated to
      `bare-metal-mock-provisioned-deal` on 2026-10-01.
- [x] 1.2 **Decision gate.** Decide what an API-credit storefront integration test
      runs. Decided: the production application through its lifespan, with a real
      database and the canonical typed client.
- [ ] 1.3 **Decision gate.** Resolve the open questions in `design.md`.
- [ ] 1.4 Plan the implementation.

## 2. Closeout

- [ ] 2.1 The closeout task defined in
      `openspec/README.md#plan-closeout-requirements`, written out in full when this
      change is planned.
