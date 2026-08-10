## Why

`pools-9-retire-local-physical-authority` removes the VM storefront's CSV resource
import. Tracing what would replace it found a gap neither change owns.

The provisioning service already seeds hosts (`app_runtime.seed_inventory_if_empty`,
from `inventory_ini` or `inventory_path`) and imports resource-pool definitions
(`import_pool_definitions_if_configured`, from `pool_definitions_path`), both with
full CRUD APIs behind them. Sellable capacity has no equivalent. The only way to
create a site-ledger capacity resource is
`PUT /api/v1/capacity/resources/{resource_id}`, whose own docstring calls it a
"compatibility endpoint for domains that register logical capacity directly." No
startup step creates capacity resources and nothing derives them from hosts.

What fills the gap today is a fallback in
`capacity_inventory._project_host`: a host with no matching capacity resource
projects `capacity` as `{"gpu_count": host.gpu_count}`, `resource_id` as the host
name, and `resource_type` as `compute.gpu`. That works, and it is why a host-seeded
deployment publishes and sells today. But `Host` carries only `gpu_count` and
`gpu_model` — there are no vCPU, RAM, or disk columns — so the fallback can never
express more than GPU count.

The retiring `resources.csv` did carry all four dimensions; they are exactly the
dimensions `resource_capacity_validator` checks and `host_capacity_remaining` sums.
So retiring CSV import removes the only operator-facing path that has ever expressed
multi-dimensional capacity, and the provisioning service has no replacement. That is
safe for the GPU-count-only listings shipping today and forecloses multidimensional
negotiation, which `kit/site` admission, `PhysicalSettlementScheduler` fit checking,
and the Ansible playbooks already support below the operator surface.

Splitting capacity across two authorities inside one service — GPUs on `Host`,
everything else on capacity resources — would relocate the duplication this
consolidation exists to remove, so capacity moves in full.

## What Changes

- Establish the site-ledger capacity resource as the single authoritative
  declaration of sellable capacity, across every dimension including GPU count and
  GPU model. Promote `PUT /api/v1/capacity/resources/{resource_id}` from a
  compatibility endpoint to a documented operator administration surface.
- Add a startup capacity-definitions import mirroring
  `import_pool_definitions_if_configured` exactly: a new `capacity_definitions_path`
  setting resolved the same way as `pool_definitions_path`, an idempotent diff-based
  import that runs on every startup, and a registered
  `ComputeProvisioningStartupStep`. Idempotence is what makes every-startup import
  correct rather than a re-seeding hazard, the same reasoning the pool-definitions
  import already records.
- **BREAKING (deployment/data):** make `Host` executor identity only — addressing,
  SSH credentials, Ansible alias, pool membership, enabled state. Retire
  `gpu_count`/`gpu_model` as capacity sources and retire `_project_host`'s
  host-derived capacity fallback. A migration derives a capacity resource from every
  existing `Host` row carrying GPU data so INI-seeded deployments keep their current
  published capacity across the upgrade without operator action.
- Follow the freeze-then-redirect pattern the POOLS campaign uses: stop reading
  `Host.gpu_count`/`gpu_model` for capacity and leave the columns in place. A schema
  `DROP` is explicitly a later follow-up, after a deployment cycle confirms the
  derivation was never rolled back.
- Fix a projection divergence this consolidation exposes: `_project_host` builds
  `capacity` from the capacity resource when one exists but builds `attributes`
  from the host unconditionally, so a capacity resource declaring four GPUs on a
  host recorded with eight projects `capacity={"gpu_count": 4}` alongside
  `attributes={"gpu_count": 8}`. Projected attributes must not contradict projected
  capacity.
- Give the INI host format a disposition for its `gpus=`/`gpu_model=` variables,
  which currently feed the retiring columns.
- **Added 2026-08-06 (Goal 4 analysis):** stop writing a compute dimension name into
  every domain's capacity declaration. `register_resource` currently sets
  `capacity[PRIMARY_DIMENSION] = total_units` unconditionally when a caller supplies no
  capacity map, and `PRIMARY_DIMENSION` is the module constant `"gpu_count"`. The
  API-credits storefront calls `register_resource(total_units=100,
  resource_type="api_credits")` with no capacity map, so an API-credits quota is stored
  as a GPU count today. A caller supplying `capacity={"tokens": 1000}` alongside
  `total_units` gets both keys written, declaring the resource as 1000 tokens *and*
  1000 GPUs. This belongs here rather than with the publication or kit-extraction work
  because it is a defect in `register_resource`, which this change already rewrites,
  and because this change's whole subject is making capacity declarations authoritative.
- Add operator-facing coverage: CLI, `docs/seller-quickstart.md`, and the
  configuration reference, so registering capacity is a documented workflow rather
  than a raw HTTP call.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `site-capacity`: capacity resources become an operator-administered authoritative
  declaration of multi-dimensional sellable capacity rather than a compatibility
  registration path; projected physical inventory must be internally consistent
  between `capacity` and `attributes`.
- `physical-provisioning`: host inventory is executor identity and MUST NOT be the
  authoritative source of sellable capacity dimensions; the compute provisioner
  imports capacity definitions at startup on the same idempotent contract as pool
  definitions.

## Non-Goals

- Do not `DROP` `Host.gpu_count`/`gpu_model`. Freeze-then-redirect only; the schema
  removal is a later follow-up.
- Do not change capacity admission, matching, scheduling, or fairness policy.
  `kit/site` already accepts and matches multidimensional capacity correctly; this
  change supplies the operator path to declare it, nothing below that.
- Do not implement negotiation or pricing over the newly declarable dimensions. That
  is the negotiation/pricing work tracked separately; this change is its
  precondition, not its delivery.
- Do not retire the VM storefront's local physical tables — `pools-9` owns that and
  depends on this change.
- Do not change the resource-pool definitions import, the host INI seeding path's
  host-identity behavior, or the bare-metal publication view's contract beyond
  keeping it correct across the derivation.
- Do not add a capacity declaration format for domains that register logical
  (non-physical) capacity directly; the endpoint continues to serve them unchanged.

## Impact

- **Affected code:** `kit/site/src/market_site/ledger.py` (`register_resource`'s
  `total_units` mirror and `_resource_capacity`'s fallback),
  `provisioning/compute/service/src/compute_provisioning_service/`
  (`app_runtime.py` startup steps, `config.py` path resolution, `settings.toml`,
  `services/capacity_inventory.py`, `db/models.py`, `db/migrations.py`),
  `kit/site` (`router.py`, `http_models.py`) and `kit/site-client`,
  `domains/vms/provisioning/adapter` host service and INI parser.
- **Affected deployment:** a new `capacity_definitions_path` setting and its Helm and
  compose wiring; an ordered migration that derives capacity resources before the
  application serves requests, per `deployment-state`'s service-owned migration
  history requirement.
- **Affected data:** every existing `Host` row with GPU data gains a derived capacity
  resource. Rollback within the freeze window is a code rollback; the derived rows
  are additive and harmless to a rolled-back reader.
- **Affected tests:** provisioning unit and integration suites for startup import,
  derivation migration, and projection consistency; `kit/site` ledger and router
  suites; sync/async client parity for any new client method; the VM e2e scenarios
  that depend on projected capacity shape.
- **Wire compatibility:** the projection's `capacity`/`attributes` shape is unchanged
  structurally; only the divergence case changes value. `ResourceRegisterRequest`
  gains no required field.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the authority-boundaries table's physical
      resource row and the shared-vocabulary entry for Physical Resource, which
      currently do not distinguish executor identity from capacity declaration.
- [x] Existing subsystem specification — `openspec/specs/site-capacity/spec.md` and
      `openspec/specs/physical-provisioning/spec.md`.
- [ ] New subsystem specification — none.
- [ ] No permanent documentation change — not applicable.

### Knowledge to promote

- Capacity resources are the single authoritative declaration of sellable capacity;
  host rows are executor identity — `openspec/specs/physical-provisioning/spec.md`
  and the `ARCHITECTURE.md` authority-boundaries table.
- Projected inventory `attributes` must not contradict projected `capacity` —
  `openspec/specs/site-capacity/spec.md`, alongside the existing physical-inventory
  projection requirement.
- Why capacity declaration is a separate concern from executor inventory, and why
  splitting dimensions across both was rejected — `openspec/specs/site-capacity/architecture.md`.

## Dependencies and Related Changes

- `pools-9-retire-local-physical-authority` **depends on this change**. Retiring the
  storefront's CSV import before an operator path for multi-dimensional capacity
  exists is what would create the regression this change prevents.
- `structured-capacity-requirements` and `negotiation-driven-capacity-resize` consume
  what this change makes declarable. Neither blocks it, and this change does not
  wait on their vocabulary decisions — it uses the dimension names `arkhai_vms`
  already defines.
- `pools-8-capacity-projection-and-listing-hints` built the projection and hint
  mechanism this change writes into. No conflict; this change adds no projection
  field.
- `market-platform-bare-metal-10-storefront-composition` owns the bare-metal
  per-resource publication view that `_project_host` produces. This change must keep
  that view correct across the derivation but does not alter its contract.
