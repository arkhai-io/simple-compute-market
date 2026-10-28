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

- [x] 1.1 In `shape_problems`, check a field marked `required` only when the shape names
  its family, and say so in `ShapeField`'s, `shape_problems`', and `flatten_shape`'s
  docstrings and the module docstring (D1). `unflatten_shape` inherits the rule through
  `shape_problems`. Unit (`test_capability_shape.py`): a shape omitting a family whose
  fields are required is accepted and flattens to nothing for it; a shape naming that
  family without one required field is refused naming `family.field`; `unflatten_shape`
  refuses the same; existing refusals (undefined field, wrong kind, structure) unchanged.
  *Done.* Unit, `kit/capability-shape` `make test`: 42 passed. New cases: a family whose
  fields are required omitted (accepted, flattens to nothing for it); a named family
  missing one required field beside another family (refused naming it); `unflatten_shape`
  refusing a named family missing a required field, accepting flat values naming no
  required family, and refusing empty flat values as an empty shape. Existing refusals
  unchanged.
- [x] 1.2 Rewrite the compute schema's comment ("Only ``gpu`` is required…") to state that
  no family is required and that `gpu.count` and `gpu.model` are required together (D1).
  Unit (`test_capability_schema.py`): replace `test_only_the_gpu_family_is_required` with
  the delta's four scenarios — `{cpu: {count: 8}, memory: {gib: 32}}` accepted and
  flattening to `vcpu_count`/`ram_gb` with no attribute; `{gpu: {model: H100}, cpu:
  {count: 8}}` refused naming `gpu.count`; `{gpu: {count: 2}}` refused naming
  `gpu.model`; the existing two-domain flattening unchanged.
  *Done.* Unit, `domains/compute` `make test`: 7 passed; the two-domain flattening is the
  existing round-trip test. Outside the plan's file list: the VM domain's
  `test_compute_requirements.py` carried a test of the same name, now false, renamed
  `test_gpu_count_and_model_are_the_only_required_fields` (assertion unchanged).
- [x] 1.3 Prove the admissibility kit keeps D1's refusals and admits GPU-less shapes, with
  no change to its code (D1 rationale). Unit (`test_admissibility.py`): a stated shape
  `{gpu: {count: {min: 2, max: 8}, model: H100}}` still has an unreadable base shape naming
  `gpu.count`; a stated `{cpu: {count: {offer: 8, max: 16}}, memory: {gib: 32}}` splits into
  a readable base shape and a policy whose `admissible_values("cpu.count", …)` answers 8
  through 16.
  *Done, with two corrections.* Unit, `kit/capability-admissibility` `make test`: 111
  passed. The kit's suite names no compute vocabulary and the kit imports only the shape
  kit, so the cases use its local schema, where `widget` (count and colour both required)
  stands for `gpu`. The first case is the existing
  `test_a_constraint_removing_a_required_field_is_a_base_shape_problem`, which still
  refuses `{widget: {count: {min: 2}, colour: red}}` as a malformed base shape; no new test
  was added for it. The second is new: `{space: {units: {offer: 8, min: 8, max: 16}},
  power: {watts: 32}}` splits into a readable base shape and answers 8 through 16. The
  plan's `{offer: 8, max: 16}` answers 1 through 16: an offer sets no minimum.
- [x] 1.4 **Verification checkpoint.** Unit: 1.1–1.3. Run `make test` in
  `kit/capability-shape`, `kit/capability-admissibility`, and `domains/compute`, and
  `make check-comment-hygiene`. Bare-metal suites asserting that a declaration without a
  GPU count is unresolvable change in section 2, in the same session; no VM suite states a
  GPU-less shape.
  End-to-end: every compute lane flattens through the kit (`e2e_listing_shapes`,
  `e2e_bare_metal_publication`, `e2e_deal`), proving existing GPU shapes are unchanged;
  sections 2 and 8 add the GPU-less scenarios. No scenario is owed here.
  *Done.* The three suites pass as above; `make check-comment-hygiene` and `make
  check-change` pass. Root `make test` passed (exit 0) over the tree holding sections 1–3
  together, after `make dist`; no VM, pool, or override suite asserted that a shape naming
  no `gpu` family is refused. End-to-end scenarios confirmed as planned:
  `e2e_listing_shapes`, `e2e_bare_metal_publication`, and `e2e_deal` exercise the kit with
  GPU shapes; none states a GPU-less shape for this section.

  *Handoff.* Between sections 1 and 5 the shape kit accepts a VM pool hint or override
  stating a GPU-less shape, which the VM reconciler cannot yet publish (as `design.md`'s
  cadence states). A dependent's tests see the new rule only once its wheel is rebuilt
  (`make dist`, or the kit's own `make build`); a reinit alone installs the stale wheel.

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

- [x] 2.1 Make `BareMetalListing.gpu_count` and `gpu_model` optional (default absent), drop
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
  *Done.* The serializer is a wrap `model_serializer` dropping only a `None` GPU field, so
  both `model_dump()` and `model_dump(mode="json")` omit it, including the negotiation
  path's dump that does not pass `exclude_none`; other absent optional fields keep
  serializing as `null` there (D6's recorded gap). `shape` builds its attributes from
  `claimed_attributes`. Unit, `domains/bare_metal` `make test`: 194 passed — the GPU-less
  listing (shape, empty claimed attributes, no GPU key in either dump, round trip), a
  listing with no hardware refused naming the empty shape, and the parametrization naming
  `region`, `gpu.count`, and `gpu.model`: the shape kit names the family path, not the flat
  field.
- [x] 2.2 Derivation follows the delta (D7). Unit (`test_shapes.py`): `{units: 1,
  vcpu_count: 64, ram_gb: 512}` with no attribute derives `{cpu: {count: 64}, memory:
  {gib: 512}}`; `{units: 1}` alone, `gpu_count: 0`, a GPU count without a model, and a model
  without a count stay unresolvable, each naming its reason. Unit (`test_publication.py`,
  `test_storefront_publication.py`): a GPU-less declaration yields a candidate whose payload
  carries no GPU key; a `{units: 1}`-only declaration is held and reported by name.
  *Done.* Unit, in the same 194: `test_shapes.py` for each case;
  `test_publication.py` derives a GPU-less listing from a projected resource and dumps no
  GPU key; `test_storefront_publication.py` classifies a GPU-less machine as a candidate
  whose `listing_resource` has no GPU key and whose digest is the GPU-less shape's, and
  holds `{units: 1}` alone and `gpu_count: 0` naming their reasons beside a readable
  resource. "Reported" here is the held classification's problems; the cycle's report of a
  never-readable declaration is the existing `test_a_declaration_never_readable_publishes_nothing`.
- [x] 2.3 `whole_machine_claim` refuses a context with no `claimed_attributes` key, or one
  that is not a mapping, and accepts an empty mapping, returning one `units` and the offering
  mode with no attribute (D7; delta "A bare-metal listing sells one whole unit"). Unit
  (`test_claims.py`): both cases. Application integration
  (`test_fulfillment_service.py`, through the storefront's fake site): a backed GPU-less
  listing's accepted deal reserves its Physical Resource with a claim carrying no attribute,
  and the site admits it.
  *Done, at a lower level than planned.* Unit, `domains/bare_metal/storefront` `make test`:
  506 passed. `test_claims.py`: a missing, `None`, or non-mapping record refused; `{}`
  accepted, yielding one `units` and the mode; and the site ledger's own admission matcher
  (`dict_resource_satisfies_claim`) admitting that claim for a GPU-less declaration.
  `test_fulfillment_service.py` is not application integration: it calls
  `BareMetalFulfillmentService.begin` directly over recording doubles, with no app and no
  site admission. It shows a record carrying `{}` reserves the Physical Resource with a
  claim of one `units` and no attribute, which the same matcher admits. The storefront's
  loader copies `BareMetalListing.claimed_attributes` into that record
  (`sqlite_client.py`, `load_bare_metal_fulfillment_context`); the property is unit-tested
  in 2.1, the loader path for a GPU-less listing is not.
  *Implementation-round fix (review 22 F1): the claim through a real site.*
  `tests/integration/test_site_reservation.py` runs the fulfillment service against a
  real site over the wire. The site is `kit/site`'s capacity router over a real
  `CapacityLedgerService`, configured as the compute provisioning service configures its
  own (`unit_claim_keys=("units", "gpu_count")`, `mirror_dimension="gpu_count"`), in a
  FastAPI app signing as the site authority, holding one GPU-less whole-host declaration
  (`units: 1, vcpu_count: 64, ram_gb: 512`, no GPU attribute) in a pool delivering
  `bare_metal`. `BareMetalFulfillmentService.begin` reaches it through the production
  capacity client, `AggregateCapacityClient` over `SiteCapacityClient` over
  `ASGITransport`, from a record whose `claimed_attributes` is a GPU-less
  `BareMetalListing`'s. The site admits the claim, holds it against that resource with
  dimensions `{units: 1}` and no attribute constraint but the pinned `resource_id`, and
  leases it at commit, leaving the resource's `units` at 0 available. Its scalar
  `available_units` is `None`, since it mirrors `gpu_count`, which the declaration does
  not name; the test asserts both. It is still below application integration: the
  storefront's app and persistence, its settlement evidence, and provisioning are
  in-memory stand-ins, and the loader path stays untested as above. The test's own
  imports led to declaring `sqlalchemy` in the storefront's `dev` group (`make lock`) and
  to a comment on `arkhai-kit-site` naming the router and ledger.
  Evidence: `make -C domains test-bare-metal` — `domains/bare_metal` 194 passed (unit);
  `domains/bare_metal/storefront` 507 passed (unit and integration, the new test among
  them); buyer 16 and provisioning adapter 57 passed. `make check-packaging`, `make
  check-comment-hygiene`, and `make check-change` pass. Root `make test` passed (exit 0),
  after the relock.
  Fresh-context check of the fix's diff: it found the test importing `sqlalchemy` and
  `starlette` undeclared (now `sqlalchemy` in `dev`, `Response` from `fastapi`), an
  unasserted `available_units` claim in this note (now asserted), and 2.6 overstating the
  level and implying validation 23 ran the test (both reworded). No comment-hygiene,
  fixture, or placement problem.
- [x] 2.4 Application integration (`test_publication_cycle.py`): one publication cycle
  over a site projecting a GPU-less machine publishes it, and the registry body the cycle
  sends has no GPU key (D7, D11).
  *Done; not application integration.* The module runs the cycle's public API against a
  real storefront database and held projection state, with the site and the registry
  replaced by doubles, and its own docstring says it is not integration evidence. The new
  test publishes a GPU-less machine with no hold, sends a registry body with `vcpu_count`,
  `ram_gb`, and `region` and no GPU key, stores the listing resource with no GPU key, and
  sends nothing on an unchanged second cycle. In the storefront's 506.
- [x] 2.5 System: extend `test_bare_metal_publication.py` with a second whole-host
  declaration `{units: 1, vcpu_count: 64, ram_gb: 512}` and no GPU model, in the advertised
  pool; after one site-projection step and one publication cycle, a buyer query
  `vcpu_count>=64` through the registry's filter vocabulary finds it, `gpu_count>=1` does
  not, and its `listing_resource` carries no GPU key (D11).
  *Written; runs at validation.* Stage `05e`, after the override is deleted and before the
  regionless pool, requiring `reinstated` (the advertised pool advertises again only after
  stage 05). `_whole_host` and `_declare_whole_host` take a capacity and an optional GPU
  model. `make test-e2e-unit`: 169 passed (it does not run the scenario).
- [x] 2.6 **Verification checkpoint.** Unit 2.1–2.3; application integration 2.3–2.4. Run
  `make test` in `domains/bare_metal` and `domains/bare_metal/storefront`, `make
  test-e2e-unit`, and `make check-comment-hygiene`.
  End-to-end: `e2e_bare_metal_publication` (2.5) proves the GPU-less machine's publication
  and discovery; `e2e_bare_metal_mock_deal` and `e2e_bare_metal_introduction` prove GPU
  machines are unchanged. The GPU-less claim is proven against a real site's admission
  (2.3); no further scenario is owed.
  *Done.* Unit 2.1–2.3; 2.3's service test and 2.4's cycle test are below application
  integration, as their notes say. `domains/bare_metal` 194 passed;
  `domains/bare_metal/storefront` 506 passed (its provisioning adapter 16 and buyer 57 also
  pass under `make -C domains test-bare-metal`); `make test-e2e-unit` 169 passed; `make
  check-comment-hygiene`, `make check-change`, and `make check-packaging` pass (the
  storefront's `pyproject.toml` changed only a comment on its test-only `arkhai-kit-site`
  dependency). Root `make test` passed over sections 1–3.
  End-to-end, confirmed: `e2e_bare_metal_publication` (stage 05e) proves the GPU-less
  machine's publication and discovery; `e2e_bare_metal_mock_deal`,
  `e2e_bare_metal_introduction`, and `e2e_bare_metal_unbacked_introduction` run GPU
  machines through the changed listing model; validation 23 passed all three lanes at
  `834e192ac`. No scenario reserves a GPU-less machine. The claim's admission, reservation,
  and commit at a real site are proven by 2.3's round fix (review 22 F1), which postdates
  validation 23: the fulfillment service against a real site over the wire, still below
  application integration, since the storefront's app and persistence are stand-ins and
  the loader path is untested.

  *Handoff.* `docs/development/DEPLOYMENT_AND_CONFIG.md` ("Definition documents", the bare-metal
  declaration bullet) still says `gpu_count` and `gpu_model` are required for bare-metal
  publication; the promotion record names the quickstart's matching paragraph but not that
  bullet, so closeout (9.9) should rewrite it too.

## 3. The compute registry's listing schema requires only `region`

Delivers filter spec version 7 with `listing_resource.required: [region]` and unchanged,
fail-closed GPU filters (D3; delta `registry-discovery` "The compute listing shape does not
require GPU fields").

Files: `core/registry/filter-spec.yaml`; tests
`core/registry/tests/unit/test_filter_spec.py`,
`core/registry/tests/integration/{test_validate_publish.py,test_filter_spec.py}`.

- [x] 3.1 Set `version: 7`, keep `schema: {id: compute.market, version: 2}`, and make
  `listing_resource.required` `[region]`, with a `v7` comment beside the existing version
  notes saying a listing may omit `gpu_model` and `gpu_count` (D3). Unit
  (`test_filter_spec.py`): the loaded spec reports version 7, the unchanged schema identity,
  and `required == ["region"]`.
  *Done.* Unit (`tests/unit/test_filter_spec.py`): version 7, `compute.market`/2,
  `required == ["region"]`, and `on_missing: fail` on `gpu_model` and `gpu_count_min`.
  Nothing else in the repository pins the spec's version.
- [x] 3.2 Application integration (`test_validate_publish.py`): a dry run of a compute
  listing carrying `region`, `vcpu_count`, and `ram_gb` and no GPU field is valid; one
  missing `region` is not (delta scenario "A listing without GPUs is validated").
  *Done.* Application integration: both cases go through the canonical
  `RegistryClient.validate_publish_listing` against the in-process app. The invalid case
  replaces the module's raw-HTTP test that asserted `gpu_model` was required; it now
  asserts `region` is named and `gpu_model` is not.
- [x] 3.3 Application integration (`test_filter_spec.py`, the listings query): with a
  GPU-less and a GPU listing published, `gpu_count>=1` and `gpu_model=H100` return only the
  GPU listing, and `vcpu_count>=16` returns both where both state sixteen vCPUs (delta
  scenarios "A buyer bounds a GPU field" and "A buyer bounds only CPU and memory").
  *Done.* Application integration (`tests/integration/test_filter_spec.py`): both listings
  published and queried through the canonical `RegistryClient` against the in-process app
  under the shipped spec.
- [x] 3.4 **Verification checkpoint.** Unit 3.1; application integration 3.2–3.3. Run
  `make test` in `core/registry`, `make -C helm test-render` (it reads the spec's identity,
  which is unchanged), and `make check-comment-hygiene`.
  End-to-end: `e2e_deal` and `e2e_deal_buyer_cli` dry-run their listings through
  `validate-publish` against version 7; section 8's scenario publishes and filters a
  GPU-less VM listing. No scenario is owed here.
  *Done.* `make test-registry`: 129 unit and 128 integration passed; `make
  test-registry-client`: 25 passed; `make -C helm test-render` passed; `make
  check-comment-hygiene` and `make check-change` pass; root `make test` passed over
  sections 1–3. End-to-end confirmed: `e2e_deal` (`test_full_deal.py`) and
  `e2e_deal_buyer_cli` (`test_full_deal_buyer_cli.py`) call `validate-publish`; section 2's
  stage 05e also queries the bare-metal lane's registry at version 7 by `vcpu_count` and
  `gpu_count`.

  *Handoff.* The registry's publish route still enforces no listing schema (design D3, "The
  publish requirement"), so version 7 changes only the dry run and the advertised spec;
  buyers holding a version-6 ETag refetch.

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

- [x] 4.1 Remove `gpu_count` and `gpu_model` from `HostCreate`, `HostUpdate`, and
  `HostResponse`, leaving the models' handling of undefined fields as it is, so a request
  carrying them is accepted with them ignored (D5 "API"). Unit (`test_contracts.py`): each
  model parses a body carrying both fields and exposes neither; `HostResponse` serializes
  no GPU key.
  *Done.* Unit, `provisioning/compute/contracts` `make test`: 63 passed. Each of the three
  models parses a body carrying both fields equal to one without them, defines neither,
  and dumps no GPU key; an update naming only the GPU fields sets no field. The module
  docstring states that a host describes no hardware and that the request models ignore
  an undefined field. This is the only evidence that a response carries no GPU key: the
  typed client parses every response through `HostResponse`, so no integration test
  through it can see a GPU key the server sent.
- [x] 4.2 Remove both columns from the `Host` model and both fields from `InventoryHost`,
  its serialization, and the host authority's create, update, and inventory apply (D5).
  Library integration (`test_host_authority.py`) and unit (`test_host_route_service.py`):
  create, update, and apply record and return no GPU field. Application integration
  (`test_hosts_api.py`): `POST /api/v1/hosts/` with `gpu_count` and `gpu_model` creates the
  host, and neither the response nor a read carries a GPU field (delta scenario "A host is
  created with GPU fields"); `test_host_writes_declare_no_capacity_api.py`'s INI and API
  cases drop their GPU inputs and still declare nothing (deltas "Host writes declare no
  capacity", scenarios "Deployment configured only through host inventory" and "A host is
  created through the individual host API").
  *Done.* Library integration, `provisioning/compute` `make test`: 243 passed.
  `test_host_authority.py`'s new `test_no_write_records_a_gpu_field` creates and updates
  from requests parsed from bodies carrying both fields (the models drop them before the
  authority sees them) and imports an entry, which cannot carry them; the rows the three
  writes leave, read by SQL, hold the expected hosts and enabled states and no GPU column.
  Its GPU-reading cases now assert pool, connection, and enabled state.
  `test_host_route_service.py` (unit, in the same 243) only swapped its update body for
  `enabled`: the route service passes the parsed models through and holds no GPU handling.
  Application integration, `provisioning/compute/service` (544 integration passed):
  `test_hosts_api.py` sends `gpu_count` and `gpu_model` on create and update through the
  typed client — a test subclass of each request model declares them, so the client
  serializes them onto the wire — and the host is created, the update applied, and the
  application database's stored row, read by SQL, has no GPU column. That responses carry
  no GPU key rests on 4.1's unit test, since the client parses responses through
  `HostResponse`. `test_host_writes_declare_no_capacity_api.py`'s INI, startup-seed, and
  API cases carry no GPU input and still declare and project nothing.
- [x] 4.3 Stop reading `gpus=` and `gpu_model=` in `_parse_entries`: remove the mapping
  lines from its docstring, the malformed-`gpus=` comment, and the two dict keys, so they
  fall under "All other variables → ignored" with no warning (D5 "INI"). Unit
  (`test_inventory.py`): a line carrying `gpus=8 gpu_model=H200` parses to the same
  `InventoryHost` as one without, and a malformed `gpus=x` no longer matters. Update the
  example inventory's `gpus=` lines and comments to describe only connection fields.
  Application integration (`test_host_writes_declare_no_capacity_api.py`): an INI import
  with those variables registers the host and records nothing for them (delta scenario "An
  inventory line carries GPU variables").
  *Done.* Unit, `provisioning/compute/ansible` `make test`: 94 passed; the new case parses
  a line with `gpus=8 gpu_model=H200`, and one with `gpus=x`, to the same host as the bare
  line, logging nothing. The malformed-`gpus=` half of the port comment is gone; the
  `ansible_port=` rationale stays. The example inventory's template line and option list
  carry no GPU variable, and its header says a line describes reaching a machine, not its
  hardware. Application integration: `test_an_inventory_line_carrying_gpu_variables_records_nothing_for_them`
  imports such a line through the typed import client; the host is registered with its
  connection and pool, its stored row has no GPU column, and nothing is declared or
  projected.
- [x] 4.4 Append a migration after `20261027_001` that rebuilds `hosts` from the model
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
  *Done, with two changes the plan did not name.* `20261028_001_hosts_drop_gpu_columns`
  rebuilds `hosts` through `_rebuild_hosts_from_model`, the rebuild body extracted from
  `_migrate_hosts_pool_optional`, which now calls it too. A fresh database creates `hosts`
  from the model and then runs the whole chain, so two earlier entries had to tolerate a
  table with no GPU column: `20260804_001` adds `gpu_model` only where `gpu_count` exists,
  and `20260921_004` returns when `hosts` has no `gpu_count`, since such a table holds no
  legacy count. On a database that has not yet applied `20261023_002`, that rebuild copies
  only the model's columns and so drops the GPU columns itself; the new entry then finds
  neither and does nothing. Persistence integration (`test_host_gpu_columns_drop_migration.py`,
  in the service's 544): the "before" state runs the chain from the `20260911_001`
  fixture, restores both columns with `ALTER TABLE` and each host's values, and deletes the
  drop's record — a reconstruction, not a schema captured from the previous release. Every
  other column of every host (identity, connection, the protected key's ciphertext, pool,
  enabled, timestamps) survives, the foreign key to `resource_pools` holds and
  `foreign_key_check` is empty, and no log record names a host; a declaration an operator
  changed after the upgrade derived it is unchanged; a fresh database has no GPU column and
  the entry leaves its table's page alone; a repeated run changes nothing. Of the delta
  scenario "Host record carries a legacy capacity column", this test proves only that the
  migrations drop the values; that projection reads no host is the existing projection
  tests' (`test_capacity_api.py`, "publishes declarations, not hosts"). Existing migration tests that wrote `gpu_count`
  into a table created from the model, or asserted the GPU columns after the chain,
  changed with it (`test_host_pool_optional_migration.py`, `test_database.py`,
  `test_legacy_host_capacity_migration.py`, `test_legacy_vm_lease_migration.py`,
  `test_legacy_backfill_teardown.py`, `test_vm_provider_identity_migration.py`,
  `test_fulfillment_convergence_after_legacy_backfill.py`); the legacy-capacity test's
  "host rows unchanged" case now runs the chain to the entry before `20260921_004`, then that
  entry alone.
- [x] 4.5 The e2e host harness compares an existing host's pool alone when deciding to
  update it, and passes no GPU field (D5 "The one non-production reader"). Unit: `make
  test-e2e-unit` passes.
  *Done; the harness was not the only reader.* `register_e2e_host` reconciles on pool
  alone and passes no GPU field; `E2E_HOST_GPU_COUNT` and `provision_e2e_executor`'s
  `host_gpu_count` are gone. Five more scenario modules asserted or logged an executor
  host's `gpu_count` (VM `compute_deal_driver.py`, `test_full_deal_buyer_cli.py`,
  `test_buy_oneshot_buyer_cli.py`, `test_compute_dynamic_listings.py`,
  `test_multi_registry.py`) and would have failed on the new `HostResponse`; the GPU
  assertion and log argument are gone, and `test_compute_dynamic_listings.py` and
  `test_multi_registry.py` assert the host's id in their place (the other three already
  did). Two passed GPU fields to `HostCreate` (the VM lane's
  `conftest.py` stub host and bare metal's `compute_deal_driver.py`). `make
  test-e2e-unit`: 169 passed; it does not import the scenario modules, and collecting them
  locally was not run in this session, so their first import is the lanes' at validation.
- [x] 4.6 Remove the GPU fields from every test fixture and assertion that reads a host's
  GPU field across `provisioning/compute` and its service; fixtures passing GPU values only
  as declaration capacity are unaffected. A repository search for `HostCreate(`/`HostUpdate(`
  with a GPU argument, and for `.gpu_count`/`.gpu_model` on a host, finds none (D5).
  *Done.* Fixtures changed beyond 4.2–4.4's: `test_capacity_api.py` (an INI line, two
  `HostCreate` calls, and three host rows carrying GPU values; a docstring and a comment
  that described host GPUs),
  `test_pool_seed_api.py`, `test_provisioning_client_endpoint_coverage.py`,
  `test_test_controller.py`; and, outside the plan's file list, the issue-discovery tool's
  local host registration body (`tools/issue-discovery/config/phases/local.yaml`). The
  search finds only the deliberate retired-field inputs of 4.1–4.3's tests, declaration
  capacity and attributes, and the test-only `schema_through_20260911_001.sql` fixture and
  `test_host_connection_migration.py`, which build legacy tables of their own.
- [x] 4.7 **Verification checkpoint.** Unit 4.1, 4.3, 4.5; library integration 4.2;
  application integration 4.2–4.3; persistence integration 4.4. Run `make test` in
  `provisioning/compute/contracts`, `provisioning/compute`, `provisioning/compute/ansible`,
  and `provisioning/compute/service`, `make test-e2e-unit`, `make check-packaging`, and
  `make check-comment-hygiene`.
  End-to-end: every VM and bare-metal scenario registers hosts through the harness and the
  provisioning service migrates its database through the new step, so the lanes prove
  nothing read the retired fields. No scenario is owed: the field handling is a model and
  API behaviour application integration owns.
  *Done.* After `make dist`: contracts 63 passed; `provisioning/compute` 243; ansible 94;
  service 669 unit and 544 integration; `provisioning/compute/client` 58; `make
  test-e2e-unit` 169. `make check-packaging` (no dependency or lock changed),
  `make check-comment-hygiene`, and `make check-change` pass; root `make test` exited 0
  over the tree holding sections 1–4, before the fresh-context check's fixes (tests and
  two docstrings), after which the contracts, `provisioning/compute`, service, and
  e2e-unit suites were rerun and pass.
  End-to-end, confirmed: the lanes' provisioning services start on fresh databases, so the
  chain they run includes the guarded `20260804_001` and `20260921_004` and the new entry
  as a no-op; no lane upgrades a database holding GPU columns, so the drop's rebuild is
  proven only at persistence integration. Scenarios exercising the changed host harness and
  host reads: `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`, `e2e_compute_dynamic_listings`,
  `e2e_listing_shapes`, and `multi_registry` (VM), and `e2e_bare_metal_mock_deal` (bare
  metal's driver registers its host with no GPU field). None asserts the absence of a GPU
  field: that a stored host has none is application integration's evidence, and that a
  response has none is 4.1's unit test.

  A fresh-context check of the section's diff found no layering, import, packaging, or
  placement problem. It found that the first version of the integration tests asserted
  GPU-key absence on typed-client responses, which cannot fail; they now read the stored
  rows, and the notes above say what each level proves. Declined: rewording
  `_migrate_hosts_gpu_model`'s first paragraph, which describes what that historical step
  does at its point in the chain; and moving the service's chain-running migration tests
  out of `tests/unit`, an existing pattern this section did not introduce.

  *Handoff.* The design called the e2e harness the one non-production reader of the host
  GPU fields; five more scenario modules read them (4.5). They were changed by inspection
  and have not been imported locally, so a lane failure on import or on a removed name in
  a scenario is this section's to fix. The column drop is fail-forward; its operator note
  in `DEPLOYMENT_AND_CONFIG.md` ("Migrations at startup") and the rewrite of the "`gpus=`
  and `gpu_model=` are descriptive" sentence are closeout's (9.9), as are
  `VALIDATION_RUNBOOK.md`'s host body and inventory line and both quickstarts' inventory
  text. The `hollow-pre-floor-provisioning-migrations` change will meet the two guards
  this section added to `20260804_001` and `20260921_004`.

## 5. VM listing models, dispatch, and serialization

Delivers VM listing resources without GPU fields: optional fields with D1's rule, one
dispatch rule at every seam, and a serializer that omits absent GPU fields (D6, D1).

Files: `domains/vms/domain/src/arkhai_vms/schema.py`;
`domains/vms/listings/src/arkhai_vms_listings/{models.py,resources.py,pricing.py,buyer_cli.py}`;
tests `domains/vms/domain/tests/test_schema.py`,
`domains/vms/storefront/tests/unit/{test_resources.py,test_listing_model_capacity_identity.py}`,
`domains/vms/storefront/tests/integration/test_listings_api.py`.

- [x] 5.1 Make `ComputeResource.gpu_count` and `gpu_model` optional, and replace
  `VmListing`'s presence checks with flattening the resource's quantity and attribute fields
  through the compute schema, so the shape kit refuses one GPU field without the other and a
  mapping with no quantity (D6, D1). Unit (`test_schema.py`): a GPU-less listing validates;
  `gpu_model` alone, `gpu_count` alone, and no quantity are refused naming the shape kit's
  reason.
  *Done.* One reader, `arkhai_vms.vm_listing_resource_shape` (`capability_shapes.py`), builds
  a flat resource's shape through `unflatten_shape`, taking only the schema's flat names and
  reading a `None` value as absent; `VmListing`'s validator and a new `ComputeResource`
  after-validator both call it, so neither restates the rule. Unit, `domains/vms/domain`
  `make test`: 58 passed — a GPU-less listing validates and reads as `{cpu, memory}`; GPU
  fields stated as `None` state nothing; model alone, count alone, no quantity, and zero GPUs
  are refused with the kit's reason. `ComputeResource`'s refusals are 5.2's unit cases.
  Outside the plan's files: `test_domain_runtime_wiring.py` matched the old message and now
  matches `gpu.model: is required`.
- [x] 5.2 One dispatch rule at every seam (D6 "Dispatch"): `Resource.parse_from_dict`
  (`models.py`), `resource_is_compute` (`pricing.py`), the adapter registry's
  `parse_resource_from_dict` and the compute adapter's discriminator (`resources.py`), and
  `format_resource` (`buyer_cli.py`). An explicit `resource_type` selects its adapter;
  otherwise a `token` key is a `TokenResource`, and any other mapping a `ComputeResource`.
  Unit (`test_resources.py`): a GPU-less compute mapping, a stored GPU listing, a token
  mapping, and an explicit `resource_type` each dispatch as the rule says; a mapping with no
  quantity is refused by compute validation; `resource_is_compute` and `format_resource`
  agree with the parser.
  *Done.* The rule is `payload_resource_type` in `models.py`, beside `COMPUTE_RESOURCE_TYPE`
  and `TOKEN_RESOURCE_TYPE`; `parse_from_dict`, `resource_is_compute`, and `format_resource`
  call it. The adapter registry keeps third-party adapters selectable by their key, so its
  rule is: a registered `resource_type`, else an adapter whose `discriminator_key` the
  payload carries, else compute; the compute adapter's key is now `None`, and over the
  built-in adapters this is the same rule, which is how D6's "one rule" holds while a
  registered extension adapter can still select itself. `resource_is_compute` of an object
  is now `isinstance(…, ComputeResource)`, not `hasattr(…, "gpu_model")`, and an empty
  mapping is not compute, so `extract_compute_from_order` still refuses an order with no
  `listing_resource`. `format_resource` renders every non-compute payload as a token, so its
  JSON fallback, which the rule left unreachable but for a token type with no `token` key,
  is gone. Unit (VM storefront `tests/unit`, 1146 passed): each of the four payloads
  dispatches alike through `payload_resource_type`, both parsers, `resource_is_compute`, and
  `format_resource` (for compute, by its `region=` line); a GPU-less mapping parses with
  both GPU fields `None`; one GPU field alone and no quantity are refused by
  `ComputeResource`'s validation (the old "Cannot determine resource type" case is gone,
  since no mapping is undecidable); an empty mapping is not compute and its order is
  refused; a token-typed payload renders as a token. The buyer's `format_resource` test
  (`domains/vms/buyer`, 207 passed) is unchanged.
- [x] 5.3 The `ComputeResource` serializer omits an absent `gpu_count` and `gpu_model` as it
  omits `asking_rate` (D6 "Serialization"). Unit (`test_listing_model_capacity_identity.py`
  or `test_resources.py`): a GPU-less resource's `model_dump(mode="json")` has no GPU key; a
  stored listing whose resource holds `gpu_model: null` and one missing the key compare equal
  under `compare_listing`, so no stored listing churns.
  *Done.* The wrap serializer now drops `asking_rate`, `gpu_count`, and `gpu_model` when
  `None`. Unit (`test_resources.py`): a GPU-less resource's `model_dump()`, its
  `model_dump(mode="json")`, and the compute adapter's `to_dict` carry neither GPU key; a GPU
  resource dumps both GPU fields; a stored resource with both GPU fields `null` and a
  fresh one without them compare `unchanged`. `compare_listing` needed no change: it already
  compares an identity field only when both sides publish it.
- [x] 5.4 Application integration (`test_listings_api.py`, through the storefront's typed
  client): the publication path's `parse_resource_from_dict` accepts a GPU-less payload,
  still parses a stored GPU listing, and refuses a compute mapping with no quantity (D6,
  D11).
  *Done.* Application integration, VM storefront `tests/integration` (481 passed), through
  `StorefrontClient.create_listing` against the in-process listings app: a GPU-less
  resource with a `{cpu, memory}` listing shape is created and stored with no GPU key; a GPU
  resource naming no `resource_type`, as every stored VM listing does, is created and
  stored with its GPU fields; a compute resource stating no quantity is refused with 400
  naming the empty shape. That refusal is the domain codec's (`VmListing`, which runs first
  in `_parse_listing_resource_and_escrows` and reads the shape through the same
  `vm_listing_resource_shape`), not `parse_resource_from_dict`'s, whose own refusal is 5.2's
  unit case. The parser's one production caller, `derive_listing`, serves both create and
  the publication loop's refresh comparison, so these cases run the loop's derivation too.
- [x] 5.5 **Verification checkpoint.** Unit 5.1–5.3; application integration 5.4. Run
  `make test` in `domains/vms/domain` and `domains/vms/storefront` (`arkhai_vms_listings`
  has no suite of its own; its behaviour suites live in the VM storefront's unit suite),
  and `make check-comment-hygiene`.
  End-to-end: every VM lane scenario publishes GPU listings through the changed dispatch
  and serializer (`e2e_deal`, `e2e_listing_shapes`, `e2e_compute_dynamic_listings`); section
  8 adds the GPU-less one.
  *Done.* After `make dist`: `domains/vms/domain` 58 passed; `domains/vms/storefront` 1146
  unit and 481 integration passed; `domains/vms/buyer` 207 passed; `make check-change`
  (comment hygiene included) passes; root `make test` exited 0 before the fresh-context
  check's fixes, after which the storefront and buyer suites were rerun and pass. No
  dependency or lock changed. End-to-end, confirmed as planned: `e2e_deal`,
  `e2e_listing_shapes`, and `e2e_compute_dynamic_listings` publish GPU listings through the
  changed models; none states a GPU-less shape until section 8.

  Fresh-context check: no layering, packaging, import, or comment-hygiene problem. Fixed
  from it: `payload_resource_type`'s docstring claimed every seam called it (the registry
  reduces to it instead, now said); `format_resource`'s token branch re-tested the `token`
  key; `resource_is_compute({})` had become true; the test module's docstring; and four
  overstated notes (5.3's `to_dict` and "unchanged", 5.4's refusal and "only caller").
  Declined: raising `arkhai-vms-listings`' `arkhai-vms>=0.6.0` bound for the new
  `vm_listing_resource_shape`, since every lock pins the tree's 0.7.0 wheel and versions
  are not bumped per change. *Correction (section 7):* versions are bumped once per change
  under `RELEASING.md`'s policy, and this change has bumped none; the bound moves with that
  bump, which section 7's handoff leaves to the owner. The round-2 triage fix (31 F1,
  under 7.5) raised it to `arkhai-vms>=0.8.0`.

  *Handoff.* `DEPLOYMENT_AND_CONFIG.md` ("Storefront listing shapes and pool overrides",
  the constraint bullet) still says "`gpu.count` and `gpu.model` are required, so
  `gpu.count` always states an `offer`"; the promotion record does not name it, so closeout
  (9.9) should rewrite it to "required together".

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

- [x] 6.1 `ResolvedShape.gpu_count` and `gpu_model` return `None` for a shape stating no
  GPUs, and every reader handles `None` (D8). Unit (`test_listing_shape_resolution.py`): a
  stated GPU-less shape resolves with both `None`; a GPU shape is unchanged.
  *Done.* Unit (VM storefront `tests/unit`): a stated `{cpu, memory}` shape resolves with
  both properties `None`, its quantities `vcpu_count`/`ram_gb`, and no attribute; a GPU
  shape still names its count and model. The readers are the reconciler's pricing and
  family-rate grouping (6.3) and the candidate builder's per-model lookups, which key on
  `None` for such a shape.
- [x] 6.2 A member's GPU count is no precondition for membership (D8):
  `_projected_resource_usage` no longer returns an absent-count outcome for a member without
  `gpu_count`; GPU usage and fungible GPU availability apply only to shapes naming GPUs, and
  a GPU-less shape's availability is judged on the dimensions it declares through the site
  predicate (`shape_feasibility.py`). A malformed `gpu_count` still holds the pool; a zero
  yields no default shape and no report. Unit (`test_reconciler.py`, `_reconciler_cases.py`):
  a GPU-less member is feasible for a stated GPU-less shape; a GPU host's spare vCPU and
  memory are feasible for it (delta scenario "A GPU host's spare capacity sells as a VM
  without GPUs"); a backed GPU-less shape whose member's available memory is below it is not
  published; a malformed count holds.
  *Done.* `_projected_resource_usage` reads an absent `gpu_count` as zero, so a member
  declaring none, or zero, is a member with zero GPU usage; only a malformed count
  (negative, non-integer, boolean) or a missing resource kind keeps a member out, as
  before. Feasibility needed no change: `shape_feasibility.py` already builds the shape's
  claim and judges it with the site's predicate, which requests only the dimensions the
  shape declares. Unit (VM storefront `tests/unit`): a member with no count or a zero count
  uses zero GPUs; a malformed count is still unresolvable; a GPU-less member is feasible for
  a stated `{cpu: 16, memory: 64}`; a GPU host's (`_BIG`) spare vCPU and memory are, and the
  shape's claim requests `vcpu_count` and `ram_gb` and no GPU dimension or model; a backed
  GPU-less member with 32 GiB free is not, and is reported infeasible `available`; a
  malformed member beside a GPU-less one holds the pool. Library integration
  (`test_shape_feasibility.py`, the storefront's judgement against a real
  `CapacityLedgerService.probe`): four cases added — a GPU-less shape on a GPU host's spare
  capacity, on a member without GPUs, beyond that member's free memory under a hold, and a
  GPU shape on a member without GPUs — each agreeing with admission on declared capacity,
  on availability, and through the capacity bucket.
- [x] 6.3 Group pricing and family rates by an optional GPU model, so a GPU-less shape
  resolves flat rates or cpu, memory, and storage family rates, and a pool whose only rates
  are per GPU model leaves it with no settlement option, refused and reported as
  `no_settlement_option` (D8). Order the availability reopen by GPU count with an absent
  count as zero, then listing id, keeping it deterministic. Unit (`test_reconciler.py`): a
  mixed pool's GPU and GPU-less shapes each resolve their rates without error; a
  per-model-only pool's GPU-less shape is refused as `no_settlement_option`; reopen ordering
  of a GPU-less listing does not fail.
  *Done, at three levels.* `pricing_resolution.py` already handled `gpu_model=None` (no
  hint or per-model configured terms, no GPU family rates); the reconciler now sorts its
  models with `None` first, which a plain `sorted` of a mixed set could not, and keys
  `pricing_by_model`/`family_rates_by_model` on `None` for a GPU-less shape. Reopen order is
  GPU count with an absent count as zero, then listing id. Unit (`test_reconciler.py`): a
  mixed pool resolves `None` and `H100` terms, the GPU-less shape the flat default's clause
  and the `cpu` and `memory` rates, the GPU shape its own clause and the GPU rate too; a
  pool priced only per model leaves the GPU-less shape no clause and no rates. The refusal
  itself is the publication cycle's, so it is application integration
  (`test_publication_loop.py`, below): with `[pricing].settlements` empty and the pool's
  only clause under `pricing.gpu.H100`, the GPU shape publishes and the GPU-less one is
  refused as `no_settlement_option` naming its digest. Reopen ordering reads the database,
  so it is library integration (`test_reconciler_derivation.py`): two closed GPU-less
  listings and a one-GPU listing reopen as `cpu-a`, `cpu-b`, `gpu-1`; the old code raised
  `KeyError`. `_reconciler_cases.py`'s `_seed_listing` gained a `listing_shape` argument
  for it.
- [x] 6.4 Replace the per-member `member_gpu_count_missing` report with one pool report when
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
  *Done.* The report's category is `pools_without_default_shapes`; its entry is a `report`
  (holding nothing) with reason `listing_shapes_required` and a `message`
  (`POOL_SHAPES_REQUIRED_MESSAGE`) saying the default generates GPU shapes only and the
  pool must state `listing_shapes`, on its hint or an override. It is made when the shapes
  are generated and the pool has at least one enabled member and none declares a positive
  GPU count. Two choices the plan did not state, now recorded in `design.md` D2 ("Which
  pools are reported"): a pool with no enabled member is not reported; and a pool whose
  only members declare zero is reported as the pool, since the delta's condition is "no
  positive GPU count", which departs from this task's "a zero count yields … no report" for
  such a pool, while a zero-count member beside a GPU member is silent as the task says.
  `members_without_gpu_count` is gone from the report. The generator's module docstring
  states that a member declaring no GPUs yields no default shape. Unit
  (`test_shape_generation.py`, in `domains/vms/domain`'s 60): a GPU member beside a
  GPU-less one yields the GPU defaults; GPU-less members yield none. Unit
  (`test_reconciler.py`): the same through the row builder with no report; a GPU-less pool
  stating no shapes yields one `listing_shapes_required` entry from
  `site_derivation_entries`; zero beside GPUs is silent; a zero-only pool is reported; a
  stating pool and an empty pool are not. Library integration
  (`test_reconciler_derivation.py`, `TestEnumerationQuantity`): the old absent-count case
  now asserts the pool report; the old zero-only "silent" case, false now that a zero-only
  pool is reported, is replaced by zero beside a GPU member, and a third case puts a
  GPU-less member beside a GPU member, both silent.
- [x] 6.5 Application integration (`test_publication_loop.py`, through the storefront's
  typed client and fake site): a pool hint stating `{cpu: {count: 16}, memory: {gib: 64}}`
  publishes one listing whose exact registry body carries `vcpu_count: 16` and `ram_gb: 64`
  and no GPU key, on first publication and on a refresh (D11; delta "A pool states a shape
  with no GPUs"); a GPU-less pool with no stated shapes publishes nothing and system status
  reports it (D2, D12). Library integration (`test_reconciler_derivation.py`,
  `test_shape_feasibility.py`): mixed and GPU-less pools derive as 6.2–6.4 say.
  *Done.* Application integration (VM storefront `tests/integration`, 501 passed), cycles
  run through the typed client's lifecycle controls against `tests.publication_app`, whose
  registries are the recording double where `MultiRegistryClient` wraps them: a pool hint
  stating `{cpu: 16, memory: 64}` over a member declaring no GPU publishes one listing; every
  registry's publish body carries a `listing_resource` equal to the stored one, with
  `vcpu_count: 16`, `ram_gb: 64`, and no GPU key, and a term change refreshes it at every
  registry with that same `listing_resource`. "Exact" is this equality and the GPU keys'
  absence: the other absent optional fields still publish as `null` (D6's recorded gap). A
  GPU-less pool stating no shapes publishes nothing and `get_system_status`'s
  `publication_derivation` carries its `listing_shapes_required` report; a pool whose two
  default listings were published closes both once its member declares no GPUs, and is
  reported; the per-model-only refusal of 6.3. That the claim requests no GPU is unit
  evidence here (6.2) and the deal path's in section 7. `publication_app.pool` takes
  `gpu_model=None` for a member without GPUs. Library integration
  (`test_reconciler_derivation.py`, against SQLite, through `available_compute_slices`): a
  GPU-less pool derives one candidate for its stated shape with no GPU field and no report;
  a mixed pool derives candidates for its GPU and GPU-less shapes; reopen ordering (6.3).
  `test_shape_feasibility.py` as in 6.2.
- [x] 6.6 **Verification checkpoint.** Unit 6.1–6.4; library integration and application
  integration 6.5. Run `make test` in `domains/vms/domain` and `domains/vms/storefront`, and
  `make check-comment-hygiene`.
  End-to-end: `e2e_listing_shapes`, `e2e_compute_dynamic_listings`, and `e2e_deal` prove GPU
  publication unchanged; section 8 proves GPU-less publication in the running stack.
  *Done.* After `make dist`: `domains/vms/domain` 60 passed; `domains/vms/storefront` 1165
  unit and 501 integration passed; `make check-change`, comment hygiene included, passes;
  root `make test` exited 0 before the fresh-context check's fixes (a message, a docstring,
  a test comment, a stronger refresh assertion, and one new publication-loop case), after
  which the storefront suite was rerun and passes. No `pyproject.toml` or lock changed, so
  `make check-packaging` was not rerun; no suite runs a type checker over these packages
  (the storefront declares `mypy` but no target runs it), and none was run for
  `ResolvedShape`'s `int | None` and `str | None`. End-to-end, not run in this section and
  owed to validation: `e2e_listing_shapes`, `e2e_compute_dynamic_listings`, and `e2e_deal`
  publish GPU shapes through the changed reconciler; no lane states a GPU-less shape before
  section 8.

  Fresh-context check: no layering, import, packaging, or comment-hygiene problem; the code
  meets D2, D8, D12 and the delta. Fixed from it: the pool report's message said "a GPU
  count" where the condition is a positive one; `_projected_pool_rows`' docstring did not
  say a GPU-less shape's terms key on `None`; a unit test's comment claimed a reservation
  it does not make; the refresh assertion and the "defaults close" clause of the delta
  scenario, now tested; D8's pricing rule had no promotion row, now added; and five
  overstated notes. Declined: moving the listings package's reconciler tests out of the
  storefront's suite, an existing arrangement; and reporting a pool whose members declare
  a GPU count but no model, which the delta does not ask for and which predates this
  change.

  *Handoff.* Section 7's readers of a listing's GPU fields remain: the admin reserve's
  `or 1` and the Alkahest lease terms. A GPU-less candidate still carries its pool's
  `total_gpu_count` and `available_gpu_count`, which nothing publishes or reads.

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

- [x] 7.1 `extract_compute_from_order` accepts a GPU-less compute resource through D6's
  `resource_is_compute`, so claim building, the seller's recheck, and the negotiation
  opening reach a GPU-less listing (D9). Unit (`test_vm_job_spec_service.py`): the claim
  for a GPU-less listing carries `resource_type: compute.gpu`, `offering_mode: vm`, its
  pool, and `dimensions` with its vCPU and memory, and no `gpu_model` or `gpu_count` (D4,
  D9). Unit (`test_listing_source_check.py`): a GPU-less listing whose source still serves
  its shape is confirmed, and one whose member shrank below it is refused as a declared
  mismatch.
  *Done; no code change was needed beyond section 5's.* `resource_is_compute` (5.2) already
  answers true for a non-empty GPU-less mapping, and the claim builder, the opening's
  dimension check (`_validate_vm_opening`), and the source check (through the reconciler,
  section 6) read only the fields a listing states. The claim builder's comment on
  `_VM_RESOURCE_TYPE` now states D4's rule: the resource type is the category a claim
  matches, `compute.gpu` for every VM declaration. Unit (VM storefront `tests/unit`, 1172
  passed): a GPU-less order's claim is exactly `{offering_mode: vm, resource_type:
  compute.gpu, pool_id, region, dimensions: {vcpu_count: 8, ram_gb: 32}}` from a dict, and
  the same claim from a parsed `ComputeResource`. The opening
  (`test_sync_negotiation_seller_round_hook.py`, through the negotiation runtime's opening
  over a real `SQLiteClient`): a buyer naming `vcpu_count: 16` against a GPU-less listing
  of 8 is refused `resource_shape_not_negotiable` naming the listing's 8, so the opening
  reads the GPU-less listing as compute. `test_listing_source_check.py` (in `tests/unit`, but over
  a real `SQLiteClient` and the fake projection site, as the module's existing cases are):
  a backed listing of a stated `{cpu: 16, memory: 64}` over a GPU-less member is confirmed
  `matches`; the same member declaring 32 GiB is a `declared_mismatch`. Its `_bind` helper
  now derives the bound shape through `vm_listing_resource_shape`.
- [x] 7.2 The Alkahest lease terms omit each GPU key the listing does not state (D9). Unit
  (`test_vm_evidence_validation.py` or a new `test_compute_lease.py` in the VM storefront's
  unit suite): `encode_compute_lease` for a GPU-less resource yields JSON with no
  `gpu_model` or `gpu_count` key and every other key unchanged; a GPU resource's bytes are
  unchanged.
  *Done.* `encode_compute_lease` writes `gpu_model` and `gpu_count` only when the resource
  states them, keeping the existing key order. Unit (new
  `tests/unit/test_compute_lease.py`): a GPU-less resource's terms have neither key and
  equal a GPU resource's terms less those two; a GPU resource's bytes equal the
  hand-written JSON of the previous order and values.
- [x] 7.3 The admin reserve response's `gpu_count` is optional and absent for a GPU-less
  reservation, with the `or 1` fallback removed (`admin_controller.py`,
  `capacity_admin_models.py`), and the storefront client model's `gpu_count` default of `0`
  becomes optional (D9). Application integration (`test_admin_api.py`, through the typed
  client): reserving a GPU-less listing returns no `gpu_count`; a GPU listing's reservation
  returns its count as before.
  *Done.* The route reports `gpu_count` from the reservation's `allocated_gpu_count`, or
  `None` (`null` on the wire, not an omitted key) when that is zero or absent; the
  server's `ReserveCapacityResponse.gpu_count` and the client's are `int | None`,
  defaulting to `None`, and the client parses an absent or null value as `None` (unit,
  new `core/storefront-client/tests/test_reserve_capacity_response.py`: a count, an absent
  key, and a null). The VM storefront's `FakeSite` allocated one GPU to a claim stating
  dimensions without one; it now allocates the claim's GPU count, zero when it states none,
  as the real ledger's mirror reports it (`kit/site` `_match_payload`). Application
  integration (VM storefront `tests/integration`, 503 passed): reserving a bound GPU-less
  listing through `StorefrontClient.admin_reserve_capacity` returns `gpu_count` `None` and
  the fake site holds `{vcpu_count: 8, ram_gb: 32}`; the existing GPU case still returns 2.
  `core/storefront-client` `make test`: 68 passed.
- [x] 7.4 Admission and fulfillment are unchanged (D10). Unit
  (`test_vm_fulfillment_plan.py`): a committed reservation with no `gpu_count` dimension
  yields no `vm_gpu_count` or `gpu_provisioned` variable. Application integration
  (`test_negotiate_controller.py` and `test_payment_settlement.py`): a GPU-less listing opens
  a negotiation, and its settled deal's reservation, admitted on a GPU host's fake-site
  member, holds only the listing's vCPU and memory.
  *Done, in a different file and up to the acceptance hold.* Unit
  (`domains/vms/provisioning/adapter` `make test`, 39 passed): a settlement resource whose
  dimensions are `{vcpu_count: 8, ram_gb: 32}` prepares a create with `vm_vcpus` 8 and
  `vm_gpu_count` and `gpu_provisioned` stored unset (`None`, as every uncommitted sizing
  field is; the codec's dropping of `None` variables is not exercised here); one with
  `{gpu_count: 2}` sets both. Application
  integration: neither planned file composes publication, negotiation, and a site that
  admits — `test_negotiate_controller.py` seeds GPU listings through its own helpers and
  `test_payment_settlement.py` replaces delivery and reserves nothing — so the case is in
  `test_publication_loop.py`, beside the existing stated-shape negotiation case: a GPU
  host's pool states `{cpu: 8, memory: 32}`, a cycle publishes it with neither GPU key,
  the buyer's `negotiate_new` (naming no `compute_resource`, so the opening's dimension
  check is 7.1's unit case) opens and is accepted, and the acceptance hold at the fake site
  holds `{vcpu_count: 8, ram_gb: 32}`, zero units, and leaves the host's two GPUs
  available. Settlement's commit of that hold and fulfillment through mock provisioning
  are section 8's scenario, not shown here.
- [x] 7.5 **Verification checkpoint.** Unit 7.1–7.2, 7.4; application integration 7.3–7.4.
  Run `make test` in `domains/vms/storefront` (which carries the listings and settlement
  packages' behaviour suites), `domains/vms/provisioning/adapter`, and
  `core/storefront-client`, `make check-packaging`, and `make check-comment-hygiene`.
  End-to-end: section 8's scenario settles a GPU-less deal through mock provisioning.
  *Done.* After `make dist`: VM storefront 1172 unit and 503 integration passed;
  provisioning adapter 39; `core/storefront-client` 68; `make check-packaging` passes (no
  dependency or lock changed); `make check-change`, comment hygiene included, passes; root
  `make test` exited 0 before the fresh-context check's fixes (tests, a test-double
  comment, a docstring), after which the four suites above were rerun and pass.
  End-to-end: as planned, section 8's `e2e_listing_shapes` step; GPU deals in `e2e_deal`,
  `e2e_deal_buyer_cli`, and `e2e_compute_dynamic_listings` still assert the admin
  reserve's `gpu_count` for GPU claims, which the route still reports.

  Fresh-context check: no layering, import, packaging-check, or change-name problem; the
  lease terms, the reserve response, and the fake site's change match D9 and the real
  ledger. Fixed from it: `FakeSite._match`'s stale comment ("now always routes
  `gpu_count`"); the server model's docstring said "absent" where the wire carries `null`;
  the new admin fixture's development addresses had no comment; the client model had no
  unit test; the parsed-model claim and the opening check were not asserted as the notes
  said; and two notes' wording. Declined: moving `test_listing_source_check.py`'s cases out
  of `tests/unit`, an existing arrangement; reporting `None` rather than 0 in the release
  and fulfillment-event responses, which D9 does not name and which hold a site's answer.

  *Handoff.* The check found that no package version has been bumped anywhere in this
  change (`git diff` of every `pyproject.toml` against the merge base with `dev` changes
  none), while `docs/development/RELEASING.md` ("Versioning policy") bumps each changed
  package once per change, minor for an incompatible change below 1.0, and earlier changes
  did (`kit/resource-pools`, `provisioning/compute/contracts`, `core/storefront-client`).
  This change makes incompatible edits from section 1 on (host contracts losing fields, the
  storefront client's `gpu_count`, optional listing-model fields). No task plans the bumps,
  and they move exact pins and need `make lock`, so they are the owner's to place: a fix
  round before closeout, or a plan amendment. Section 5's note declining a raised bound
  "since versions are not bumped per change" was wrong on that point (see its correction).

  *Round-2 triage fix (31 F1).* Every published package whose wheel this change alters
  takes one minor bump against its version on `dev`, as `RELEASING.md`'s versioning policy
  sets for a change below 1.0: `arkhai-kit-capability-shape` 0.3.0, `arkhai-compute` 0.2.0,
  `arkhai-bare-metal` 0.14.0, `arkhai-bare-metal-storefront` 0.23.0, `arkhai-vms` 0.8.0,
  `arkhai-vms-listings` 0.8.0, `arkhai-vms-settlement` 0.4.0, `arkhai-vms-storefront`
  0.23.0, `arkhai-core-storefront-client` 0.28.0, `arkhai-compute-provisioning-contracts`
  0.11.0, `arkhai-compute-provisioning` 0.21.0, `arkhai-compute-provisioning-ansible`
  0.5.0, and `arkhai-compute-provisioning-service` 0.19.0. `arkhai-core-registry` is not
  bumped: `filter-spec.yaml` is copied into its image, not built into its wheel. Lower
  bounds rise where a consumer needs the new behaviour: `arkhai-compute`, `arkhai-vms`, and
  `arkhai-bare-metal` on `arkhai-kit-capability-shape>=0.3.0` (a required field only in a
  named family) and the two domains on `arkhai-compute>=0.2.0`; `arkhai-vms-listings` on
  `arkhai-vms>=0.8.0` (`vm_listing_resource_shape`); `arkhai-bare-metal-storefront` on
  `arkhai-bare-metal>=0.14.0`; `arkhai-vms-storefront` on `arkhai-vms>=0.8.0`,
  `arkhai-vms-listings>=0.8.0`, and `arkhai-vms-settlement>=0.4.0` (lease terms without
  GPU keys); `arkhai-compute-provisioning` on contracts `>=0.11.0`, since it builds a
  `HostResponse` without the GPU fields contracts 0.10.0 requires; the provisioning
  service on contracts `>=0.11.0`, `arkhai-compute-provisioning>=0.21.0`, and
  `arkhai-compute-provisioning-ansible>=0.5.0`, since an `InventoryHost` without GPU
  fields refuses the older parser's entries. Two packages whose source this change leaves
  alone take a patch bump for a raised bound: `arkhai-compute-provisioning-client` 0.8.1 on
  contracts `>=0.11.0`, since it parses a `HostResponse` a 0.11.0 service sends without
  GPU fields, and `arkhai-kit-capability-admissibility` 0.1.1 on
  `arkhai-kit-capability-shape>=0.3.0`, since it splits a shape omitting the GPU family
  only under 0.3.0. The unpublished e2e suite parses host responses too, so it requires
  contracts `>=0.11.0`. Exact pins moved: the VM storefront's
  `arkhai-bare-metal-storefront==0.23.0` and the provisioning service's
  `arkhai-core-storefront-client==0.28.0`. Consumers whose own code works with either
  version keep their bounds: the buyers, which on older listing and domain packages still
  run but cannot read a GPU-less listing, and the provisioning adapters, which use no host
  GPU field.
  `make lock` refreshed every lock; it changed only internal package versions.
  Checks: `make check-packaging` passes (lock, image-install, and architecture rules); root
  `make test`, every unit and integration suite, exited 0 on the final manifests and locks;
  `make check-change` passes. Fresh-context check: every changed published package bumped
  once, by a minor, and no stale exact pin; it found the provisioning client's and the
  admissibility kit's bounds still admitting a version that misbehaves, and the e2e
  sentence false (the suite parses host responses), all three now fixed; it noted the VM
  storefront's direct `arkhai-bare-metal>=0.10.0`, which its `==0.23.0` pin on the
  bare-metal storefront already lifts to 0.14.0, left as it is. When `dev` is merged
  into this branch before closeout, each of these bumps is rechecked against the merged
  `dev` version, and a package `dev` has since bumped is bumped again from it, its pins
  moving with it.

## 8. A GPU-less VM deal end to end

Delivers the VM lane's proof that a GPU-less stated shape is published, discovered, excluded
from GPU queries, and settled through mock provisioning (D11; deltas `storefront-publication`
"A pool states a shape with no GPUs" and `registry-discovery` "The compute listing shape does
not require GPU fields").

Files: `e2e-tests/tests/e2e/roles/scenarios/vms/test_listing_shapes.py`, and
`host_registry.py` for the scenario's declaration.

- [x] 8.1 Extend `test_listing_shapes.py` with a step after its existing ones: the pool's
  hint states one GPU-less shape `{cpu: {count: 8}, memory: {gib: 32}}` against a member
  declaring vCPU and memory and no GPU; one publication cycle publishes it with no GPU key in
  the storefront's and the registry's listing; a buyer `vcpu_count>=8` query finds it and a
  `gpu_count>=1` query does not; `market buy`, discovering it through the vCPU query,
  negotiates, escrows, settles, and provisions it to ready through mock provisioning, and the
  site's reservation holds the shape's vCPU and memory and no GPU. Update the module
  docstring's numbered steps.
  *Written; runs at validation.* Stage `TestStage09_ShapeWithoutGpus`, after stage 08,
  needing only stage 00's `site_id`. Two departures from the plan's wording, each for
  determinism: the GPU-less member is in a pool of its own
  (`compute-e2e-listing-shapes-cpu-pool`, host `kvm-shapes-cpu`), not the stage-00 pool,
  because a stated GPU-less shape is feasible on the stage-00 GPU host too (D4), so a
  reservation there could land on either member; and the discovery queries are scoped by a
  region no other scenario declares (`Oregon, US`), since the filter spec's capacity
  filters have lower bounds only and other listings in the lane state vCPUs. The pool
  carries stage 00's `pricing` hint, keyed by GPU model, which a GPU-less shape cannot use
  (D8), so a storefront override states that hint's flat clause, which also keeps the
  stage off the storefront's configured default rate; `09g` removes it. Stages: `09a`
  declares the pool, host, and a declaration of `{vcpu_count: 16, ram_gb: 64, disk_gb:
  200}` with no GPU, and writes the override, checked against the live projection; `09b`
  one cycle publishes `{vcpu_count: 8, ram_gb: 32}` with no `gpu_count`, `gpu_model`, or
  `disk_gb` at the storefront and the registry; `09c` `region="Oregon, US" vcpu_count>=8`
  finds one listing and `… gpu_count>=1` none; `09d` arms a completing create rule for the
  host; `09e` `market buy` through the vCPU query reaches `ready` (escrow and settlement
  are implied by `ready`, as in stage 04); `09f` the reservation's dimensions are exactly
  `{vcpu_count: 8, ram_gb: 32}` and the create job has `vm_vcpus` 8, `vm_ram` 32768, and no
  GPU count; `09g` the override's deletion is confirmed. `host_registry.py`'s
  `declare_e2e_capacity` and `provision_e2e_executor` take `sellable_units=None` with a
  capacity naming no `gpu_count`, so the site records no GPU mirror for the machine, and
  refuse `None` beside a `gpu_count`. The module docstring has step 9; the `e2e_listing_shapes`
  marker description and the pool-override dependency comment in `e2e-tests/pyproject.toml`
  name the new stage. Of the registry-discovery delta, this stage shows the GPU filter
  excluding the listing (`gpu_count`, not `gpu_model`) and a CPU-only query finding it;
  the `validate-publish` dry run is section 3's integration evidence.
- [x] 8.2 **Verification checkpoint.** Run `make test-e2e-unit` and `make
  check-comment-hygiene`; the scenario itself runs in the VM lane at validation.
  End-to-end: `e2e_listing_shapes` (8.1).
  Owed by validation: none beyond the pipeline's VM lane.
  *Done.* `make test-e2e-unit`: 169 passed (it does not import the scenario modules, and
  neither compiling nor collecting the module was allowed in this session, so stage 09's
  first import and run are the VM lane's at validation). `make check-change`, comment
  hygiene included, and `make check-packaging` pass (`e2e-tests/pyproject.toml` changed a
  comment and a marker description only); root `make test` exited 0 before the
  fresh-context check's fixes, which touched only the scenario, `host_registry.py`'s
  docstring, and that `pyproject.toml`, after which `make test-e2e-unit` and `make
  check-packaging` were rerun and pass. End-to-end, confirmed: `e2e_listing_shapes` stage
  09 is the section's scenario; no other marker exercises a GPU-less VM listing.
  Owed by validation: none beyond the pipeline's VM lane, confirmed.

  Fresh-context check: no runtime problem found by reading (imports, fixtures, client
  signatures, the query grammar for `region="Oregon, US"`, state fields, the e2e source
  checks); no comment-hygiene or test-level problem. Fixed from it: the override's stated
  reason was false while the pool had no `pricing` hint (it now carries stage 00's); 09b
  did not assert the omitted `disk_gb`; 09a and 09g did not measure their writes; a
  duplicated listing helper; `provision_e2e_executor`'s docstring; the mock output's
  fixture comment; the `pyproject.toml` marker text. Declined: a dry-run preview before
  09b's cycle, which no stage of this module takes.

  *Handoff.* Stage 09 is unrun. A first failure there is this section's to fix. Two parts
  of it no in-process test has exercised: the real site ledger committing and leasing a
  VM reservation of zero GPU units (it reserves one in `test_shape_feasibility.py`), and
  the buyer CLI's ranking and display over a GPU-less listing.

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
| D8 a VM shape stating no GPUs takes only the override's and flat default's terms and the unkeyed families' rates, so a pool priced only per GPU model leaves it with no settlement option, refused as `no_settlement_option` | `openspec/specs/storefront-publication/architecture.md` — "Listing shapes and the storefront's authority", beside the paragraph on family rates or, failing one, after the D4 paragraph below | |
| D4 a GPU machine's spare server resources may sell as VMs: the mechanisms are neutral and nothing forbids it | `openspec/specs/storefront-publication/architecture.md` — "Listing shapes and the storefront's authority", after the paragraph on feasibility | |
| D4 the resource type is the category a claim matches by equality, `compute.gpu` for every VM declaration | `openspec/specs/site-capacity/spec.md` — "Resource-pool projection metadata", via archive | |
| D6 a VM listing resource carries no GPU key when its shape states no GPUs; one dispatch rule decides a resource payload's kind | `openspec/specs/storefront-publication/architecture.md` — "Listing shapes and the storefront's authority", after the paragraph on a published dimension being a commitment | |
| D7 bare-metal machines without GPUs; claims with no attributes | `openspec/specs/storefront-publication/spec.md` — the two bare-metal requirements, via archive; `openspec/specs/storefront-publication/architecture.md` — "Bare-metal listing shapes", the paragraphs beginning "A bare-metal seller sells one whole machine" and "The commitment differs from VM's"; `docs/bare-metal-seller-quickstart.md` — "Start and inspect", the paragraph saying `gpu_count` and `gpu_model` are required | |
| D3 the compute listing schema requires only `region`; GPU filters exclude GPU-less listings | `openspec/specs/registry-discovery/spec.md` — the added requirement, via archive | |
| D5 a host record describes no hardware; retired fields and INI variables are ignored | `openspec/specs/physical-provisioning/spec.md` — the three requirements, via archive, and its Evidence section; `openspec/specs/site-capacity/architecture.md` — "Declared capacity and connection identity", the paragraph beginning "The alternatives each left capacity"; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Definition documents", the sentence beginning "`gpus=` and `gpu_model=` are descriptive"; `docs/seller-quickstart.md` — "6. Live KVM provisioning", step 3's inventory paragraph; `docs/development/VALIDATION_RUNBOOK.md` — the host registration body and inventory line that carry GPU fields | |
| D5 the host column drop is fail-forward, its rollback restores the pre-upgrade backup, and why the expand/contract rule does not govern it | `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Migrations at startup", beside the VM storefront's fail-forward upgrade | |
| The resource type as the compute-shape category; bare metal's `compute.bare-metal`; null-published absent fields | `docs/development/ROADMAP.md` — Goal 2's open-gap table, as unowned rows | |
| The registry's `exists:false` cannot express absence | `openspec/changes/README.md` — "Unowned work found by `gpu-optional-compute-shapes`" under the Goal 2 campaign | |
