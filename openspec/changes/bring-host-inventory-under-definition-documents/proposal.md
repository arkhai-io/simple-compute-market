## Why

Relays, pools, and capacity declarations reach the provisioning service as
definition documents. A startup applies such a document only when its digest
differs from the one recorded with the last apply, so editing a mounted document
and rolling the deployment applies the edit, while a restart against an
unchanged document changes nothing and API edits survive.

Host inventory follows an older rule. The inventory (`inventory_ini`, or the
file at `inventory_path`) is read at startup only when the host registry is
empty, and never again. An operator who edits the inventory of a running
deployment and rolls it sees nothing happen: the new host is not registered,
and no error says why. Since execution renders only from the registered host
record and refuses a host with none, the gap surfaces as refused dispatch. The
seed also swallows its own failures: an inventory naming an unknown pool, or one
the parser cannot read, starts the service with no hosts and only a log line.
Under Helm the inventory sits in an operator-managed Secret whose edits do not
roll the pod.

The principle the definition documents already follow, that a process start is
not a submission but a changed document is, applies to hosts exactly as it
applies to relays.

## What Changes

- Hosts are declared in a YAML host definitions document with the registration
  API's field names (`host_id`, `pool_id`, `enabled`, `connection`), configured
  by `host_definitions_path` and, under Helm, the provisioning chart's
  `definitions.hosts`, rendered into its ConfigMap.
- A startup reconciles the document only when its digest differs from the last
  applied one, recording the digest in the apply's transaction, after pools and
  before capacity declarations. A document that cannot be applied fails startup
  whole and records no digest.
- An entry declares its whole host: an omitted pool unplaces it and an omitted
  `enabled` enables it, through the pool-change hooks; an entry equal to the
  stored host writes nothing. A host the document stops naming is retained and
  reported. The document never carries a credential.
- `GET /api/v1/hosts/definitions/export` returns the registry as a canonical
  host document in YAML, and `POST /api/v1/hosts/definitions/import` reconciles a
  submitted document regardless of the digest, with a validate-only mode; like
  the capacity-definitions import, an applying request with any problem answers
  422 with every problem and validate-only answers 200.
- **BREAKING** Startup reads no INI inventory: `inventory_ini` and
  `inventory_path` are retired and refused at startup whenever stated, an empty
  value included, and every packaged statement of them is removed. The INI
  remains the format of `POST /api/v1/hosts/import`.
- The provisioning chart's schema also refuses `relay_definitions_path` under
  `config`, as it refuses the pool and capacity paths.
- The `ssh` connection codec validates its fields strictly for every submission,
  so a document refuses a quoted number in a connection, and the host API now
  refuses one it used to coerce.
- `DEPLOYMENT_AND_CONFIG.md` states the method every definition document kind
  follows. A new operator handbook, `docs/operator-handbook.md`, holds the
  operator account of the host, pool, and capacity documents, moved out of
  `DEPLOYMENT_AND_CONFIG.md`, whose normative rules go to their specs.

## Capabilities

### Modified Capabilities

- `physical-provisioning`: how hosts enter the host registry — the host
  definitions document, its startup reconciliation, its export and import
  routes, and the retirement of startup INI seeding — and strict typing of a
  connection's codec fields for every submission.
- `deployment-state`: the provisioning chart's `definitions.hosts` value and its
  refused keys.
- `resource-pool-management`: a host definitions entry's rule for its host's
  pool, beside the create, update, and INI rules of explicit host membership;
  and the startup rule of a configured pool document, which
  `DEPLOYMENT_AND_CONFIG.md` stated and no requirement did.
- `site-capacity`: a declaration's capacity names at least one dimension, a
  rule the authority enforces and the operator account of capacity documents
  states, which the requirement accepting any set of dimensions left unstated.
- `change-workflow`: a shell write refused by a deny rule that exists only to
  keep file writes on the Edit and Write tools, and then made with the tool the
  step's rules allow, is a gap rather than a workaround.

### New Capabilities

None.

## Non-Goals

- Do not change how execution resolves a host: it renders only from the
  registered host record.
- Do not decide who generates a host's key material;
  `contain-embedded-host-key-material` owns key material's lifetime on the
  execution path.
- Do not make a disabled host unsellable;
  `keep-new-deliveries-off-disabled-hosts` owns that.
- Do not require a capacity declaration to sit in its host's pool.
- Do not change the INI import route's semantics.

## Impact

- The compute family kit's host authority (`compute_provisioning.hosts`), its
  contracts and typed client: the host document, its session-scoped apply, the
  export and import routes.
- The provisioning service: its definition-document importer, startup steps,
  settings, retired-settings refusal, and controllers; `seed_inventory_if_empty`
  is removed. Every packaged statement of the retired settings goes: both keys in
  `settings.toml`, `inventory_path` in `config-docker.yml`, the service
  Makefile's local run target, and `config-local.yml.example`.
- The provisioning Helm chart's `definitions` values, schema (including the
  `relay_definitions_path` refusal), ConfigMap, deployment mounts, and render
  tests, and the `inventory_path` in its `values.yaml`; the topology secrets
  script stops writing `inventory_ini`.
- The VM seller and bare-metal compose stacks, and the bare-metal end-to-end
  lane's host file.
- The Ansible distribution's `ssh` codec (`compute_provisioning_ansible`, a minor
  version): strict field types for every submission, including
  `POST`/`PUT /api/v1/hosts`.
- Operator documentation of how hosts are added, and both seller quickstarts.
- A new `docs/operator-handbook.md` holding the operator account of the host,
  pool, and capacity documents, moved from `DEPLOYMENT_AND_CONFIG.md`'s
  "Definition documents"; a row for it in `openspec/README.md`'s placement table
  and a line in `AGENTS.md`'s documentation ownership.
- Deployments: an operator stating `inventory_ini` or `inventory_path` must
  replace it with a host document before upgrading, and every Helm deployment
  whose provisioning-secrets Secret states `inventory_ini`, even empty, must drop
  the key before upgrading.
- The change workflow's tooling, fixed on this branch: the design step's
  proposal-worktree rules in `.claude/change-steps.toml`, the review wrapper's
  title check in `scripts/change_workflow/review.py`, and the reading of a
  deny-rule denial redone with the Edit or Write tool. The last is stated in the
  change-workflow spec and companion, the step skills, the change-orchestrate
  skill, and `docs/agents/change-workflow.md`, with the table's markings left
  for the owner's local run. Also, from the implementation round's triage: a
  run ended by a signal keeps the denials its stream's `permission_denied` events
  name, whether or not they give a reason (`scripts/change_workflow/stream.py`), and the change-orchestrate skill gives
  each step run the harness's longest timeout.

## Dependencies and Related Changes

- Independent: nothing must land first.
- `keep-new-deliveries-off-disabled-hosts`, opened from this design, makes
  disabling a host keep new deliveries off it; when it lands, whether a document
  should disable the hosts it stops naming is open to revisiting.
- Coordinates with `contain-embedded-host-key-material`: a host document names a
  key by file path or keeps a stored protected key, and never carries key
  material.
- `prove-relay-provisioning` and `admit-relay-proxies-by-grant` rework relays; the
  open question of a declaration's pool against its host's waits on them.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `physical-provisioning`,
      `deployment-state`, `resource-pool-management`, `site-capacity`,
      `change-workflow`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Host inventory is a digest-gated definition document (D1), its YAML format with
  registration field names and the retirement of startup INI seeding (D2), whole
  replacement per entry (D5), retention of unnamed hosts (D4), whole-document
  failure (D7), no credential in the document (D9), its export (D12) and import
  route (D14) → `openspec/specs/physical-provisioning/spec.md` (by the archive),
  and the operator account in `docs/operator-handbook.md`.
- A codec types its connection's public fields strictly for every submission
  (D7, 45 F1) → `openspec/specs/physical-provisioning/spec.md`, "Host
  connections are typed by their implementation's codec" (by the archive).
- The operator account of the host, pool, and capacity documents (D13, 47 O1) →
  `docs/operator-handbook.md`, with its row in `openspec/README.md`'s placement
  table and `AGENTS.md`'s documentation ownership; the rules that account
  stated and no spec did → the `resource-pool-management`,
  `physical-provisioning`, and `site-capacity` deltas (by the archive); the
  last, a declaration's one-dimension minimum (61 F1), → "A capacity
  declaration names no mandatory dimension".
- The chart's `definitions.hosts` value and refused keys, the relay path's
  refusal included (D3) → `openspec/specs/deployment-state/spec.md` (by the
  archive) and `DEPLOYMENT_AND_CONFIG.md`.
- A host definitions entry's pool rule (D5) →
  `openspec/specs/resource-pool-management/spec.md`, "Explicit valid host
  membership" (by the archive).
- Why host inventory is a reconciled declaration owned by the family kit, why
  unnamed hosts are retained, and the first-document path through the export (D4,
  D6, D8, D12) → `openspec/specs/physical-provisioning/architecture.md`, beside
  "Selected-resource execution" and "The host registry owns the connection".
- A deny-rule denial redone with the Edit or Write tool is a gap when the rule
  exists only to keep file writes on those tools (D11) →
  `openspec/specs/change-workflow/spec.md`, "Unattended runs are held to their
  step's permissions" (by the archive), and
  `openspec/specs/change-workflow/architecture.md`, the denial paragraph of
  "Restrictions bind unattended runs only" (written in section 6).
- The general method every definition document kind follows (D13) →
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Definition documents".
- Startup order with host definitions in place of the inventory seed (D8) →
  `openspec/specs/resource-pool-management/architecture.md`, "Administrative
  reconciliation", and `docs/development/ARCHITECTURE.md`, "Resource pools".
- The inventory file no longer seeds the registry at first boot →
  `docs/development/ARCHITECTURE.md`, `docs/development/ROADMAP.md` Goal 1's
  current state and its gap row, `docs/seller-quickstart.md`,
  `docs/bare-metal-seller-quickstart.md`, `domains/vms/provisioning/iac/README.md`
  (which says the service registers every entry of `provisioning-hosts.ini`),
  `openspec/specs/site-capacity/architecture.md` (no host write declares
  capacity, "not an INI inventory applied at startup"), and the evidence
  paragraph of `openspec/specs/physical-provisioning/spec.md` that cites the
  startup inventory seed.
- Two scenarios the `physical-provisioning` delta modifies keep titles naming an
  inventory file over bodies that describe a host definitions document, because
  a modified requirement cannot rename its scenarios → after the archive, retitle
  them in `openspec/specs/physical-provisioning/spec.md`: "The inventory file
  seeds the host registry" to "A changed host definitions document registers its
  hosts", and "Fresh selected-site inventory binds to a bare-metal pool" to "A
  fresh site's host document binds to a bare-metal pool".
