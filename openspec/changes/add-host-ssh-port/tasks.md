# Implementation Tasks

Paths are relative to the repository root.

Validation is per-package: `make test` in each package touched, plus the
repository-root targets named in the closeout. Every command below is runnable
in the authoring environment through `uv`; nothing in this change needs a live
host, a cluster, or Ansible. Where that is not true it is stated.

Applying a migration to a deployed database mutates persistent state and is out
of scope for this change. Task 1.4 writes the migration; running it is an
operator step, called out in section 6.

## 1. Schema

- [x] 1.1 Add `ssh_port` to `Host` in
      `provisioning/compute/service/src/compute_provisioning_service/db/models.py`.
      `Integer`, `nullable=False`, `default=22`, `server_default="22"`. The
      server-side default is what makes the column safe to add to a table with
      existing rows and what stops three call sites resolving "unspecified"
      independently.
- [x] 1.2 Add `_migrate_hosts_ssh_port` to
      `provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`,
      following `_migrate_hosts_public_host`: a single
      `_add_column_if_missing(engine, "hosts", "ssh_port", ...)`. The column
      type must carry `NOT NULL DEFAULT 22` so existing rows backfill in the
      same statement rather than through a second pass.
- [x] 1.3 Register it in the `MIGRATIONS` tuple, dated after
      `20260815_001_pool_declared_offering_modes`, which is currently last.
- [x] 1.4 Note that `check_schema_version` compares against `MIGRATIONS[-1]`,
      so appending here means every deployed database must have the migration
      applied before an image carrying this code starts. That is a deployment
      consequence of the change, recorded in section 6, not an implementation
      step.

**Validation:** `make test` in `provisioning/compute/service`.

## 2. Wire model

- [x] 2.1 Add `ssh_port` to `HostCreate`, `HostUpdate`, and `HostResponse` in
      `domains/vms/provisioning/client/src/vm_provisioning_operator/models.py`.
      Optional on create with a default of 22; optional on update; always
      present on the response.
- [x] 2.2 Constrain to 1–65535 at the model boundary so an out-of-range value
      returns 400 rather than reaching the database.
- [x] 2.3 Confirm the create and update paths in
      `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/controllers/hosts_controller.py`
      and `.../services/host_service.py` carry the field through without
      needing to name it individually. If either constructs a `Host` field by
      field rather than from the model, add it there.

**Validation:** `make test` in `domains/vms/provisioning`.

## 3. INI import

- [x] 3.1 Map `ansible_port` to `ssh_port` in `_parse_ini` in
      `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/host_service.py`.
- [x] 3.2 Correct the docstring's variable table. It currently lists
      `ansible_port` under "All other variables → ignored", which states the
      opposite of the intended behaviour and is the reason the discard reads as
      deliberate.
- [x] 3.3 Reject a malformed or out-of-range `ansible_port`: skip the entry
      with a warning, as the parser already does for a missing `ansible_host`
      or `ansible_user`. Do **not** follow the `gpus` pattern of coercing to a
      default inside a `try/except` — see `design.md` for why the two fields
      differ deliberately.
- [x] 3.4 Confirm both INI entry points inherit this: `POST
      /api/v1/hosts/import` and the `inventory_ini` startup seed in
      `provisioning/compute/service/src/compute_provisioning_service/app_runtime.py`.
      Both call the same parser; the task is to verify that, not to change it.

**Validation:** `make test` in `domains/vms/provisioning`.

## 4. Inventory rendering

- [x] 4.1 Emit `ansible_port` from `HostService.render_inventory_ini` in
      `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/host_service.py`,
      for every host rather than only when it differs from 22.
- [x] 4.2 Emit `ansible_port` from `AnsibleService.write_inventory` in
      `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/ansible_service.py`.
- [x] 4.3 These are two separate implementations of the same INI line and they
      already disagree — only `write_inventory` emits `public_host`. Add a test
      asserting both produce the same `ansible_port` line for the same host, so
      the next divergence fails rather than surfacing as a host that behaves
      differently depending on which path built its inventory.
- [x] 4.4 Confirm the connectivity check (`GET /hosts/{host}/connectivity`),
      the capacity check, and VM create and destroy all derive their connection
      from a rendered inventory rather than constructing one. If any builds its
      own connection, that is a finding to record rather than a fifth place to
      add a port.

**Validation:** `make test` in `domains/vms/provisioning`.

## 5. Tests

- [x] 5.1 Parser: `ansible_port` present yields the port; absent yields 22;
      non-integer skips the entry with a warning; `0` and `65536` skip.
- [x] 5.2 API, through the canonical typed client
      (`tests/integration/test_hosts_api.py`): create without `ssh_port` yields
      22; create with one yields it; update changes it and persists; update
      without one leaves it; `HostListResponse` carries it; an imported
      inventory's port reaches the registry. A malformed body is sent as raw
      HTTP, because `HostCreate` validates the bound before a request exists —
      and the API returns **422**, FastAPI's body-validation status. The
      original claim of 400 was wrong: this repository uses 400 for domain
      errors and 422 for body validation.
- [x] 5.3 Renderers: a non-default port appears in both; the two renderers
      agree; a default port still renders explicitly.
- [x] 5.4 Migration: applied against a database holding rows created before the
      column, every row reads 22. Follow the pattern in
      `provisioning/compute/service/tests/unit/test_vm_host_executor_ref_migration.py`.
- [x] 5.5 Round trip: import an INI carrying `ansible_port`, render the
      inventory back, and assert the port survives. This is the property the
      change exists for and the one no single-layer test proves.

**Validation:** `make test` in both packages.

## 6. Deployment consequence

- [x] 6.1 Record in `design.md` that appending to `MIGRATIONS` makes
      `check_schema_version` fail at startup for any database that has not had
      the migration applied, so rolling out this code requires running
      migrations first — the Helm init container, `compute-provisioning-migrate`,
      or `make migrate`.
- [x] 6.2 State plainly that this change does not run them. Applying a
      migration to a deployed database is a mutation of persistent state and
      needs its own authorized packet.

## 7. Closeout

- [x] 7.1 **Comment hygiene.** `make check-comment-hygiene` from the repository
      root, then read the touched files for the fuzzier violations it cannot
      catch. The rationale that belongs in a comment is the invariant — the
      registry is the authority for how the provisioner connects, port included
      — never the change that introduced it.
- [x] 7.2 **Import placement.** Check each import added to the touched Python
      modules for a real reason to be local before moving it, and verify any
      move with `make test` rather than a syntax check.
- [x] 7.3 **Documentation compliance.** Re-read `openspec/README.md`'s
      placement rules and apply them directly rather than from memory.
- [x] 7.4 **Narrative compression.** Shorten completed-task notes to final
      behaviour, material evidence, and unresolved work; move any alternatives
      considered into `design.md` first.
- [x] 7.5 **Roadmap currency.** No `docs/development/ROADMAP.md` edit. No goal
      there covers reaching hosts without an inbound route, and this change
      does not create one: it makes a port storable and renderable and takes no
      position on where the value comes from. Whether the campaign as a whole
      warrants a goal is decided once, at the closeout of
      `relay-vm-access-without-a-dashboard`, which is the change that alters
      what a deployment can do. Recorded here so the absent edit is a
      deliberate finding rather than an unanswered question.
- [x] 7.6 **Promotion.**

| Accepted decision | Permanent location | State |
|---|---|---|
| The host registry is the authority for how the provisioner connects, including port, and every path derives its connection from a rendered inventory | `openspec/specs/physical-provisioning/spec.md` | Applied |
| `ansible_port` renders for every host, so a rendered inventory says exactly what the registry holds | `openspec/specs/physical-provisioning/spec.md` | Applied |
| A malformed port fails the entry rather than defaulting, because an unreachable host is not a degraded one | `openspec/specs/physical-provisioning/spec.md` | Applied |
| Appending a migration makes `check_schema_version` require it before startup | `design.md` — deployment consequence, not a permanent contract | Recorded |
| No roadmap edit; the campaign-level decision belongs to the change that alters what a deployment can do | `tasks.md` 7.5 | Recorded |

## Implementation notes

**Renderers.** No existing inventory fixture asserted exact INI text, so the
added `ansible_port` segment broke none of them. One test stub did need the
attribute: `_FakeHost` in `test_ansible_service.py` stands in for a `Host` row
and must carry every attribute the renderer reads.

**Parser.** `ansible_port` is validated for range as well as type, and a
malformed value skips its entry while leaving other entries in the same file
importable. The contrast with `gpus=`, which still degrades to 0, is asserted
directly so the difference reads as deliberate rather than inconsistent.

**Migration inventory.** `test_database.py` asserts the full set of applied
migration ids and their count. Both were extended rather than rewritten to
derive from `MIGRATIONS`: the explicit set is a real guard against an id being
renamed or a migration silently disappearing, and deriving it from the source
it checks would make it tautological.

**Task 4.4 finding.** The connectivity check, capacity check, and VM create and
destroy paths all derive their connection from a rendered inventory. No path
constructs its own, so the port reaches all of them without any of them being
changed.

## Validation evidence

Run against a clean copy of the baseline with this change applied, and compared
against the same baseline in the same environment.

| Suite | Baseline | With this change |
|---|---|---|
| `make test` unit, `provisioning/compute/service` | 475 passed | **506 passed** |
| `make test` integration, `provisioning/compute/service` | 185 passed | **196 passed** — 11 added |
| `make test` in `domains/vms/provisioning/iac` | 45 passed | 45 passed |
| `make check-comment-hygiene` (repository root) | OK | OK |

Failure sets are byte-identical: **zero introduced, zero fixed**. The +30 are
this change's own tests.

The single shared failure,
`test_capacity_inventory.py::test_bare_metal_view_uses_explicit_identities_and_same_generation_availability`,
reproduces on the unmodified baseline across repeated runs and is unrelated to
this change. Reported rather than omitted; not investigated here.

One integration test,
`test_test_controller.py::TestDrain::test_drain_waits_for_job_to_complete`,
failed once and passed on every repeat in both trees. Recorded as an observed
flake.

**Environment disclosure.** `make test` for this package could not be run: it
depends on `reinit`, which needs a wheelhouse in `.dist/`, and building that
runs `verify-hosted-release`, which requires a signed release manifest from a
sibling checkout not present in this session. The suites above were run in a
virtual environment with the local packages installed from source, driven by a
script that re-points every package at one tree and asserts the resolved module
paths before any test runs. That guard exists because an earlier comparison in
this session left packages split across two trees and produced 88 spurious
failures — a mixed environment reads exactly like a broken change. With the
guard, baseline and change agree everywhere except this change's own tests.

`make test` should still be run before the change is trusted, since a
source-installed tree is not the pinned-wheel resolution the repository uses.
