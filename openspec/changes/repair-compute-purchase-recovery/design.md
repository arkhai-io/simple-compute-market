# Design — repair compute purchase recovery

## Context

A controlled real purchase of a whole bare-metal host, settled through
`arkhai.payments.v1` in test mode, showed four failures. Each was diagnosed against
this branch's base before anything was designed.

1. **A buyer rejected a correctly signed receipt.** The installed buyer refused the
   payments service's receipt because `receipt.livemode` was an unknown field. The
   repository's payments kit already models and verifies `livemode`. The installed
   wheel was a stale build carrying the same version number. Replaying the captured
   signed test receipt through the current kit parses it and verifies its signature,
   transaction, deal, parties, and mode. It still refuses a live-mode expectation, a
   flipped mode, a tampered proof, another mandate, and an unknown extra field.
   **Nothing is changed for this.** It is qualified by rebuilding the buyer
   environment through the wheelhouse workflow.
2. **A real grant's result was lost.** The grant ran, created the tenant account, and
   installed the buyer's key, but its job recorded no result, so the fulfillment
   failed for lack of delivery evidence.
   - The provisioning service exports the Ansible configuration it packages, which
     sets `callback_result_format = yaml`.
   - Under it, `debug: var: node_grant_access_data` prints the fact as YAML with an
     unquoted key.
   - `compute_provisioning_ansible.runner.extract_fact` looks only for the JSON-quoted
     key `"node_grant_access_data":`, so it finds nothing.
   - The VM codec survives because it falls back to the JSON `msg:` block its role
     also prints. The bare-metal codec has no fallback.
   - Every mock output and codec test uses the JSON callback form, so no lane ever ran
     the shipped form.

   Replaying the captured output through current source reproduces the null result.
3. **A buyer could not recover its run.** `market bare-metal access --run-id` refused
   the run log its own `buy` wrote. The producer recorded `publisher_principals` as a
   list, and the consumer reads a `TrustedIdentitySet`. The producer was corrected
   before this change; the current producer's form round-trips. Nothing tests that
   what `buy` writes, `access` reads.
4. **A failed create could not be released.** After the failed create, the buyer's
   teardown left the lease `release_failed` with no teardown job and its capacity
   held. That is the specified behaviour: a `failed` aggregate has no teardown, and the
   lease waits for an operator to verify the host and force-release. Here the host
   carried real effects (a tenant account and key) that no automated path could
   remove.

Investigating the delivered endpoint found a fifth problem. The grant reports the
management connection's address and port as the buyer's endpoint. In the purchase's
topology the provisioner reaches the host through an in-cluster tunnel on a
non-standard port, while the buyer reaches the same host through a private network on
port 22. The registry records a tenant-facing `public_host`, but no tenant-facing port,
and the bare-metal path uses neither.

The second qualification target is a CPU-only ARM64 virtual machine on the same kind of
host. Three findings stand in its way:

- The compute capability schema requires the `gpu` family, so no VM shape without a
  GPU can be stated, published, or claimed. Any VM listing carries a GPU dimension,
  which selects the GPU passthrough path.
- The VM create recipe hard-codes an amd64 cloud image and passes no architecture,
  machine type, or firmware.
- VM teardown fails when a partial create left no cleanup script, and its rule cleanup
  matches guest addresses by prefix, so one guest's removal can touch another's rules.

Two design reviews on 2026-10-28 shaped the decisions below:
- The first (`reviews/01-design.md`) and its triage revised D1, D4, D7, and D10, and
  added D6's promotion.
- The follow-up (`reviews/02-design.md`) and its triage did three things:
  - D1 takes on the VM pipeline scenarios' fixed create output.
  - D4 states the `authorize` adapter, what of a create's failure stays durable, and
    the handle a refusal is recorded under.
  - D10 names the site's own states, compares the projection's full availability,
    and states the pause's precondition and coverage gaps.

The decisions below are written as settled by those triages. The Round 1
implementation review's F1 (`reviews/03-implementation-external.md`) reopened D3's
compatibility: the owner settled that `ssh` is served at version 2 only.

## Goals and non-goals

**Goals.**
- A real grant's result reaches fulfillment whatever the callback's display format,
  and only a document selected for the job's own action and target is taken as its
  result.
- The buyer receives a tenant-facing endpoint.
- A failed create that may have left effects is compensated by the same teardown its
  domain already defines, and its capacity returns only once that teardown is proven.
- A bare-metal run log is recoverable by the commands that read it.
- A truthful CPU-only ARM64 VM can be sold, delivered, and torn down without GPU
  passthrough.

**Non-goals.**
- GPU passthrough, and guest or tenant isolation and sanitization.
- Network or security redesign of VM guests.
- Marketplace or pricing redesign. The five-minute price refusal is recorded only.
- Unrelated route and pause defects.
- Retiring the host record's GPU fields.
- A general teardown-retry redesign.
- Any change to the payments kit or the payments service.
- A cross-site accounting redesign, or a generic change to the site ledger's scalar
  mirror.

## Decisions

### D1. One fact reader for the compute family, independent of the callback's format

`compute_provisioning_ansible` owns reading a printed result fact. Its reader is given
the output, the fact name, and the action it expects, and accepts the fact in either
form a role prints:

- the `debug: var:` form under the JSON callback format, which `extract_fact` reads
  today;
- the JSON document a `debug: msg:` task prints, under the YAML callback format, as
  a literal block (`msg: |` or `msg: |-`) of indented lines. Every compute role
  prints the fact this way for external parsing.

The YAML `var:` form is not parsed: reading it needs a YAML parser the kit declares
only for development. Both roles already print the JSON `msg:` block, so it carries
the same fact.

**Block boundaries.** A `msg:` literal block is the indented lines that follow its
`msg: |` or `msg: |-` line. The block ends at the first non-blank line indented no
deeper than the `msg:` key. The reader parses each block on its own, as one JSON
document after removing the common indentation. It never scans past a block's end
into a later task's output.

**What the reader takes and ignores.** For each block:

- A block that is not JSON is ignored. The playbook's human-readable summary block
  is one such block.
- A block whose JSON is not an object is ignored.
- A document with no `action` key is ignored.
- A document naming another action is ignored.

The reader cannot know what action an unparsable block was meant to carry, so an
ignored block is never a "malformed result" in its own right. When no block is a
well-formed document for the expected action, and no JSON `var:` fact is printed,
the fact is absent. An absent fact means no result, so delivery fails closed. The
job's redacted log is then the diagnostic. The reader logs, at debug level, only how
many blocks it ignored and why, never their content, since a block may carry
credentials.

When several well-formed documents name the expected action, the last is the fact.
The JSON `var:` form, when present, is taken first, as today. The reader judges
nothing else about the fact; what it means, and whether it belongs to the job, is the
codec's.

The VM codec's private `msg:` fallback (`extract_vm_fact`) is replaced by this reader,
so both domains read facts through one implementation. This follows `ARCHITECTURE.md`
("one behavior is chosen for both and composed from the kit both use"). The fallback
it replaces scans forward from any `msg:` to the next `{` and takes the last document
with any `action`. A `vm_remove` run could therefore adopt a create document, and a
summary block could adopt a later task's JSON.

**The expected action is the domain's.** Each codec passes the `action` its role
prints for the job, from its own mapping:

| Domain | Job | Expected fact `action` | Fact name |
|---|---|---|---|
| Bare metal | `node_grant_access` | `node_grant_access` | `node_grant_access_data` |
| Bare metal | `node_reclaim_access` | `node_reclaim_access` | `node_reclaim_access_data` |
| VM | `vm_action` `create` | `create` | `vm_creation_data` |
| VM | `vm_action` `vm_remove` | `vm_remove` | `vm_remove_data` |

On this base a VM job's action is its `vm_action` (`jobs_model.py`), and both VM roles
print `action` equal to it (`vm-create.yml`, `vm-remove.yml`). Other VM actions keep
the expected action their `VM_RESULT_FACTS` entry implies.

**Linkage at the owning seam.** The codec, which owns what a result means, compares a
selected fact with the variables the job itself passed to the role. This guards
against taking the wrong document from one run's output. It is not proof of
provenance across runs, and no stronger claim is made for it.

A bare-metal grant's fact yields delivery evidence only when:
- its `action` is the job's action;
- its `host_id` is the job's host (the role prints `executor_target`, which bare metal
  sets to the host);
- its `ssh_user` is the tenant account the job's parameters name;
- its `physical_host_id`, when the job names one, is that machine's;
- its `status` is `success`.

A bare-metal reclaim's fact is checked the same way, and its result is a diagnostic:
- a selected fact that matches the job is the result, unchanged;
- a selected fact that does not match is replaced by `{"mismatch": ...}`, naming
  what differs, so an unlinked document is never recorded as the reclaim's result;
- with no fact selected, the job carries no result.

The mismatch decides nothing about the teardown. Whether the teardown succeeded or
failed is still the reclaim job's status, and no evidence or linkage gate is added
to teardown. That keeps proof-driven release as the release requirement states it:
the release follows the fulfillment aggregate, which follows the teardown job. No
production code reads a reclaim's result value. A mismatch therefore records what
the run printed for an operator. It does not prove the cleanup was safe, and it does
not stop one.

A VM create's fact yields delivery evidence only when:
- its `action` is `create`;
- its `vm_name` is the job's `vm_target`, which the play passes as `vm_name`;
- its `status` is `success`.

Its tenant account and forwarded port are then read from that fact (`tenant_user`,
`external_ssh_port`) or its relay block, not from a search of the whole output. A
marketplace create carries the buyer's key, because the key is a negotiated term, so
it runs the role's provided-key variant, which prints the relay block as `frp`, the
key the codec reads. The
fact's `host` is the play's `tenant_ssh_host`, `public_host` or else the inventory
alias. It is not compared: the buyer-facing address remains the registry's
(`public_host` or `ssh_host`), as today.

A fact failing any check yields a result with no evidence and a detail naming the
mismatch. The family's provider then fails the create, as it fails any create without
evidence. Nothing fabricates evidence from a mismatched fact.

**Mocks print what the shipped configuration prints.** Each compute adapter's mock
output renders the YAML `var:` block and the `msg: |-` JSON block, as the real runner's
output contains them, so the mock lanes exercise the real read path. The reader's own
unit tests keep the JSON `var:` form covered.

The default output is rendered for the job, as bare metal's already is:
- **A VM create** prints the role's provided-key create fact. Its `vm_name` is the
  job's `vm_target`, and its `tenant_user` is derived from that name as the role
  derives it, by removing every non-alphanumeric character and lower-casing. Its
  `status` is `success`, its `timestamp` is the time of the run, and it reports a
  forwarded port, and reports no relay. A relay's address is filled in only at
  execution and is not among the job's stored parameters, which are all a mock
  render reads. A relay-backed case therefore arms a rule with its output, at the
  level that tests it. No pipeline lane is relay-backed.
- **A VM remove** prints `vm_remove_data` naming the job's guest, as the remove role
  does.

The fixed create output VM prints today (`mock-vm`, status `running`) fails D1's
linkage, and so is replaced.

**The VM pipeline scenarios use that default.** Five VM scenario modules arm a create
rule with a fixed, successful `result_stdout`:
- `e2e-tests/tests/e2e/roles/scenarios/vms/compute_deal_driver.py`;
- `test_full_deal_buyer_cli.py`;
- `test_listing_shapes.py`;
- `test_buy_oneshot_buyer_cli.py`;
- `test_non_erc20_settlement.py`.

A rule's stdout replaces the default output. Each of these names a guest that is not
the job's (`e2e-test-vm`, `e2e-shapes-vm`, `e2e-buy-vm`), states no `status`, and is
printed in the JSON `var:` form. Under D1 their creates yield no evidence and fail, and
they never reach the `msg:` path.

The rules keep their match, their gate, and their identities, and drop
`result_stdout`, so each create gets the per-job default. No other part of those
scenarios depends on the fixed values: nothing asserts on `vmuser`, port `2222`, or a
fixed guest name. None of the five is a deliberate invalid-output case. A case that
needs invalid output stays at the codec's or the provider's unit or application level.
No mock framework or template mechanism is added: the default output is already a
per-job function, and a fixed successful fixture has no other reason to exist.

Alternatives rejected:
- *Switch the packaged configuration to the JSON format.* Parsing would then depend
  on a display setting any deployment may override through `ansible_cfg`.
- *Parse YAML.* This adds a runtime dependency to read a fact the role already prints
  as JSON.
- *A structured callback plugin.* This replaces the output contract of every role,
  for no gain over D1.
- *Compare the VM fact's `host` with `host_id`.* The role prints `tenant_ssh_host`
  there, so the comparison would fail every host that names a `public_host`, and
  would claim a relation the role never states.

### D2. Fixtures are synthetic

Public tests use synthetic output in the shipped callback's shape, built with
development values: a reserved documentation address, a synthetic tenant name, and
zeroed identifiers. Captured output from a real purchase never enters the repository.

One integration case drives such output through the job authority and the job-backed
fulfillment provider, and observes an active fulfillment through the typed client. A
mismatched or absent fact leaves the fulfillment `failed`.

### D3. The tenant-facing endpoint has an address and a port, each falling back to the connection's

An `ssh` connection gains an optional `public_port` beside `public_host`: the port
tenants use to reach what the host delivers, from the network they reach it on.

- It is validated as a port, 1–65535.
- Absent, the tenant-facing port is the connection's `ssh_port`, as an absent
  `public_host` is the connection's `ssh_host`.
- The runner renders `public_port=` beside `public_host=` when set.
- The INI host format reads `public_port=`, and refuses a malformed value by rejecting
  its entry, as it does `ansible_port`.
- `ssh_connection()` takes it, so the INI parser and typed callers submit it.
- The rule "The tenant-facing host address falls back to the connection address"
  extends to the port.

A bare-metal grant's delivery evidence is built by its codec from the registered host
the job ran against: `public_host` or else `ssh_host`, `public_port` or else
`ssh_port`, and the tenant account the fact confirmed. The host registry owns the
connection, and the fact's own `host` and `port` describe the provisioner's inventory,
not the buyer's route. They remain operator detail only.

The VM codec takes its host from `public_host` or `ssh_host`, as today. Its tenant
port stays what its role reports for the guest (the forwarded or relay port), not the
host's `public_port`.

**Compatibility: `ssh` is served at version 2 only.** `RELEASING.md`'s versioning
policy says a contract that carries its own version is never changed in place, so
`public_port`, which a version-1 reader refuses, belongs to a new version. Before 1.0.0
the release that introduces a version may stop accepting the one before, and this
change does so. The repository has no production deployment, and every host record it
has written is a development or test record, so no reader or writer of version 1 needs
to be kept:
- **Version 2 is the only version served.** It is version 1 with the optional
  `public_port`. A connection is submitted and stored at version 2 whether it states
  a port, states none, or states it as null; an absent or null port is stored with no
  key, and the address and port fall back as above.
- **What writes it.** `ssh_connection()`, and the INI import through it, always submit
  version 2. The generic `ConnectionSubmission` keeps its default of version 1, which
  is not `ssh`'s to change: a caller that states no version is refused, naming version
  2, rather than read as version 2. Every typed caller in the repository states it.
- **Dispatch.** The host authority's codec registry is keyed by kind, as on `dev`, and
  `build` refuses a submission at another version than its kind's codec serves, naming
  it. The service registers one `ssh` codec. No caller needs more than one version of a
  kind, so the registry keyed by kind and version that served both is removed, and the
  family kit is unchanged from `dev`.
- **Reading.** `SshConnectionCodec.parse`, the strict read that execution and probes
  use, checks kind and version before any field, and refuses a host stored at version 1,
  telling the operator to re-register it. Host reads (`GET /api/v1/hosts`) do not pass
  through a codec and still list such a host, at version 1.
- **Moving a stored host forward.** A host stored at version 1 runs nothing until it is
  submitted again at version 2, and nothing rewrites it on its own:
  - `PUT /api/v1/hosts/{host_id}` with a version-2 connection. An update replaces the
    connection's whole public mapping, so it restates every stored public field,
    `key_path` included where the host has one, and the tenant route, at version 2,
    and submits no `private_key` secret. A host whose key is a file keeps it through
    the restated `key_path`; omitting it would leave the connection naming no key,
    which is refused. A host with a protected key and no `key_path` keeps that key: a
    protected key the submission neither resubmits nor replaces with a file is
    carried forward from the stored row as opaque ciphertext, never read or
    decrypted. Pool, enabled state, and GPU description are untouched unless the
    update states them.
  - An inventory import (`POST /api/v1/hosts/import`), which upserts each entry it
    names at version 2 with the key the entry names; for a host whose key is a file,
    an entry naming the same file is the alternative to the update. An entry stating
    no `pool_id` leaves the host's pool as it is.
  - Startup seeding from an inventory file applies the same upsert, but only on a
    service whose registry is empty, so it upgrades nothing that is already stored.
- **When.** A retained development or test host is moved forward in the same rollout
  that deploys the service serving version 2, after that service is running and before
  any work is dispatched to the host. The service serving version 2 refuses a
  version-1 record at execution, and the service before it was never written or
  qualified to read a version-2 record: its strict read does not check the version,
  and refuses only a record stating `public_port`, so nothing relies on how it treats
  one. The update keeps the host's
  identity, pool, enabled state, route, and key, whether a file reference or a
  protected key, and changes no host-side state; a listing that
  must not trade during the rollout stays paused through it. No database row is
  rewritten by hand.
- **No downgrade.** This change provides and qualifies no downgrade to version 1. Its
  rollout installs the service serving version 2 together with the components that
  call it, and moves retained test data forward explicitly, as above.

Alternatives rejected:
- *Additive to version 1.* This is the change in place the policy forbids.
- *Serve versions 1 and 2 side by side, with a documented downgrade.* This was the
  choice after merging `dev`. It lets existing records keep running without an
  explicit upgrade, at the cost of keeping a second contract, a registry keyed by
  version, and a downgrade path to test. No production deployment exists, so no
  compatibility obligation requires that cost, and the owner chose coordinated
  upgrades instead (`reviews/03-implementation-external.md`, F1).
- *Read version 1 as version 2.* A stored version-1 row would then be reinterpreted
  silently; refusing it until it is submitted again keeps every upgrade explicit.
- *Change `ConnectionSubmission`'s default to version 2.* The default is the generic
  contract's, shared by every connection kind.

**Completed results are not rewritten.** A grant's endpoint is computed when its job
completes and stored in the job's result. The delivery is read back from that
stored result. A host's later route edit does not change an active lease's reported
endpoint, and a job completed before this change keeps its stored result. The
bare-metal storefront's recorded result carries no endpoint, so the storefront's
delivery-conflict refusal cannot be triggered by the change.

### D4. A failed create that dispatched is compensated by its domain's teardown

Today a `failed` aggregate is terminal, and its lease waits for an operator to
force-release. This change makes one class of failure compensable automatically:
**a create that was dispatched and failed, whose provider can prepare its teardown
from durable state.**

#### Eligibility

One predicate, `compensable(state, failure_reason, provider_metadata)`, decides it. It
is owned by `compute_provisioning.release`, because the compute family owns both the
reason its convergence records for a reported create failure and the job-backed
provider's metadata, `JobFulfillmentMetadata`, which
`compute_provisioning.job_fulfillment` owns. It is a pure function of those three
durable fields of one aggregate. An aggregate is compensable when every one of these
holds:

- its state is `failed`;
- its `failure_reason` is `provider_reported_failure`. Convergence writes that reason
  only when it moves an aggregate from `dispatching` to `failed`, after a create job
  was submitted and acknowledged;
- its provider metadata parses as `JobFulfillmentMetadata` whose `operation` is
  `create` and which names its create job, host, and target.

Every other `failed` aggregate is ineligible, and its lease goes to `release_failed`
for an operator, exactly as today:

- a quarantined row (`legacy_executor_identity_quarantined`);
- a row failed for `invalid_provisioned_resource_metadata`;
- a row with no or unreadable provider metadata, such as a create never acknowledged;
- a provider that is not job-backed.

A compensable row whose provider then cannot prepare its teardown, because its create
job is missing or the selected resource disagrees, is refused when compensation
begins. That refusal is handled below.

#### The kit operation

The fulfillment kit adds the transition `failed` → `teardown_dispatch_pending`, and one
operation that takes it:

```text
async FulfillmentOrchestrator.begin_compensating_teardown(
    fulfillment_id, *, authorize: Callable[[CompensationCandidate], bool]
) -> FulfillmentAcceptance
```

`CompensationCandidate` carries the record's state, its failure reason, and its provider
metadata as an opaque mapping. The kit passes these without interpreting them. The caller's `authorize` judges them, so the kit never interprets compute
provider metadata, and nothing of it reaches a wire DTO.

Inside one write transaction, mirroring `begin_fulfillment_teardown`:

| Current state | Answer |
|---|---|
| unknown `fulfillment_id` | `SettlementEntityNotFoundError` |
| `teardown_dispatch_pending`, `tearing_down`, `teardown_failed`, `torn_down` | the current view, writing nothing (idempotent adoption, as `begin_fulfillment_teardown` answers) |
| `failed`, `authorize` false | `CompensationRefusedError` (a `FulfillmentConflictError`); nothing written |
| `failed`, `authorize` true, the provider's `prepare_teardown` raises `ProviderConfigInvalidError` (the job-backed provider raises it for a missing create job, and for metadata naming another host or target) | `CompensationRefusedError`; nothing written; the aggregate stays `failed` |
| `failed`, `authorize` true, preparation raises anything else | that error propagates; nothing written; the caller treats it as transient |
| `failed`, `authorize` true, preparation succeeds | records the prepared teardown and moves to `teardown_dispatch_pending` with `failure_reason` `create_compensation`; returns the view |
| `assigned`, `dispatch_pending`, `dispatching`, `active`, `abandoned` | `FulfillmentConflictError`; nothing written |

`begin_fulfillment_teardown` is unchanged: it still begins only from `active`, adopts
an already-begun teardown, and refuses `failed`.

#### The compensation marker

`create_compensation` is the kit's constant for the reason a compensating teardown
records. **A compensated aggregate is one whose `failure_reason` is
`create_compensation`.** It ended compensated when its state is also `torn_down`. A
non-null reason alone means nothing: a delivered fulfillment whose teardown failed
once and later succeeded also reaches `torn_down` carrying `provider_reported_failure`,
because convergence never clears a reason.

What the fields hold:
- **When compensation begins**, `failure_reason` becomes `create_compensation`, and
  `failure_message` keeps the create failure's message that convergence recorded.
- **On a teardown failure**, convergence writes `teardown_failed` with the teardown's
  detail. For an aggregate whose reason is `create_compensation`, it keeps that reason
  and replaces only `failure_message` with the teardown's detail. For every other
  aggregate it writes `provider_reported_failure`, as today.
- **After a requeue and success**, the reason stays `create_compensation`, and the
  message is whatever it last held.

`failure_message` is therefore the latest diagnostic. It is not a promise to preserve
the original create failure's message. What stays durable is the create job itself:
its identity in the provider metadata, and its status, result, and redacted log in the
job authority.

The fulfillment's original diagnostic is not promised to survive verbatim anywhere
else. In particular, it is not the job's `error`. A create job that succeeded but
reported no usable delivery evidence is failed by the provider at the fulfillment
(`JobFulfillmentProvider.get_status`), not at the job. That job's `error` is
null, and the reason it failed exists only in the fulfillment's `failure_message`,
which a failed compensating teardown then replaces. No column is added to keep it:
this design does not promise it, and the job's result and log still show what the
create reported.

**No schema migration.** The marker is a value in the existing `failure_reason` column.
State plus that value is sufficient, because no other path writes
`create_compensation`, and convergence's one writer of teardown failures is changed to
keep it.

**Readers.**
- *Fulfillment status and result reads, and their DTOs*
  (`compute_provisioning_contracts`; `market_fulfillment.FulfillmentStatus`) carry
  state, reason, and message unchanged. The marker is visible to any caller with no
  wire change.
- *The bare-metal storefront's fulfillment lifecycle*
  (`domains/bare_metal/storefront/.../fulfillment_service.py`) copies the remote state
  and `failure_reason or failure_message`. It shows teardown states and then
  `torn_down` with `create_compensation`, and records `released` only on the site's
  capacity-released callback, as for any teardown. No change is needed.
- *The VM storefront's fulfillment resume*
  (`domains/vms/storefront/src/market_storefront/services/fulfillment_resume_runtime.py`)
  treats only `failed` as a failed delivery, and waits otherwise. A VM storefront that
  first reads the aggregate after compensation began would wait forever. It is changed
  to treat a reason of `create_compensation`, in any state, as a failed delivery, as
  it treats `failed`.
- *VM failure actions* (`domains/vms/storefront/src/market_storefront/failure_actions.py`)
  run on a failed delivery. Their capacity release still asks the guarded site
  release, which refuses a `failed` aggregate and frees a compensated one only once it
  is `torn_down`. No change is needed. Compensation itself starts only from the lease
  (below), never from a storefront failure action.
- *Recovery diagnostics* (`SettlementRepository.recovery_diagnostics`) count rows by
  state. A row leaves `failed_count` when compensation begins, appears under the
  teardown states while it runs, counts in `teardown_failed_count` if its teardown
  fails, and ends under `torn_down`. Nothing relabels a compensated `torn_down` as
  failed. This is tested.

#### The compute-owned seam

All of this sits in `compute_provisioning.release` and its composition in the
provisioning service.

- **`compensable(state, failure_reason, provider_metadata)`**, above, is one pure
  function, and every caller uses it:
  - the release decision and the status port call it with the record's
    `state`, `failure_reason`, and `provider_metadata`;
  - the teardown adapter gives the kit a one-line adapter over the same function,
    `authorize=lambda candidate: compensable(candidate.state,
    candidate.failure_reason, candidate.provider_metadata)`.

  The kit's `authorize` takes one `CompensationCandidate`, while `compensable` takes
  the three fields. The adapter is the only place the two signatures meet, and no
  second predicate exists.
- **`FulfillmentReleaseExecutor.submit_release`** already reads the record. It answers
  `TEARDOWN` for an `active` aggregate, a begun teardown, and a compensable `failed`
  one. It answers `UNRELEASABLE` (`fulfillment_failed`) for any other `failed` one.
  Every other state's answer is unchanged.
- **`FulfillmentServiceTeardownPort.begin_teardown(fulfillment_id)`** decides from the
  durable state at the moment it is called, never from a decision taken earlier. It
  reads the aggregate's state through the service's `get_fulfillment_status`, then:
  - `failed`: it calls `begin_compensating_teardown` with that adapter as
    `authorize`, so eligibility is re-judged on the record in the kit's write
    transaction;
  - any other state: it calls `begin_fulfillment_teardown`, as today, which adopts a
    begun teardown and refuses a state that is neither `active` nor begun.

  A state that changes between that read and the kit's transaction is caught there:
  the compensating operation answers only from `failed` or a begun teardown, and the
  ordinary one refuses `failed`. The adapter translates the kit's
  `CompensationRefusedError` into the compute-owned `TeardownRefused`, carrying the
  reason `compensation_refused` and the refusal's message. Every other error passes
  through unchanged.
- **`FulfillmentReleaseStatusPort.get_status(fulfillment_id)`** is given the same
  `settlement_repository` and `session_factory` the executor already holds. It reads
  the record, and answers by state:

  | State | Progress |
  |---|---|
  | `torn_down` | `TORN_DOWN` |
  | `teardown_failed` | `FAILED` (`teardown_failed`) |
  | `teardown_dispatch_pending`, `tearing_down` | `TEARING_DOWN` |
  | `active` | `READY_FOR_TEARDOWN` |
  | `dispatch_pending`, `dispatching` | `CREATE_IN_FLIGHT` |
  | `failed`, compensable | `READY_FOR_TEARDOWN` |
  | `failed`, not compensable | `FAILED` (`fulfillment_failed`) |
  | absent record | `FAILED` (`teardown_failed`), as today |
  | `assigned`, `abandoned` | `TEARING_DOWN`, as today |

  The metadata it reads never leaves the compute package.

#### Release paths

Transaction-first recording is unchanged: the lease records `releasing` with the
fulfillment as its handle before any teardown begins.

- **On release** (termination, expiry, or retry-release): `submit_release` answers
  `TEARDOWN`; the lease records `releasing`; then `begin_teardown` runs. A transient
  failure to begin leaves the lease `releasing` for the releasing pass to retry, as
  today.
- **A create in flight when the lease is released, which then fails.** The lease is
  already `releasing` (`CREATE_IN_FLIGHT`). When the create fails and the aggregate is
  compensable, the status port answers `READY_FOR_TEARDOWN`, and the releasing pass
  calls `begin_teardown`, which begins the compensation. An ineligible failure answers
  `FAILED`, and the lease is `release_failed` as today.
- **A permanent refusal.** When `begin_teardown` raises `TeardownRefused`, the
  lifecycle records the lease `release_failed` with the refusal's reason
  (`compensation_refused`) and message. It records it under the release handle,
  through the site's conditional write, which fails a releasing reservation only
  under the handle it names:
  - **On the release path** (termination, expiry, retry-release), the lifecycle's
    reservation was read before `begin_release` wrote the handle, so it still reads
    `leased` or `release_failed` with no current handle. The lifecycle therefore
    passes the decision's `fulfillment_id` explicitly as the expected handle, the
    handle `begin_release` has just recorded. `_mark_release_failed` gains that
    explicit argument. The old snapshot is never used without the handle.
  - **In the releasing pass**, the reservation was read in that cycle, so its
    recorded `release_job_id` is the expected handle, as today.

  A refusal recorded under a handle another release has since replaced is refused
  by the site, and the lifecycle leaves the reservation as it is. Capacity stays held
  and the failure is visible. Every other exception is transient, as today:
  - on release, the lease stays `releasing` for the next cycle;
  - in the releasing pass, the error is logged and the next cycle retries, and the
    grace period applies once teardown has begun.
- **An operator's retry-release** of a `release_failed` lease re-decides from the
  current state. A compensable aggregate begins compensation; a refused one returns to
  `release_failed`. Force-release stays the operator's override, with its own audit.
- **Idempotency.**
  - A repeated termination finds the lease `releasing` or `released` and starts
    nothing new.
  - A repeated `begin_compensating_teardown` adopts the begun teardown.
  - The teardown job's identity is fixed per reservation, so one compensation submits
    one job.
- **What starts compensation.** Only the lease's release does: termination, expiry by
  the lease watchdog, or retry-release. A lease already terminal — `released` or
  `force_released` — is never revisited. A reservation an operator already
  force-released after verifying its host stays as it is, with its fulfillment still
  `failed`. Nothing re-runs its teardown.

**The guard and held resources.** The guard frees capacity only for `torn_down`, or
for an undelivered row with provenance proof, as today. A relay port held for the
reservation is returned with the capacity in the guarded release, as for any release,
and never on the fulfillment state alone.

**Fail-closed properties.**
- No capacity returns without `torn_down`.
- A refused or failed compensation leaves the lease `release_failed` with capacity
  held, visible and operator-repairable.
- Nothing writes the database outside these transitions.

**Each domain's teardown must be safe when the create did only part of its work.**
- *Bare-metal reclaim.* The reclaim removes the lease's key, or locks or deletes the
  account. When the tenant account does not exist it reports the account absent
  (`account_present: false`), rather than failing on the key-removal module's user
  lookup. An existing account is handled as today.
- *VM remove.* Covered by D9.

Alternatives rejected:
- *Keep operator-only release.* That leaves real host effects with no automated
  cleanup, and capacity stranded until someone notices.
- *Force-free capacity after a failed create.* Returning capacity unproven is exactly
  what the release guard exists to forbid.
- *Let the kit infer eligibility from metadata.* The kit treats provider metadata as
  opaque. Only compute provisioning knows its failure reasons and its job metadata.
- *Mark compensation by any retained failure reason.* Convergence overwrites the
  reason on every teardown failure and never clears it, so a non-null reason marks
  nothing.
- *A new column for the marker.* State plus a dedicated reason value is sufficient,
  and needs no migration.
- *Carry eligibility from the release decision into the port.* The aggregate can
  change between decision and begin; the port re-reads the state it acts on.

### D5. Run-log recovery is qualified, not shimmed

A bare-metal buyer test drives `buy_bare_metal` with the module's factories replaced:
`fresh_identity`, `registry_client`, and `payment_approval` for the write, and
`recovery_identity` for the read. Both run under one temporary XDG state directory, so
the test writes a real run log. It then recovers the deal through `_recovered_deal`,
the path `access`, `result`, and `teardown` share. The test fails if what `buy` records
is not what recovery reads.

A run log written in the retired list form stays unreadable. No compatibility reader
is added, because the one such run is closed and its log is preserved. This qualifies
the producer correction already on the branch's base.

### D6. A failed teardown job is not re-run

A teardown job whose own retries are exhausted stays failed. Because the teardown's job
identity is fixed per reservation (`{capacity_reservation_id}:teardown`), convergence's
requeue of `teardown_failed` re-observes that same failed job. The lease therefore
stays `release_failed` and its capacity held, which is visible and fail-closed.

Re-running an exhausted teardown is a separate redesign, taken up only if a
qualification run is stopped by it. Nothing in this change claims that a failed
teardown recovers on its own. The physical-provisioning companion's sentence saying
convergence requeues `teardown_failed` "on its own" is corrected at promotion to say
what the requeue does and does not do.

### D7. A CPU-only VM shape is sold through a stated shape

The qualification target is a truthful CPU-only ARM64 VM: no listing may advertise a
GPU its guest lacks, and no mock stands in for delivery. This change takes the narrowest
slice of `gpu-optional-compute-shapes` that the target forces, and nothing else from it:

- the compute capability schema requires no family;
- a VM shape stated by a pool's `listing_shapes` hint or a storefront override may
  omit the `gpu` family, and is then declared, published, discovered, negotiated,
  admitted, scheduled, and provisioned with no GPU;
- a VM shape that states the `gpu` family still names both count and model;
- a listing whose shape names no GPU model resolves its terms and family rates from
  the storefront's override, the pool's flat hint fields, and the flat configured
  default alone. `resolve_gpu_pricing` and `resolve_family_rates` already do this for
  a `None` model. No per-GPU-model term or rate applies, so no GPU price is assigned to
  a CPU-only guest.

What the slice leaves to `gpu-optional-compute-shapes`, unchanged here:

- retiring the host record's GPU fields;
- what the VM default generator publishes for a pool whose members declare no GPU. The
  generator keeps yielding nothing for them, and the pool sells only the shapes it
  states;
- bare-metal shapes without GPUs. Bare metal keeps requiring the GPU family through its
  own rules;
- whether a declaration without GPUs keeps the resource type `compute.gpu`. It does
  here: the resource type is the site's VM inventory kind, matched by exact equality in
  admission, scheduling, and feasibility, and never published as a GPU term. Neither
  the listing model nor the registry filter specification carries it, and every listing
  field a buyer reads states no GPU;
- how the registry's compute filters treat a listing that states no `gpu` family.
  Publication and unfiltered or CPU, memory, and disk queries already work, and a query
  filtering on a GPU field excludes such a listing as missing. Only the registry
  filter specification's advisory `required: [gpu_model, region]`, read by the dry-run
  `validate-publish` alone, misstates it.

Ownership:
- `gpu-optional-compute-shapes` stays the owner of the remaining items.
- Its index row lists this change in `Depends on`, gating its planning, and its
  proposal records the slice this change delivers.
- Neither change duplicates the other's work.
- `gpu-optional-compute-shapes` has not started design, so no active design is
  overtaken.

### D8. VM deal terms are pinned for the VM lane

A VM purchase needs a lease long enough to cover guest boot, readiness, buyer SSH, and
teardown, within a test-mode spending cap set for that lane. Neither the bare-metal
lane's 360 seconds nor its ten-minute listing maximum carries over. Boot readiness
alone may take several minutes, and the create waits up to about fifteen minutes for
it. A finite term of up to 30 minutes is recommended.

The VM pool's lease bound and rates are set operationally, through the pool override
or hint, before a live purchase is authorized. This change adds no code for it.

### D9. VM teardown removes only what one guest created, and proves what it cannot find

Two problems are fixed, without redesigning guest networking:

- **Exact matching.** Every firewall and NAT rule a create adds for a guest carries a
  comment naming that guest, and cleanup removes rules by that exact comment. Rules
  written before the comment existed are removed by an exact match on the guest's
  address (a `/32` match on the address), never a prefix of it. The subnet-wide
  masquerade rule shared by every guest is left as it is.
- **A missing cleanup script is not proof of absence.** When the cleanup script is
  missing, VM remove looks for each artifact attributable to the guest by name: its
  libvirt domain, its disk and cloud-init images, its relay proxy block, its DHCP
  reservation, and rules carrying its comment.
  - It removes each one found.
  - It reports the guest `absent` only when none is found.
  - When it finds an artifact it cannot attribute by name, it fails, naming the
    artifact. The teardown then ends `teardown_failed` and the lease waits for an
    operator. An example is a rule with no comment on a host where the guest's address
    is unknown.

### D10. One physical host is never sold twice

A whole-host bare-metal deal and a VM on the same machine are admitted by different
provisioning services. Each storefront trusts its own service, so cross-mode accounting
by `physical_host_id`, which works within one site, does not span them. The two lanes
therefore run sequentially, and this change does not redesign cross-site accounting.

**The control is the idle lane's durable per-listing pause, bounded by a freeze and
proven by a drain read-back.** It keeps the retained listing open and published.

What the pause is, on this base:
- `POST /api/v1/listings/{id}/pause` is the typed client's `pause_listing`, an
  administrator operation. Both storefronts serve it.
- It writes the `paused` column of the storefront's own listing row, so it survives a
  restart and a redeploy that keeps the storefront's database. It does not survive a
  database reset.
- It is not the storefront-wide trading pause, which is process-local and lost on
  restart.
- Publication keeps it on every refresh and reopen of the same listing, because those
  write through `update_listing`, which takes no pause. Resume clears it and
  republishes. That survival is a property of `update_listing`'s signature, not a
  rule anything states. It is therefore an operational precondition of this control,
  stated in the runbook, and not a guarantee this change adds.

What it refuses, and what it does not:
- It refuses only a **new opening** on that listing, answering 503
  (`NegotiationRuntime._plan_opening`).
- A counter or accept on a thread opened before the pause, an administrator's
  force-accept or reserve, settlement, payment reconciliation, fulfillment, and
  teardown all proceed. **A pause drains nothing.** Work that began before it can
  still reserve and provision the machine.
- A listing bound under a new derivation key is created unpaused. Such a key comes
  from a corrected declaration or shape, a new member, a changed hint or override, or
  a new site. The one exception is the VM storefront's one-time carry-over of
  listings bound before shapes, which pauses their successors. It is an upgrade
  step, not a general rule, and this control does not rely on it.

Rejected controls:
- *Disabling the declaration* closes the listing, which breaks retention.
- *The administrator reservation* closes the listing by availability, which also
  breaks retention. It takes no TTL on this base (`ttl_seconds` is left `None`, and the
  site's expiry sweep ignores a null `hold_expires_at`), so it holds until explicitly
  released. A pool's `max_reservation_hold_seconds` is an advisory negotiation hint,
  not a limit the site enforces.
- *The trading pause alone* is lost on restart.

**Operational conditions.** These gate a lane switch. They are re-checked from fresh
live read-backs before each lane's purchase, and after any restart or redeploy of the
idle side.

1. **Freeze.** Make no change to the idle side's capacity declarations, pools, hints,
   overrides, or sites until the switch completes, so no unpaused listing can be bound.
2. **Pause.** Pause every idle-lane listing whose source is the shared machine. Read
   each back open and paused, and the retained listing open at its registry.
3. **Stable listing set.** No open listing for the machine on the idle storefront is
   unpaused.
4. **No open negotiation.** No thread on those listings has a null terminal state. The
   negotiation watchdog abandons a stale thread after its configured timeout.
5. **Every accepted deal is drained.** Every accepted deal on those listings is
   accounted for at every layer:
   - its storefront settlement and fulfillment state is terminal;
   - its site reservation is `released`, or `force_released` after verification. A
     reservation in the retired state `provisioning_failed`, which nothing on this
     base writes, is read as terminal and holds no capacity. Its deal's host-side
     effects are verified like any other's;
   - every provider job for its reservation is terminal;
   - its host-side effects are verified removed: the tenant key and account for bare
     metal, the guest and its artifacts for VM;
   - no approved receipt or recorded materialization remains that could still start
     a delivery.

   A refund or an expired approval is checked as well, as the financial disposition.
   It never stands in for any of these. A refund alone is never proof of a drain.
6. **Site drained.** At the idle lane's site, two read-backs must both hold:
   - **No held reservation.** No reservation for the machine is in `reserved`,
     `provisioning`, `leased`, `releasing`, `release_failed`, or `unmanaged`, the
     states the site counts as holding capacity.
   - **Full availability.** In the site's resource-pool projection, every member on
     the machine has an `available` mapping equal to its declared `capacity` mapping,
     dimension by dimension.

   The lease list alone is not enough, because it omits a hold with no lease window,
   which the projection still counts. The projection's scalar `available_units` is
   not enough either: it reports only the mirror dimension, and a member declaring no
   GPU has no mirror, so its scalar is null.
7. **Then the active lane.** Only then may the active lane's listing trade.

The pause and its opening check must be present in the deployed storefronts before this
is relied on, or the lane runs on the candidate artifacts.

If a condition cannot be met — a restart that reset the database, an unpaused successor
listing, work that cannot be drained, or a deployment lacking the pause — the lane
switch stops at that named boundary, and no unsafe shortcut is taken.

The reservation an operator force-released before this change stays as it is. Its
evidence is preserved, and it is not force-released again.

Limits recorded rather than fixed:
- **Successor listings.** Carrying a pause onto a successor listing is not
  implemented in general; the freeze avoids it.
- **No stated requirement.** No permanent requirement yet states per-listing pause
  semantics, including that a refresh or reopen under the same identity keeps the
  pause.
- **Test coverage.**
  - Bare metal's application test
    (`domains/bare_metal/storefront/tests/test_listing_controls.py`,
    `test_a_paused_listing_stays_paused_through_a_cycle_until_resumed`) proves a
    publication cycle leaves a paused listing open, paused, and unsent. That cycle
    publishes and refreshes nothing, so it does not reach the reconciliation close
    and reopen path.
  - No test, in either storefront, closes a paused listing by reconciliation and
    reopens it.
  - Neither storefront has an application test of a paused listing refusing an
    opening. VM proves it below the HTTP route, against a real SQLite listing row
    (`domains/vms/storefront/tests/unit/test_order_pause_state.py`,
    `test_order_pause_raises`). Bare metal has no test of it.

  These gaps are named here and in the roadmap. The control is verified during live
  qualification by the read-backs above. No unit test is added that would only inspect
  `update_listing`'s signature: it would prove nothing a persisted or application
  test does not.

D10 gates the second lane's live run, never a section of this change.

## CPU-only VM shapes

Every point on a real VM purchase that refuses or misreports a GPU-less shape was
traced through the code, and each was rechecked where a decision rests on it. The slice
changes these:

| Point | Today | Change |
|---|---|---|
| Compute capability schema (`domains/compute`) | `gpu.count` and `gpu.model` are required, so flattening, unflattening, digest, and splitting a stated shape refuse one without `gpu` | Neither is required. The VM shape rule (`arkhai_vms` canonical shapes) refuses a `gpu` family naming only one of the two |
| VM listing models (`domains/vms/listings`) | `ComputeResource` requires `gpu_model` and `gpu_count`, and a listing resource is recognised as compute by its `gpu_model` key, so every `Listing` parse of a CPU listing fails | Both fields optional. Compute and token resources are told apart by the token resource's own fields, so a compute resource needs no GPU key |
| `resource_is_compute` (`domains/vms/listings` pricing) | recognises compute by `gpu_model`, so the capacity claim cannot be built | The same discriminator as the models |
| `VmListing` (`domains/vms/domain`) | requires `gpu_model` and `gpu_count` | Requires both or neither |
| Reconciler member usage (`domains/vms/listings`) | drops a member without a positive GPU count before feasibility, so a stated CPU shape is judged infeasible | Keeps every member with a resource type and declared capacity for stated shapes. GPU totals become optional, and are reported only for default generation |
| Resolved shape GPU accessors and listing reopening (`domains/vms/listings`) | read the GPU count and model by key, which raises for a CPU shape, and order GPU models in a way that fails with an absent model | Absent-tolerant reads. A shape with no GPU model sorts apart from one with |
| Alkahest compute lease encoding (`domains/vms/settlement`) | would encode an absent model as text | Omits absent GPU fields |
| VM administrator reservation response (`domains/vms/storefront` admin controller and `capacity_admin_models`; `core/storefront-client` `ReserveCapacityResponse`) | coerces a reservation's GPU count with `or 1`, so a CPU-only hold reports one GPU | `gpu_count` is optional. It is read from the reservation's authoritative `dimensions` when they are present, and is absent when they name no `gpu_count`. The legacy scalar is read only for a row that has no `dimensions` |

**The site ledger's scalar mirror is unchanged.** For an explicit, non-empty
`dimensions` map naming no `gpu_count`, the site stores `units = 0` and keeps
`dimensions` authoritative (`market_site.ledger`). Admission, holding, release, and
`_reservation_dimensions` read the dimensions. Only a legacy row with no dimensions
falls back to the mirror. A CPU-only claim therefore round-trips through admission and
release holding exactly its vCPU, memory, and disk. This is tested, and nothing generic
in the ledger is redesigned.

Unchanged, because each already handles a shape without `gpu`:

- site declaration, admission, and scheduling, which match any declared dimensions and
  exact resource type;
- the capacity claim built from the listing;
- buyer commands and provision terms;
- registry publication;
- VM fulfillment, whose requirement delegate sets a GPU count and passthrough only
  when the reservation reserves GPUs, and maps vCPU, memory, and disk from the
  reservation or the pool's defaults.

A CPU shape is priced by the flat tiers, as D7 states.

Tests that pin the old assumption change with the code. Among them are the compute
schema's required-field test, the VM schema tests, and the reconciler derivation case
for a member without GPUs, which keeps its default-generation meaning. No end-to-end
lane provisions a CPU-only VM. Its system evidence is the live VM lane's qualification,
kept apart from mock lanes.

**The guest recipe.** An `aarch64` host gets an `aarch64` cloud image, pinned to a dated
release by checksum, booted on the `virt` machine under UEFI. The architecture is the
host's own, read by the playbook. Nothing is configured per pool. The host
prerequisites are installed by an operator, not by a playbook:

- an `aarch64` QEMU system emulator with KVM;
- the UEFI firmware for it;
- libvirt and its client;
- `virt-install`;
- an ISO image writer;
- the `default` libvirt network.

The host-setup playbook (`playbooks/host-kit/vm-setup.yaml`) is never run on a host whose
management access must be preserved. It enables a default-deny firewall, adds bans,
edits SSH configuration and the boot loader, and reboots unconditionally. The VM README
says so beside the prerequisites.

**Live VM qualification is outside this change's sections**, and gated separately:

- host package installation;
- a test-mode purchase under pinned VM terms (D8);
- proof that a real guest booted, by hypervisor identity and guest architecture;
- buyer SSH into the guest;
- teardown, refused access afterwards, and restored capacity;
- the lane conditions (D10).

A blocked lane is recorded as blocked, never as passed by a mock lane.

## Coordination with `resolve-compute-family-findings`

That change, `ready for implementation`, plans edits to files this change also edits:
- `provisioning/compute/src/compute_provisioning/lease_lifecycle.py` (its
  `TERMINAL_FAILURE_STATES`);
- `provisioning/compute/service/src/compute_provisioning_service/services/fulfillment_convergence.py`
  (its `_TERMINAL_RESERVATION_STATES`);
- `domains/vms/storefront/src/market_storefront/controllers/admin_controller.py`;
- the VM codec tests, which it moves.

The overlap is textual, not behavioural:
- `_TERMINAL_RESERVATION_STATES` is a set of site reservation states, not fulfillment
  states. Neither it nor `TERMINAL_FAILURE_STATES` changes because `failed` gains an
  outgoing fulfillment edge.
- This change edits other functions in those files: the teardown-failure write, the
  releasing pass's refusal handling, and the admin reservation response.

This change is implemented against its pinned base. Whichever change lands second
reconciles the overlap when it merges `dev`, without importing the other's unfinished
sections.

`resolve-compute-family-findings` landed first. This change merged `dev` after
Section 4, so it is the one that reconciles. The merge changed no decision above,
and the plan's remaining sections carry its corrections in `tasks.md`:
- the VM codec tests, moved unchanged to the VM adapter (Section 5);
- the scenario rules, now built as typed `MockRuleCreate` models (Section 5);
- the terminal-state sets, which no longer hold `provisioning_failed` (Section 8);
- the dead administrator surfaces removed beside the reservation response
  (Section 12).

The site's reservation states also changed under D10. The provisioning service
migrates the retired `provisioning` state to `unmanaged` and `provisioning_failed` to
`force_released`. The states that hold capacity are therefore `reserved`, `leased`,
`releasing`, `release_failed`, and `unmanaged`, and D10's read-backs in the runbook use
those (Section 14.9).

## Compatibility, migration, and rollback

- **No schema migration.** `public_port` lives in the connection envelope's public
  fields, and the compensation marker is a value of the existing `failure_reason`
  column. Each host row already records its connection's version, and no automatic
  migration rewrites it. A host stored at `ssh` version 1 is moved to version 2 by an
  explicit data update, a host update or an inventory import, as D3 says.
- **Wire.**
  - The fulfillment status and result reads are unchanged in shape. A compensated
    aggregate reads `torn_down` with `failure_reason` `create_compensation`.
  - The VM administrator reservation response's `gpu_count` becomes optional, in the
    server model and the storefront client's.
- **Rollback.**
  - No downgrade of `ssh` connections to version 1 is provided or qualified (D3).
  - An older service treats a compensating teardown already recorded as an ordinary
    teardown. Its teardown-failure write replaces the marker with
    `provider_reported_failure`, so an in-flight compensation completes and is still
    proven by `torn_down`, without its marker.
  - A `failed` aggregate not yet compensated is left for an operator, as before.
- **Packaging.** Each changed package bumps its minor version. Dependants' pins are
  updated, and the locks are refreshed with `make lock` under the repository's uv
  minimum.

## Implementation cadence

One implementation session per round, by one writer. Each round is reviewed and
validated before the next starts.

- **Round 1:**
  - the shared fact reader and both codecs, with linkage checks and shipped-format
    mocks, and the VM pipeline scenarios moved onto the per-job default output (D1,
    D2);
  - the tenant-facing port and endpoint (D3);
  - the run-log round-trip test (D5).

  The payments upgrade is qualified by rebuilding environments, with no code.
- **Round 2:** compensation of a failed dispatched create (D4): the fulfillment kit's
  operation and marker, the compute-owned seam and release paths, the convergence
  write, the VM resume reader, and the idempotent bare-metal reclaim.
- **Round 3:** the CPU-only VM slice (D7), including the administrator reservation
  response; the aarch64 guest recipe; and the VM teardown repairs (D9).
- **Closeout.**

Round 1's merge of `dev`, between Sections 4 and 5, was resolved in a session of its
own, by the same role. The writer session that had implemented Sections 2 to 4 could
not also hold the full read of the guidance that the merge requires. Its sections
stay as they were recorded. Section 5 continues from the merge.

From that merge on, the owner set the round's test cadence:
- Focused suites and packaging gate each intermediate commit, sections and merges
  alike.
- One full `make test` and one independent implementation review run on each frozen
  round candidate, Round 1's after Sections 5 and 6.
- A passing result is reused while its candidate is unchanged.
- Validation and the live lanes remain required.

## Open questions

- **D7's resource type and registry advisory.** Both stay with
  `gpu-optional-compute-shapes`. Keeping `compute.gpu` for a declaration without GPUs,
  and the filter specification's advisory `required` list, are its decisions. This
  change makes neither, and depends on neither.

D10 is decided above. Its operational conditions are live read-backs, not open design.

## Design promotion record

Spec deltas are merged by the archive. Every other destination is written at
closeout, under the heading named.

| Accepted decision | Permanent location |
|---|---|
| D1 fact reading, block boundaries, and linkage | `openspec/specs/physical-provisioning/spec.md` ("A create succeeds only with readable delivery evidence", and "A bare-metal reclaim's printed fact is a diagnostic" for the reclaim's result and the job status's authority over teardown, by the archive); rationale in `openspec/specs/physical-provisioning/architecture.md` under "Durable jobs, transient workers" |
| D2 mocks print the shipped form, rendered for the job, and pipeline scenarios use it | `docs/development/TESTING.md` under "4. System Integration Tests (End-to-End)", beside its paragraph on the compute lanes' mock profile |
| D3 tenant-facing port | `openspec/specs/physical-provisioning/spec.md` ("The tenant-facing host address falls back to the connection address", for the fallback and the delivery endpoint, and "Host registry records the connection port", for the INI `public_port=` rule, rendering, and the record stored without the field; both by the archive); `openspec/specs/physical-provisioning/architecture.md` under "The host registry owns the connection"; `docs/development/DEPLOYMENT_AND_CONFIG.md` under "Definition documents", in its host-inventory paragraph (`public_port=`; every `ssh` host connection, through the API or an inventory, at version 2; and a host stored at version 1 moved forward by an update or an import, never on its own); `ssh` served at version 2 alone, other versions refused, and a re-registration keeping a protected key: `openspec/specs/physical-provisioning/spec.md` ("Host connections are typed by their implementation's codec", by the archive) and `openspec/specs/physical-provisioning/architecture.md` under "The host registry owns the connection". `docs/development/VALIDATION_RUNBOOK.md`'s host requests state version 2 already (task 3.11). `docs/development/RELEASING.md` is unchanged |
| D4 compensating teardown, its marker, and the compute seam | `openspec/specs/fulfillment/spec.md` and `openspec/specs/physical-provisioning/spec.md` (by the archive); `openspec/specs/fulfillment/architecture.md` under "Durable persistence and recovery"; `openspec/specs/physical-provisioning/architecture.md` under "Proof-driven release"; `docs/development/ARCHITECTURE.md` under "Release", whose table's `failed` row splits into compensable and not |
| D5 run-log round trip | None: a test that qualifies the producer's existing form. No behaviour changes |
| D6 an exhausted teardown job is not re-run | `openspec/specs/physical-provisioning/architecture.md` under "Proof-driven release", whose `teardown_failed` requeue sentence is corrected |
| D7 CPU-only VM shapes and flat-tier pricing | `openspec/specs/market-composition/spec.md` ("The compute family shares one capability schema", by the archive); `openspec/specs/storefront-publication/spec.md` ("Every VM listing is a listing shape", "A listing's published shape comes from its source declaration", by the archive); `openspec/specs/storefront-publication/architecture.md` under "Listing shapes and the storefront's authority" and "Shape pricing"; `docs/development/DEPLOYMENT_AND_CONFIG.md` under "Storefront listing shapes and pool overrides", whose shape-constraints bullet says `gpu.count` and `gpu.model` are required |
| D7 guest recipe and host prerequisites | `openspec/specs/physical-provisioning/spec.md` ("A VM guest matches its host's architecture", by the archive); `domains/vms/provisioning/iac/README.md` under "Prerequisites"; `docs/seller-quickstart.md` under "6. Live KVM provisioning" |
| D8 VM lane terms | None: operational configuration, set before a live purchase |
| D9 VM teardown | `openspec/specs/physical-provisioning/spec.md` ("A VM teardown removes only what its guest created", by the archive) |
| D10 sequential lanes, pause, drain conditions, and the pause's precondition | `docs/development/VALIDATION_RUNBOOK.md`, a new generic section on running two lanes against one machine in sequence: freeze, pause, read-backs in the site's own states, full projection availability, and the precondition that a refresh or reopen under the same identity keeps the pause; `docs/development/ROADMAP.md` "Payment qualification boundaries", for the pause's limits and coverage gaps |
| Roadmap currency | `docs/development/ROADMAP.md` "Goal 1 — Consolidate physical-resource authority in the provisioning service" (the real runner's evidence row) and "Goal 2 — Negotiate full compute capability, not GPU count alone" (VM shapes stated without GPUs) |
| Campaign index currency | `openspec/changes/README.md`: this change's row and the dependency graph line to `gpu-optional-compute-shapes` |
