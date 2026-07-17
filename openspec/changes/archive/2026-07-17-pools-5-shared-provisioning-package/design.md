## Closure Note (2026-07-17)

This design.md intentionally stayed minimal for POOLS-5's entire life —
detailed decisions (exact module layout, what moves vs. what stays
VM-local) were deferred to the design-review pass its activation condition
would trigger. That pass never happened under this change; see
`proposal.md`'s "Disposition" for why. Whatever design-review depth this
question needs now belongs to
`market-platform-compute-30-extract-service`'s own design.md, before that
change leaves taskless status.

One concrete, code-verified finding from POOLS-5's closing session is worth
preserving here since it was discovered under this change: `provisioning/
compute/src/compute_provisioning/pools.py` and `pool_config_handler.py` are
byte-identical duplicates of the files in
`kit/resource-pools/src/market_resource_pools/`. `compute_provisioning`'s
own `__init__.py` does not import its local copies — it re-exports the real
ones from `market_resource_pools` instead. No code anywhere imports
`compute_provisioning.pools` or `compute_provisioning.pool_config_handler`
as submodules (verified by repository-wide grep, 2026-07-17). These two
files are dead, unreferenced duplicates, most likely left over from before
the re-export approach was adopted. This is tracked as a concrete task in
`market-platform-compute-30-extract-service/tasks.md`.

## Original Context

See the original `proposal.md` for the supersession finding: the
originally-planned `core/provisioning`/`core_provisioning` package should
not be created, because `provisioning/compute`/`compute_provisioning`
already existed and `market-platform-compute-30-extract-service` already
owned extracting the remaining generic machinery there.

## Original Decisions

### 1. The ownership rule already exists; this change only extends its scope

`physical-provisioning`'s "Compute-owned caller contract" requirement
already establishes that shared, executor-neutral models belong in
`compute_provisioning` rather than the VM domain. This change's only
concrete claim was that `pools-2`/`pools-3`'s scheduler and provider
contracts should eventually follow the same rule — not a new ownership
principle, an extension of scope for one already decided. This claim
carries forward to compute-30 unchanged.

## Original Risks / Trade-offs

- **Premature extraction risk.** Moving these contracts before a second
  domain needs them risks designing a boundary against a sample size of
  one, the same anti-pattern the original POOLS-5 plan was written to avoid
  duplicating VM-domain code — just in the opposite direction. This risk
  still applies and should inform compute-30's design-review pass.
