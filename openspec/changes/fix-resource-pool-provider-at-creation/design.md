# Design

## Context

`kit/resource-pools/src/market_resource_pools/service.py` changes provider in
`replace_pool`, `update_pool`, and `_apply_definition`, deleting old configuration.
Document validation checks backing against stored state but does not check
provider. An API-only guard would therefore leave import as a bypass.

The models in `kit/resource-pools-contracts/src/market_resource_pools_contracts/pools.py`
validate declarations. The service additionally checks hold, SLA, listing shapes,
asking rates and pricing rate lists. Four checks already belong to contracts;
asking-rate structure is mixed with resolution in the authority's `asking_rates.py`.

The design uses the existing non-destructive pool lifecycle and resource-move
invariant. It needs no datastore migration, new route, or request/response field.

## Decisions

### D1. Provider immutability covers every write path

Choose provider at creation. Replace, patch and authoritative document import
refuse a differing provider before mutation, preserving all metadata and provider
configuration. Validate-only reports the violation and no diff. Provider supplies
routing context for existing inventory; checking only replace and patch leaves
import able to violate the same rule. Warning and proceeding preserves the defect.

### D2. Remove unused configuration deletion

Remove `delete_config` from `PoolConfigHandler`, the Ansible and bare-metal
handlers, and test fakes. Remove the direct deletion test in
`provisioning/compute/service/tests/integration/test_ansible_pool_config_handler.py`.
Replace the kit integration test expecting provider replacement with refusal and
preservation evidence.

Remove `delete_config` from the runtime required hooks in
`provisioning/compute/src/compute_provisioning/composition.py`'s
`_validate_pool_config_handler` at the same time. In
`provisioning/compute/tests/unit/test_composition.py`, prove that composition
accepts a handler implementing the remaining required hooks without
`delete_config`, and still rejects a handler missing another required hook.

Provider swaps are the only production callers. Pools are disabled rather than
hard-deleted; same-provider configuration replacement already has `replace_config`.
Keeping deletion leaves a misleading unused protocol surface. Deferring removal
would leave this change's dead surface without reducing its implementation risk.

### D3. Retain the patch provider field

`PoolUpdate.provider` stays, documented as requiring the pool's own value. Equal
has no effect; differing receives the explanatory refusal. PUT retains provider
as full desired state. Removing the patch field would lose that explanation;
deprecating it would add an unnecessary removal promise. Field shapes do not change.

### D4. Immutable-field refusals remain HTTP 400

Use `PoolValidationError` and its existing HTTP 400 mapping, matching backing.
A provider change can never become valid after draining or waiting, unlike a
host move blocked by a relay lease, so that move's HTTP 409 rationale does not
apply. A new conflict exception would split equivalent immutability rules;
changing backing too would widen the contract change without a semantic benefit.
Malformed model bodies are the separate HTTP 422 boundary in D11.

### D5. Field-specific problems explain the migration path

The provider message mirrors backing:

```text
provider of pool 'hetzner-eu' is fixed at creation as 'vm.ansible' and cannot become 'bare_metal.ansible'; declare a second pool with the intended provider and migrate its members instead
```

Document code is `provider_immutable` at `pools[<i>].provider`, using the submitted
source index. Backing keeps `capacity_backing_immutable` at
`pools[<i>].policy_tags.capacity_backing` and its existing message. One generic
code would change backing's contract unnecessarily; prohibition-only wording
would omit the supported path. “Members” covers hosts and capacity resources
without treating their move guards as identical.

### D6. Share stored-state comparisons and keep request checks first

One pure comparison returns provider and backing immutability problems from a
stored pool and proposed values. Each problem identifies its relative field,
code, values and message. It performs no session access and knows no document
index. Individual writes adapt its first problem into `PoolValidationError`;
document administration prefixes every problem with its entry path.

Replace supplies full proposed values. Patch uses stored values for omitted
fields, so omitted tags are not compared with an empty map. New document entries
do not compare against an existing pool. Preserve backing's repair allowance:
supplying backing where none is stored is accepted. Provider has no such exception.

This replaces `_require_backing_unchanged` and `_backing_change_problems`.
Separate field-specific builders and separate API/document implementations were
rejected because their comparisons duplicate the rule and can drift. Models
cannot enforce immutability because they cannot inspect stored state.

Request-only model checks run before database work. Provider registration and
configuration checks remain service-owned because they require the composed
handler registry; contracts must not import authority or provider implementations.
Replace keeps pre-session normalization. Document structure and handler checks
finish before stored-state comparison. Patch may need stored provider context
when provider is omitted; checks needing it remain in the transaction. Unknown
providers may be reported first where the existing path can check them first.
Do not reorder methods or add a lookup merely to prefer another error message.
Use local names or comments to explain this split where necessary.

### D7. Equal provider on patch does not rewrite configuration

Restating the stored provider has the effect of omitting it. Write configuration
only when `provider_config` is supplied, through the pool's own handler. A
same-provider replacement still replaces configuration, retaining existing
secret-retention rules. Rewriting merely because provider was restated would
invoke write checks and touch state without an intended configuration change.

### D8. Documents preserve atomicity and digest behavior

Only a document passing request-only checks reaches stored-state comparison.
An immutability problem makes validate-only return `valid: false`, structured
problems and no diff. Import rejects the complete document before any entry or
omitted-pool disablement is applied. It keeps HTTP 400 and path-named detail text
rendered from the problems; it does not gain a structured import error body.
Applying valid entries while skipping invalid ones would violate atomicity.

The startup importer in
`provisioning/compute/service/src/compute_provisioning_service/services/definition_documents.py`
uses `import_pools_in_session` and records the digest in the same transaction.
A changed-provider document fails startup and records no new digest. Unchanged
documents are still skipped. New entries create their own pools. Omitting an old
entry disables it without requiring members to have moved first: disablement is
draining and preserves obligations. Reusing the same ID for a new pool or
inventing derived IDs is not the supported second-pool path.

Reconciliation may keep comparing provider for equality; no new diff category or
export behavior is needed.

### D9. Keep the existing member-migration guards

Create a second pool and migrate members through existing operations. The
site-capacity requirement “A capacity resource does not move pools under live
obligations” in `openspec/specs/site-capacity/spec.md` protects reassignment,
including across providers. The ledger refuses while a held reservation is
debited against the resource or assigns it for settlement, holding serialization
through commit. The reservation's pool resolves through its capacity resource.

Host moves instead run `HostAuthority` pool-change hooks. The VM adapter refuses
a relay-changing move while the host holds relay leases. A move keeping the
relay may succeed while work exists; it does not reassign the capacity resource
or change the reservation's pool. Do not claim every host move is blocked by the
capacity drain rule.

No pool-level obligation guard is added: it duplicates the site rule across an
authority boundary, and refusing disablement contradicts draining. The delta
refers to the site requirement rather than copying its obligation-state definition.

### D11. Move domain-neutral hint checks into Pydantic

`PoolCreate`, `PoolReplace` and a `PoolUpdate` supplying policy tags validate
hold, SLA, listing shapes, asking rates and pricing rate lists alongside existing
declarations using contracts-owned functions. Individual service writes stop
repeating those checks. Raw document entries reuse them with their existing
field paths/codes. Unknown tags and domain-owned vocabulary keep existing behavior.

Move `ASKING_RATES_POLICY_TAG`, `asking_rate_entry_problems`,
`validate_asking_rates` and their structural helpers into contracts. Resolution,
accepted publication periods, source precedence and rate carriers stay in the
authority. The resolver imports the structural entry check rather than copying
it, and its resolution API and behavior stay unchanged.

Declare `arkhai-kit-capability-shape` in contracts dependencies and its package
allowlist. This foundation-kit edge is permitted and admissibility already
installs the distribution transitively. Leaving this hint in the service would
retain an unnecessary asymmetry. No contracts-to-authority dependency is added.

Malformed hints in individual API bodies become HTTP 422; typed construction
fails locally. Documents carry raw YAML, so invalid document hints still produce
structured validate-only problems or HTTP 400 on import. Provider/configuration
and immutable-field refusals remain service-owned HTTP 400 errors. Ordinary
validated writes do not include `model_construct` or post-construction mutation
of nested data. Keeping duplicate checks solely for bypassing callers was rejected.

Model unit tests own the full hint matrix. Library integration tests own stored
state and transactions. Representative service rejection tests establish HTTP
422 and unchanged state using the documented malformed-request exception to
typed-client testing, without depending on error response field names.

## Whole-design check

### 19 V1 / 20 V1 — Default creation and canonical VM identity

Validation of `a3bd6b1d` exposed a missed bootstrap caller: migration seeded
`default` as `ansible`, then the bare-metal fixture tried to change it to
`bare_metal.ansible`. The owner clarified that bare metal has not launched,
fixtures and the development cluster are disposable, and VM's provider should
be named `vm.ansible`. The owner accepted the revised recommendation: "I agree
with the revised recommendation."

For a genuinely empty database with a configured pool document, migrations
create the schema without the implicit VM default. Ordinary startup imports
contributed definitions first, then creates the default and its configuration
atomically through the complete pool document, then admits inventory. This also
keeps referenced relays ahead of pool configuration without parsing the document
twice or adding a second default-provider setting. A configured but missing or
invalid document fails startup; it does not fall back to a VM pool. An existing
database retains its seeded default and host backfill. With no document, fresh
bootstrap retains the VM default. An existing provider never changes because a
document requests it.

The canonical runtime VM provider is `vm.ansible`, alongside
`bare_metal.ansible`. A versioned migration updates only old VM provider columns
in pools and fulfillment records. It preserves pool IDs, configuration, host
membership, lifecycle state, job IDs, and accepted operation envelopes. Legacy
backfill recognizes both historical and canonical VM names without interpreting
them as distinct providers. Versioned `vm.ansible.*` operation kinds stay as they
are. Existing VM definition documents must use the canonical name; no old-name
runtime alias is introduced.

Keeping an inert VM default and adding a VM playbook to the bare-metal fixture
was the smaller alternative; the owner instead chose creation from the mounted
declaration. A separate configurable provider setting would duplicate the
document's authority, and exempting the default from immutability would retain
the routing defect. No compatibility migration is owed for disposable bare-metal
state. These choices expand the implementation beyond the original review;
another independent implementation review is recommended after the fix.

Permanent destinations: resource-pool spec/default lifecycle and provider
identity requirements, its architecture's administrative reconciliation,
deployment definition-document and migration guidance, repository Resource pools,
and current operator examples. Section 3's appended tasks own implementation and
evidence; closeout promotes durable rationale.

Contracts own domain-neutral request checks; the service owns composed-provider
knowledge and stored-state comparisons; handlers own provider configuration.
The shared comparison stays in the pool authority with no new dependency into
site or fulfillment. The final rationale distinguishes structural and semantic
checks, document text and structured errors, and capacity and host guards.

### Callers and interfaces

| Interface | Callers and resulting behavior |
|---|---|
| Shared comparison | Replace/patch adapt the first problem to the existing exception; validate-only and session-scoped import prefix every problem with its document entry. Omitted fields use stored values; creation is not an immutable-field change. |
| Typed hint validation | Sync/async pool clients, the hosting controller, direct service callers and setup helpers construct the same models. Malformed hints fail before dispatch; a patch omitting tags stays valid. |
| Asking-rate structural helpers | Models, raw document validation, authority asking-rate resolution and structural unit tests share the contracts implementation. Resolution retains its domain callbacks and source precedence. |
| Handler without deletion | The authority keeps validate/read/replace operations. Both concrete handlers, resource-pool/fulfillment/provisioning fakes and the direct deletion test remove unused deletion surfaces. `_validate_pool_config_handler` in `provisioning/compute/src/compute_provisioning/composition.py` stops requiring deletion; `provisioning/compute/tests/unit/test_composition.py` proves acceptance without it and preserves rejection for missing remaining required hooks. |
| Session-scoped import | Explicit import and startup get the same refusal before apply; startup retains its combined apply/digest transaction. |
| Member administration | Site registration and capacity documents retain the obligation guard; host update and inventory retain hooks. No caller implements a new migration interface. |

Every caller can act through these interfaces. Clients and startup do not need
to interpret a new internal problem representation.

### Scope against the original proposal

Additions are document-path coverage (D1/D8), dead handler cleanup (D2), shared
comparisons (D6) and model hints/asking-rate relocation (D11). All remain within
`resource-pool-management`; none adds a prerequisite, a second domain's behavior
or a separate authority. The owner explicitly included the validation migration
and agreed D11's same-change scope. No further split is needed. D10's destination
list is documentation work, not a decision requiring owner approval.

### Owner principle for closeout consideration

Check what the request can establish by itself first, in Pydantic where package
boundaries permit; then check composition-dependent and stored-state semantics
in the service. This trades a sometimes less specific error for avoiding database
work on a request wrong on its face. Share pure comparisons across paths instead
of duplicating the validation in adapters.

The design applies this locally. General guidance, its wording and permanent
home remain for the owner's closeout consideration.

## Open Questions

- At closeout, the owner decides whether the validation-order principle warrants
  general guidance and chooses its wording and home. Revisit during promotion;
  no task may prescribe the guidance edit before that decision. No implementation
  design question remains open.

## Permanent documentation and planning handoff

`proposal.md` names provisional permanent destinations for planning and review.
Promotion includes the subsystem spec and architecture, repository Resource
pools and thin-distributions descriptions, testing ownership, document behavior,
roadmap and campaign currency. The Evidence section needs an explicit edit;
requirement merging does not update it.

Planning preserves task history and adds all write paths, shared comparisons,
handler cleanup including the direct deletion test and the runtime required-hook
check in `provisioning/compute/src/compute_provisioning/composition.py`'s
`_validate_pool_config_handler`. Include
`provisioning/compute/tests/unit/test_composition.py` coverage accepting a handler
without deletion while preserving rejection for missing other required hooks.
Also include contracts model/asking-rate tests, direct shape dependency and
affected locks/wheels, HTTP 422 evidence and the named promotions. Design does
not edit `tasks.md` or promote unimplemented behavior into permanent documentation.

## Design validation

The owner settled the design after the whole-design check. Independent review
`14-design` has run; the owner accepted F1 and F2, and both document corrections
are recorded. The owner passed the review gate: "Pass the gate." The change is
`ready for planning`; the existing plan must be amended to match the settled design.

- `npx --yes @fission-ai/openspec@1.14.0 validate fix-resource-pool-provider-at-creation --strict`
  passed. The repository-pinned version was selected explicitly rather than the
  older globally installed executable.
- `make check-doc-citations CHANGE=fix-resource-pool-provider-at-creation` passed
  for all four change documents; every checked citation resolves and none targets
  a tombstone.
- `git diff --check` passed.

Code and behavioral suites belong to implementation; this pass claims no
implementation validation. `tasks.md`, code and permanent documents were not
edited during recording.
