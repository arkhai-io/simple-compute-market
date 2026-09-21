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
name, and `resource_type` as `compute.gpu`. That is why a host-seeded deployment
publishes listings today — though it cannot sell against them, because admission
matches only capacity resources and nothing creates one from a host (corrected
2026-09-21; an earlier version said such a deployment "publishes and sells"). And
`Host` carries only `gpu_count` and `gpu_model` — there are no vCPU, RAM, or disk
columns — so the fallback can never express more than GPU count.

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
- Add a capacity-definitions import mirroring
  `import_pool_definitions_if_configured` exactly: a new `capacity_definitions_path`
  setting resolved the same way as `pool_definitions_path`, reconciliation through
  the existing `DefinitionDocumentImporter`, and a registered
  `ComputeProvisioningStartupStep`. **Corrected 2026-09-09:** an earlier version of
  this bullet described an idempotent diff applied on every startup, which was the
  pool import's behaviour when this change was written. `DEPLOYMENT_AND_CONFIG.md`
  has since established the opposite rule — "a process start is not a submission",
  and import "is idempotent with respect to the document, not the database" — so
  capacity definitions follow the same digest gate: reconcile a new or edited
  document, do nothing for an unchanged one, reconcile regardless of digest on an
  explicit import, and commit the digest in the same transaction as the apply.
  Mirroring the pool import exactly is still the instruction; what that means has
  changed underneath it. **Amended 2026-09-21:** an explicit
  `POST /api/v1/capacity/definitions/import` follows the host import convention — it
  always reconciles and records no digest — and both paths upsert only, retaining
  declarations a document does not name.
- Make the legacy scalar mirror's dimension name composition-supplied rather than the
  hardcoded `PRIMARY_DIMENSION = "gpu_count"` at every site that reads it, and stop
  writing it when a caller declares capacity explicitly. VM supplies `gpu_count`;
  API credits supplies `units`. Without this, the domain-neutral declaration contract
  below cannot be satisfied: an `api_credits`-only declaration acquires a manufactured
  GPU dimension on its way through `register_resource`.
- **BREAKING (wire):** require `pool_id` on capacity registration, rejected by
  validation when missing, and make `total_units` optional. Existing `NULL` pool ids
  are migrated to the default pool.
- Forbid moving a capacity resource between Resource Pools while it has live capacity
  obligations. A reservation's pool is resolved through the resource's *current*
  `pool_id`, so reassignment rewrites the authority under an existing reservation.
- **BREAKING (deployment/data):** make `Host` connection identity only — addressing,
  SSH credentials, Ansible alias, pool membership, enabled state. Retire
  `gpu_count`/`gpu_model` as capacity sources and retire `_project_host`'s
  host-derived capacity fallback. Derivation creates a capacity resource from every
  `Host` row carrying GPU data and no correlated declaration — once by migration for
  existing rows, and wherever INI host data is applied thereafter — so INI-seeded
  deployments keep their current published capacity across the upgrade without
  operator action. A derived declaration is admissible, so such a deployment also
  becomes able to reserve against it. A host with no declaration is no longer
  projected.
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
- Add operator-facing coverage: `docs/seller-quickstart.md`, the configuration
  reference, and Helm values, so registering capacity is a documented workflow.
  **Amended 2026-09-21:** no CLI. Site administrators configure through values files,
  configuration files, and the REST API.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `site-capacity`: capacity resources become an operator-administered authoritative
  declaration of multi-dimensional sellable capacity rather than a compatibility
  registration path; projected physical inventory must be internally consistent
  between `capacity` and `attributes`.
- `physical-provisioning`: host inventory is connection identity and MUST NOT be the
  authoritative source of sellable capacity dimensions; the compute provisioner
  imports capacity definitions at startup on the same digest-gated contract as pool
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
  (non-physical) capacity directly; the endpoint continues to serve them, subject
  to the `pool_id` requirement above.
- Do not deliver storefront wiring for selling an individual physical resource end
  to end. Derivation makes INI hosts reservable at the provisioning service; the
  storefront path is separate work.
- Do not preserve API-credits ledger data. The domain is not launched; its databases
  are recreated rather than migrated.
- Do not add a CLI.

## Impact

- **Affected code:** `kit/site/src/market_site/ledger.py` (every mirror-dimension
  site, `register_resource` and a new in-session variant, the drain rule, and the
  capacity-document reconciliation),
  `provisioning/compute/service/src/compute_provisioning_service/`
  (`app_runtime.py` startup steps, `config.py` path resolution, `settings.toml`,
  `services/capacity_inventory.py`, `db/models.py`, `db/migrations.py`,
  `services/definition_documents.py`, a capacity-definitions controller),
  `kit/site` (`router.py`, `http_models.py`) and `kit/site-client`,
  `domains/vms/provisioning/adapter` host service, `domains/apicredits` service
  composition and storefront seed registration, `kit/fulfillment` callers of the
  module-level matching helpers. **Amended 2026-09-21:** also a new
  `kit/site/src/market_site/capacity_definitions.py` (document shape, validation,
  planned reconciliation, wire models); `resource_feasibility_view`'s fact order and
  mirror-keyed unit fact; `compute_provisioning`'s re-exports and route contract; and
  `vm_provisioning_operator.ProvisioningClient` (async and sync).
- **Affected deployment:** a new `capacity_definitions_path` setting, set by Helm
  only from a non-empty `definitions.capacity` value, and `pool_definitions_path`
  newly settable the same way from `definitions.pools` so a capacity document's pools
  exist at first boot (both empty by default; no Compose wiring); an ordered
  compute migration that makes `capacity_buckets.total_units` nullable, backfills
  `NULL` pool ids, removes reserved keys from stored declaration attributes, and
  derives capacity resources, applied by the init container
  before the application serves requests, per `deployment-state`'s service-owned
  migration history requirement.
- **Affected data:** every existing `Host` row with GPU data gains a derived capacity
  resource. Rollback within the freeze window is a code rollback; the derived rows
  are additive and harmless to a rolled-back reader.
- **Affected tests:** provisioning unit and integration suites for startup import,
  derivation migration, and projection consistency; `kit/site` ledger and router
  suites; sync/async client parity for any new client method; the VM e2e scenarios
  that depend on projected capacity shape.
- **Wire compatibility (amended 2026-09-21):** `ResourceRegisterRequest.pool_id`
  becomes required and `total_units` optional; the projection's `attributes` lose
  `gpu_count` and take categorical fields from the declaration; hosts with no
  declaration leave the projection. None of these payloads is a versioned envelope,
  so compatibility is carried by distribution versions of `kit/site`,
  `kit/site-client`, and their consumers. **Amended 2026-09-21:** registration
  refuses attribute keys naming a declaration field (422); a new
  `POST /api/v1/capacity/definitions/import` with a validate-only mode; and
  `compute-provisioning` moves to 0.7.0 for its route contract.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the authority-boundaries table's physical
      resource row and the shared-vocabulary entry for Physical Resource, which
      currently do not distinguish connection identity from capacity declaration.
- [x] Existing subsystem specification — `openspec/specs/site-capacity/spec.md` and
      `openspec/specs/physical-provisioning/spec.md`.
- [ ] New subsystem specification — none.
- [ ] No permanent documentation change — not applicable.

### Knowledge to promote

- Capacity resources are the single authoritative declaration of sellable capacity;
  host rows are connection identity — `openspec/specs/physical-provisioning/spec.md`
  and the `ARCHITECTURE.md` authority-boundaries table.
- Projected inventory `attributes` must not contradict projected `capacity` —
  `openspec/specs/site-capacity/spec.md`, alongside the existing physical-inventory
  projection requirement.
- Why capacity declaration is a separate concern from host inventory, and why
  splitting dimensions across both was rejected — `openspec/specs/site-capacity/architecture.md`.

## Dependencies and Related Changes

- **Depends on `unify-host-identity`** (added 2026-09-21). Derivation and projection
  correlation use the declaration's first-class `host_id` that change introduces.
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
