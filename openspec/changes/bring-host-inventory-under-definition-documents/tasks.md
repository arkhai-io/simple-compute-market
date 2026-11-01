# Tasks

Planned against the design settled in `design.md` and advanced by
`reviews/19-design-external.triage.md`. Every implementation task answers to a
decision D1–D14, a delta requirement under `specs/`, or a repository obligation
cited at the task: `openspec/README.md#plan-closeout-requirements`, the task rules
in `openspec/config.yaml`, `docs/development/TESTING.md`'s level definitions, and
`docs/development/BUILD_AND_PACKAGING.md`.

Test levels follow `docs/development/TESTING.md`: unit; library integration (a
kit's service API against a real database); persistence integration (the
provisioning service's own startup steps against file-backed SQLite, in its
`tests/integration`, without the app); application integration (the in-process
app through its typed clients); and system (the `e2e-tests` markers).

Order: 1 → 7, then the closeout, 8. Sections 1–3 deliver the family host
document, its routes, and its client (D2, D5, D7, D9, D12, D14); sections 4–5
wire it into startup and the deployments and retire startup INI seeding (D1, D3,
D6, D8, D2's retirement); section 6 carries the change-workflow tooling fixes
D11 records; section 7 drafts the operator documentation the code change makes
false. Each section needs only the sections before it. No dependency gates
implementation. The permanent specification, architecture companions,
`ARCHITECTURE.md`, and the roadmap are written at closeout.

## 1. Host definitions contracts

Delivers the wire models and route contracts of the host definitions document,
its import, and its export, with no behaviour behind them yet (D2, D9, D12, D14;
deltas "A host definitions entry declares the whole host", "A host definitions
document is validated whole and carries no credential", "The host registry
exports a canonical host definitions document").

Files: `provisioning/compute/contracts/src/compute_provisioning_contracts/{hosts.py,
routes.py,__init__.py}`; `provisioning/compute/contracts/tests/`.

- [ ] 1.1 Add the import's request and response models beside `HostCreate` in
  `hosts.py` (D14), following `market_site`'s
  `CapacityDefinitionsImportRequest`/`CapacityDefinitionsImportResponse`: the
  request carries `yaml_text` and `validate_only`; the response carries whether
  it applied, the created, updated, and unchanged host ids, the registered host
  ids the document does not name, and every problem, each with a `path`, a
  `code`, and a message. Name the problem codes the kit will emit as constants in
  the contracts package, `pool_change_refused` among them, so the service, the
  client, and tests share one spelling. Unit: the models round-trip, and a
  response with problems and `applied: false` validates.
  *Implemented, left unchecked by the return below.* `hosts.py` holds `HostDefinitionsImportRequest`,
  `HostDefinitionsImportResponse` (`applied`, `diff`, `not_named`, `problems`),
  `HostDefinitionsDiff`, `HostDefinitionProblem` (`path`, `code`, `message`;
  `code` read as text so an unknown newer code parses), and the codes as
  `HostDefinitionProblemCode`, a `StrEnum`. Beyond the task, per D8, the entry
  model is here too: `HostDefinition` and `HostDefinitionConnection`, both
  `extra="forbid", strict=True` in their own configuration, so no reader can
  validate an entry leniently, with `connection.version` required; the models
  refuse `connection.secrets` as an undefined field, and section 2's document
  validation is to report it as `connection_secrets`. The not-named hosts are a
  top-level `not_named` rather than a diff list, since they are not a change.
  Unit (`contracts/tests/unit/test_host_definitions.py`): the entry and import
  models round-trip; validation without any caller flag refuses a null or quoted
  value and any undefined field at its location; a refused response with two
  problems parses; an unknown code parses — passed.
- [ ] 1.2 Add the two route contracts to `routes.py` (D12, D14):
  `GET /api/v1/hosts/definitions/export` (`provisioning_host_definitions_export`)
  and `POST /api/v1/hosts/definitions/import`
  (`provisioning_host_definitions_import`), both admitting the administrator
  like every provisioning route, and add them wherever the module lists the host
  operations. Confirm the existing `GET /api/v1/hosts/(?P<host>[^/]+)` pattern
  cannot match `/api/v1/hosts/definitions/export` — it matches one segment, and
  the path has two — and say so in a unit assertion that resolves both paths to
  their own contracts. Unit: the route table resolves each new path and method
  to its operation, and the host-get contract does not claim either.
  *Implemented; its unit evidence passes, but the service suite fails on it, so
  the section returns to planning (notes below).* Both contracts sit among the
  host routes in
  `PROVISIONING_ROUTE_CONTRACTS` and in `ADMIN_PROVISIONING_OPERATIONS`, so each
  admits the administrator alone, like every host route. Unit
  (`test_host_definitions.py`): each path and method resolves to its own
  operation with roles `("admin",)`; neither `provisioning_host_get` nor
  `provisioning_host_update` matches either path; `GET /api/v1/hosts/definitions`
  still resolves to `provisioning_host_get`, so no host name is reserved — passed.
- [ ] 1.3 **Verification checkpoint.** Unit: the contracts suite
  (`make test-compute-provisioning-contracts`). `make check-comment-hygiene`.
  End-to-end: none — the models carry no behaviour, and no scenario calls the
  routes. None is owed.
  *Not passed.* `make test-compute-provisioning-contracts`: 126 passed. `make
  check-comment-hygiene`: OK. `make check-packaging`: OK. `make test`: failed in
  `make test-provisioning` (2 failed, 597 passed in its unit run), and stopped
  there, so the suites after it did not run. End-to-end: confirmed none; no
  marker in `e2e-tests/` calls either route. None is owed.

Section 1 notes:

- **The plan is wrong: task 1.2 cannot land before section 3.** The service's
  unit suite holds every contract in the composed route table to a mounted
  route:
  `provisioning/compute/service/tests/unit/test_route_binding.py::test_every_contract_resolves_to_a_mounted_route`
  fails for `provisioning_host_definitions_export` and
  `provisioning_host_definitions_import` ("no mounted GET route serves
  /api/v1/hosts/definitions/export", and the same for the POST). The family's
  contracts reach that table through `assemble_provisioning_route_table`, so a
  family route contract and its controller binding must land in one commit.
  Section 1's premise, "route contracts … with no behaviour behind them yet",
  does not hold for the routes; it does for the models (1.1), which nothing
  binds. Recommended amendment: move 1.2's route contracts and their unit
  assertions into section 3, beside 3.1's binding, and keep 1.1 in section 1.
  Merging sections 1–3 into one commit would also pass, at the cost of
  per-section review. The work-in-progress commit carries 1.1 and 1.2 as
  implemented here.
- **Section 2 work begun in the same commit, untested beyond the existing
  suites.** `compute_provisioning/hosts/service.py` gained
  `HostAuthority.put_host_in_session` (the session-scoped write 2.2 asks for,
  with the codec-normalized equality 2.3 needs), `UnknownPoolError` (a
  `ValueError`, so existing callers keep catching it), `HostChange`,
  `serves_connection`, `host_ids_in_session`, and `session()`; `apply_inventory`
  is rebuilt on `put_host_in_session` with no change of behaviour; and
  `hosts/connection.py`'s `ConnectionCodecs` gained `serves(kind, version)`. No
  test of the new methods exists yet. `make test-compute-provisioning`: 281
  passed; `make test-compute-provisioning-ansible`: 134 passed — the existing
  `apply_inventory` tests hold on the rebuilt path.
- **Section 2 needs a relock this session could not make.** `hosts/definitions.py`
  imports `yaml`, so `provisioning/compute/pyproject.toml` must declare `pyyaml`
  (AGENTS.md, "Package and dependency discipline"); it is already in that
  project's lock, through `arkhai-kit-site`. Declaring it changes the project's
  requirements, so its lock must be rewritten by `make lock`, which refuses this
  session's uv, 0.11.32: the locks need uv 0.12 or newer, and updating uv
  (`uv self update 0.12.19`) was not permitted. Running a project's `make
  reinit` after the declaration would rewrite the lock with the older uv, which
  the repository refuses, so the next session declares `pyyaml` and relocks
  only with uv 0.12 or newer.
- **No version bump yet, and no task owns one.** RELEASING.md's policy gives a
  minor bump to each package these sections change, against its version on
  `dev`: contracts 0.12.0 → 0.13.0, the kit (`provisioning/compute`) 0.23.0 →
  0.24.0, the client 0.9.1 → 0.10.0, and the service 0.21.0 → 0.22.0, each
  dependent's lower bound raised to the version whose API it uses. A bump moves
  every exact pin, so `make lock` must rewrite the locks (`make check-locks`
  refused the contracts bump alone in eleven projects), and this session's uv,
  0.11.32, cannot. The bump is reverted here; without it every lock matches its
  project and `make check-packaging` passes. Recommended for the plan's
  amendment: a task owning the bumps, the `pyyaml` declaration below, `make
  lock`, and `make check-packaging`, in the first section that runs with uv 0.12
  or newer.
- **Fresh-context check.** Run on this section's diff before these notes were
  rewritten. It found the `make test` failure above and the missing task for the
  version bump, both now recorded; a response docstring that gave a structurally
  invalid document a diff (corrected: its `diff` and `not_named` are empty); a
  version rationale that assumed a default served version (corrected to D2's
  reason); two accounts of how `secrets` is refused (the docstring now names the
  model's refusal and the document's code); an uncommented `INVALID_VALUE`
  (commented); and that strictness rested on each caller's `strict=True` flag
  (the models now carry it, and the tests pass no flag). It found the models and
  routes consistent with D2, D8, D9, D12, D14 and the deltas, and nothing in
  layering, comments, or test level.

## 2. The family host document

Delivers the document's parsing, two-stage validation, codec-normalized equality,
session-scoped apply, and export in the host authority, and the route-service
operations the service binds (D2, D4, D5, D7, D8, D9, D12, D14; deltas "A host
definitions entry declares the whole host", "A host definitions document retains
the hosts it does not name", "A host definitions document is validated whole and
carries no credential", "The host registry exports a canonical host definitions
document"; `resource-pool-management` delta "Explicit valid host membership").

Files: `provisioning/compute/src/compute_provisioning/hosts/{definitions.py (new),
service.py,route_service.py,__init__.py}`; `provisioning/compute/tests/unit/
{test_host_definitions.py (new),test_host_route_service.py}`;
`provisioning/compute/pyproject.toml` if a YAML dependency is not yet declared.

- [ ] 2.1 Structural validation (D2, D7, D9). A new `hosts/definitions.py` parses
  a document's text into entries, reporting every structural problem with its
  location, as `market_site`'s capacity documents do
  (`kit/site/src/market_site/capacity_definitions.py`): unparseable YAML; a root
  that is not a mapping, an empty document included; a missing or non-list
  `hosts`; an unknown field at the root, in an entry, or in its `connection`; a
  missing `host_id`, `connection`, `connection.kind`, or `connection.version`; a
  `host_id` named twice; a value of the wrong type, strictly (a quoted number is
  an error; `enabled: null` is one); and any `connection.secrets`. `pool_id:
  null` reads as an omitted pool; `hosts: []` is valid. Unit: one case per
  problem, a document with several problems reporting all of them with their
  paths, and the delta's scenarios "A document has several structural problems",
  "A document has no hosts list", and "An entry carries key material".
- [ ] 2.2 Session-scoped writes in the host authority (D5, D8). Give
  `HostAuthority` a form of its writes that joins a caller's session and never
  commits, through the same codecs and pool-change hooks as today; keep
  `apply_inventory` and the single-host writes behaving as they do now, built on
  it where that removes a duplicate path rather than adding one. A pool move made
  through it runs every hook exactly as `_move_to_pool` does.
  Library integration (the kit's tests against SQLite, as
  `test_host_route_service.py` composes the authority): a write in a caller's
  session is invisible until the caller commits, and a hook's refusal in it
  raises `PoolChangeRefusedError` without committing.
- [ ] 2.3 Stored-state evaluation, equality, and apply (D4, D5, D7). For a
  structurally valid document, evaluate every entry in the caller's session:
  refuse an unknown pool; build the connection through its kind's codec with the
  stored connection as `previous` and report a codec refusal (an unknown kind, a
  version not served, a new host naming no key, an entry naming no `key_path`
  for a host whose key is a key file) at that entry's path; compare the built
  connection's kind, version, canonical public fields, and protected-value
  schemes, and the entry's pool and enabled state, with the stored host; write
  nothing for an equal entry; otherwise register or wholly replace the host
  (omitted `pool_id` unplaces, omitted `enabled` enables), moving its pool
  through the hooks. Continue past a hook's refusal, coding it
  `pool_change_refused`, so every refusal is reported, and return a diff —
  created, updated, unchanged, the registered hosts not named — with every
  problem. The caller decides whether to commit; the module never does, and
  leaves its writes for the caller to roll back on any problem.
  Library integration: each scenario of "A host definitions entry declares the
  whole host" (omitted pool unplaces through the hooks, omitted `enabled`
  enables, an equal entry writes nothing and leaves `updated_at`, an entry
  omitting `ssh_port` and `ssh_user` equals a host stored with 22 and `root`, a
  key-file host with no `key_path` refused, a protected key kept, a new host
  naming no key refused, an empty list reporting every host not named); "A
  document stops naming a host"; "A document has structural and stored-state
  problems"; a hook refusal and an unknown pool in one document both reported; and
  the `resource-pool-management` scenario "A host definitions entry omits the pool
  of a placed host" with a refusing hook leaving every host unchanged.
- [ ] 2.4 Export (D12). Render every registered host as a host document: entries
  ordered by `host_id`, stating `pool_id` and `enabled` always and the
  connection's kind, version, and canonical public fields, with no secret; a host
  holding a protected key states no `key_path`. Omit a host whose connection kind
  no registered codec serves, or whose stored version its codec does not serve.
  Library integration: "An operator exports the registry and imports it
  unedited" (every host unchanged, nothing written), "A host holds a protected
  key", "A host is stored at an unserved connection version" (no entry; importing
  the export reports it not named), and "A host's connection kind is not served".
- [ ] 2.5 Route-service operations (D12, D14). `HostRouteService` gains
  `export_definitions()`, returning the document text, and
  `import_definitions(body)`, which opens its own session, evaluates the
  document, commits only an applying request with no problem, and returns the
  response model with whether it applied; it raises no error for a problem, so
  the binding chooses 422 or 200. Unit (`test_host_route_service.py`): an
  applying request with a problem applies nothing and reports `applied: false`;
  validate-only applies nothing and reports the planned diff; a clean applying
  request commits.
- [ ] 2.6 **Verification checkpoint.** Unit and library integration: the family
  kit's suite (`make test-compute-provisioning`), including
  `test_host_definitions.py` and `test_host_route_service.py`; the Ansible
  distribution's suite (`make test-compute-provisioning-ansible`), since
  `apply_inventory` is rebuilt on the session-scoped writes; `make test`. Run
  `make check-packaging` if `provisioning/compute/pyproject.toml` gained a
  dependency. `make check-comment-hygiene`.
  End-to-end: none — the document reaches no deployed surface until section 3.
  None is owed.

## 3. Host definitions routes and typed client

Delivers the export and import on the running service and through the typed
family client (D12, D14; deltas "A host definitions document is validated whole
and carries no credential", "The host registry exports a canonical host
definitions document").

Files: `provisioning/compute/service/src/compute_provisioning_service/controllers/
hosts_controller.py` (or a sibling controller registered beside it);
`provisioning/compute/service/src/compute_provisioning_service/main.py` where it
mounts host routes; `provisioning/compute/client/src/compute_provisioning_client/
client.py`; `provisioning/compute/client/tests/`;
`provisioning/compute/service/tests/integration/{test_host_definitions_api.py
(new),test_provisioning_client_endpoint_coverage.py}`;
`provisioning/compute/service/tests/unit/{test_route_table_composition.py,
test_provisioning_client_contract.py}` as the route table requires.

- [ ] 3.1 Bind the routes (D12, D14). `GET /api/v1/hosts/definitions/export`
  answers the document as `application/yaml`; `POST
  /api/v1/hosts/definitions/import` answers 422 with the response model for an
  applying request with any problem, and 200 otherwise, validate-only included.
  Register both before any `/{host_id}` route if the router would otherwise
  shadow them, and add their contracts to the service's composed route table.
  The single-host `PUT` keeps answering a hook refusal with 409. Unit: route
  table composition holds the two contracts once each.
- [ ] 3.2 Typed client methods (D12, D14). `compute_provisioning_client`'s async
  and sync clients gain `export_hosts()`, returning the document's text, and
  `import_host_definitions(yaml_text, *, validate_only=False)`, returning the
  response model for 200 and for 422 alike, so a caller reads `applied` and
  `problems` rather than catching an error. Client unit tests cover both
  methods' requests and their 200 and 422 parsing; the endpoint-coverage test
  names both routes.
- [ ] 3.3 Application integration through the typed client
  (`test_host_definitions_api.py`, D12, D14): a document registering two hosts
  applies and reports them created; re-importing it reports them unchanged;
  "An operator explicitly imports an unchanged document" (reconciled, and no
  `hosts` digest written by the route); "A pool-change hook refuses a move on
  import" (422, `pool_change_refused`, no host changed), using VM's relay hook as
  `test_host_pool_moves_api.py` does; "A document has a hook refusal and another
  stored-state problem" (422, both reported); "An operator validates a document"
  (200, planned diff, nothing applied); export then unedited import reporting
  every host unchanged; an unauthenticated request to either route refused.
- [ ] 3.4 **Verification checkpoint.** Unit: the client's suite (`make
  test-compute-provisioning-client`) and the service's route unit tests.
  Application integration: `test_host_definitions_api.py` and the endpoint
  coverage test, in the service's suite (`make test-provisioning`). `make test`.
  `make check-comment-hygiene`.
  End-to-end: none — no lane calls the routes, and the application-integration
  cases prove them through the typed client against the composed app. None is
  owed.

## 4. Startup reconciliation and the retired inventory settings

Delivers the `hosts` document kind at startup in place of the inventory seed, and
the retirement of startup INI seeding (D1, D2, D6, D7, D8; deltas "Host
definitions are imported from a mounted document", "Startup reads no INI
inventory", and the modified "Bare-metal inventory binds an existing provider
pool", "Execution inventory comes only from the registered host record", "Host
writes declare no capacity", and "Capacity definitions are imported from a
mounted document").

Files: `provisioning/compute/service/src/compute_provisioning_service/{config.py,
settings.toml,app_runtime.py,services/definition_documents.py}`; its
`config/{config-docker.yml,config-local.yml.example,config-mock.yml,config.yml}`
where they state or describe the inventory settings;
`provisioning/compute/service/Makefile`; the service's tests and fixtures naming
`inventory_ini`, `inventory_path`, or `resolved_inventory_path`
(`tests/integration/{conftest.py,test_host_writes_declare_no_capacity_api.py,
test_test_controller.py,test_vms_api.py}` and any other the search finds); new
`tests/integration/test_host_definitions_startup.py`.

- [ ] 4.1 The `hosts` document kind (D1, D8). Add `host_definitions_path` to
  `settings.toml` (empty by default, with a comment describing the document as
  the capacity setting's does) and `Settings.resolved_host_definitions_path`
  (`None` when empty). `DefinitionDocumentImporter` gains
  `import_host_definitions()`, gated under the stable kind `hosts` by `_import`,
  whose applier evaluates the document in the importer's session through the
  family kit and raises, naming every problem, when there is any, so the digest
  is not recorded and the transaction rolls back; it logs the created, updated,
  and unchanged counts and names the registered hosts not named. Persistence
  integration (`test_definition_document_digest.py`): the `hosts` kind is
  recorded apart from pools, relays, and capacity.
- [ ] 4.2 The startup step (D6, D7, D8). Replace `seed-inventory` in
  `app_runtime.startup_steps()` with `import-host-definitions` at the same place —
  after `verify-pool-declarations`, before `import-capacity-definitions` — and
  remove `seed_inventory_if_empty` and its `parse_inventory_ini` import. Update
  the capacity importer's docstring, which says capacity runs "after host
  seeding". Persistence integration (`test_host_definitions_startup.py`, running
  the startup steps against file-backed SQLite as `test_pool_seed_api.py` and
  `test_pool_declaration_startup.py` do): "An operator adds a host to the
  document and restarts" (registered as stated); "An unchanged document is
  present at restart" (an API change survives); "The document names a pool the
  pool document creates"; a first document on a site with registered hosts and
  no recorded digest applies (D6); "Configured document is missing" (startup
  fails); "No host definitions are configured" (registered hosts unchanged); a
  document with a structural problem fails startup and records no digest, and the
  next start retries; "A pool-change hook refuses a move at startup" (startup
  fails naming the host, nothing applied, no digest); and the modified "Fresh
  selected-site inventory binds to a bare-metal pool" with a `bare_metal.ansible`
  pool document and an unknown pool failing startup.
- [ ] 4.3 Retire the inventory settings (D2). Add `inventory_ini` and
  `inventory_path` to `config.RETIRED_SETTINGS`, both replaced by
  `host_definitions_path`, so any statement in any layer refuses startup, an
  empty one included. Remove `Settings.resolved_inventory_path`. Remove every
  packaged statement: both keys and their comments in `settings.toml`,
  `inventory_path` in `config-docker.yml` and `config-local.yml.example`, the
  `PROVISIONING_INVENTORY_PATH` of the service `Makefile`'s local run target, and
  the inventory comment in `config-mock.yml` and `config.yml`. Update every test
  and fixture that sets either setting or `resolved_inventory_path`: the startup
  seed case in `test_host_writes_declare_no_capacity_api.py` becomes a host
  definitions document applied at startup declaring nothing ("Deployment
  configured only through host inventory"); `test_vms_api.py`'s dispatch case
  that sets `resolved_inventory_path` to a file naming an unregistered host
  (TESTING.md's "Host Requirement Enforcement" list) becomes a refused host
  document naming it, which dispatch refuses exactly as it refuses an unknown
  host ("A static inventory file names the host", as modified). Unit (`test_config.py`): each key refuses in a profile
  and through the `PROVISIONING_` environment layer, an empty `inventory_ini`
  included, naming `host_definitions_path`. Application integration
  (`test_retired_settings_startup.py`): the app's lifespan refuses either key
  before any other step; the packaged settings and every packaged profile start
  without a refusal ("The packaged configuration is started unchanged"). A
  repository search for `inventory_ini`, `inventory_path`, and
  `resolved_inventory_path` outside the retirement list, its tests, the Ansible
  distribution's transient inventory mechanics, and `openspec/changes/archive`
  finds nothing in the service.
- [ ] 4.4 **Verification checkpoint.** Unit: the service's `test_config.py`.
  Persistence integration: `test_definition_document_digest.py`,
  `test_host_definitions_startup.py`. Application integration:
  `test_retired_settings_startup.py`, `test_host_writes_declare_no_capacity_api.py`,
  `test_vms_api.py`, `test_test_controller.py`.
  Run the service's suite (`make test-provisioning`), `make test`, and `make
  check-comment-hygiene`.
  End-to-end: every VM lane scenario (`e2e_deal`, `e2e_deal_buyer_cli`,
  `e2e_buy`, `e2e_listing_shapes`, `e2e_compute_dynamic_listings`,
  `e2e_pool_declared_modes`, `multi_registry`, `e2e_vm_introduction`) boots
  provisioning on packaged configuration with no host document, so the pipeline
  proves that no packaged statement of a retired setting remains; the
  bare-metal lane's scenarios exercise startup with a configured document once
  section 5 lands. None proves the reconciliation itself, which persistence and
  application integration own; no scenario is owed.

## 5. Chart, compose, and deployment scripts

Delivers `definitions.hosts` in the provisioning chart, host documents in the
compose stacks and the bare-metal lane, and the removal of every deployment-side
statement of the retired settings (D2, D3; `deployment-state` delta "The
provisioning chart renders a host definitions document").

Files: `helm/charts/provisioning/{values.yaml,values.schema.json,
templates/configmap.yaml,templates/deployment.yaml,tests/test_render.py}`;
`helm/values.schema.json`'s provisioning section; `helm/scripts/topology-secrets.sh`;
`compose/seller.yml`; `domains/bare_metal/compose.yml`; the root `Makefile`'s
`e2e-bare-metal-dev-env` and the comment above `deploy-helm`;
`dev-env/bare-metal/hosts.ini`, replaced by a host document.

- [ ] 5.1 The chart (D3). Add `definitions.hosts: {}` to `values.yaml`, with its
  line in the header comment (retained when unnamed; an entry declares its whole
  host); remove `config.inventory_path` and correct the persistence comment that
  says hosts reseed "from the secret-overlay". `configmap.yaml` renders a
  non-empty value as `host-definitions.yaml` and sets `host_definitions_path`;
  `deployment.yaml` mounts it at `/app/config/host-definitions.yaml`. The schema
  refuses `config.host_definitions_path`, `config.inventory_path`,
  `config.inventory_ini` (already refused), and `config.relay_definitions_path`,
  accepts `definitions.hosts` as an object, and adds `host-definitions.yaml` to
  the names `configFiles` refuses. Mirror the refusals in the umbrella
  `helm/values.schema.json`'s provisioning `config`. Render tests: every scenario
  of the `deployment-state` delta, including "A release states the relay
  definitions path" and the ConfigMap checksum changing with the document; extend
  the existing per-kind tests' table with `hosts`. Run `make -C helm
  test-render`.
- [ ] 5.2 Deployment scripts and compose (D2, D3). `topology-secrets.sh` stops
  writing `inventory_ini: ""` and its comment; the provisioning-secrets profile it
  writes states nothing the mock profile needs, as a valid empty YAML mapping.
  `domains/bare_metal/compose.yml` mounts the host document named by
  `BARE_METAL_PROVISIONING_HOST_DEFINITIONS_FILE` and sets
  `PROVISIONING_HOST_DEFINITIONS_PATH`, in place of the inventory file and
  `PROVISIONING_INVENTORY_PATH`; the root `Makefile`'s `e2e-bare-metal-dev-env`
  prints the new variable; `dev-env/bare-metal/hosts.ini` becomes
  `dev-env/bare-metal/hosts.yaml` holding `hosts: []`, with its comment kept (a
  development fixture, deliberately empty, not for any real site).
  `compose/seller.yml` mounts an operator host document and sets
  `PROVISIONING_HOST_DEFINITIONS_PATH`, and its header comment stops describing an
  inventory baked into the image. Correct the `Makefile` comment above
  `deploy-helm` that says inventory content never passes through Helm values.
  Verify: `docker compose -f domains/bare_metal/compose.yml config` and `docker
  compose -f compose/seller.yml config` render with the lane's and a sample
  environment, and a search finds no `INVENTORY_PATH`, `INVENTORY_FILE`, or
  `inventory_ini` left in `helm/`, `compose/`, `domains/*/compose.yml`, `dev-env/`,
  or the root `Makefile`.
- [ ] 5.3 **Verification checkpoint.** Chart render: `make -C helm test-render`.
  `make test-deployment-packaging`, which runs it with the release tooling.
  `make test`. `make check-comment-hygiene`.
  End-to-end: the bare-metal lane (`e2e_bare_metal_publication`,
  `e2e_bare_metal_mock_deal`, `e2e_bare_metal_introduction`,
  `e2e_bare_metal_unbacked_introduction`, and, where its target is reachable,
  `e2e_bare_metal_payment_deal`) starts its site with the empty host document
  mounted, so it proves the compose wiring and that an empty document applies;
  the VM lane proves the topology script's profile no longer states a retired
  key wherever the Helm topology runs. No scenario applies a non-empty document,
  which section 4's persistence integration owns; none is owed.
  Owed by validation: `tests.yml`, job `test · test-deployment-packaging` —
  `make -C helm test-render` passes with the `definitions.hosts` render, mount,
  and path, and with every refused key.

## 6. Change-workflow tooling fixes

Delivers the three tooling fixes D11 records, accepted at the design review's
triage to land with this change.

Files: `.claude/change-steps.toml` (the orchestrator's edit);
`.agents/skills/change-design/SKILL.md`; `scripts/change_workflow/review.py`;
`scripts/tests/test_change_workflow_review.py`.

- [ ] 6.1 The design step's proposal-worktree rules (D11, records 07 R1 and 10
  R2). **The orchestrating session's edit, made on the owner's word before this
  section's session starts; the session commits it with this section.** In
  `.claude/change-steps.toml`, the design step's worktree rule names `origin/dev`
  rather than a local `dev`, and its write rules reach the proposal worktree and
  cover its `docs/development/ROADMAP.md`, found by testing against a real
  worktree, with no rule naming an absolute path. The session then makes
  `.agents/skills/change-design/SKILL.md`'s section 4 step 2 name the same
  command, `git worktree add ../<prerequisite>-proposal -b
  propose-<prerequisite> origin/dev`, and records in the section notes how the
  orchestrating session tested the write rules. Verify: `make
  check-agent-skills`.
- [ ] 6.2 The review wrapper's title (D11, record 18 R3). In
  `scripts/change_workflow/review.py`, take the first line that is a `# <kind>
  review … <change>` title as the review's start, drop anything before it (the
  transcript keeps it), and apply the existing section and finding checks to the
  rest unchanged; output with no such title is still rejected and kept with its
  transcript. Unit (`scripts/tests/test_change_workflow_review.py`, beside
  `test_rejected_output_is_kept_with_its_transcript`): a review preceded by a
  narrating line and a blank line is published from its title, and output with
  no title line is rejected.
- [ ] 6.3 **Verification checkpoint.** Unit: `pytest -q scripts/tests` (part of
  `make test-release-tooling`). `make check-agent-skills`. `make test`. `make
  check-comment-hygiene`.
  End-to-end: none — the workflow tooling is not deployed. None is owed.
  Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — its
  `test-release-tooling` step runs `scripts/tests` and passes.

## 7. Operator documentation drafts

Drafts the operator-facing documents sections 4 and 5 make false, so each
pipeline run of the implemented commits is described by its documents (D2, D3,
D6, D7, D12, D13, D14). Closeout's promotion (8.9) reconciles them with the
permanent documents it writes.

Files: `docs/development/DEPLOYMENT_AND_CONFIG.md`; `docs/seller-quickstart.md`;
`docs/bare-metal-seller-quickstart.md`; `domains/vms/provisioning/iac/README.md`;
`domains/vms/provisioning/iac/ansible/inventory/provisioning-hosts.example`.

- [ ] 7.1 `DEPLOYMENT_AND_CONFIG.md`, "Definition documents" (D13, D3, D7, D14):
  open with the method every kind follows, as D13 lists it — the validate-only
  pre-flight before a release included — and state each kind's own rules under
  it. Replace the "Host inventory is not a definition document" paragraph with a
  "Host definitions" subsection: the document's fields and an example, whole
  replacement per entry and what it restores, retention of unnamed hosts, no
  credential, the import and export routes, the startup order, a refused move
  keeping the service down until the edit is reverted under the chart's
  `Recreate`, and the upgrade path (drop `inventory_ini` and `inventory_path`,
  export, edit, mount). Correct the pool-and-capacity-only refusal sentence: every
  kind's path is refused under `config`.
- [ ] 7.2 The seller quickstarts, the IaC README, and the example INI (D2, D6,
  D12): `docs/seller-quickstart.md`'s section 4 step 2 and "Bring it up", and
  `docs/bare-metal-seller-quickstart.md`'s "Define the selected site" and
  "Configure public bindings", describe the host document, its compose variable,
  and the export-edit-mount upgrade, and keep the INI for Ansible host
  preparation and `POST /api/v1/hosts/import`; `domains/vms/provisioning/iac/README.md`
  and the header of `provisioning-hosts.example` say the INI is Ansible's own
  host list and the input of the import route, not what the service reads at
  startup. Verify: `make check-doc-citations CHANGE=bring-host-inventory-under-definition-documents`
  reports nothing these drafts introduced.
- [ ] 7.3 **Verification checkpoint.** `make check-doc-citations
  CHANGE=bring-host-inventory-under-definition-documents`; `make
  check-comment-hygiene`. A read of every changed document against the code of
  sections 1–5: the setting names, the routes, the response codes, the chart
  value, and the compose variables match.
  End-to-end: none — documentation only. None is owed.

## 8. Closeout

Confirm and promote the verified design, then archive last (D1–D14 and every
delta requirement). The eleven parts follow
`openspec/README.md#plan-closeout-requirements` in order. Closeout changes no
code: a part needing a code, lock, or test change returns the change to
implementation.

- [ ] 8.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene` and read
  every comment and docstring sections 1–7 added or rewrote — the new
  `hosts/definitions.py`, the importer's applier and docstrings, `settings.toml`'s
  `host_definitions_path` comment, `RETIRED_SETTINGS`, the chart's values comments,
  the compose headers, and `review.py` — for current-system rationale with no
  change, review, or migration narration. A needed correction returns to
  implementation.
- [ ] 8.2 **Import placement — confirm.** Check that every import sections 1–6
  added or touched is at module level unless a verified cycle or a recorded
  lazy-load reason keeps it local. A needed move returns to implementation.
- [ ] 8.3 **Documentation compliance.** Check D1–D14 against
  `openspec/README.md`'s placement rules and the promotion record: normative
  behaviour in the three deltas, rationale in the companions, repository shape in
  `ARCHITECTURE.md`, operator behaviour in `DEPLOYMENT_AND_CONFIG.md` and the
  quickstarts, test ownership in `TESTING.md`. Record a disposition for every
  decision, and check every promoted statement against the code.
- [ ] 8.4 **Narrative compression.** Compress section notes to final behaviour,
  validation evidence, deferred work (the two open questions), and destinations,
  moving any durable rationale into `design.md` first.
- [ ] 8.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, Goal 1 —
  "Consolidate physical-resource authority in the provisioning service": remove
  the open-gap row this change owns ("Host inventory seeds the host registry only
  when it is empty…"), and replace the current-state sentence "An inventory file
  seeds the host registry at first boot and is never read at execution" with
  hosts reconciled from a digest-gated host definitions document, exported and
  imported through the provisioning API. Per D10's open question: if
  `prove-relay-provisioning` and `admit-relay-proxies-by-grant` have not both
  landed on this branch by now, add the relay-pool mismatch (a declaration in a
  relay-backed pool naming a host placed under another relay) to Goal 1's open
  gaps as unowned; if they have landed, record which and whether they settled it.
- [ ] 8.6 **Campaign index currency.** Set this change's Goal 1 row in
  `openspec/changes/README.md` to `in closeout`, its notes naming the validation
  and the destinations; keep its graph line. Leave other rows' `Depends on` for
  archive cleanup. Run `make check-change-index`.
- [ ] 8.7 **Packaging.** Confirm `make check-packaging` and `make
  check-architecture-change CHANGE=bring-host-inventory-under-definition-documents`
  pass against the last implementation commit; the change touched `.claude/` and
  `.agents/` (section 6), so run `make check-agent-skills` too.
- [ ] 8.8 **End-to-end pipeline.** Confirm the pipeline passes at the last
  implementation commit and record the run, its result, and the scenarios that
  exercise this change: every VM lane scenario (packaged configuration with no
  host document and no retired setting) and every bare-metal lane scenario (an
  empty host document mounted through compose). If the pipeline cannot run for a
  reason unrelated to the change, record the blocker and its owner and treat the
  validations it gates as unrun.
- [ ] 8.9 **Promotion.** Write the permanent documents and the design-promotion
  record below:
  - `openspec/specs/physical-provisioning/architecture.md`: a section after "The
    host registry owns the connection", "Hosts are a reconciled declaration": why
    the host document is digest-gated, family-owned and format-neutral, why
    unnamed hosts are retained while disabling does not stop selling, why an entry
    replaces its whole host, and the first-document path through the export (D1,
    D4, D5, D6, D8, D12); and correct "Selected-resource execution", whose
    "Bootstrap inventory may import hosts" now means the host document.
  - `openspec/specs/resource-pool-management/architecture.md`, "Administrative
    reconciliation": the startup order names host definitions in place of
    seeding host inventory, and the one-process paragraph names the host
    document's import in place of the host-inventory seed.
  - `openspec/specs/site-capacity/architecture.md`: the statement that no host
    write declares capacity, "not an INI inventory applied at startup", names the
    host definitions document and the INI import route.
  - `docs/development/ARCHITECTURE.md`, "Resource pools": the paragraph "No host
    write places a host in a pool…" states that hosts reach the registry through
    the host API, the Ansible INI import, or a host definitions document
    reconciled at startup like pool and capacity documents.
  - `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Definition documents" (D13) and
    "Host definitions", and both seller quickstarts and the IaC README: reconcile
    section 7's drafts with the final code.
  - `docs/development/TESTING.md`, "Host Requirement Enforcement": the dispatch
    case's "configured inventory file naming the host" becomes the refused host
    document 4.3 tests.
  - The `physical-provisioning`, `deployment-state`, and `resource-pool-management`
    specs are written by the archive (8.11), and the record names them.
- [ ] 8.10 **Documentation citations.** Run `make check-doc-citations
  CHANGE=bring-host-inventory-under-definition-documents` after promotion and
  resolve every match; `keep-new-deliveries-off-disabled-hosts` is cited by name
  and exists on this branch once `dev` is merged in. Then run `openspec validate
  bring-host-inventory-under-definition-documents --strict`.
- [ ] 8.11 **Archival.** Archive last with `openspec archive
  bring-host-inventory-under-definition-documents -y`, which merges the three
  deltas into `openspec/specs/`. Then, in the same commit, make the edits the
  merged text cannot carry: retitle the two scenarios a modified requirement
  could not rename in `openspec/specs/physical-provisioning/spec.md` — "The
  inventory file seeds the host registry" to "A changed host definitions document
  registers its hosts", and "Fresh selected-site inventory binds to a bare-metal
  pool" to "A fresh site's host document binds to a bare-metal pool" — and update
  that spec's evidence paragraph, which cites "the startup inventory seed", to
  cite the host definitions startup and import tests. Run `bunx
  @fission-ai/openspec@1.14.0 validate --specs --strict` afterwards. The change
  row then links its archive directory.

**Closeout verification:** the eleven recorded outcomes, valid synchronized specs,
and a clean `make check-change-index`.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Host inventory is a digest-gated definition document (D1), its startup order (D8), first-document behaviour (D6), whole-document failure (D7) | `openspec/specs/physical-provisioning/spec.md`, "Host definitions are imported from a mounted document" and "A host definitions document is validated whole and carries no credential" (by the archive) |
| The YAML entry format, whole replacement, codec-normalized equality (D2, D5) | `openspec/specs/physical-provisioning/spec.md`, "A host definitions entry declares the whole host"; `openspec/specs/resource-pool-management/spec.md`, "Explicit valid host membership" (by the archive) |
| Unnamed hosts are retained (D4) | `openspec/specs/physical-provisioning/spec.md`, "A host definitions document retains the hosts it does not name" (by the archive) |
| No credential in the document (D9) | `openspec/specs/physical-provisioning/spec.md`, "A host definitions document is validated whole and carries no credential" (by the archive) |
| Startup INI seeding retired (D2) | `openspec/specs/physical-provisioning/spec.md`, "Startup reads no INI inventory" (by the archive) |
| The chart's `definitions.hosts` and refused keys (D3) | `openspec/specs/deployment-state/spec.md`, "The provisioning chart renders a host definitions document" (by the archive) |
| Export and import routes (D12, D14) | `openspec/specs/physical-provisioning/spec.md`, "The host registry exports a canonical host definitions document" and "A host definitions document is validated whole and carries no credential" (by the archive) |
| Why hosts are a reconciled, family-owned declaration (D1, D4, D5, D6, D8, D12) | `openspec/specs/physical-provisioning/architecture.md`, "Hosts are a reconciled declaration" (8.9) |
| The general definition-document method (D13) and the operator account | `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Definition documents" (7.1, 8.9) |
| Startup order with host definitions | `openspec/specs/resource-pool-management/architecture.md`, "Administrative reconciliation" (8.9) |
| How hosts reach the registry | `docs/development/ARCHITECTURE.md`, "Resource pools" (8.9) |
| No startup INI seeding | `docs/development/ROADMAP.md` Goal 1 (8.5); `openspec/specs/site-capacity/architecture.md` (8.9); both seller quickstarts and `domains/vms/provisioning/iac/README.md` (7.2, 8.9) |
| D10 (no same-pool rule) and the D4 revisit trigger | `design.md` Open Questions; `docs/development/ROADMAP.md` Goal 1 if the relay changes have not landed (8.5) |
| D11 tooling fixes | Workflow tooling itself (`.claude/change-steps.toml`, `.agents/skills/change-design/SKILL.md`, `scripts/change_workflow/review.py`); no permanent document |
