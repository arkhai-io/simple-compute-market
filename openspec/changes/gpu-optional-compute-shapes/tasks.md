# Tasks

Planned against the design settled in `design.md` and advanced by
`reviews/10-design.triage.md`. Every implementation task answers to a decision D1–D12, a
delta requirement under `specs/`, or a repository obligation cited at the task:
`openspec/README.md#plan-closeout-requirements`, the task rules in `openspec/config.yaml`,
`docs/development/TESTING.md`'s level definitions, and
`docs/development/BUILD_AND_PACKAGING.md`.

Test levels follow `docs/development/TESTING.md`: unit; library integration (a kit's
service API against a real database); persistence integration (the provisioning service's
own migrations against file-backed SQLite, in its `tests/integration`, without the app);
application integration (the in-process app through its typed clients); and system (the
`e2e-tests` markers).

Order: sections 1–4, then 5–8, then the closeout, 9. Sections 1–3 deliver the shape
vocabulary, bare metal, and the registry (D1, D3, D7); section 4 the host retirement (D5);
sections 5–8 the VM path (D2, D6, D8–D10, D12). Section 2 and every VM section need
section 1's kit rule; section 8's scenario needs sections 3 and 5–7. Between section 4 and
section 5 the tree accepts GPU-less shapes the VM reconciler cannot yet publish, as
`design.md`'s cadence states; no lane states one until section 8. No dependency gates
implementation.

Permanent documentation — the specifications' companions, `ARCHITECTURE.md`,
`DEPLOYMENT_AND_CONFIG.md`, the quickstarts, the validation runbook, and the roadmap — is
written at closeout (9.9). Sections change only code, tests, and the example inventory that
ships beside the playbooks, which section 4's change makes wrong.

## 1. A required shape field is required when its family appears

Delivers the shape kit's family-conditional `required` and the compute schema that requires
no family while binding `gpu.count` and `gpu.model` together (D1; deltas
`market-composition` "Family-grouped capability shapes share one flattening contract" and
"The compute family shares one capability schema").

Files: `kit/capability-shape/src/market_capability_shape/__init__.py` and
`tests/unit/test_capability_shape.py`; `domains/compute/src/arkhai_compute/capability_schema.py`
and `domains/compute/tests/test_capability_schema.py`;
`kit/capability-admissibility/tests/unit/test_admissibility.py`.

- [ ] 1.1 In `shape_problems`, check a field marked `required` only when the shape names
  its family, and say so in `ShapeField`'s, `shape_problems`', and `flatten_shape`'s
  docstrings and the module docstring (D1). `unflatten_shape` inherits the rule through
  `shape_problems`. Unit (`test_capability_shape.py`): a shape omitting a family whose
  fields are required is accepted and flattens to nothing for it; a shape naming that
  family without one required field is refused naming `family.field`; `unflatten_shape`
  refuses the same; existing refusals (undefined field, wrong kind, structure) unchanged.
- [ ] 1.2 Rewrite the compute schema's comment ("Only ``gpu`` is required…") to state that
  no family is required and that `gpu.count` and `gpu.model` are required together (D1).
  Unit (`test_capability_schema.py`): replace `test_only_the_gpu_family_is_required` with
  the delta's four scenarios — `{cpu: {count: 8}, memory: {gib: 32}}` accepted and
  flattening to `vcpu_count`/`ram_gb` with no attribute; `{gpu: {model: H100}, cpu:
  {count: 8}}` refused naming `gpu.count`; `{gpu: {count: 2}}` refused naming
  `gpu.model`; the existing two-domain flattening unchanged.
- [ ] 1.3 Prove the admissibility kit keeps D1's refusals and admits GPU-less shapes, with
  no change to its code (D1 rationale). Unit (`test_admissibility.py`): a stated shape
  `{gpu: {count: {min: 2, max: 8}, model: H100}}` still has an unreadable base shape naming
  `gpu.count`; a stated `{cpu: {count: {offer: 8, max: 16}}, memory: {gib: 32}}` splits into
  a readable base shape and a policy whose `admissible_values("cpu.count", …)` answers 8
  through 16.
- [ ] 1.4 **Verification checkpoint.** Unit: 1.1–1.3. Run `make test` in
  `kit/capability-shape`, `kit/capability-admissibility`, and `domains/compute`, and
  `make check-comment-hygiene`. Bare-metal suites asserting that a declaration without a
  GPU count is unresolvable change in section 2, in the same session; no VM suite states a
  GPU-less shape.
  End-to-end: every compute lane flattens through the kit (`e2e_listing_shapes`,
  `e2e_bare_metal_publication`, `e2e_deal`), proving existing GPU shapes are unchanged;
  sections 2 and 8 add the GPU-less scenarios. No scenario is owed here.

## 2. Bare-metal machines without GPUs

Delivers bare-metal listings, derivation, and claims for machines that declare no GPUs, with
no migration of bare-metal state (D7; deltas `storefront-publication` "A bare-metal
listing's shape is derived from its declaration" and "A bare-metal listing sells one whole
unit"; delta `market-composition` "The compute family shares one capability schema").

Files: `domains/bare_metal/src/arkhai_bare_metal/{schema.py,shapes.py}`;
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/claims.py`; tests
`domains/bare_metal/tests/{test_schema.py,test_shapes.py,test_publication.py,test_storefront_publication.py}`,
`domains/bare_metal/storefront/tests/{test_claims.py,test_publication_cycle.py,test_fulfillment_service.py}`;
`e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_publication.py`.

- [ ] 2.1 Make `BareMetalListing.gpu_count` and `gpu_model` optional (default absent), drop
  `gpu_model` from the non-empty loop, and check D1's rule by building `shape` through the
  compute schema in the validator, so a listing naming one GPU field without the other, or
  no hardware at all, is refused by the shape kit (D7, D1). `claimed_attributes` returns
  only the schema attributes the listing states. The serializer omits an absent GPU field,
  so a published listing carries no GPU key (D6's serialization rule, which bare metal
  shares through its own model). Update `shapes.py`'s docstring ("a missing GPU count or
  model"). Unit (`test_schema.py`): a GPU-less listing validates, its `shape` is
  `{cpu: …, memory: …}`, its `claimed_attributes` is empty, and its JSON dump has no
  `gpu_count` or `gpu_model` key; the `missing` parametrization keeps `region` refused and
  refuses `gpu_count` alone and `gpu_model` alone.
- [ ] 2.2 Derivation follows the delta (D7). Unit (`test_shapes.py`): `{units: 1,
  vcpu_count: 64, ram_gb: 512}` with no attribute derives `{cpu: {count: 64}, memory:
  {gib: 512}}`; `{units: 1}` alone, `gpu_count: 0`, a GPU count without a model, and a model
  without a count stay unresolvable, each naming its reason. Unit (`test_publication.py`,
  `test_storefront_publication.py`): a GPU-less declaration yields a candidate whose payload
  carries no GPU key; a `{units: 1}`-only declaration is held and reported by name.
- [ ] 2.3 `whole_machine_claim` refuses a context with no `claimed_attributes` key, or one
  that is not a mapping, and accepts an empty mapping, returning one `units` and the offering
  mode with no attribute (D7; delta "A bare-metal listing sells one whole unit"). Unit
  (`test_claims.py`): both cases. Application integration
  (`test_fulfillment_service.py`, through the storefront's fake site): a backed GPU-less
  listing's accepted deal reserves its Physical Resource with a claim carrying no attribute,
  and the site admits it.
- [ ] 2.4 Application integration (`test_publication_cycle.py`): one publication cycle
  over a site projecting a GPU-less machine publishes it, and the registry body the cycle
  sends has no GPU key (D7, D11).
- [ ] 2.5 System: extend `test_bare_metal_publication.py` with a second whole-host
  declaration `{units: 1, vcpu_count: 64, ram_gb: 512}` and no GPU model, in the advertised
  pool; after one site-projection step and one publication cycle, a buyer query
  `vcpu_count>=64` through the registry's filter vocabulary finds it, `gpu_count>=1` does
  not, and its `listing_resource` carries no GPU key (D11).
- [ ] 2.6 **Verification checkpoint.** Unit 2.1–2.3; application integration 2.3–2.4. Run
  `make test` in `domains/bare_metal` and `domains/bare_metal/storefront`, `make
  test-e2e-unit`, and `make check-comment-hygiene`.
  End-to-end: `e2e_bare_metal_publication` (2.5) proves the GPU-less machine's publication
  and discovery; `e2e_bare_metal_mock_deal` and `e2e_bare_metal_introduction` prove GPU
  machines are unchanged. The GPU-less claim is proven at application integration (2.3); no
  further scenario is owed.

## 3. The compute registry's listing schema requires only `region`

Delivers filter spec version 7 with `listing_resource.required: [region]` and unchanged,
fail-closed GPU filters (D3; delta `registry-discovery` "The compute listing shape does not
require GPU fields").

Files: `core/registry/filter-spec.yaml`; tests
`core/registry/tests/unit/test_filter_spec.py`,
`core/registry/tests/integration/{test_validate_publish.py,test_filter_spec.py}`.

- [ ] 3.1 Set `version: 7`, keep `schema: {id: compute.market, version: 2}`, and make
  `listing_resource.required` `[region]`, with a `v7` comment beside the existing version
  notes saying a listing may omit `gpu_model` and `gpu_count` (D3). Unit
  (`test_filter_spec.py`): the loaded spec reports version 7, the unchanged schema identity,
  and `required == ["region"]`.
- [ ] 3.2 Application integration (`test_validate_publish.py`): a dry run of a compute
  listing carrying `region`, `vcpu_count`, and `ram_gb` and no GPU field is valid; one
  missing `region` is not (delta scenario "A listing without GPUs is validated").
- [ ] 3.3 Application integration (`test_filter_spec.py`, the listings query): with a
  GPU-less and a GPU listing published, `gpu_count>=1` and `gpu_model=H100` return only the
  GPU listing, and `vcpu_count>=16` returns both where both state sixteen vCPUs (delta
  scenarios "A buyer bounds a GPU field" and "A buyer bounds only CPU and memory").
- [ ] 3.4 **Verification checkpoint.** Unit 3.1; application integration 3.2–3.3. Run
  `make test` in `core/registry`, `make -C helm test-render` (it reads the spec's identity,
  which is unchanged), and `make check-comment-hygiene`.
  End-to-end: `e2e_deal` and `e2e_deal_buyer_cli` dry-run their listings through
  `validate-publish` against version 7; section 8's scenario publishes and filters a
  GPU-less VM listing. No scenario is owed here.

## 4. The host GPU fields are retired

Delivers host records with no hardware description, ignored retired inputs, and the
fail-forward column drop (D5; deltas `physical-provisioning` "A host record describes no
hardware", "Host writes declare no capacity", and "Host inventory is connection identity").

Files: `provisioning/compute/contracts/src/compute_provisioning_contracts/hosts.py`;
`provisioning/compute/src/compute_provisioning/hosts/{db.py,service.py}`;
`provisioning/compute/ansible/src/compute_provisioning_ansible/inventory.py`;
`provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`;
`domains/vms/provisioning/iac/ansible/inventory/provisioning-hosts.example`;
`e2e-tests/tests/e2e/roles/scenarios/vms/host_registry.py`; tests
`provisioning/compute/contracts/tests/unit/test_contracts.py`,
`provisioning/compute/tests/integration/test_host_authority.py`,
`provisioning/compute/tests/unit/test_host_route_service.py`,
`provisioning/compute/ansible/tests/unit/test_inventory.py`,
`provisioning/compute/service/tests/integration/{test_hosts_api.py,test_host_writes_declare_no_capacity_api.py}`,
a new `provisioning/compute/service/tests/integration/test_host_gpu_columns_drop_migration.py`,
and every fixture asserting a host's GPU field.

- [ ] 4.1 Remove `gpu_count` and `gpu_model` from `HostCreate`, `HostUpdate`, and
  `HostResponse`, leaving the models' handling of undefined fields as it is, so a request
  carrying them is accepted with them ignored (D5 "API"). Unit (`test_contracts.py`): each
  model parses a body carrying both fields and exposes neither; `HostResponse` serializes
  no GPU key.
- [ ] 4.2 Remove both columns from the `Host` model and both fields from `InventoryHost`,
  its serialization, and the host authority's create, update, and inventory apply (D5).
  Library integration (`test_host_authority.py`) and unit (`test_host_route_service.py`):
  create, update, and apply record and return no GPU field. Application integration
  (`test_hosts_api.py`): `POST /api/v1/hosts/` with `gpu_count` and `gpu_model` creates the
  host, and neither the response nor a read carries a GPU field (delta scenario "A host is
  created with GPU fields"); `test_host_writes_declare_no_capacity_api.py`'s INI and API
  cases drop their GPU inputs and still declare nothing (deltas "Host writes declare no
  capacity", scenarios "Deployment configured only through host inventory" and "A host is
  created through the individual host API").
- [ ] 4.3 Stop reading `gpus=` and `gpu_model=` in `_parse_entries`: remove the mapping
  lines from its docstring, the malformed-`gpus=` comment, and the two dict keys, so they
  fall under "All other variables → ignored" with no warning (D5 "INI"). Unit
  (`test_inventory.py`): a line carrying `gpus=8 gpu_model=H200` parses to the same
  `InventoryHost` as one without, and a malformed `gpus=x` no longer matters. Update the
  example inventory's `gpus=` lines and comments to describe only connection fields.
  Application integration (`test_host_writes_declare_no_capacity_api.py`): an INI import
  with those variables registers the host and records nothing for them (delta scenario "An
  inventory line carries GPU variables").
- [ ] 4.4 Append a migration after `20261027_001` that rebuilds `hosts` from the model
  without the two columns, following `_migrate_hosts_pool_optional` (`20261023_002`), a
  no-op on a table already in that shape, and logging nothing per host (D5 "Storage"). Its
  docstring states the upgrade is fail-forward: an older provisioner cannot read the
  rebuilt table, so a rollback past it restores the pre-upgrade backup (D5 "Upgrade").
  Persistence integration (`test_host_gpu_columns_drop_migration.py`): hosts carrying GPU
  values keep every other column — identity, connection with its protected key's
  ciphertext, pool, enabled, timestamps — and the table has no GPU column; a fresh database
  and a repeated run are no-ops; `foreign_key_check` passes (delta scenarios "An existing
  database is upgraded", "Host record carries a legacy capacity column", "Operator
  declaration and legacy host value disagree").
- [ ] 4.5 The e2e host harness compares an existing host's pool alone when deciding to
  update it, and passes no GPU field (D5 "The one non-production reader"). Unit: `make
  test-e2e-unit` passes.
- [ ] 4.6 Remove the GPU fields from every test fixture and assertion that reads a host's
  GPU field across `provisioning/compute` and its service; fixtures passing GPU values only
  as declaration capacity are unaffected. A repository search for `HostCreate(`/`HostUpdate(`
  with a GPU argument, and for `.gpu_count`/`.gpu_model` on a host, finds none (D5).
- [ ] 4.7 **Verification checkpoint.** Unit 4.1, 4.3, 4.5; library integration 4.2;
  application integration 4.2–4.3; persistence integration 4.4. Run `make test` in
  `provisioning/compute/contracts`, `provisioning/compute`, `provisioning/compute/ansible`,
  and `provisioning/compute/service`, `make test-e2e-unit`, `make check-packaging`, and
  `make check-comment-hygiene`.
  End-to-end: every VM and bare-metal scenario registers hosts through the harness and the
  provisioning service migrates its database through the new step, so the lanes prove
  nothing read the retired fields. No scenario is owed: the field handling is a model and
  API behaviour application integration owns.

## 5. VM listing models, dispatch, and serialization

Delivers VM listing resources without GPU fields: optional fields with D1's rule, one
dispatch rule at every seam, and a serializer that omits absent GPU fields (D6, D1).

Files: `domains/vms/domain/src/arkhai_vms/schema.py`;
`domains/vms/listings/src/arkhai_vms_listings/{models.py,resources.py,pricing.py,buyer_cli.py}`;
tests `domains/vms/domain/tests/test_schema.py`,
`domains/vms/storefront/tests/unit/{test_resources.py,test_listing_model_capacity_identity.py}`,
`domains/vms/storefront/tests/integration/test_listings_api.py`.

- [ ] 5.1 Make `ComputeResource.gpu_count` and `gpu_model` optional, and replace
  `VmListing`'s presence checks with flattening the resource's quantity and attribute fields
  through the compute schema, so the shape kit refuses one GPU field without the other and a
  mapping with no quantity (D6, D1). Unit (`test_schema.py`): a GPU-less listing validates;
  `gpu_model` alone, `gpu_count` alone, and no quantity are refused naming the shape kit's
  reason.
- [ ] 5.2 One dispatch rule at every seam (D6 "Dispatch"): `Resource.parse_from_dict`
  (`models.py`), `resource_is_compute` (`pricing.py`), the adapter registry's
  `parse_resource_from_dict` and the compute adapter's discriminator (`resources.py`), and
  `format_resource` (`buyer_cli.py`). An explicit `resource_type` selects its adapter;
  otherwise a `token` key is a `TokenResource`, and any other mapping a `ComputeResource`.
  Unit (`test_resources.py`): a GPU-less compute mapping, a stored GPU listing, a token
  mapping, and an explicit `resource_type` each dispatch as the rule says; a mapping with no
  quantity is refused by compute validation; `resource_is_compute` and `format_resource`
  agree with the parser.
- [ ] 5.3 The `ComputeResource` serializer omits an absent `gpu_count` and `gpu_model` as it
  omits `asking_rate` (D6 "Serialization"). Unit (`test_listing_model_capacity_identity.py`
  or `test_resources.py`): a GPU-less resource's `model_dump(mode="json")` has no GPU key; a
  stored listing whose resource holds `gpu_model: null` and one missing the key compare equal
  under `compare_listing`, so no stored listing churns.
- [ ] 5.4 Application integration (`test_listings_api.py`, through the storefront's typed
  client): the publication path's `parse_resource_from_dict` accepts a GPU-less payload,
  still parses a stored GPU listing, and refuses a compute mapping with no quantity (D6,
  D11).
- [ ] 5.5 **Verification checkpoint.** Unit 5.1–5.3; application integration 5.4. Run
  `make test` in `domains/vms/domain` and `domains/vms/storefront` (`arkhai_vms_listings`
  has no suite of its own; its behaviour suites live in the VM storefront's unit suite),
  and `make check-comment-hygiene`.
  End-to-end: every VM lane scenario publishes GPU listings through the changed dispatch
  and serializer (`e2e_deal`, `e2e_listing_shapes`, `e2e_compute_dynamic_listings`); section
  8 adds the GPU-less one.

## 6. VM publication of GPU-less shapes

Delivers GPU-less members, availability judged per shape, pricing grouped by an optional
model, and the pool report replacing the per-member omission report (D2, D8, D12; delta
`storefront-publication` "A listing's published shape comes from its source declaration"
and "Every VM listing is a listing shape").

Files: `domains/vms/listings/src/arkhai_vms_listings/{reconciler.py,listing_shapes.py}`;
`domains/vms/domain/src/arkhai_vms/shape_generation.py` (docstring);
`domains/vms/storefront/src/market_storefront/services/{publication_loop.py,shape_feasibility.py}`;
tests `domains/vms/domain/tests/test_shape_generation.py`,
`domains/vms/storefront/tests/unit/{test_reconciler.py,test_listing_shape_resolution.py}`,
`domains/vms/storefront/tests/_reconciler_cases.py`,
`domains/vms/storefront/tests/integration/{test_reconciler_derivation.py,test_publication_loop.py,test_shape_feasibility.py}`.

- [ ] 6.1 `ResolvedShape.gpu_count` and `gpu_model` return `None` for a shape stating no
  GPUs, and every reader handles `None` (D8). Unit (`test_listing_shape_resolution.py`): a
  stated GPU-less shape resolves with both `None`; a GPU shape is unchanged.
- [ ] 6.2 A member's GPU count is no precondition for membership (D8):
  `_projected_resource_usage` no longer returns an absent-count outcome for a member without
  `gpu_count`; GPU usage and fungible GPU availability apply only to shapes naming GPUs, and
  a GPU-less shape's availability is judged on the dimensions it declares through the site
  predicate (`shape_feasibility.py`). A malformed `gpu_count` still holds the pool; a zero
  yields no default shape and no report. Unit (`test_reconciler.py`, `_reconciler_cases.py`):
  a GPU-less member is feasible for a stated GPU-less shape; a GPU host's spare vCPU and
  memory are feasible for it (delta scenario "A GPU host's spare capacity sells as a VM
  without GPUs"); a backed GPU-less shape whose member's available memory is below it is not
  published; a malformed count holds.
- [ ] 6.3 Group pricing and family rates by an optional GPU model, so a GPU-less shape
  resolves flat rates or cpu, memory, and storage family rates, and a pool whose only rates
  are per GPU model leaves it with no settlement option, refused and reported as
  `no_settlement_option` (D8). Order the availability reopen by GPU count with an absent
  count as zero, then listing id, keeping it deterministic. Unit (`test_reconciler.py`): a
  mixed pool's GPU and GPU-less shapes each resolve their rates without error; a
  per-model-only pool's GPU-less shape is refused as `no_settlement_option`; reopen ordering
  of a GPU-less listing does not fail.
- [ ] 6.4 Replace the per-member `member_gpu_count_missing` report with one pool report when
  a pool states no listing shapes and no enabled member declares a positive GPU count,
  naming the site and pool and saying the VM default generates GPU shapes only and the pool
  must state `listing_shapes`; it is recorded through the storefront's derivation log and
  served in system status as `publication_derivation` (D2, D12). The default generator's
  docstring states that a member declaring no GPUs yields no default shape. Unit
  (`test_shape_generation.py`, `test_reconciler.py`): a GPU member beside a GPU-less one
  yields the GPU defaults and no report (delta scenario "A declaration omits the enumerated
  quantity"); a pool of GPU-less members with no stated shapes yields nothing and one pool
  report (delta "A pool whose members declare no GPUs states no shapes"); a zero count
  yields nothing and no report.
- [ ] 6.5 Application integration (`test_publication_loop.py`, through the storefront's
  typed client and fake site): a pool hint stating `{cpu: {count: 16}, memory: {gib: 64}}`
  publishes one listing whose exact registry body carries `vcpu_count: 16` and `ram_gb: 64`
  and no GPU key, on first publication and on a refresh (D11; delta "A pool states a shape
  with no GPUs"); a GPU-less pool with no stated shapes publishes nothing and system status
  reports it (D2, D12). Library integration (`test_reconciler_derivation.py`,
  `test_shape_feasibility.py`): mixed and GPU-less pools derive as 6.2–6.4 say.
- [ ] 6.6 **Verification checkpoint.** Unit 6.1–6.4; library integration and application
  integration 6.5. Run `make test` in `domains/vms/domain` and `domains/vms/storefront`, and
  `make check-comment-hygiene`.
  End-to-end: `e2e_listing_shapes`, `e2e_compute_dynamic_listings`, and `e2e_deal` prove GPU
  publication unchanged; section 8 proves GPU-less publication in the running stack.

## 7. Claims, recheck, opening, delivery facts, and the admin reserve without GPUs

Delivers the deal path for a GPU-less VM listing, from the opening through fulfillment, with
admission and fulfillment unchanged (D9, D10, D6).

Files: `domains/vms/listings/src/arkhai_vms_listings/pricing.py` (`extract_compute_from_order`);
`domains/vms/storefront/src/market_storefront/services/{vm_job_spec_service.py,listing_source_check.py}`;
`domains/vms/storefront/src/market_storefront/negotiation_runtime.py`;
`domains/vms/settlement/src/arkhai_vms_settlement/compute_lease.py`;
`domains/vms/storefront/src/market_storefront/controllers/admin_controller.py`;
`domains/vms/storefront/src/market_storefront/models/capacity_admin_models.py`;
`core/storefront-client/src/storefront_client/models.py`; tests
`domains/vms/storefront/tests/unit/{test_vm_job_spec_service.py,test_listing_source_check.py,test_vm_evidence_validation.py}`,
`domains/vms/storefront/tests/integration/{test_admin_api.py,test_negotiate_controller.py,test_payment_settlement.py}`,
`domains/vms/provisioning/adapter/tests/unit/test_vm_fulfillment_plan.py`.

- [ ] 7.1 `extract_compute_from_order` accepts a GPU-less compute resource through D6's
  `resource_is_compute`, so claim building, the seller's recheck, and the negotiation
  opening reach a GPU-less listing (D9). Unit (`test_vm_job_spec_service.py`): the claim
  for a GPU-less listing carries `resource_type: compute.gpu`, `offering_mode: vm`, its
  pool, and `dimensions` with its vCPU and memory, and no `gpu_model` or `gpu_count` (D4,
  D9). Unit (`test_listing_source_check.py`): a GPU-less listing whose source still serves
  its shape is confirmed, and one whose member shrank below it is refused as a declared
  mismatch.
- [ ] 7.2 The Alkahest lease terms omit each GPU key the listing does not state (D9). Unit
  (`test_vm_evidence_validation.py` or a new `test_compute_lease.py` in the VM storefront's
  unit suite): `encode_compute_lease` for a GPU-less resource yields JSON with no
  `gpu_model` or `gpu_count` key and every other key unchanged; a GPU resource's bytes are
  unchanged.
- [ ] 7.3 The admin reserve response's `gpu_count` is optional and absent for a GPU-less
  reservation, with the `or 1` fallback removed (`admin_controller.py`,
  `capacity_admin_models.py`), and the storefront client model's `gpu_count` default of `0`
  becomes optional (D9). Application integration (`test_admin_api.py`, through the typed
  client): reserving a GPU-less listing returns no `gpu_count`; a GPU listing's reservation
  returns its count as before.
- [ ] 7.4 Admission and fulfillment are unchanged (D10). Unit
  (`test_vm_fulfillment_plan.py`): a committed reservation with no `gpu_count` dimension
  yields no `vm_gpu_count` or `gpu_provisioned` variable. Application integration
  (`test_negotiate_controller.py` and `test_payment_settlement.py`): a GPU-less listing opens
  a negotiation, and its settled deal's reservation, admitted on a GPU host's fake-site
  member, holds only the listing's vCPU and memory.
- [ ] 7.5 **Verification checkpoint.** Unit 7.1–7.2, 7.4; application integration 7.3–7.4.
  Run `make test` in `domains/vms/storefront` (which carries the listings and settlement
  packages' behaviour suites), `domains/vms/provisioning/adapter`, and
  `core/storefront-client`, `make check-packaging`, and `make check-comment-hygiene`.
  End-to-end: section 8's scenario settles a GPU-less deal through mock provisioning.

## 8. A GPU-less VM deal end to end

Delivers the VM lane's proof that a GPU-less stated shape is published, discovered, excluded
from GPU queries, and settled through mock provisioning (D11; deltas `storefront-publication`
"A pool states a shape with no GPUs" and `registry-discovery` "The compute listing shape does
not require GPU fields").

Files: `e2e-tests/tests/e2e/roles/scenarios/vms/test_listing_shapes.py`, and
`host_registry.py` for the scenario's declaration.

- [ ] 8.1 Extend `test_listing_shapes.py` with a step after its existing ones: the pool's
  hint states one GPU-less shape `{cpu: {count: 8}, memory: {gib: 32}}` against a member
  declaring vCPU and memory and no GPU; one publication cycle publishes it with no GPU key in
  the storefront's and the registry's listing; a buyer `vcpu_count>=8` query finds it and a
  `gpu_count>=1` query does not; `market buy`, discovering it through the vCPU query,
  negotiates, escrows, settles, and provisions it to ready through mock provisioning, and the
  site's reservation holds the shape's vCPU and memory and no GPU. Update the module
  docstring's numbered steps.
- [ ] 8.2 **Verification checkpoint.** Run `make test-e2e-unit` and `make
  check-comment-hygiene`; the scenario itself runs in the VM lane at validation.
  End-to-end: `e2e_listing_shapes` (8.1).
  Owed by validation: none beyond the pipeline's VM lane.

## 9. Closeout

Confirm and promote the verified design, then archive last (D1–D12 and every delta
requirement). The eleven parts follow `openspec/README.md#plan-closeout-requirements` in
order. Closeout changes no code: a part needing a code, lock, or test change returns the
change to implementation.

- [ ] 9.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene` and read every
  comment and docstring sections 1–8 added or rewrote — the shape kit's `required`
  docstrings, the compute schema comment, the bare-metal model and `shapes.py` docstrings,
  the INI parser's docstring, the column-drop migration's docstring, the default generator's
  docstring, the filter spec's `v7` comment — for current-system rationale with no change,
  review, or migration narration. A needed correction returns to implementation.
- [ ] 9.2 **Import placement — confirm.** Check that every import sections 1–8 added or
  touched is at module level unless a verified cycle or a recorded lazy-load reason keeps it
  local. A needed move returns to implementation.
- [ ] 9.3 **Documentation compliance.** Check D1–D12 and review 10's four findings against
  `openspec/README.md`'s placement rules, the promotion record below, and the code:
  normative behaviour in specs through the deltas, rationale in the companions, repository
  principles in `ARCHITECTURE.md`, operator behaviour in `DEPLOYMENT_AND_CONFIG.md` and the
  quickstarts, direction in the roadmap. Record a disposition for every decision.
- [ ] 9.4 **Narrative compression.** Compress section notes to final behaviour, validation
  evidence, deferred work, and destinations, moving any durable rationale into `design.md`
  first.
- [ ] 9.5 **Roadmap currency.** In `docs/development/ROADMAP.md`: Goal 1's current-state
  paragraph beginning "Sellable capacity is declared in the site authority" drops "a host's
  GPU count is descriptive" and states that a host record describes no hardware; Goal 2's
  current-state paragraph beginning "Publication carries the shape it is given" states that a
  shape may state no GPUs, that a stated GPU-less shape publishes, filters, and settles, and
  that a pool with no stated shape and no GPUs publishes nothing and is reported. This change
  owns no open-gap row. Add three unowned rows to Goal 2's table: the resource type as the
  compute-shape category (`compute.cpu`, `compute.db`) orthogonal to the offering mode, with
  a scheduling cursor per category; bare metal's `compute.bare-metal` restating its offering
  mode, on which its scheduling request depends; and a VM listing resource publishing its
  other absent optional fields as `null` where the specification says they are not
  published.
- [ ] 9.6 **Campaign index currency.** In `openspec/changes/README.md`, set this change's
  row (Goal 2) to `in closeout` with notes naming the validation and destinations, and add an
  "Unowned work found by `gpu-optional-compute-shapes`" table under the Goal 2 campaign with
  the registry's `exists:false` defect: a listing the path resolves nothing for is decided by
  `on_missing` before the `exists` test, so `exists:false` matches nothing. The graph lines
  in both campaigns stay. Run `make check-change-index`.
- [ ] 9.7 **Packaging.** Confirm `make check-packaging` and `make check-architecture-change
  CHANGE=gpu-optional-compute-shapes` pass against the last implementation commit; the change
  plans no `.agents/`, `.claude/`, or `.codex/` edit, so record that `make
  check-agent-skills` is not owed, or run it if one was touched.
- [ ] 9.8 **End-to-end pipeline.** Confirm the latest validation record covers the last
  implementation commit with the three lanes passing, and record its run and the scenarios
  that exercise this change: `e2e_listing_shapes` (the GPU-less VM deal, section 8),
  `e2e_bare_metal_publication` (the GPU-less machine, section 2), and every lane's host
  registration and provisioning migration (section 4). An unrelated blocker names its cause
  and owner, and leaves what it gates unrun.
- [ ] 9.9 **Promotion.** Write every destination in the promotion record below, and
  hand-edit each touched spec's Evidence section where its named tests moved or were added
  (`physical-provisioning`'s host-write bullet names `gpus=`). The archive in 9.11 merges the
  deltas. `openspec/specs/README.md` needs no change: no capability or companion is added.
  Complete the record's third column.
- [ ] 9.10 **Documentation citations.** Run `make check-doc-citations
  CHANGE=gpu-optional-compute-shapes` and resolve every match; then run pinned `npx --yes
  @fission-ai/openspec@1.14.0 validate gpu-optional-compute-shapes --strict`.
- [ ] 9.11 **Archival — last.** Run pinned `npx --yes @fission-ai/openspec@1.14.0 archive
  gpu-optional-compute-shapes -y` without `--skip-specs`, merging the deltas into
  `market-composition`, `storefront-publication`, `registry-discovery`,
  `physical-provisioning`, and `site-capacity` once; read each merged requirement in its
  spec's diff; point this change's index row at the archive with status `in closeout`; run
  `make check-change` on the archived change.

**Closeout verification:** the eleven recorded outcomes, valid synchronized specs, resolvable
citations, and a current index.

## Decision-to-section map

| Decision / requirement | Implementation | Promotion |
|---|---|---|
| D1 family-conditional `required`; `market-composition` "Family-grouped capability shapes…", "The compute family shares one capability schema" | 1, 2.1, 5.1 | 9.9 |
| D2 GPU-only default, pool report; `storefront-publication` "A listing's published shape comes from its source declaration", "Every VM listing is a listing shape" | 6.4, 6.5 | 9.9 |
| D3 filter spec version 7; `registry-discovery` "The compute listing shape does not require GPU fields" | 3, 8.1 | 9.9 |
| D3 the overstated publish requirement (review 10 F4) | none: `store-registry-listings-as-published` reconciles it | 9.3 records the disposition |
| D4 `compute.gpu` for every VM declaration; `site-capacity` "Resource-pool projection metadata" | 7.1, 7.4 (no code change) | 9.5, 9.9 |
| D5 host fields retired, fail-forward drop; `physical-provisioning` "A host record describes no hardware", "Host writes declare no capacity", "Host inventory is connection identity" | 4 | 9.9 |
| D6 VM models, dispatch, serialization (review 10 F1, F2) | 5, 6.5 | 9.5 (null gap), 9.9 |
| D7 bare metal without GPUs; `storefront-publication` "A bare-metal listing's shape is derived…", "A bare-metal listing sells one whole unit" | 2 | 9.9 |
| D8 VM publication of GPU-less shapes | 6.1–6.3, 6.5 | 9.9 |
| D9 claim, recheck, opening, delivery facts, admin reserve | 7.1–7.3 | none: implementation detail under existing requirements |
| D10 admission, scheduling, fulfillment unchanged | 7.4 | none |
| D11 validation levels | every section's checkpoint; 2.5, 8.1 | 9.8 |
| D12 the storefront report | 6.4, 6.5 | 9.6 (existing unowned item stands) |
| Resource-type direction and bare-metal kind debt (D4) | none: direction | 9.5 |
| Registry `exists:false` defect (D3) | none | 9.6 |

## Design promotion record

| Accepted knowledge | Permanent destination | Written |
|---|---|---|
| D1 a required field is required when its family appears; the compute schema requires no family and binds GPU count and model | `openspec/specs/market-composition/spec.md` — the two requirements, via archive; `openspec/specs/market-composition/architecture.md` — "The compute family vocabulary", a paragraph after the one on `unflatten_shape` | |
| D2 the VM default stays GPU-only; GPU-less members are members; a pool with no shapes and no GPUs is reported once | `openspec/specs/storefront-publication/spec.md` — the two requirements, via archive; `openspec/specs/storefront-publication/architecture.md` — "Listing shapes and the storefront's authority", the paragraph beginning "Shapes are stated or generated"; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Definition documents", the sentence beginning "A pool that states no shapes publishes its domain's default shapes", and "Storefront listing shapes and pool overrides" | |
| A pool may create no listings, provided its operator can easily discover why | `docs/development/ARCHITECTURE.md` — "Holding or closing a listing the storefront cannot fully derive", a closing paragraph | |
| D4 a GPU machine's spare server resources may sell as VMs: the mechanisms are neutral and nothing forbids it | `openspec/specs/storefront-publication/architecture.md` — "Listing shapes and the storefront's authority", after the paragraph on feasibility | |
| D4 the resource type is the category a claim matches by equality, `compute.gpu` for every VM declaration | `openspec/specs/site-capacity/spec.md` — "Resource-pool projection metadata", via archive | |
| D6 a VM listing resource carries no GPU key when its shape states no GPUs; one dispatch rule decides a resource payload's kind | `openspec/specs/storefront-publication/architecture.md` — "Listing shapes and the storefront's authority", after the paragraph on a published dimension being a commitment | |
| D7 bare-metal machines without GPUs; claims with no attributes | `openspec/specs/storefront-publication/spec.md` — the two bare-metal requirements, via archive; `openspec/specs/storefront-publication/architecture.md` — "Bare-metal listing shapes", the paragraphs beginning "A bare-metal seller sells one whole machine" and "The commitment differs from VM's"; `docs/bare-metal-seller-quickstart.md` — "Start and inspect", the paragraph saying `gpu_count` and `gpu_model` are required | |
| D3 the compute listing schema requires only `region`; GPU filters exclude GPU-less listings | `openspec/specs/registry-discovery/spec.md` — the added requirement, via archive | |
| D5 a host record describes no hardware; retired fields and INI variables are ignored | `openspec/specs/physical-provisioning/spec.md` — the three requirements, via archive, and its Evidence section; `openspec/specs/site-capacity/architecture.md` — "Declared capacity and connection identity", the paragraph beginning "The alternatives each left capacity"; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Definition documents", the sentence beginning "`gpus=` and `gpu_model=` are descriptive"; `docs/seller-quickstart.md` — "6. Live KVM provisioning", step 3's inventory paragraph; `docs/development/VALIDATION_RUNBOOK.md` — the host registration body and inventory line that carry GPU fields | |
| D5 the host column drop is fail-forward, its rollback restores the pre-upgrade backup, and why the expand/contract rule does not govern it | `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Migrations at startup", beside the VM storefront's fail-forward upgrade | |
| The resource type as the compute-shape category; bare metal's `compute.bare-metal`; null-published absent fields | `docs/development/ROADMAP.md` — Goal 2's open-gap table, as unowned rows | |
| The registry's `exists:false` cannot express absence | `openspec/changes/README.md` — "Unowned work found by `gpu-optional-compute-shapes`" under the Goal 2 campaign | |
