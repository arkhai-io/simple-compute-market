# Compute provisioning

This directory is the home for shared cross-domain compute provisioning code.
It is intentionally outside `core/`, `domains/`, and `kit/`:

- `core/` defines marketplace role skeletons and shared storefront/site
  primitives.
- `domains/` define deterministic market semantics and concrete domain adapters.
- `kit/` contains opt-in reusable libraries and caller contracts.
- `provisioning/compute/` is for deployable compute provisioners that can serve
  multiple compute domains, such as VM and bare-metal.

The current transitional implementation remains in
`provisioning/compute/service` until the compute provisioner can be moved
without breaking existing VM clients, Docker images, or Helm/developer flows.

Current package:

- `arkhai-compute-provisioning` — shared app/lifecycle/startup helpers for
  compute provisioning services.

Expected future split:

```text
provisioning/compute/
  service/      # deployable FastAPI service and composition root
  client/       # HTTP/generated client, if split out
  contracts/    # shared DTOs/contracts, if split out
```

See `docs/development/provisioning-migration-plan.md` for the migration map and
extraction sequence.
