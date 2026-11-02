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
- **Amended by the replan.** Recorded at the top of this section: the route
  contracts move to 3.1; 1.2 carries the bumps, the `pyyaml` declaration, and the
  relock; 1.3 takes the route contracts out of this section's commit; 1.4 is the
  checkpoint.
- **Second run: the notes above are the first run's.** Their "task 1.2" is the
  former route-contracts task, now 3.1. The relock and the bumps they describe as
  owed are done (1.2): `pyyaml` is declared and every lock rewritten with uv
  0.12.19. The kit declares `pyyaml` one commit before it imports `yaml`, in
  section 2's `hosts/definitions.py`.
- **Second run's fresh-context check.** It found no layering, comment, test-level,
  placement, or packaging break. Fixed: the overstated strictness docstring and
  the narrow model evidence (1.1); a test named for applying nothing, which a
  wire model cannot do (renamed to
  `test_a_refused_response_parses_with_every_problem`); 1.4 checked without
  saying `make test` was incomplete (now said); these stale notes (this entry).
- **Open for review: the `ssh` codec coerces a quoted number in `public`.** D7
  says a document's validation is strict, "a quoted number is an error". The
  entry model is strict for its own fields, but `public` is the kind's mapping,
  and `SshConnection` (`provisioning/compute/ansible/.../connection.py`) is not
  strict, so `ssh_port: "22"` in a document is accepted as 22. Making it strict
  would change `POST /api/v1/hosts` and the INI route too, which this change does
  not plan. Left as it is for the round's triage to decide.

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

Section 2 notes:

- **The kit's `tests/integration` is now a package** (an empty `__init__.py`),
  as `TESTING.md`'s "Test File Layout" describes and the other kits' are, so
  `test_host_definitions.py` exists in both `unit/` and `integration/`.
- **For section 3.** The import's refusal reaches the binding as
  `ProvisioningRouteError(422, detail)`, so the binding is `routed(lambda:
  service.import_definitions(body))` with `response_model=
  HostDefinitionsImportResponse`, and the 422 body is `{"detail": <response>}`:
  the client's `import_host_definitions` reads `body["detail"]` for 422 and the
  body itself for 200. The export route must answer `application/yaml`: the
  service's response signer signs a non-JSON body over its decoded text
  (`middleware/auth.py`, `_response_body`), and the client's `finish` falls back
  to `response.text` when the body is not JSON, which a block-style YAML
  document never is; the client method should still not rely on that guess
  where the content type says YAML.
- **A section-1 note overstated "no change of behaviour"** in `apply_inventory`
  on the session-scoped write. Two things differ, neither against a scenario:
  an INI entry equal to its stored host now writes nothing, so its `updated_at`
  is no longer bumped; and on a move, the hooks run before the connection is
  replaced rather than after, both inside the one transaction.
- **Fresh-context check.** No layering, import, packaging, or placement break.
  Fixed: 2.6 checked without its results (now recorded); the route service
  leaving the 422 to the binding (now raised, see 2.5); an `IntegrityError` at
  commit answering 500 (now 409); equality against raw rather than canonical
  stored fields (now canonical, see 2.3); test docstrings citing "the delta"
  (now the `physical-provisioning` scenario); the fake codec's description and
  two thin assertions (no hook run in the defaults case). Declined: none.
  Still open from section 1: the `ssh` codec coerces a quoted number in
  `public`.
- **Second fresh-context check, on those fixes.** No layering, import, comment,
  or test-level break; the 422/409 handling and canonical equality hold. Fixed:
  `canonical` had widened the export's omissions to a stored connection its
  codec refuses, beyond D12's two (now stated as stored; see 2.4), with a
  docstring claiming such a host runs no work, which holds only for an unserved
  kind or version; a host with an empty id, which `POST /api/v1/hosts` accepts,
  failed the whole export (now stated, and refused on import); an ambiguous
  scenario citation in a test docstring (now names its requirement). Declined:
  none.

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

Section 3 notes:

- **Status observed at a transport seam.** The typed import reads a 422 and a
  200 alike by design (D14), so the status a scenario names cannot be seen
  through it. `test_host_definitions_api.py` builds the administrator's client
  on `_Recording`, an `httpx` transport over the in-process app that records
  each response's status and content type, and reads them there; no test sends
  a hand-built request except the 401 rejection-path case.
- **The export's body is read as text by the shared transport's fallback.**
  `SigningBase.finish` parses JSON and falls back to text, so `export_hosts`
  receives the YAML as signed only because a block-style document is never
  JSON; `_text` refuses anything else. Making `finish` choose by content type,
  as the service's signer does, would change every client's reading of every
  response, so it is left for a change that wants it; the integration test
  proves the route answers `application/yaml`.
- **Fresh-context check.** No layering, import, packaging, or placement break;
  the controller is thin and D12 and D14 hold in the code. Fixed: a status test
  that called the client's transport with a hand-written route and body,
  against the "no raw calls" rule (replaced by the recording transport, which
  now also shows the 422 for both hook scenarios); the module docstring that
  claimed every import went through the typed method; a 422 with a mapping
  detail of another shape raising a pydantic error rather than the client's
  (now `ComputeProvisioningError`); the export's content type unproved (now
  asserted); validate-only never asserting `unchanged` (now does); docstrings
  saying the import reconciles "whatever startup last applied", which no
  startup step records yet (now "regardless of any document applied before");
  the middleware note's "both schemes" (only the seller's varies). Declined:
  the client still relies on `finish`'s text fallback for the export, as the
  note above says; and importing the pool-move module's private helpers, which
  has precedent (`test_capacity_definitions_api.py` imports from
  `test_capacity_api`) and keeps one copy of the relay fixture.
- **For section 4.** The kit's `reconcile_host_definitions_in_session(db,
  hosts, yaml_text)` is what the importer's `hosts` applier calls inside its own
  session; it returns `HostDefinitionsOutcome` with `valid`, `diff`,
  `not_named`, and `problems`, and never commits, so the importer raises on an
  invalid outcome and its transaction rolls back with no digest. The host
  authority is `container.resolved_host_authority`.

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

Section 4 notes:

- **Sections 4 and 5 are one unit for the pipeline.** Section 4 makes any
  statement of `inventory_ini` or `inventory_path` refuse startup, and three
  deployment-side statements remain until section 5: `domains/bare_metal/compose.yml`
  sets `PROVISIONING_INVENTORY_PATH`, the provisioning chart's `values.yaml`
  states `config.inventory_path`, and `helm/scripts/topology-secrets.sh`
  writes `inventory_ini: ""`. At this commit alone the bare-metal lane and any
  Helm deployment therefore refuse to start, while the VM lane, whose compose
  states neither, starts. `compose/seller.yml` starts but registers no host:
  it relied on `settings.toml`'s removed `inventory_path` default naming the
  INI baked into its image, and section 5 mounts a host document in its place.
  The round's validation reads HEAD, after section 5.
- **The importer takes the host authority by injection,** like the capacity
  ledger, and the applier calls the kit's session-scoped reconciliation with
  the gate's own session, so the digest and every host write commit or roll
  back together. A hook's writes in a refused document roll back with it.
- **Retired-key detection relies on Dynaconf's `exists`,** which reports an
  empty value, from a profile or from the environment, as stated; the unit
  tests pin both, so a loader change that dropped empty values would fail
  them.
- **Left for later sections:** the e2e docstrings in
  `e2e-tests/tests/e2e/roles/scenarios/vms/` (`host_registry.py`,
  `conftest.py`, and three scenario modules) still explain registering hosts
  through the API by `inventory_path` being "docker-compose-specific"; and
  `e2e-tests/tests/unit/test_domain_stack_configuration.py` pins the
  bare-metal compose's `BARE_METAL_PROVISIONING_INVENTORY_FILE`. Section 5
  changes that compose file, so it takes both. Permanent documents that still
  describe startup INI seeding, each owned by a later task:
  `DEPLOYMENT_AND_CONFIG.md`'s "Definition documents" (7.1; the new
  `settings.toml` comment points there for the host format), the quickstarts
  and IaC README (7.2), `TESTING.md`'s "Host Requirement Enforcement" and
  `resource-pool-management/architecture.md` (8.9), the
  `physical-provisioning` spec's scenario titles and evidence paragraph
  (8.11), and the roadmap (8.5).
- **Fresh-context check.** No layering, import, raw-call, or packaging
  structure break; D1, D2, D6, D7, D8 hold. Fixed: the rejection docstring
  claiming every problem names its host (structural ones name a location);
  a unit test pinning the removed step's names, like a tombstone (removed);
  the packaged-configuration case labelled application integration while it
  only loads configuration (now a unit test, with dotenv off); the
  dispatch-case note not saying the file half is untestable; "End-to-end:
  confirmed" reading as a run; the seller stack's interim loss of hosts not
  disclosed; `make check-packaging` not run (now run, passed); this list of
  stale documents being incomplete. Declined: creating the hook test's relay
  through the contributed relay-definitions step instead of a direct row —
  the step needs the VM contribution composed, a row is the precondition the
  hook reads, and the pool-move tests set it up the same way.

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

Section 5 notes:

- **The chart render tests have never run.** Written against the templates by
  reading, and traced by the fresh-context check, but not executed:
  validation's `test-deployment-packaging` job is their first run. TESTING.md's
  "break the template once" step was not done, for the same reason.
- **Section 4's commit was pushed with this one.** `make push-branch` refuses a
  dirty worktree, and this section's edits were already in it when section 4
  was committed.
- **Still stale until section 7:** `docs/seller-quickstart.md`'s "Bring it up"
  runs `compose/seller.yml` without the now-required `SELLER_HOST_DEFINITIONS`,
  and `docs/bare-metal-seller-quickstart.md` exports the retired
  `BARE_METAL_PROVISIONING_INVENTORY_FILE`; 7.2 owns both.
- **Fresh-context check.** No comment-hygiene, packaging, or compose-wiring
  break; every `deployment-state` scenario has a render case, and it found no
  render assertion likely to fail. Fixed: the umbrella loop passing on any
  failure (it now requires the error to name the key, and no longer claims the
  umbrella's own schema is what refused, which the subchart's also would); the
  host-document cut that never matched (now the manifest's end); the values
  comment pointing every document at the host import route; a mis-wrapped
  `Makefile` comment; `hosts.yaml` saying the lane always runs mock;
  `dev-env/identities/README.md`'s "empty host inventory". Disclosed rather
  than fixed: the service-parser check (5.1).

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
  *Amended (seq 44): on the owner's word, the whole of 6.1 is left for the
  owner's local run, the skill text included, since it must match the rule.* No
  orchestrated session makes the `.claude/` edit. Section 6's session leaves
  6.1 unchecked, with a note saying so, and the owner's local run completes and
  checks it before closeout.
- [ ] 6.2 The review wrapper's title (D11, record 18 R3). In
  `scripts/change_workflow/review.py`, take the first line that is a `# <kind>
  review … <change>` title as the review's start, drop anything before it (the
  transcript keeps it), and apply the existing section and finding checks to the
  rest unchanged; output with no such title is still rejected and kept with its
  transcript. Unit (`scripts/tests/test_change_workflow_review.py`, beside
  `test_rejected_output_is_kept_with_its_transcript`): a review preceded by a
  narrating line and a blank line is published from its title, and output with
  no title line is rejected.
- [ ] 6.3 A deny-rule denial redone with the Edit or Write tool (D11's fourth
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
- [ ] 6.4 **Verification checkpoint.** Unit: `pytest -q scripts/tests` (part of
  `make test-release-tooling`). `make check-agent-skills`. `make test`. `make
  check-comment-hygiene`. `make check-change
  CHANGE=bring-host-inventory-under-definition-documents`.
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
  behaviour in the four deltas, rationale in the companions, repository shape in
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
  - The `physical-provisioning`, `deployment-state`, `resource-pool-management`,
    and `change-workflow` specs are written by the archive (8.11), and the record
    names them. The change-workflow companion and the skills were written in 6.3;
    confirm they still match the merged requirement, and that 6.1 and the table's
    deny-rule markings were completed by the owner's local run. If they were not,
    record that in the promotion record and the index notes, and do not invent
    the markings here.
- [ ] 8.10 **Documentation citations.** Run `make check-doc-citations
  CHANGE=bring-host-inventory-under-definition-documents` after promotion and
  resolve every match; `keep-new-deliveries-off-disabled-hosts` is cited by name
  and exists on this branch once `dev` is merged in. Then run `openspec validate
  bring-host-inventory-under-definition-documents --strict`.
- [ ] 8.11 **Archival.** Archive last with `openspec archive
  bring-host-inventory-under-definition-documents -y`, which merges the four
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
| D11 tooling fixes 1–3 | Workflow tooling itself (`.claude/change-steps.toml`, `.agents/skills/change-design/SKILL.md`, `scripts/change_workflow/review.py`); no permanent document |
| D11 fix 4: a write-steering deny rule's denial redone with Edit or Write is a gap | `openspec/specs/change-workflow/spec.md`, "Unattended runs are held to their step's permissions" (by the archive); `openspec/specs/change-workflow/architecture.md`, "Restrictions bind unattended runs only", the eight step skills, `.agents/skills/change-orchestrate/SKILL.md`, and `docs/agents/change-workflow.md` (6.3); the table's markings in `.claude/change-steps.toml` (the owner's local run) |
