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

## 1. Host definitions models, versions, and the relock

*Replanned after the first implementation run returned to planning (workflow log
seq 38–40, the owner's direction at seq 40).* The service suite requires every
family route contract to have a mounted route, so the two route contracts move
to section 3 (3.1), beside the controller binding that serves them. Their
former task 1.2 is replaced by the version bumps, the `pyyaml` declaration, and
the relock that no task owned. The container's uv is now 0.12.19, so `make lock`
can run.

Delivers the wire models of the host definitions document and its import (D2,
D9, D14; deltas "A host definitions entry declares the whole host" and "A host
definitions document is validated whole and carries no credential"), together
with this change's package version bumps and its relock (RELEASING.md,
"Versioning policy"; AGENTS.md, "Package and dependency discipline";
`docs/development/BUILD_AND_PACKAGING.md`).

Files: `provisioning/compute/contracts/src/compute_provisioning_contracts/{hosts.py,
routes.py,__init__.py}`; `provisioning/compute/contracts/tests/unit/
test_host_definitions.py`; the `pyproject.toml` of `provisioning/compute/contracts`,
`provisioning/compute`, `provisioning/compute/client`, and
`provisioning/compute/service`; every lock `make lock` rewrites.

- [x] 1.1 Add the import's request and response models beside `HostCreate` in
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
  *Checked by the second run.* The fresh-context check found the first run's
  evidence narrower than its claim; the second run added unit cases for every
  bound (an empty `host_id`, `pool_id`, or `kind`, a version below 1, a
  non-mapping `public` or `connection`), a missing `host_id`, `connection`, or
  `kind`, and a refused response with a problem round-tripping. Unit, the
  contracts suite (`make test-compute-provisioning-contracts`): 131 passed, with
  the route assertions moved out by 1.3. The `HostDefinitionConnection`
  docstring now says strictness covers the fields the model defines: `public`
  holds the kind's fields, which its codec validates under its own rules (see
  the section notes on the `ssh` codec).
- [x] 1.2 Versions, the `pyyaml` declaration, and the relock (RELEASING.md,
  "Versioning policy"; AGENTS.md, "Package and dependency discipline").
  - Bump each package this change changes once, minor, against its version on
    `dev`: `arkhai-compute-provisioning-contracts` 0.12.0 → 0.13.0,
    `arkhai-compute-provisioning` (`provisioning/compute`) 0.23.0 → 0.24.0,
    `arkhai-compute-provisioning-client` 0.9.1 → 0.10.0, and
    `arkhai-compute-provisioning-service` 0.21.0 → 0.22.0. First confirm each
    `dev` version with `git show origin/dev:<project>/pyproject.toml`. The service
    and client change in sections 3 and 4, but each package is bumped once per
    change, so all four bumps belong here.
  - Raise each dependent's lower bound to the version whose new API it uses:
    the kit's and the client's bounds on the contracts to `>=0.13.0`; the
    service's bounds on the contracts to `>=0.13.0` and on the kit to `>=0.24.0`;
    and its dev-group bound on the client to `>=0.10.0`. The Ansible distribution
    uses none of the new API, so its bounds stay.
  - Declare `pyyaml` in `provisioning/compute/pyproject.toml`'s dependencies,
    since section 2's `hosts/definitions.py` imports `yaml`. It is already in that
    project's lock, through `arkhai-kit-site`.
  - Run `make check-uv-version`, then `make lock`, and commit every lock it
    rewrites.

  Verify: `make check-locks` and `make check-packaging` pass.
  *Done.* Each `dev` version confirmed with `git show origin/dev:…` as planned;
  bumped and bounded as listed; `pyyaml>=6.0` declared in the kit, with a
  comment naming the host definitions document. `make check-uv-version` passed
  (uv 0.12.19), and `make lock` rewrote the locks of the four projects plus every
  dependent that pins them: the Ansible distribution, the VM and bare-metal
  adapters and storefronts, the VM provisioning client, and `e2e-tests`.
  `make check-locks` and `make check-packaging` passed.
- [x] 1.3 Leave the route contracts to section 3. The work-in-progress commit
  `1164438` added `provisioning_host_definitions_export` and
  `provisioning_host_definitions_import` to `routes.py`
  (`PROVISIONING_ROUTE_CONTRACTS` and `ADMIN_PROVISIONING_OPERATIONS`), with their
  assertions in `contracts/tests/unit/test_host_definitions.py`. Remove both from
  this section's commit; task 3.1 adds them back beside the binding that serves
  them. The service's unit test
  `test_route_binding.py::test_every_contract_resolves_to_a_mounted_route` then
  passes again. Verify: `make test-provisioning` passes, and `git diff origin/dev
  -- provisioning/compute/contracts/src/compute_provisioning_contracts/routes.py`
  is empty.
  *Done.* Both contracts and both admin operations removed, and the two route
  tests removed from `contracts/tests/unit/test_host_definitions.py` with their
  imports; 3.1 restores them from `1164438`. The `routes.py` diff against
  `origin/dev` is empty. Application integration and unit, the service's suite
  (`make test-provisioning`): 500 passed, `test_route_binding.py` among them.
- [x] 1.4 **Verification checkpoint.** Unit: the contracts suite (`make
  test-compute-provisioning-contracts`), with `test_host_definitions.py`'s model
  cases. Run `make test`, which must pass in full; it stopped at
  `test-provisioning` in the first run. Also run `make check-packaging`, since
  1.2 changes dependencies and locks, and `make check-comment-hygiene`.
  End-to-end: none — the models carry no behaviour, and no scenario calls a host
  definitions route. None is owed.
  Owed by validation: `tests.yml`, every `test · <target>` job — each suite
  installs from the relocked environments, and each passes.
  *Run.* Contracts suite: 131 passed. `make test`: every target passed up to
  its last, `test-deployment-packaging`, whose `scripts/tests` step passed (1805
  passed, 11 skipped) and whose `make -C helm test-render` could not start
  because this container has no `helm` binary (`make[2]: helm: No such file or
  directory`). So `make test` did not pass in full here, and the task is checked
  on that disclosure: the one step unrun is the chart render, which this section
  does not touch, and the owed `tests.yml` job `test · test-deployment-packaging`
  runs it. `make check-packaging`: passed. `make check-change`
  (comment hygiene, skills, citations, task list, index, strict OpenSpec
  validation): passed. End-to-end: none, as planned; none owed.

Section 1 notes (compressed at closeout):

- **Replanned once.** A family route contract must land with the binding that
  serves it, since the service suite holds every contract to a mounted route, so
  the route contracts moved to 3.1, and 1.2 took the version bumps, the `pyyaml`
  declaration, and the relock (uv 0.12.19).
- **The `ssh` codec is strict for every submission** (45 F1; D7). A quoted
  number in a document's connection is `invalid_connection` at the entry's
  connection; the host API answers 400 for one; the INI parser reads ports as
  integers, so the INI route is unaffected. `arkhai-compute-provisioning-ansible`
  0.6.0 → 0.7.0, the service's bound `>=0.7.0`. Evidence: the Ansible suite's
  quoted and fractional port cases; the service's document (422) and host API
  (400) cases. Destination: the `physical-provisioning` delta's MODIFIED "Host
  connections are typed by their implementation's codec".
- **Fresh-context checks** ran on both runs; their fixes are in the tasks above.

## 2. The family host document

Delivers the document's parsing, two-stage validation, codec-normalized equality,
session-scoped apply, and export in the host authority, and the route-service
operations the service binds (D2, D4, D5, D7, D8, D9, D12, D14; deltas "A host
definitions entry declares the whole host", "A host definitions document retains
the hosts it does not name", "A host definitions document is validated whole and
carries no credential", "The host registry exports a canonical host definitions
document"; `resource-pool-management` delta "Explicit valid host membership").

Files: `provisioning/compute/src/compute_provisioning/hosts/{definitions.py (new),
service.py,connection.py,route_service.py,__init__.py}`;
`provisioning/compute/tests/unit/{test_host_definitions.py (new),
test_host_route_service.py}`. `pyyaml` is already declared, by 1.2.

The work-in-progress commit `1164438` already carries part of 2.2 and 2.3:
`HostAuthority.put_host_in_session` (a session-scoped write with
codec-normalized equality), `UnknownPoolError`, `HostChange`,
`serves_connection`, `host_ids_in_session`, `session()`, `apply_inventory` rebuilt
on `put_host_in_session`, and `ConnectionCodecs.serves(kind, version)`. Only the
existing suites test it (section 1 notes). Each task here reviews that code
against its own text, completes it, and gives it the tests the task names; none
is checked until then.

- [x] 2.1 Structural validation (D2, D7, D9). A new `hosts/definitions.py` parses
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
  *Done.* `parse_host_definitions` validates each entry with the contracts'
  strict `HostDefinition` and maps pydantic's error types to the contracts'
  codes: `missing` → `required_field`, `extra_forbidden` → `unknown_field`
  (`connection_secrets` at `connection.secrets`, with a message that never
  echoes the material), `string_too_short` and `greater_than_equal` →
  `invalid_value`, anything else → `invalid_type`. A missing root `hosts` is
  `required_field`, a non-list one `invalid_type`, an empty document a root that
  is no mapping. Unit (`provisioning/compute/tests/unit/test_host_definitions.py`):
  one case per problem, the three delta scenarios, and a rendered document
  parsing back — passed in the kit suite.
- [x] 2.2 Session-scoped writes in the host authority (D5, D8). Give
  `HostAuthority` a form of its writes that joins a caller's session and never
  commits, through the same codecs and pool-change hooks as today; keep
  `apply_inventory` and the single-host writes behaving as they do now, built on
  it where that removes a duplicate path rather than adding one. A pool move made
  through it runs every hook exactly as `_move_to_pool` does.
  Library integration (the kit's tests against SQLite, as
  `test_host_route_service.py` composes the authority): a write in a caller's
  session is invisible until the caller commits, and a hook's refusal in it
  raises `PoolChangeRefusedError` without committing.
  *Done*, reviewing the first run's `put_host_in_session` against this text:
  it joins the caller's session, never commits, builds through the codecs with
  the stored connection as `previous`, and moves through `_move_to_pool`, so
  every hook runs as for an update. `apply_inventory` is built on it;
  `register_host` and `update_host` are not, since a duplicate create answers
  409 and an update leaves an omitted connection alone, so neither duplicates
  its path. The first run's unused `serves_connection` was removed (the export
  asks the codecs directly). Library integration
  (`tests/integration/test_host_authority.py`): against a file-backed SQLite with
  separate connections, a session-scoped create is unseen by another session
  until committed; a hook refusing a session-scoped move raises
  `PoolChangeRefusedError` and leaves the session's other write and the moved
  host uncommitted; `enabled` and the pool change only when stated, and an equal
  host is `unchanged` with no hook run — passed. The existing `apply_inventory`
  cases pass on the rebuilt path, as do the Ansible distribution's 134.
- [x] 2.3 Stored-state evaluation, equality, and apply (D4, D5, D7). For a
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
  *Done.* `reconcile_host_definitions_in_session(db, hosts, yaml_text)` reads
  the registered ids before writing, applies each entry through
  `put_host_in_session` with its `pool_id` (an omission is `None`, so it
  unplaces) and its `enabled`, and records `unknown_pool` and
  `pool_change_refused` at `hosts[i].pool_id` and a codec refusal as
  `invalid_connection` at `hosts[i].connection`, each message naming the host.
  It returns a `HostDefinitionsOutcome` (diff, `not_named`, problems) and never
  commits. Library integration (`tests/integration/test_host_definitions.py`,
  the kit's authority on in-memory SQLite with a fake codec carrying the `ssh`
  rules equality and keys turn on — `port` and `user` filled in its canonical
  form, key file or protected token, a kept token, no key refused; it stores a
  null `key_path` as `ssh` does but none of `ssh`'s other optional fields):
  every listed scenario, with "writes nothing" observed as no `INSERT`/`UPDATE`
  of `hosts` issued (the recorder is shown to see both), plus `updated_at`
  unchanged and no hook run; a new host registered as stated; an unserved kind
  or version refused as `invalid_connection`; a stored row in an older normal
  form unchanged by an entry stating it and by its export — passed. The three
  structural scenarios of 2.1 are proved at parse level, and one structural
  document through reconciliation. The real `ssh` codec is exercised through
  the service in 3.4.
  *Amended after the fresh-context check:* the stored side of the equality is
  now read in its codec's canonical form (`ConnectionCodecs.canonical`, which
  replaces the first run's `serves`), so a row stored before its codec's current
  normalization equals an entry stating it; D5 compares "canonical public
  fields".
- [x] 2.4 Export (D12). Render every registered host as a host document: entries
  ordered by `host_id`, stating `pool_id` and `enabled` always and the
  connection's kind, version, and canonical public fields, with no secret; a host
  holding a protected key states no `key_path`. Omit a host whose connection kind
  no registered codec serves, or whose stored version its codec does not serve.
  Library integration: "An operator exports the registry and imports it
  unedited" (every host unchanged, nothing written), "A host holds a protected
  key", "A host is stored at an unserved connection version" (no entry; importing
  the export reports it not named), and "A host's connection kind is not served".
  *Done.* `HostAuthority.host_definitions()` reads every host ordered by
  `host_id` and leaves out only those `ConnectionCodecs.canonical` cannot
  state, an unserved kind or version (D12's two omissions); an entry carries
  the canonical public fields and no protected value. A host stored at a served
  version its codec now refuses, or under an id no entry can name, is stated as
  stored — the entries are built with `model_construct` — so the export never
  fails on one host or silently drops it, and importing it reports the entry.
  `render_host_definitions` writes `pool_id` and `enabled` always and drops a
  public field whose value is null, so a protected-key host states no
  `key_path`. Library integration (same file): the four scenarios, the unserved
  hosts stored directly as rows no current write can produce; a stored row its
  codec refuses, exported and reported `invalid_connection` on import; a host
  registered under an empty id, exported and reported `invalid_value` — passed.
- [x] 2.5 Route-service operations (D12, D14). `HostRouteService` gains
  `export_definitions()`, returning the document text, and
  `import_definitions(body)`, which opens its own session, evaluates the
  document, commits only an applying request with no problem, and returns the
  response model with whether it applied; it raises no error for a problem, so
  the binding chooses 422 or 200. Unit (`test_host_route_service.py`): an
  applying request with a problem applies nothing and reports `applied: false`;
  validate-only applies nothing and reports the planned diff; a clean applying
  request commits.
  *Done, departing from the plan in two ways.* `export_definitions()` renders
  `host_definitions()`; `import_definitions(body)` opens a session through the
  authority's `session()`, commits only an applying request with a valid
  outcome, and rolls back any other.
  - It raises, against this task's "raises no error for a problem":
    `ARCHITECTURE.md`, "Route contracts and their HTTP binding", has the route
    service report a refusal as `ProvisioningRouteError` and the binding only
    translate it. So an applying request with any problem raises
    `ProvisioningRouteError(422, <the response as JSON>)`, and 3.2's binding is
    `routed(...)` like every host route; the wire answer is D14's, a 422
    carrying the response (under `detail`, as capacity's import carries it).
    Validate-only returns the response, problems included, as 200.
  - A commit failing on a host another request created first (`IntegrityError`)
    is rolled back and refused 409, as a duplicate `POST /api/v1/hosts` is;
    nothing in the plan covered it, and it would otherwise answer 500.

  Whether a request commits is a transaction boundary, which `TESTING.md` gives
  to library integration, and a mocked authority could not show it, so the
  applying, refused (422), validate-only (with and without a problem), and
  export-then-import cases are in `tests/integration/test_host_definitions.py`.
  Unit (`test_host_route_service.py`): the 409 on a commit's `IntegrityError`,
  with a rollback. Both passed.
- [x] 2.6 **Verification checkpoint.** Unit and library integration: the family
  kit's suite (`make test-compute-provisioning`), including
  `test_host_definitions.py` and `test_host_route_service.py`; the Ansible
  distribution's suite (`make test-compute-provisioning-ansible`), since
  `apply_inventory` is rebuilt on the session-scoped writes; `make test`. Run
  `make check-packaging`, which also checks that the kit imports `yaml` only as
  the `pyyaml` that 1.2 declared. `make check-comment-hygiene`.
  End-to-end: none — the document reaches no deployed surface until section 3.
  None is owed.
  *Run.* Unit and library integration, the kit's suite (`make
  test-compute-provisioning`): 335 passed. The Ansible distribution's suite,
  against the rebuilt kit wheel: 134 passed. The service's suite against it:
  595 unit and 500 integration passed. `make test` on the final code, wheels
  rebuilt: every suite passed, up to `test-deployment-packaging`'s `make -C helm
  test-render`, which cannot start without a `helm` binary, as in section 1;
  this section touches nothing under `helm/`. `make check-packaging`: passed,
  the kit now importing the `yaml` its `pyyaml` declaration names. `make
  check-change` (comment hygiene among its checks): passed.

Section 2 notes (compressed at closeout):

- **The kit's `tests/integration` is a package** (an empty `__init__.py`), as
  `TESTING.md`'s "Test File Layout" describes, so `test_host_definitions.py`
  exists in both `unit/` and `integration/`.
- **Consequences recorded in `design.md`,** "Consequences found in
  implementation": the INI route's shared write (an equal entry writes nothing;
  hooks run before the connection is replaced), the route service raising the
  422 and answering a concurrent registration 409, and the export stating what
  it can read.
- **Fresh-context checks** ran twice; their fixes are in 2.3–2.6.

## 3. Host definitions routes and typed client

*Amended by the replan after the first implementation run (workflow log seq
38–40).* The route contracts move here from section 1, as 3.1. A family route
contract must land in the same commit as the binding that serves it, because the
service suite requires every contract to have a mounted route. The former
3.1–3.4 become 3.2–3.5.

Delivers the export and import route contracts, the routes on the running
service, and the typed family client (D12, D14; deltas "A host definitions
document is validated whole and carries no credential", "The host registry
exports a canonical host definitions document").

Files: `provisioning/compute/contracts/src/compute_provisioning_contracts/routes.py`;
`provisioning/compute/contracts/tests/unit/test_host_definitions.py`;
`provisioning/compute/service/src/compute_provisioning_service/controllers/
hosts_controller.py` (or a sibling controller registered beside it);
`provisioning/compute/service/src/compute_provisioning_service/main.py` where it
mounts host routes; `provisioning/compute/client/src/compute_provisioning_client/
client.py`; `provisioning/compute/client/tests/`;
`provisioning/compute/service/tests/integration/{test_host_definitions_api.py
(new),test_provisioning_client_endpoint_coverage.py}`;
`provisioning/compute/service/tests/unit/{test_route_table_composition.py,
test_provisioning_client_contract.py}` as the route table requires.

- [x] 3.1 Add the two route contracts to `routes.py` (D12, D14), in this
  section's commit beside 3.2's binding:
  - `GET /api/v1/hosts/definitions/export`
    (`provisioning_host_definitions_export`);
  - `POST /api/v1/hosts/definitions/import`
    (`provisioning_host_definitions_import`).

  Both admit the administrator alone, like every host route, and both go into
  `PROVISIONING_ROUTE_CONTRACTS` and `ADMIN_PROVISIONING_OPERATIONS`. The existing
  `GET /api/v1/hosts/(?P<host>[^/]+)` pattern matches one segment and the export
  path has two, so neither path is claimed by a host route, and no host name is
  reserved.
  Unit (`contracts/tests/unit/test_host_definitions.py`):
  - each path and method resolves to its own operation, with roles `("admin",)`;
  - neither `provisioning_host_get` nor `provisioning_host_update` matches either
    path;
  - `GET /api/v1/hosts/definitions` still resolves to `provisioning_host_get`.

  The first implementation run wrote and tested exactly these, at commit
  `1164438`; 1.3 removes them from section 1 so that this task restores them.
  *Done*, restored from `1164438` unchanged. Unit, the contracts suite (`make
  test-compute-provisioning-contracts`): 135 passed, the three listed cases
  among them.
- [x] 3.2 Bind the routes (D12, D14). `GET /api/v1/hosts/definitions/export`
  answers the document as `application/yaml`; `POST
  /api/v1/hosts/definitions/import` answers 422 with the response model for an
  applying request with any problem, and 200 otherwise, validate-only included.
  Register both before any `/{host_id}` route if the router would otherwise
  shadow them. The single-host `PUT` keeps answering a hook refusal with 409.
  Unit:
  - route table composition holds the two contracts once each;
  - `test_route_binding.py::test_every_contract_resolves_to_a_mounted_route`
    passes with them.
  *Done* in `hosts_controller.py`, declared before the `/{host}` routes though
  FastAPI would not shadow them (one segment against two). The export returns a
  `Response` with media type `application/yaml`; the import is
  `routed(lambda: service.import_definitions(body))`, the route service raising
  the 422 with the response as its detail (see the 2.5 note), so the binding
  holds no outcome logic. Unit (`test_route_table_composition.py`): each
  contract composed exactly once and resolving to itself; the generic
  `test_route_binding.py` and `test_every_assembled_route_resolves_to_itself`
  cases cover both — passed in the service suite. The single-host `PUT` is
  unchanged (its 409 test in `test_host_pool_moves_api.py` passes).
- [x] 3.3 Typed client methods (D12, D14). `compute_provisioning_client`'s async
  and sync clients gain `export_hosts()`, returning the document's text, and
  `import_host_definitions(yaml_text, *, validate_only=False)`, returning the
  response model for 200 and for 422 alike, so a caller reads `applied` and
  `problems` rather than catching an error. Client unit tests cover both
  methods' requests and their 200 and 422 parsing; the endpoint-coverage test
  names both routes.
  *Done.* `export_hosts()` returns the body as text and raises if it is not
  text; `import_host_definitions` accepts 422 and reads the response from
  `detail` for it, raising `ComputeProvisioningError` for a 422 whose detail is
  not that response — not a mapping, or one without `applied` (the service
  refusing the request body itself). Unit (`client/tests/unit/test_client.py`,
  async and sync): the export's request and text; the import's request body and
  its parsing of an applied 200, a 200 carrying problems, and a 422; a 422 whose
  detail is a list or another mapping raised — 86 passed. The
  service's parity unit test (`test_provisioning_client_contract.py`) holds the
  two variants' signatures equal. *Departure:* the endpoint-coverage test does
  not name the routes. Its module covers "endpoints not exercised elsewhere",
  and 3.4's `test_host_definitions_api.py` exercises both through the typed
  client, so naming them there would duplicate it.
- [x] 3.4 Application integration through the typed client
  (`test_host_definitions_api.py`, D12, D14): a document registering two hosts
  applies and reports them created; re-importing it reports them unchanged;
  "An operator explicitly imports an unchanged document" (reconciled, and no
  `hosts` digest written by the route); "A pool-change hook refuses a move on
  import" (422, `pool_change_refused`, no host changed), using VM's relay hook as
  `test_host_pool_moves_api.py` does; "A document has a hook refusal and another
  stored-state problem" (422, both reported); "An operator validates a document"
  (200, planned diff, nothing applied); export then unedited import reporting
  every host unchanged; an unauthenticated request to either route refused.
  *Done.* Application integration (`service/tests/integration/
  test_host_definitions_api.py`, the composed app with the real `ssh` codec,
  through `ComputeProvisioningClient`): two hosts created then unchanged on
  reimport; an unchanged document under a recorded `hosts` digest (seeded as the
  row startup would write, since no startup step records one until section 4)
  reconciled — an API disable restored — with the digest row untouched; VM's
  relay hook refusing a move, `pool_change_refused`, the new host absent and the
  moved one unchanged; an unknown pool and a hook refusal both reported; for
  those two, and validate-only, the status read on a transport recording each
  response under the typed method (422, 422, 200), since the typed method reads
  both alike; validate-only reporting created, updated, unchanged, and a problem
  with nothing applied; the export answering `application/yaml`; API-registered hosts (codec-defaulted
  port and user, a `public_host`, a disabled host, an unplaced one) exported and
  reimported unchanged with every `updated_at` kept; a seller refused by the
  client for both routes; an unsigned request to either route answered 401
  (rejection path, status only). Passed in the service suite. The seller case
  there is the typed client refusing to sign; the server's own refusal is
  proved in the middleware's unit tests (`tests/unit/middleware/test_auth.py`,
  which check admin-only routes one by one): a seller-signed request to either
  route answered 403, under either seller signature scheme, and the
  administrator's (Ed25519) 200.
- [x] 3.5 **Verification checkpoint.** Unit: the contracts suite (`make
  test-compute-provisioning-contracts`) for 3.1, the client's suite (`make
  test-compute-provisioning-client`), and the service's route unit tests.
  Application integration: `test_host_definitions_api.py` and the endpoint
  coverage test, in the service's suite (`make test-provisioning`). `make test`.
  `make check-comment-hygiene`.
  End-to-end: none — no lane calls the routes, and the application-integration
  cases prove them through the typed client against the composed app. None is
  owed.
  *Run.* Contracts suite: 135 passed. Client suite (`make
  test-compute-provisioning-client`): 86 passed. Service suite (`make
  test-provisioning`), wheels rebuilt: 606 unit and 510 integration passed,
  `test_host_definitions_api.py`, the route-table, route-binding, parity, and
  middleware cases among them. `make test` on the final code, wheels rebuilt:
  every suite passed up to `test-deployment-packaging`'s `make -C helm
  test-render`, which cannot start without `helm`, as in sections 1 and 2;
  nothing under `helm/` changed. `make check-packaging` and `make check-change`
  (comment hygiene among its checks): passed. A search of `e2e-tests/` finds nothing calling either route, so
  the end-to-end "none" holds.

Section 3 notes (compressed at closeout):

- **Status observed at a transport seam.** The typed import reads a 422 and a
  200 alike (D14), so `test_host_definitions_api.py` builds the administrator's
  client on `_Recording`, an `httpx` transport over the in-process app recording
  each response's status and content type; only the 401 rejection-path case
  sends a hand-built request.
- **Left as it is:** the client reads the export through the shared transport's
  text fallback (recorded in `design.md`, "Consequences found in
  implementation"). The test imports the pool-move module's private relay
  helpers, as `test_capacity_definitions_api.py` imports from
  `test_capacity_api`, keeping one copy of the fixture.
- **Fresh-context check** ran; its fixes are in 3.3 and 3.4.

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

- [x] 4.1 The `hosts` document kind (D1, D8). Add `host_definitions_path` to
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
  *Done.* The importer takes the host authority as an injected collaborator
  (`host_authority=`, which `app_runtime._definition_importer` passes from
  `container.resolved_host_authority`) and its applier calls the kit's
  `reconcile_host_definitions_in_session` in the gate's own session. An invalid
  outcome raises `HostDefinitionsRejected`, whose message lists every problem
  as `path (code): message`; a stored-state problem's message also names its
  host, a structural one only its location. The applied detail,
  logged by the gate, is `created=… updated=… unchanged=…; registered and not
  named, left as they are: <ids or none>`. Persistence integration
  (`test_definition_document_digest.py`, the real importer and host authority
  against migrated in-memory SQLite): a host document recorded as `hosts` with
  the pools, relays, and capacity digests recorded beforehand unchanged, and a
  second import of it not reapplied — passed in the service suite. Unit
  (`test_config.py`): the path resolves when stated and is `None` by default.
- [x] 4.2 The startup step (D6, D7, D8). Replace `seed-inventory` in
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
  *Done.* `import-host-definitions` (`import_host_definitions_if_configured`)
  sits where `seed-inventory` sat; `seed_inventory_if_empty` and the
  `parse_inventory_ini` import are gone, and the capacity importer's docstring
  names host definitions. Persistence integration
  (`tests/integration/test_host_definitions_startup.py`, the service's own
  startup entry points and importer against file-backed SQLite, real pool and
  host documents, the host authority built by the container's
  `_make_host_authority` with the real `ssh` codec and VM's
  `HOST_POOL_CHANGE_HOOKS`): every listed scenario, plus a host naming a pool
  the fresh-site seed creates. "Work can be dispatched to it" is shown as far as
  this level reaches: the host authority's `lookup`, the read dispatch makes
  before running, returns the added host. "An unchanged document" shows the
  API's disable surviving with `updated_at` kept and the gate's "unchanged"
  log line. The first-document case (D6) registers hosts through
  `register_host` first, then shows the document replacing the one it names,
  adding one, and keeping and logging the disabled host it does not name. The
  hook case seeds a relay row and a port lease as the pool-move tests seed
  them; the document names a new host before the refused move, and neither
  lands. Passed in the service suite. Unit (`test_worker.py`): the step's
  place after the pool document, the seed, and the declaration check, and
  before capacity.
- [x] 4.3 Retire the inventory settings (D2). Add `inventory_ini` and
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
  *Done.* `RETIRED_SETTINGS` maps both keys to `host_definitions_path`;
  `resolved_inventory_path` is gone; both keys and the seeding comment are out
  of `settings.toml`, `inventory_path` out of `config-docker.yml` and
  `config-local.yml.example` (which now shows a commented
  `host_definitions_path`), `PROVISIONING_INVENTORY_PATH` out of the service
  `Makefile`'s `serve`, and the inventory comments out of `config-mock.yml`
  and `config.yml`; the harness settings in `conftest.py` and
  `test_test_controller.py` no longer set `resolved_inventory_path`. Unit
  (`test_config.py`, the service's own loader over its `settings.toml` and one
  profile): each key refused in a profile, an empty value included, and through
  the `PROVISIONING_` environment layer, an empty `PROVISIONING_INVENTORY_INI`
  included, naming `host_definitions_path`; all three retired keys named at
  once. Application integration (`test_retired_settings_startup.py`): the
  app's lifespan refuses an empty `inventory_ini` and an `inventory_path`
  before its second step runs. *Departure:* "The packaged configuration is
  started unchanged" is a unit test in `test_config.py`, not in
  `test_retired_settings_startup.py`, since it reads only the loader's output:
  the packaged `settings.toml` and `config.yml` under no profile and under each
  packaged profile (`docker`, `mock`, `seller`, found from the packaged
  `config/` directory), loaded with no dotenv file, state no retired setting,
  and the refusal passes. No test starts the whole lifespan on packaged
  configuration, whose later steps need a database and credentials no packaged
  profile carries. `test_host_writes_declare_no_capacity_api.py`
  (application integration): the startup case is now a host document applied
  through `import_host_definitions_if_configured` over the harness's host
  authority, registering a placed and an unplaced host and declaring nothing;
  a new case imports the same document through the typed client's
  `import_host_definitions`, declaring nothing. `test_vms_api.py`
  (application integration): the dispatch case imports, through the typed
  client, a document naming `unregistered-kvm` in an unknown pool, refused
  (`applied: false`, `unknown_pool`), and dispatch to that host is then refused
  404 before any job, inventory, or playbook — as the modified scenario says,
  exactly as with no document, since a refused document writes nothing. The
  scenario's "file" half is no longer testable: no setting names an inventory
  file, and stating either retired one refuses startup. The repository search finds the
  keys in the service only in `RETIRED_SETTINGS`, the `settings.toml` comment
  that names them as retired, their tests, and `test_vms_api.py`'s
  `start_playbook(inventory_path=…)`, the Ansible runner's transient
  inventory.
- [x] 4.4 **Verification checkpoint.** Unit: the service's `test_config.py`.
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
  *Run.* Service suite (`make test-provisioning`), after the fresh-context
  fixes: 620 unit and 525 integration passed, the cases above among them.
  `make test`, before those fixes, which touched only this section's tests and
  one docstring: every suite passed up to `test-deployment-packaging`, whose
  `scripts/tests` step passed (1805 passed, 11 skipped) and whose `make -C helm
  test-render` could not start without a `helm` binary, as in sections 1–3;
  this section touches nothing under `helm/`. `make check-change` (comment
  hygiene among its checks) and `make check-packaging`: passed. End-to-end: no
  pipeline runs in an implementation session; the planned scenarios are
  confirmed by reading the lanes' configuration, with one correction below —
  at this section's own commit the bare-metal lane, the Helm topology, and the
  seller stack still depend on retired settings until section 5 changes them,
  so the pipeline is evidence only for sections 4 and 5 together. None is owed.

Section 4 notes (compressed at closeout):

- **Sections 4 and 5 are one unit for the pipeline:** at section 4's commit
  alone the bare-metal lane and Helm still stated retired settings, so every
  validation read `HEAD` after section 5.
- **The importer takes the host authority by injection,** like the capacity
  ledger, and the applier reconciles in the gate's own session, so the digest
  and every host write, a refusing hook's included, commit or roll back
  together.
- **Retired-key detection relies on Dynaconf's `exists`** (recorded in
  `design.md`, "Consequences found in implementation").
- **Handed on and done:** the e2e docstrings and stack-configuration test (5.2);
  the operator documents (7.1, 7.2, 7.4); `TESTING.md`, the companions, and the
  roadmap (8.5, 8.9); the spec's scenario titles and evidence paragraph (8.11).
- **Fresh-context check** ran; its fixes are in 4.2–4.4. Declined: creating the
  hook test's relay through the contributed relay step rather than a direct row,
  which the pool-move tests also seed directly.

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

- [x] 5.1 The chart (D3). Add `definitions.hosts: {}` to `values.yaml`, with its
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
  *Done, its render tests unrun here.* `values.yaml` gains `definitions.hosts:
  {}`, its header lines (hosts retained and reported; an entry declares its
  whole host; the example; validate-only before a release under `Recreate`),
  drops `config.inventory_path`, and corrects the persistence comment and the
  "never accepts … inventory" comment; `configmap.yaml` renders
  `host-definitions.yaml` and sets `host_definitions_path`; `deployment.yaml`
  mounts it read-only. The chart schema refuses `host_definitions_path`,
  `relay_definitions_path`, and `inventory_path` beside the existing
  `inventory_ini`, accepts `definitions.hosts` as an object, and refuses
  `host-definitions.yaml` as a `configFiles` name; the umbrella schema refuses
  the same four keys under provisioning `config`. Render tests
  (`helm/charts/provisioning/tests/test_render.py`): `hosts` joins the per-kind
  table, so the empty, alone, and together cases cover it; new cases for the
  document rendered verbatim with a read-only mount, the ConfigMap checksum
  changing with an edit to the document, every path refused (relay included),
  both retired keys refused and absent from the default render, and the
  `configFiles` name refused. `helm/scripts/test-render.sh` adds an umbrella
  loop asserting each of the four keys fails the render with an error naming
  it. **Not run:** this container has no `helm` binary, and fetching one has
  no allow rule, so `make -C helm test-render` is owed by validation (below).
  *Departure from TESTING.md's "parse one rendered instance with the service's
  own parser":* the render tests check the rendered host document's text only,
  as the pool and capacity cases do; the kit's parser needs an interpreter with
  `compute_provisioning`, which `test-render.sh` runs without.
- [x] 5.2 Deployment scripts and compose (D2, D3). `topology-secrets.sh` stops
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
  *Done.* `topology-secrets.sh` writes `{}` as the provisioning-secrets
  profile. `domains/bare_metal/compose.yml` mounts
  `BARE_METAL_PROVISIONING_HOST_DEFINITIONS_FILE` at
  `/run/config/host-definitions.yaml` and sets
  `PROVISIONING_HOST_DEFINITIONS_PATH`; `e2e-bare-metal-dev-env` prints the
  variable naming `dev-env/bare-metal/hosts.yaml` (`hosts: []`, its comment
  kept and corrected for `PROVISIONING_MODE=real`), and `hosts.ini` is removed.
  `compose/seller.yml` mounts `SELLER_HOST_DEFINITIONS` (required, as the SSH
  key is, since a missing bind source becomes a directory) at the same path and
  sets the variable; its header describes the document. The `deploy-helm`
  comment is corrected. Also, as section 4's notes handed over:
  `e2e-tests/tests/unit/test_domain_stack_configuration.py` now pins the host
  document's variable and path and that the bare-metal stack states no
  `INVENTORY`, and the VM scenario docstrings no longer cite `inventory_path`;
  `dev-env/identities/README.md` names the empty host document. Unit
  (`make test-e2e-unit`): 352 passed. The search finds the keys in those trees
  only in the schema refusals, their render tests, and the values comment
  naming them as retired. **Not run:** `docker compose … config` for either
  stack, and printing the lane's environment, had no allow rule here; the
  pipeline's bare-metal lane renders the stack.
- [x] 5.3 **Verification checkpoint.** Chart render: `make -C helm test-render`.
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
  *Run.* `make -C helm test-render` and therefore `make test-deployment-packaging`
  could not run (no `helm`); its `scripts/tests` step, `make
  test-release-tooling`, passed (1805 passed, 11 skipped). `make
  test-e2e-unit`: 352 passed. `make test` was not rerun in full: this section
  changes no package, dependency, or lock, and the suites covering what it
  changed ran; section 4's run passed every other suite. `make check-change`:
  passed. End-to-end: confirmed as planned, by reading the lanes'
  configuration — the bare-metal lane mounts the empty document, and the VM
  lane's Helm validation reads the topology script's empty profile. None owed.
  Owed by validation, as above: `tests.yml`, job `test ·
  test-deployment-packaging` — `make -C helm test-render` passes, including the
  chart's new render tests and the umbrella refusal loop.

Section 5 notes (compressed at closeout):

- **The chart render tests first ran in validation**, where `make -C helm
  test-render` passed (CI `test · test-deployment-packaging`, and every later
  validation's Helm part, 78 included); the implementation container had no
  `helm`. They check the host document's text, not its parse (recorded in
  `design.md`).
- **The quickstarts' stale passages** were 7.2's, and are corrected.
- **Fresh-context check** ran; its fixes are in 5.1 and 5.2.

## 6. Change-workflow tooling fixes

*Amended on the owner's word at workflow log seq 44 and 47–49, after the first
round's denials were read.* 6.1 is left for the owner's local run, and 6.3 is a
new task: a deny-rule denial redone with the Edit or Write tool is a gap when
the rule exists only to keep file writes on those tools. The checkpoint becomes
6.4. Sections 1–3 stay as committed, and sections 4, 5 and 7 are unchanged.

Delivers the four tooling fixes D11 records: three accepted at the design
review's triage, and the fourth on the owner's word at seq 49. Each lands with
this change. The fourth also delivers the change-workflow delta "Unattended runs
are held to their step's permissions".

Files: `.claude/change-steps.toml` (the orchestrator's edit, left for the owner's
local run); `.agents/skills/change-design/SKILL.md`;
`scripts/change_workflow/review.py`; `scripts/tests/test_change_workflow_review.py`;
the eight step skills' `SKILL.md` under `.agents/skills/` (`change-archive-cleanup`,
`change-closeout`, `change-design`, `change-implement`, `change-merge`,
`change-plan`, `change-triage`, `change-validate`);
`.agents/skills/change-orchestrate/SKILL.md`;
`openspec/specs/change-workflow/architecture.md`; `docs/agents/change-workflow.md`.

- [x] 6.1 The design step's proposal-worktree rules (D11, records 07 R1 and 10
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
  *Amended (seq 44): on the owner's word, the whole of 6.1 is left for the
  owner's local run, the skill text included, since it must match the rule.* No
  orchestrated session makes the `.claude/` edit. Section 6's session leaves
  6.1 unchecked, with a note saying so, and the owner's local run completes and
  checks it before closeout.
  *Left unchecked, as the owner decided (seq 44, carried by the plan at seq
  50):* the orchestrating session made no `.claude/` edit, and this section's
  session changed neither `.claude/change-steps.toml` nor
  `.agents/skills/change-design/SKILL.md`'s section 4 step 2. The owner's local
  run completes and checks it before closeout.
  *Done in the owner's local run, by the orchestrating session on the owner's
  word.* The design step's worktree rule names `origin/dev`, and the skill's
  section 4 step 2 names the same command. The write rules were found by
  headless sessions run as the wrapper runs a step (`dontAsk`, project settings
  only, the rules as `--allowedTools`) from this clone, against a scratch
  worktree `../<name>-proposal` on a branch from `origin/dev`, since removed:
  a pattern holding `..` never matched, written relative or anchored at the
  checkout (`//<clone>/../*-proposal/**`); the same pattern without the `..`
  matched; a Write outside the checkout was allowed only by an Edit rule, never
  by a Write rule; and a Read rule was needed before the Edit. So the table
  gives `Read(../*-proposal/**)`, `Edit(../*-proposal/openspec/**)`, and
  `Edit(../*-proposal/docs/development/ROADMAP.md)`, and names no absolute
  path; on the owner's choice the wrapper's anchoring resolves the `..`, a fix
  made on `dev` beside the anchoring itself, so these rules take effect once
  the merge brings it here. The same run marked the write-steering deny rules
  in `common` with a "Write-steering" comment (6.3).
- [x] 6.2 The review wrapper's title (D11, record 18 R3). In
  `scripts/change_workflow/review.py`, take the first line that is a `# <kind>
  review … <change>` title as the review's start, drop anything before it (the
  transcript keeps it), and apply the existing section and finding checks to the
  rest unchanged; output with no such title is still rejected and kept with its
  transcript. Unit (`scripts/tests/test_change_workflow_review.py`, beside
  `test_rejected_output_is_kept_with_its_transcript`): a review preceded by a
  narrating line and a blank line is published from its title, and output with
  no title line is rejected.
  *Done.* `review.py` gains `from_title`, applied to the reviewer's output
  before `review_problems`; both share `_is_title`, which reads a title line
  stripped, so an indented title is found and accepted alike. Only the
  in-memory text is trimmed: a rejected run's draft keeps the whole output. The
  module docstring says so. Unit (`scripts/tests/test_change_workflow_review.py`,
  through `run_review` with the injected fake runner): a review after a
  narrating line and a blank line is published from its title with no
  narration and no rejected draft; output with no title line raises
  `ReviewError`, publishes nothing, and is kept whole as the rejected draft —
  passed. That the transcript keeps the narration is not tested: the fake
  runner writes a fixed log, and keeping it is the harness's own log, which
  this change does not touch.
- [x] 6.3 A deny-rule denial redone with the Edit or Write tool (D11's fourth
  fix; change-workflow delta "Unattended runs are held to their step's
  permissions").

  Some deny rules exist only to keep file writes on the Edit and Write tools:
  sed's in-place forms, find's deleting, running, and writing actions, and the
  diff family's `--output` forms, each named by a comment in the step table. A
  shell write such a rule refuses, made instead with the Edit or Write tool the
  step's rules allow, is a gap that needs no ruling from the owner. Every other
  deny rule keeps the rule that no other tool does the work.

  State this, in the delta's words, everywhere the workflow states the
  deny-rule rule:
  - the denial paragraph of `openspec/specs/change-workflow/architecture.md`,
    "Restrictions bind unattended runs only", which now says "after a deny-rule
    denial, no other tool may do the work";
  - the shared paragraph of the eight step skills listed above, which now says
    "A call a deny rule refused is forbidden: no other tool does it", worded
    identically in each so `make check-agent-skills` holds them alike;
  - `.agents/skills/change-orchestrate/SKILL.md`'s reading of denials: a
    write-steering rule's denial whose write was made with the Edit or Write
    tool is recorded as a gap, with no ruling asked of the owner;
  - `docs/agents/change-workflow.md`, where it states the deny-rule rule.

  **Marking which deny rules steer writes in `.claude/change-steps.toml` is the
  orchestrating session's edit, and is left with 6.1 for the owner's local run
  (seq 44, seq 49).** Until it is made, these texts name the three kinds above;
  the owner's run makes the table's markings agree with them.

  Verify:
  - `make check-agent-skills` and `bunx @fission-ai/openspec@1.14.0 validate
    bring-host-inventory-under-definition-documents --strict` pass;
  - a search for "no other tool" across `.agents/skills/`,
    `openspec/specs/change-workflow/architecture.md`, and
    `docs/agents/change-workflow.md` finds only statements that carry the
    exception, or that concern rules forbidding the work itself.

  *Done, the table's markings left as planned.* The eight step skills' shared
  paragraph, worded identically (change-merge differs in wrapping alone), now
  carries the exception and ends "Either way, name the substitute"; the
  architecture companion's denial paragraph states it and that every other deny
  rule forbids the work itself, and its classification sentence points at it;
  `docs/agents/change-workflow.md` states it beside proposing rules; the
  orchestrate skill reads such a denial whose write was made with the Edit or
  Write tool as a gap recorded `gap:` with no ruling asked, however the denial
  was classified. *Beyond the listed places:* `scripts/change_workflow/harness.py`'s
  `UNATTENDED` prompt, which every unattended run receives beside its skill,
  stated the rule too and now carries the same exception; no test pins its
  text. *Wording:* these texts say "the step table's comments name those rules",
  which is true today (`.claude/change-steps.toml` comments on sed's, find's,
  and the diff family's rules), rather than the delta's "the step table marks
  such rules", which becomes true only once the owner's local run adds the
  markings. Verify: `make check-change`, whose checks include `make
  check-agent-skills` and the strict OpenSpec validation — passed; the search
  for "no other tool" across `.agents/skills/`, the architecture companion,
  `docs/agents/change-workflow.md`, and `scripts/change_workflow/` finds only
  statements carrying the exception.
- [x] 6.4 **Verification checkpoint.** Unit: `pytest -q scripts/tests` (part of
  `make test-release-tooling`). `make check-agent-skills`. `make test`. `make
  check-comment-hygiene`. `make check-change
  CHANGE=bring-host-inventory-under-definition-documents`.
  End-to-end: none — the workflow tooling is not deployed. None is owed.
  Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — its
  `test-release-tooling` step runs `scripts/tests` and passes.
  *Run.* `make test-release-tooling` (`pytest -q scripts/tests`): 1807 passed,
  11 skipped. `make check-change` (comment hygiene, agent skills, citations,
  task list, index, strict validation): passed. `make test` was not rerun in
  full: the section changes only `scripts/` and documentation, which
  `test-release-tooling` covers. End-to-end: none, as planned.

Section 6 notes (compressed at closeout):

- **The owner's local run completed 6.1 and the table's markings:** the design
  step's worktree rule names `origin/dev`, and `.claude/change-steps.toml` marks
  sed's, find's, and the diff family's deny rules "Write-steering", so the
  delta's "the step table marks such rules" holds at the archive.
- **The comment-hygiene check matches `design.md` in a test's text,** so 6.2's
  test asserts the reviews directory holds only the transcripts instead.
- **Workflow tooling fixed in triage, on the owner's word that each is too small
  for a change of its own:**
  - a run ended by a signal keeps every denial its stream's `permission_denied`
    events name, with a reason or without one (43 R5, 61 F2;
    `scripts/change_workflow/stream.py`, `test_change_workflow_stream.py`);
  - each step run's background command gets the harness's longest timeout
    (43 R5; `.agents/skills/change-orchestrate/SKILL.md`);
  - a subagent's denial the stream also reports names its subagent, with the
    transcript's reason where the stream gave none (68 R1;
    `scripts/change_workflow/wrapper.py`, `test_change_workflow_subagents.py`).
- **Fresh-context checks** ran on the section and on each triage fix; their
  fixes are in 6.2, 6.3, and the items above. Declined: rewording the delta's
  "marks", which the owner's run made true; a wrapper-level test of a killed
  run's line, since the stream's unit tests prove the denials.

## 7. Operator documentation drafts

Drafts the operator-facing documents sections 4 and 5 make false, so each
pipeline run of the implemented commits is described by its documents (D2, D3,
D6, D7, D12, D13, D14). Closeout's promotion (8.9) reconciles them with the
permanent documents it writes.

Files: `docs/development/DEPLOYMENT_AND_CONFIG.md`; `docs/seller-quickstart.md`;
`docs/bare-metal-seller-quickstart.md`; `domains/vms/provisioning/iac/README.md`;
`domains/vms/provisioning/iac/ansible/inventory/provisioning-hosts.example`.

- [x] 7.1 `DEPLOYMENT_AND_CONFIG.md`, "Definition documents" (D13, D3, D7, D14):
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
  *Drafted.* The section's opening names all four kinds and paths, states that
  the chart refuses every path under `config`, and gives the startup order with
  the stored-pool check and hosts; a new "Every kind follows one method"
  subsection lists D13's points, the validate-only pre-flight before a release
  among them. The "Host inventory is not a definition document" paragraph is
  replaced by a "Host definitions" subsection after "What a document does to
  entries it stops naming" (which gains the host retention rule): the fields
  and an example, whole replacement and what it restores, codec-filled
  defaults, no credential, whole-document failure and its startup effect, a
  refused move keeping the service down under `Recreate`, the export and the
  import routes with their response and 422/200, the startup order and first
  document, the upgrade path, and the INI import route's own rules, which the
  replaced paragraph carried. The retired-settings paragraph under
  "Profile-based configuration" names the two retired keys too.
- [x] 7.2 The seller quickstarts, the IaC README, and the example INI (D2, D6,
  D12): `docs/seller-quickstart.md`'s section 4 step 2 and "Bring it up", and
  `docs/bare-metal-seller-quickstart.md`'s "Define the selected site" and
  "Configure public bindings", describe the host document, its compose variable,
  and the export-edit-mount upgrade, and keep the INI for Ansible host
  preparation and `POST /api/v1/hosts/import`; `domains/vms/provisioning/iac/README.md`
  and the header of `provisioning-hosts.example` say the INI is Ansible's own
  host list and the input of the import route, not what the service reads at
  startup. Verify: `make check-doc-citations CHANGE=bring-host-inventory-under-definition-documents`
  reports nothing these drafts introduced.
  *Drafted.* `docs/seller-quickstart.md`: section 4 step 2 declares hosts in a
  host document (with the `key_path` the compose stack mounts), describes its
  reconciliation and validate-only check, keeps the INI as Ansible's own list
  and the import route's input, and gives the export-edit-mount upgrade; "Bring
  it up" passes `SELLER_HOST_DEFINITIONS`, which `compose/seller.yml` requires;
  stray "inventory" mentions in "Declaring capacity" and "Upgrading from CSV
  inventory" now name host definitions and entries; the smoke test, which named
  an INI the image does not contain, pings the host's `ssh_host` from inside the
  container with the mounted key. `docs/bare-metal-seller-quickstart.md`: "Define the
  selected site" declares the host in a host document, the INI kept for Ansible
  and the import route, with the upgrade; "Configure public bindings" exports
  `BARE_METAL_PROVISIONING_HOST_DEFINITIONS_FILE`; the prerequisites and the
  `host_id` explanation under "Start and inspect" no longer say inventory
  alias. The IaC README and the headers of `provisioning-hosts.example` and
  `hosts.example` say the INI is Ansible's own host list and the import
  route's input, not read at startup. `make check-change`, whose checks include
  the documentation citations: passed.
- [x] 7.3 **Verification checkpoint.** `make check-doc-citations
  CHANGE=bring-host-inventory-under-definition-documents`; `make
  check-comment-hygiene`. A read of every changed document against the code of
  sections 1–5: the setting names, the routes, the response codes, the chart
  value, and the compose variables match.
  End-to-end: none — documentation only. None is owed.
  *Run.* `make check-change` (documentation citations and comment hygiene among
  its checks): passed. Read against the code of sections 1–5: the setting,
  route, response field, status, chart value, and compose variable names
  match; see the fresh-context check below.
- [x] 7.4 The operator handbook (D13; the implementation round's triage, 47 O1).
  *Added at that triage, on the owner's note that `DEPLOYMENT_AND_CONFIG.md`
  holds configuration conventions, not an operator's handbook; implemented as an
  implementation round of its own, then read, validated, and reviewed.*
  `DEPLOYMENT_AND_CONFIG.md`'s "Definition documents" carries, for the host,
  pool, and capacity documents, operator knowledge that is neither a
  configuration convention nor normative behaviour. Move it, losing nothing:
  - Create `docs/operator-handbook.md`, opening with a "Definition documents"
    chapter: per kind (hosts, pools, capacity) its format and an example, the
    operator rules a spec does not state as contracts (validate a changed
    document before the release that mounts it; a refused host move keeps the
    service down under `Recreate` until the edit is reverted; exchanging hosts
    between two declarations takes two imports; for VM, state a region on the
    pool and on its declarations; a bare-metal declaration describes one whole
    machine; replacing or disabling the pool seed), and its upgrade and recovery
    steps: from an INI inventory under Helm (drop `inventory_ini` from the
    provisioning-secrets Secret, export, edit, mount as `definitions.hosts`) and
    under Compose (start once with `hosts: []`, export, edit, mount), and moving
    a pool's members to another provider.
  - Cut "Host definitions", "Pool definitions", and "Capacity definitions" in
    `DEPLOYMENT_AND_CONFIG.md` to one short paragraph each: the setting and chart
    value, and links to the kind's spec and its handbook section. Keep the
    section's opening, "The method a document kind follows", "Reconciliation
    follows the document, not the process", "What a document does to entries it
    stops naming", "Secrets are named, not carried", and the retired-settings
    sentence under "Profile-based configuration": these are how configuration
    works across kinds. Pointers into those sections from elsewhere still
    resolve.
  - Check every sentence removed against the specs: hosts against the
    `physical-provisioning` delta, pools against
    `openspec/specs/resource-pool-management/spec.md`, capacity against the
    `physical-provisioning` requirement "Capacity definitions are imported from
    a mounted document" and `openspec/specs/site-capacity/spec.md`. A normative
    rule no spec states becomes a delta requirement or scenario of this change
    (the `physical-provisioning` or `resource-pool-management` delta). Record in
    this task's note, sentence group by group, where each went: the handbook, a
    spec (already, or by a delta added here), or nowhere, with the reason.
  - Add the handbook to `openspec/README.md`'s documentation placement table
    ("Operating a deployment: document formats, procedures, upgrade and recovery
    steps") and to `AGENTS.md`'s "Documentation ownership".
  - Point both seller quickstarts' host-document and upgrade passages at the
    handbook rather than restating the procedure, keeping what a first setup
    needs in place.

  Verify: `make check-change CHANGE=bring-host-inventory-under-definition-documents`
  (documentation citations, strict OpenSpec validation, and comment hygiene among
  its checks); a search finds every heading other documents cite in
  `DEPLOYMENT_AND_CONFIG.md` still present or the citation updated; a read of the
  handbook against the code of sections 1–5 and the specs. End-to-end: none —
  documentation only. None is owed.
  *Done.* `docs/operator-handbook.md` opens with "Definition documents": what
  the method means for running a site, validating a changed document before
  the release (a table of each kind's validate and apply routes; pools validate
  at `POST /api/v1/pools/validate`), then "Pool definitions" (format, rules,
  the seed, moving a pool's members to another provider), "Host definitions"
  (format, rules, a refused move, export and import, the INI upgrade under Helm
  and under Compose, the INI import route), and "Capacity definitions"
  (format, rules, VM region, bare-metal machines). `DEPLOYMENT_AND_CONFIG.md`'s
  three kind sections are one paragraph each — setting, chart value, spec, and
  handbook section — and its opening, method, reconciliation, unnamed-entries,
  and secrets sections and the retired-settings sentence stay; the method's
  first paragraph now says where each kind's rules are. Every heading another
  document cites there still exists. `openspec/README.md` gains the placement
  row, `AGENTS.md`'s "Documentation ownership" a line naming both documents.
  Both quickstarts' host-document, pool-seed, and upgrade passages point at the
  handbook, keeping the first-setup steps; the VM quickstart's capacity pointer
  too. *Beyond the listed files:* the IaC README's pointer, and the
  `settings.toml` comments on `pool_definitions_path` and
  `host_definitions_path`, now name the handbook's sections, where the format
  is (the service wheel rebuilt; `make check-packaging` passed).

  Where each removed sentence group went:
  - **Hosts.** Fields, example, whole replacement, `enabled: null`,
    `hosts: []`, codec-default equality, unserved kind or version, key rules,
    whole-document failure and its structural and stored-state lists, the
    missing path, retention, the export's omissions and round trip, the
    import's response and 422/200, the startup order and first document → the
    `physical-provisioning` delta, already, and the handbook. Two rules no spec
    stated, both implemented and tested in sections 2–3, were **added to the
    delta**: the export orders entries by `host_id` and states each host's pool
    and enabled state ("The host registry exports a canonical host definitions
    document"; `test_an_unedited_export_imports_as_every_host_unchanged` now
    asserts the pool and enabled state of an unplaced, disabled host too), and
    an applying import whose commit meets a host another request registered
    answers 409 (a sentence and the scenario "Another request registers a named
    host during an import" in "A host definitions document is validated whole
    and carries no credential"; `test_host_route_service.py`). A refused move
    keeping the service down under `Recreate`, validating first, registering key
    material through `POST /api/v1/hosts` or the INI route's `embedded` mode,
    the typed client's method names, and both upgrade procedures → the handbook
    only: they are procedures and surfaces, not rules of the document (the
    retirement itself is the delta's "Startup reads no INI inventory", and
    `DEPLOYMENT_AND_CONFIG.md` keeps its refusal sentence). The INI route's
    rules → resource-pool management's delta ("Explicit valid host membership",
    the pool rules), the permanent "Host registry records the connection port"
    (the port rule) and "The tenant-facing host address falls back to the
    connection address", and the delta scenario "An operator imports an INI
    inventory" (no digest); the handbook keeps them. Version 2 and the version-1
    path → "Host registry records the connection port" and the codec
    requirement's scenarios. Execution only from the registered record → the
    modified "Execution inventory comes only from the registered host record".
    No capacity from a host write and `gpus=` ignored → "Host writes declare no
    capacity" and "A host record describes no hardware"; the host API ignoring
    `gpu_count` → that spec only, since the handbook's host rules concern the
    document.
  - **Pools.** No pool from migration, no special name, any pool disabled → the
    permanent "A fresh site is seeded from its seed document", "Strict lossless
    YAML validation", and "Non-destructive pool lifecycle". A configured pool
    document imported before hosts and capacity, failing startup when missing or
    invalid with the seed not standing in, was stated by no requirement (only
    the spec's evidence list) and was **added to the delta** as "A configured
    pool document is imported at startup or fails it" (proved by
    `test_pool_declaration_startup.py`, as that evidence entry says). The seed →
    the seed requirement; "sells nothing until capacity is declared" → the
    `site-capacity` requirement that the projection is built from
    declarations; one process per fresh database → the
    `resource-pool-management` companion, "One process initializes a
    database"; replacing the seed under Helm and Compose → the handbook.
    Provider immutability → "A pool's provider is fixed at creation" and
    "Documents report immutable providers atomically"; moving the members → the
    handbook's procedure, from that requirement's scenario. Required
    declarations, the stored-pool check, the repair path, API credits →
    "Required advertisement and backing declarations" and the seed
    requirement's ordering. `listing_shapes` → "Listing-shape hint validation"
    and `storefront-publication`'s "Every VM listing is a listing shape" and "A
    listing shape is published only where a source member is feasible for it".
  - **Capacity.** Fields, replacement, equality, two-stage validation and its
    refusals, the import route → the delta's modified "Capacity definitions are
    imported from a mounted document". Strict typing (a quoted number is an
    error), implemented (`market_site/capacity_definitions.py`) and tested
    (`kit/site/tests/unit/test_capacity_definitions.py::test_an_entry_is_validated_strictly`)
    but stated by no spec, was **added to that requirement**, with the scenario
    "An entry quotes a quantity". Attributes → `site-capacity`'s "Projected
    inventory is internally consistent" and "A declaration's attributes cannot
    restate its identity". VM region → `storefront-publication`'s feasibility
    requirement and "A VM pool that states no region holds its listings".
    Bare-metal declarations → its bare-metal shape requirements. Exchanging
    hosts in two imports → the handbook only, an operator consequence of
    ordered entries.
  - **Corrected on the way:** `DEPLOYMENT_AND_CONFIG.md` said `gpu_count: 0`
    "is refused"; the site accepts it, and the storefront treats the
    declaration as unresolvable, holding its listing and reporting it
    (`storefront-publication`, "A bare-metal listing's shape is derived from its
    declaration"). The handbook says so.
  - **Stated by no spec, kept in the handbook, not added (open for review):**
    three facts belong to capabilities this change does not modify, so adding
    them would add a delta capability, which is the round's triage to decide:
    the storefront's `listing_shapes_required` report of a VM pool whose
    members declare no GPUs (stated in `storefront-publication`'s companion,
    not its spec); a VM pool's `default_vm_ram`, `default_vm_vcpus`, and
    `default_vm_disk_size` supplying a dimension a shape omits (code only; the
    spec says only that the site decides it); and a capacity declaration's
    `capacity` needing at least one dimension (the registration model's rule;
    `site-capacity` states no minimum).
    *Settled at the round's triage (61 F1):* the minimum was **added** as a
    `site-capacity` delta, a modified "A capacity declaration names no mandatory
    dimension" accepting any non-empty set of dimensions and refusing a
    declaration that names none, with the scenario "A declaration names no
    dimension" (an empty or absent `capacity` map with no legacy scalar total
    standing in; the registration route's `capacity: {}` beside `total_units`
    declares the mirror dimension, so it names one). Existing tests prove it, and
    no code changed: `kit/site/tests/unit/test_declarations.py::test_a_declaration_names_at_least_one_dimension`
    (an empty map), `kit/site/tests/unit/test_capacity_definitions.py` (a
    document entry with `capacity: {}`), and the ledger's
    `test_a_declaration_naming_no_dimension_is_refused`
    (`kit/site/tests/integration/test_ledger.py`, neither map nor total). The other two are stated already: `storefront-publication`'s
    scenario "A pool whose members declare no GPUs states no shapes" states the
    report, and its shape requirement leaves an omitted dimension to the site,
    which the `default_vm_*` settings configure; 8.3 records both as kept in the
    handbook.

  *Evidence for the added rules, at its level:* the export's order and
  stated pool and enabled state, library integration in the compute family
  library (`provisioning/compute/tests/integration/test_host_definitions.py`);
  the import's 409, a unit test whose mocked session's commit raises
  `IntegrityError` (`provisioning/compute/tests/unit/test_host_route_service.py`)
  for the translation, and, since the round's triage (61 F3), library
  integration of a real concurrent registration
  (`test_host_definitions.py::test_an_import_meeting_a_concurrent_registration_is_a_conflict_and_can_be_resubmitted`);
  strict capacity typing, a
  unit test of the entry validator (`_validate_entry`), so that a quoted
  quantity applies nothing follows from the structural-problem rule rather
  than being exercised through an import; the pool document's startup rule,
  persistence integration (`test_pool_declaration_startup.py`, the missing and
  invalid documents with the seed not standing in and no digest).

  Verify: `make check-change` (comment hygiene, agent skills, documentation
  citations, task list, change index, strict OpenSpec validation) — passed,
  the citations check no longer reporting `docs/operator-handbook.md`.
  `make check-packaging` passed. The compute family library's suite (`make
  test-compute-provisioning`, unit and library integration), with the export
  assertion: 335 passed. `make test`: every suite passed, the Helm render
  included. A search for the headings other documents cite in
  `DEPLOYMENT_AND_CONFIG.md` ("Host definitions", "Definition documents", and
  the rest) finds each still there. A read of the handbook against the code of
  sections 1–5 and the specs: the fresh-context check traced its routes,
  fields, chart and Compose wiring, codec rules, hook refusal, and reason codes
  to the code, and found one contradiction, fixed (see the section notes).

Section 7 notes (compressed at closeout):

- **The upgrade under Compose needs an empty document first.** Both compose
  stacks require a host document, and the export exists only in the upgraded
  service, so an upgrading operator starts once with `hosts: []`, then exports,
  edits, and mounts (`docs/operator-handbook.md`, "Upgrading from an INI
  inventory").
- **Recorded in `design.md`,** "Consequences found in implementation": the
  provisioning image never held the INI; the bare-metal quickstart's seed
  passage, left as found (a deferral, predating this change).
- **Fixed in triage:** the `site-capacity` delta's one-dimension minimum
  (61 F1); a real concurrent registration answered 409 and resubmittable,
  library integration in the compute family library (61 F3,
  `test_host_definitions.py::test_an_import_meeting_a_concurrent_registration_is_a_conflict_and_can_be_resubmitted`);
  an INI reimport embedding a rotated key replaces the stored key (71 F1,
  `test_host_authority.py::test_an_inventory_resubmitting_a_secret_replaces_the_stored_one`).
  F2 and 68 R1 are under section 6's notes.
- **Checks of the last fix commit (71 F1, 68 R1),** at `78f412a4c`: `make
  test-compute-provisioning` 337 passed; `make test-release-tooling` 1821
  passed; `make check-packaging`, `make test` (the Helm render included), and
  `make check-change` passed. Validation 78 then passed at the merged
  `6b69b79f1` (8.8).
- **Fresh-context checks** ran on 7.1–7.3, 7.4, and each triage fix; their fixes
  are in the tasks above. 7.4's note counts "four added delta rules", true of
  that round; the capacity minimum (61 F1) made five.

## 8. Closeout

Confirm and promote the verified design, then archive last (D1–D14 and every
delta requirement). The eleven parts follow
`openspec/README.md#plan-closeout-requirements` in order. Closeout changes no
code: a part needing a code, lock, or test change returns the change to
implementation.

- [x] 8.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene` and read
  every comment and docstring sections 1–7 added or rewrote — the new
  `hosts/definitions.py`, the importer's applier and docstrings, `settings.toml`'s
  `host_definitions_path` comment, `RETIRED_SETTINGS`, the chart's values comments,
  the compose headers, `review.py`, and the round's triage fixes' `SshConnection`
  and `Stream` docstrings — for current-system rationale with no
  change, review, or migration narration. A needed correction returns to
  implementation.
  *Confirmed.* `make check-comment-hygiene`: both scans OK. Every comment and
  docstring line the diff against `origin/dev` adds was searched for change,
  review, triage, migration, and before-and-after narration: none. "Retired"
  appears only where the service refuses a retired setting, which is current
  behaviour, as `playbook_path`'s refusal is stated. Not hygiene, left for
  review to weigh: one `settings.toml` comment line about `pool_definitions_path`
  runs past the wrap, which is a code edit closeout does not make.
- [x] 8.2 **Import placement — confirm.** Check that every import sections 1–6
  added or touched is at module level unless a verified cycle or a recorded
  lazy-load reason keeps it local. A needed move returns to implementation.
  *Confirmed.* A search of the diff against `origin/dev` for added indented
  `import`/`from … import` lines finds none: every added import is at module
  level.
- [x] 8.3 **Documentation compliance.** Check D1–D14 against
  `openspec/README.md`'s placement rules and the promotion record: normative
  behaviour in the five deltas, rationale in the companions, repository shape in
  `ARCHITECTURE.md`, configuration conventions in `DEPLOYMENT_AND_CONFIG.md`,
  operator behaviour in `docs/operator-handbook.md` (7.4) and the quickstarts,
  test ownership in `TESTING.md`. Record a disposition for every
  decision, and check every promoted statement against the code.
  *Dispositions.*
  - D1, D2, D4, D5, D6, D7, D9, D12, D14: normative in the
    `physical-provisioning` delta, merged by the archive; rationale in that
    companion's "Hosts are a reconciled declaration"; operator account in the
    handbook's "Host definitions".
  - D3: the `deployment-state` delta; the convention in `DEPLOYMENT_AND_CONFIG.md`,
    "Definition documents".
  - D5's pool rule: the `resource-pool-management` delta, "Explicit valid host
    membership".
  - D8: the companion's section, the startup order in `resource-pool-management`'s
    companion, "Administrative reconciliation", and `ARCHITECTURE.md`, "Resource
    pools".
  - D10: `design.md`'s Open Questions and the roadmap's unowned Goal 1 gap (8.5).
  - D11: workflow tooling itself; fix 4 is in the `change-workflow` delta and
    companion, the step skills, and `docs/agents/change-workflow.md`.
  - D13: `DEPLOYMENT_AND_CONFIG.md`, "The method a document kind follows"; the
    handbook, with its rows in `openspec/README.md` and `AGENTS.md`.
  - Test ownership: `TESTING.md`, "Host Requirement Enforcement" (8.9).

  The two facts 7.4 found stated by no spec and the triage left out of the
  deltas are kept in the handbook, since `storefront-publication` already states
  them: the scenario "A pool whose members declare no GPUs states no shapes", and
  its shape requirement leaving an omitted dimension to the site, which the
  `default_vm_*` settings configure. Checked against the code: the startup order
  in `app_runtime.startup_steps()` (contributed definitions, pools, seed, stored
  pool check, hosts, capacity), as the companions and `DEPLOYMENT_AND_CONFIG.md`
  state it; the handbook's INI route, which upserts and so agrees with 71 F1's
  fix. No placement violation was found.
- [x] 8.4 **Narrative compression.** Compress section notes to final behaviour,
  validation evidence, deferred work (the two open questions), and destinations,
  moving any durable rationale into `design.md` first.
  *Done.* What the notes held that is worth keeping went first to `design.md`'s
  new "Consequences found in implementation": the INI route's shared write and
  71 F1, the route service's 422 and 409, the export stating what it can read,
  the client's text fallback, Dynaconf's `exists`, the render tests' text-only
  check, the INI never in the image, and the bare-metal quickstart's seed
  passage, left as found. D10's outcome went to its open question. Each section's
  notes are then cut to final behaviour, evidence, deferrals, and destinations,
  with fresh-context checks summarized by where their fixes went. Completed task
  notes are left as written, as the closeout rules require. The two open
  questions stay in `design.md`: D4's revisit when
  `keep-new-deliveries-off-disabled-hosts` lands, and D10's, now a roadmap gap.
- [x] 8.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, Goal 1 —
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
  *Done.* Goal 1's open-gap row this change owned is removed, and its
  current-state sentence now says hosts are declared in a host definitions
  document reconciled at startup when its digest changes, after pools and before
  capacity, exported and imported through the provisioning API, with the INI
  read only by the import route. `admit-relay-proxies-by-grant` has landed
  (archived 2026-11-01) and did not settle the relay-pool mismatch;
  `prove-relay-provisioning` has not landed, and its design does not address it.
  So the mismatch is added to Goal 1's open gaps as unowned, citing this
  change's archived Open Questions.
- [x] 8.6 **Campaign index currency.** Set this change's Goal 1 row in
  `openspec/changes/README.md` to `in closeout`, its notes naming the validation
  and the destinations; keep its graph line. Leave other rows' `Depends on` for
  archive cleanup. Run `make check-change-index`.
  *Done.* The row is `in closeout`, its notes naming validation 78 and the
  destinations, and it links the archive directory (8.11). The graph line's
  marker reads `(closeout)`. No other row's `Depends on` or status is touched.
  `make check-change-index` passed after the edit.
- [x] 8.7 **Packaging.** Confirm `make check-packaging` and `make
  check-architecture-change CHANGE=bring-host-inventory-under-definition-documents`
  pass against the last implementation commit; the change touched `.claude/` and
  `.agents/` (section 6), so run `make check-agent-skills` too.
  *Passed* at `6b69b79f1`, the merged `HEAD` closeout starts from: `make
  check-packaging` (every rule held, among them dependencies and kinds); `make
  check-architecture-change`: the change owns no architecture row; `make
  check-agent-skills`: every skill is loaded from its one shared source.
- [x] 8.8 **End-to-end pipeline.** Confirm the pipeline passes at the last
  implementation commit and record the run, its result, and the scenarios that
  exercise this change: every VM lane scenario (packaged configuration with no
  host document and no retired setting) and every bare-metal lane scenario (an
  empty host document mounted through compose). If the pipeline cannot run for a
  reason unrelated to the change, record the blocker and its owner and treat the
  validations it gates as unrun.
  *Passed.* Validation 78 (`reviews/78-validation.md`) ran at `6b69b79f1`, the
  merge of `origin/dev` that followed the pre-closeout triage's fix commit
  `78f412a4c`; no commit has been made since. Pipeline run 41632231282 passed:
  lanes `e2e-vm`, `e2e-bare-metal`, and `e2e-apicredits`, with the VM lane's
  native Ansible gate. The scenarios exercising this change:
  - VM lane: `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`, `e2e_listing_shapes`,
    `e2e_compute_dynamic_listings`, `e2e_pool_declared_modes`, `multi_registry`,
    and `e2e_vm_introduction`, all on packaged configuration with no host
    document and no retired setting;
  - bare-metal lane: `e2e_bare_metal_publication`, `e2e_bare_metal_mock_deal`,
    `e2e_bare_metal_introduction`, `e2e_bare_metal_unbacked_introduction`, and
    `e2e_bare_metal_payment_deal`, each with the empty host document mounted
    through compose.

  No scenario applies a non-empty document; persistence and application
  integration own that. Local (`check-packaging`, `test`) and Helm
  (`test-render`, deploy, the `e2e-scenarios` pod, exit 0) passed too.

  CI owed by validation, tests.yml run 41632237934, all 23 jobs passed:
  - every `test · <target>` job installs from the relocked environments and
    passes (1.4);
  - `test · test-deployment-packaging`: `make -C helm test-render` passes with
    the `definitions.hosts` render, mount, path, and every refused key (5.3);
    its `test-release-tooling` step passes `scripts/tests`, 1826 passed (6.4).

  No job failed, so nothing was compared with the baseline, `dev`'s tests.yml
  run 41630898702 at `aa521868c`, also 23 of 23. Closeout changes no code, so
  these runs describe the code the closeout commit carries. They name the
  pre-closeout commit's merge, not an earlier waived one.
- [x] 8.9 **Promotion.** Write the permanent documents and the design-promotion
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
  - `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Definition documents" (D13),
    `docs/operator-handbook.md` (7.4), both seller quickstarts, and the IaC
    README: reconcile section 7's drafts with the final code.
  - `docs/development/TESTING.md`, "Host Requirement Enforcement": the dispatch
    case's "configured inventory file naming the host" becomes the refused host
    document 4.3 tests.
  - The `physical-provisioning`, `deployment-state`, `resource-pool-management`,
    `site-capacity`, and `change-workflow` specs are written by the archive
    (8.11), and the record
    names them. The change-workflow companion and the skills were written in 6.3;
    confirm they still match the merged requirement, and that 6.1 and the table's
    deny-rule markings were completed by the owner's local run. If they were not,
    record that in the promotion record and the index notes, and do not invent
    the markings here.

  *Done.* Written:
  - `physical-provisioning/architecture.md`: "Hosts are a reconciled
    declaration" after "The host registry owns the connection" (D1, D2, D4, D5,
    D6, D7, D8, D9, D12), and "Selected-resource execution" now names the host
    definitions document and the INI import route as what may register hosts;
  - `resource-pool-management/architecture.md`, "Administrative
    reconciliation": the startup order names host definitions, then capacity,
    and the one-process paragraph the host-document import;
  - `site-capacity/architecture.md`: no host write declares capacity, naming the
    host definitions document and the INI submitted to the import route;
  - `ARCHITECTURE.md`, "Resource pools": hosts reach the registry through the
    host API, the INI import route, or a host definitions document reconciled
    like the pool and capacity documents;
  - `TESTING.md`, "Host Requirement Enforcement": dispatch fails even after a
    host document naming the host was submitted and refused.

  Section 7's operator documents (`DEPLOYMENT_AND_CONFIG.md`, the handbook, both
  quickstarts, the IaC README) were reconciled with the final code. The only
  code change after their review, 71 F1, agrees with the handbook's INI route
  ("it upserts"), and none needed a content change; one mis-wrapped paragraph in
  `DEPLOYMENT_AND_CONFIG.md` was rewrapped. `openspec/specs/README.md` needs no
  edit, since the change adds no capability or companion. The change-workflow
  companion, the step skills, and `docs/agents/change-workflow.md` match the
  delta. The owner's local run completed 6.1 and the table's "Write-steering"
  markings, so the delta's "the step table marks such rules" holds. The five
  deltas' specs are written by the archive (8.11).
- [x] 8.10 **Documentation citations.** Run `make check-doc-citations
  CHANGE=bring-host-inventory-under-definition-documents` after promotion and
  resolve every match; `keep-new-deliveries-off-disabled-hosts` is cited by name
  and exists on this branch once `dev` is merged in. Then run `openspec validate
  bring-host-inventory-under-definition-documents --strict`.
  *Passed* after promotion: `make check-change` reported every check passing —
  comment hygiene, agent skills, documentation citations, task list, change
  index, and `openspec validate --strict` with the pinned validator.
  `keep-new-deliveries-off-disabled-hosts` exists on this branch.
- [x] 8.11 **Archival.** Archive last with `openspec archive
  bring-host-inventory-under-definition-documents -y`, which merges the five
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
  *Done.* No delta had been synchronized by hand (none of the added requirements
  or new scenarios was in a permanent spec), so the archive merged them:
  `npx --yes @fission-ai/openspec@1.14.0 archive … -y` (no `bunx` here; `npx` is
  the fallback `scripts/check_change.py` uses), applying + 8 and ~ 8 across the
  five specs, and moving the change to
  `openspec/changes/archive/2026-11-03-bring-host-inventory-under-definition-documents/`.
  The archive's one incomplete task was this one. A read of each merged spec's
  diff found every added and modified requirement there once, as its delta
  states it, and nothing else changed; `change-workflow`'s modified requirement
  keeps the relative-rule paragraph and scenario the `dev` merge brought in.
  Then, by hand in `physical-provisioning/spec.md`: the two scenarios retitled
  as planned; the evidence paragraph's "startup inventory seed" now names the
  host definitions document, and a new evidence entry cites the host
  definitions tests at each level. The row links the archive directory, and no
  other link to the change's old directory remains. `make check-change`, which
  for an archived change runs `openspec validate --specs --strict`, passed (below).

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
| Why hosts are a reconciled, family-owned declaration (D1, D2, D4, D5, D6, D7, D8, D9, D12) | `openspec/specs/physical-provisioning/architecture.md#hosts-are-a-reconciled-declaration` (8.9); "Selected-resource execution" corrected |
| The general definition-document method (D13) | `docs/development/DEPLOYMENT_AND_CONFIG.md#definition-documents` and `#the-method-a-document-kind-follows` (7.1, 7.4) |
| The operator account of the host, pool, and capacity documents (D13, 47 O1) | `docs/operator-handbook.md#definition-documents`, its row in `openspec/README.md`'s placement table, and `AGENTS.md`'s "Documentation ownership" (7.4) |
| Rules `DEPLOYMENT_AND_CONFIG.md` stated that no spec did (D13, 47 O1, 7.4): a configured pool document fails startup when missing or invalid; the host export's order and stated pool and enabled state; the host import's 409; strict capacity document typing | `openspec/specs/resource-pool-management/spec.md`, "A configured pool document is imported at startup or fails it"; `openspec/specs/physical-provisioning/spec.md`, "The host registry exports a canonical host definitions document", "A host definitions document is validated whole and carries no credential", and "Capacity definitions are imported from a mounted document" (by the archive) |
| A capacity declaration names at least one dimension (61 F1), stated by the handbook and enforced by the authority, unstated by the requirement accepting any set of dimensions | `openspec/specs/site-capacity/spec.md`, "A capacity declaration names no mandatory dimension", and its scenario "A declaration names no dimension" (by the archive) |
| A connection submitted with a secret is always written, so an INI reimport embedding a rotated key replaces the stored key (71 F1) | Restores the INI import route's behaviour, which "Do not change the INI import route's semantics" keeps; stated in the host authority's docstrings (`provisioning/compute/src/compute_provisioning/hosts/service.py`); no permanent document |
| A codec types a connection's public fields strictly, for every submission (D7, 45 F1) | `openspec/specs/physical-provisioning/spec.md`, "Host connections are typed by their implementation's codec" and "A host definitions document is validated whole and carries no credential" (by the archive) |
| A run ended by a signal keeps its denials, with a reason or without one; step runs get the longest timeout (43 R5, 61 F2); a subagent's denial the stream also reports names its subagent (68 R1) | Workflow tooling itself (`scripts/change_workflow/stream.py`, `scripts/change_workflow/wrapper.py`, `.agents/skills/change-orchestrate/SKILL.md`); no permanent document |
| Startup order with host definitions (D8) | `openspec/specs/resource-pool-management/architecture.md#administrative-reconciliation` (8.9); `docs/development/DEPLOYMENT_AND_CONFIG.md#definition-documents` (7.1) |
| How hosts reach the registry | `docs/development/ARCHITECTURE.md#resource-pools` (8.9) |
| Dispatch to an unregistered host is refused even after a refused host document names it (test ownership) | `docs/development/TESTING.md#host-requirement-enforcement` (8.9) |
| No startup INI seeding | `docs/development/ROADMAP.md`, Goal 1's current state (8.5); `openspec/specs/site-capacity/architecture.md` (8.9); `openspec/specs/physical-provisioning/spec.md`'s retitled scenarios and evidence paragraph (8.11); both seller quickstarts and `domains/vms/provisioning/iac/README.md` (7.2, 7.4) |
| D10 (no same-pool rule) and the D4 revisit trigger | `design.md` Open Questions; `docs/development/ROADMAP.md`, Goal 1's open gaps, as unowned: `admit-relay-proxies-by-grant` landed without settling it and `prove-relay-provisioning` has not landed (8.5) |
| Consequences found in implementation: the INI route's shared write, the route service's 422 and 409, the export stating what it can read, the client's text fallback, Dynaconf's `exists`, the render tests' text check | `design.md`, "Consequences found in implementation" (8.4); the behaviour is in the code's docstrings and the deltas; no further permanent document |
| Left as found: the bare-metal quickstart describes the fresh-site seed its stack never applies | `design.md`, "Consequences found in implementation"; predates this change, no owner |
| D11 tooling fixes 1–3 | Workflow tooling itself (`.claude/change-steps.toml`, `.agents/skills/change-design/SKILL.md`, `scripts/change_workflow/review.py`); no permanent document |
| D11 fix 4: a write-steering deny rule's denial redone with Edit or Write is a gap | `openspec/specs/change-workflow/spec.md`, "Unattended runs are held to their step's permissions" (by the archive); `openspec/specs/change-workflow/architecture.md`, "Restrictions bind unattended runs only", the eight step skills, `.agents/skills/change-orchestrate/SKILL.md`, `docs/agents/change-workflow.md`, and the unattended prompt in `scripts/change_workflow/harness.py` (6.3); the table's markings in `.claude/change-steps.toml` (the owner's local run) |
