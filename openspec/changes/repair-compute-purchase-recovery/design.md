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

The second qualification target is a GPU-backed virtual machine on an x86-64 host,
qualified on a physical host of its own, independent of the bare-metal lane's. It was
first planned as a CPU-only ARM64 guest on the same kind of host as the bare-metal
lane; the owner superseded that target on 2026-10-29 ("Scope revision" below). Four
findings stand in the GPU guest's way:

- The VM create recipe downloads its x86-64 cloud image from a moving `current` path,
  with no checksum, and reuses whatever image file is already on the host.
- The recipe means to keep the host's boot GPU, the one driving its console, from any
  guest, and offers no way to pass it through even when an operator has bound it for
  passthrough and it is the host's only GPU. Its detection of the boot GPU is also
  broken: it scans `lspci -D -vmm` for a `Class:` line and expects the next line to be
  that device's `Slot:`, but that format prints `Slot:` before `Class:`, so it finds no
  boot GPU on a real host and the intended exclusion never applies. The capability
  inventory it trusts may also be stale, still listing a GPU an operator has since
  returned to its host driver.
- A GPU guest installs its driver and reboots before it is ready, and the create waits
  for that through a fixed ten attempts thirty seconds apart. Every created guest is
  also set to start on host boot, so a guest a teardown has not yet removed would
  reclaim the GPU after a host reboot.
- VM teardown fails when a partial create left no cleanup script, and its rule cleanup
  matches guest addresses by prefix, so one guest's removal can touch another's rules.

The CPU-only target's own findings — the compute capability schema requires the `gpu`
family, and the recipe is amd64-only — are no longer this change's to fix (D7).

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

**Scope revision (2026-10-29).** After Sections 2–10 were implemented, the owner settled
the live lanes' targets and asked for every preflight correction a proper bare-metal
test needs, with the plan, goal, and records made consistent:
- The VM lane qualifies a GPU-backed guest on an x86-64 host, and the bare-metal lane
  a whole GPU machine on another host. The two are physically independent and run in
  parallel. The CPU-only ARM64 target, and the sequential lanes on one machine it
  implied, are withdrawn (D7, D10).
- What the GPU guest needs from this change is the minimum recipe work above: a pinned
  and verified x86-64 image (D11), a boot-GPU detection that works, with an operator's
  explicit opt-in to pass the boot GPU through (D12), a bounded readiness wait and an operator-set autostart (D13), and
  D9's teardown. No GPU marketplace, shape, or pricing work is added.
- The Round 1 review's F2, F3, and F4 are accepted on that instruction. F2 corrects
  the promotion record's quickstart destinations, F4 the proposal's Impact, and F3
  becomes D14, implemented before the live bare-metal lane runs.

## Goals and non-goals

**Goals.**
- A real grant's result reaches fulfillment whatever the callback's display format,
  and only a document selected for the job's own action and target is taken as its
  result.
- The buyer receives a tenant-facing endpoint.
- A failed create that may have left effects is compensated by the same teardown its
  domain already defines, and its capacity returns only once that teardown is proven.
- A bare-metal run log is recoverable by the commands that read it.
- The real-host bare-metal scenario drives the buyer commands as they ship, and proves
  revocation only by an authentication refusal.
- A GPU-backed VM can be created on an x86-64 host from a verified image, with its GPU
  passed through, and torn down removing only what that guest created.

**Non-goals.**
- A GPU marketplace, shape, or pricing redesign, and any general change to how the
  recipe selects GPUs beyond D12's opt-in.
- Guest or tenant isolation and data sanitization. The live VM lane verifies only that
  the GPU returns to the host's driver baseline after teardown.
- CPU-only VM shapes and ARM64 guests (D7).
- Network or security redesign of VM guests.
- Marketplace or pricing redesign. The five-minute price refusal is recorded only.
- Unrelated route and pause defects. S5, below, is a publication defect brought in
  because it blocks the live bare-metal lane.
- Retiring the host record's GPU fields. `gpu-optional-compute-shapes` retired them on
  `dev`, and this branch merged that ("Coordination with `gpu-optional-compute-shapes`").
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
    decrypted. Pool and enabled state are untouched unless the update states them.
    A host record describes no hardware on `dev` since `gpu-optional-compute-shapes`,
    so an update states no GPU description either.
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
  teardown states while it runs, and counts in `teardown_failed_count` if its
  teardown fails. Its durable state ends `torn_down`, which the diagnostics do not
  count: it leaves every recovery-state and failure count, and no field is added
  for it. Nothing counts a compensated `torn_down` as failed. This is tested.

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

### D7. Withdrawn: a CPU-only VM shape sold through a stated shape

D7 took the narrowest slice of `gpu-optional-compute-shapes` a CPU-only ARM64 guest
forced: the compute capability schema requiring no family, and a VM shape stated by a
pool hint or storefront override omitting `gpu`, published, priced from the flat tiers,
claimed, and provisioned without one. It also chose an `aarch64` guest image on the
`virt` machine under UEFI. None of it was implemented.

The owner withdrew it on 2026-10-29, when the VM lane's target became a GPU-backed
guest on an x86-64 host ("Scope revision"). A GPU guest needs no shape without a GPU,
and no ARM64 image. So:
- the schema and VM stated-shape slice returns to `gpu-optional-compute-shapes`, which
  owns it with the rest of its scope. Its index row no longer names this change in
  `Depends on`, and its proposal no longer records the slice as delivered here. Task
  1.2's confirmation of the split stands as history, corrected there;
- the `market-composition` and `storefront-publication` deltas, which only D7 wrote,
  are removed;
- the planned sections for CPU-only shapes and the `aarch64` recipe are replaced
  (`tasks.md`, Sections 11–14). D9's teardown repairs, which were planned beside the
  recipe, are kept;
- what D7 left open — a declaration without GPUs keeping the resource type
  `compute.gpu`, and the registry filter's advisory `required` list — is
  `gpu-optional-compute-shapes`'s again.

`gpu-optional-compute-shapes` then landed on `dev` and was archived on 2026-10-29,
delivering its whole scope, CPU-only VM and bare-metal shapes included; this branch
merged it ("Coordination with `gpu-optional-compute-shapes`"). The withdrawal stands:
this change delivers none of that work, and the qualification targets above still
require a GPU. The record this branch had added to that change's active proposal was
dropped with the archive, which came from `dev` and never named this change.

### D8. VM deal terms are pinned for the VM lane

A VM purchase needs a lease long enough to cover guest boot, the GPU driver's install
and the reboot after it, readiness, buyer SSH, a computation on the GPU, and teardown,
within a test-mode spending cap set for that lane. Neither the bare-metal lane's 360
seconds nor its ten-minute listing maximum carries over. The create's own readiness
wait is bounded by the pool's setting (D13), so the term is chosen to cover that
bound, measured once on the lane's host before a purchase. A finite term of up to 30
minutes is recommended.

The VM pool's lease bound, rates, and readiness wait are set operationally, through
the pool override, hint, or provider configuration, before a live purchase is
authorized. This change adds no code for the terms.

### D9. VM teardown removes only what one guest created, and proves what it cannot find

Two problems are fixed, without redesigning guest networking. Both are required before
any real guest is created on a lane's host, since a create that fails part-way leaves
artifacts only this teardown can attribute:

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
by `physical_host_id`, which works within one site, does not span them. This change
does not redesign cross-site accounting.

**Lanes on separate machines run in parallel.** The live lanes are qualified on two
physically independent hosts, so their capacity cannot overlap, and they may run at
the same time. What they share is this repository's source, its wheelhouse and
environments, and the images built from them, and changes to those stay serialized:
neither lane's run rebuilds or reinstalls what the other is running on. Everything
below applies only where two lanes' sources are one machine: a machine whose physical
capacity both provisioning services can sell. There, the lanes run one at a time
under this control.

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
     `leased`, `releasing`, `release_failed`, or `unmanaged`, the states the site
     counts as holding capacity. The site's `HELD_RESERVATION_STATES`
     (`kit/site/src/market_site/db.py`) is the authority for that list; the retired
     states are not among them ("Coordination with `resolve-compute-family-findings`").
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

D10 gates a lane's live run only where it shares a machine with another lane, and is
never a section of this change.

### D11. An x86-64 guest is created from a pinned, verified image

The scratch image a VM create uses is one dated release of the Ubuntu Noble x86-64
(`amd64`) cloud image, not the moving `current` path:
- **The pin.** The role names the release's dated URL and the SHA-256 that release's
  published checksum list gives for the image, in one place. An operator moving the pin
  to another release verifies that release's signed checksum list before recording
  its digest; the role carries the digest alone.
- **Verification before use.** The image's SHA-256 is checked before the image backs any
  disk: after a download, and equally when a file is already on the host. A mismatch
  fails the create before any disk or domain is defined, and the file is not used.
- **The stored name carries the release.** An image left on a host at the old unpinned
  name is never adopted as the pinned one.
- **Architecture.** Before any host effect, the create reads the target's machine
  architecture. Only `x86_64` has a pinned image, so any other fails the create naming
  it, rather than failing later with an image it cannot boot.

Golden images, which an operator supplies from a bucket path, are unchanged and not
pinned here. Nothing else about the guest — machine type, firmware, cloud-init — changes.

Alternatives rejected:
- *Keep `current`.* A create could then boot a guest no one verified, and two creates on
  one host could boot different images.
- *Verify the checksum list's signature on every create.* That puts a keyring and a
  network fetch on every create's path for what is verified once, when the pin moves.

### D12. A host's boot GPU is passed through only by an operator's explicit opt-in

The recipe means to keep a host's boot GPU, the device whose `boot_vga` is set, from
every guest, because the host console runs on it. Two things are wrong with that
today. Its detection finds no boot GPU on a real host: it reads `lspci -D -vmm`
expecting a device's `Slot:` line after its `Class:` line, while that format prints
`Slot:` first, so the exclusion silently does nothing and the protection it describes
does not exist. And it offers no way to pass a boot GPU through, so a host whose only
GPU is its boot GPU cannot serve a GPU guest however its operator has prepared it.
Both are fixed together, so the default protects the boot GPU reliably and only an
operator can lift it.

- **Detection.** Whether a candidate is the boot GPU is read from that candidate's own
  sysfs `boot_vga` flag, the kernel's authoritative answer, rather than from a parse
  across `lspci` fields. Every task of the create that excludes or refuses the boot GPU
  uses that one test. That is every task that chooses a GPU, not only the single-GPU
  selector: the alternatives a create retries with after a failed attempt, and the
  multi-GPU selection, could otherwise fall back to the boot GPU.
- **The default.** Without the opt-in, the boot GPU is never selected, whatever the
  capability inventory lists.
- **The opt-in.** A pool's provider configuration may set `vm_passthrough_boot_gpu:
  true` in its `extra_vars`; absent, it is false. Only an operator writes provider
  configuration. No job parameter carries it, and the fulfillment plan already refuses
  `extra_vars` that would override a job's reserved variables, so neither a buyer's
  terms nor a storefront's request can set it.
- **What it permits, judged now.** With it set, the boot GPU is eligible only when all
  three hold at the moment of selection:
  - the host's GPU capability inventory lists it as available for passthrough;
  - the kernel reports it bound to the passthrough driver, `vfio-pci`, now, read from
    the device's own sysfs driver link. The inventory is a file written earlier and
    can be stale after an operator returns the GPU to its host driver, so it is never
    taken alone;
  - no defined guest has it attached.

  When the opt-in is set and the inventory lists the boot GPU but the kernel reports
  another driver, or none, the boot GPU is not eligible, and a create left with no
  eligible GPU fails before defining a domain, as a create with no available GPU does
  today. The recipe never binds or unbinds a device itself. The selector's choice
  among eligible GPUs, the least used, is unchanged.
- **A supplied device.** A `vm_gpu_device` a job supplies is still replaced by the
  selector's choice, as today; on a host whose one eligible GPU is the boot GPU, that
  choice is it.

Preparing a host for this — moving its console off the GPU, binding the GPU for
passthrough, and restoring both afterwards — is an operator procedure, reviewed before
any physical work. This change neither performs nor documents a host's particular
procedure.

Alternatives rejected:
- *Honour any supplied device.* That widens who can choose a GPU and is not needed: the
  opt-in makes the boot GPU eligible, and the existing selection picks it.
- *Drop the boot-GPU exclusion.* A host whose console runs on its GPU would lose it to
  the first guest.
- *Repair the `lspci` parse.* A per-candidate sysfs flag answers the one question asked
  without depending on how another tool orders its fields.
- *Trust the inventory alone.* It can outlive the binding it recorded, and selecting on
  it would take a GPU the host is driving.

### D13. A GPU guest's readiness wait is bounded by its pool, and its autostart is the operator's

- **The readiness wait.** A GPU guest installs its driver and reboots before it reports
  setup complete. The create waits for that, today ten attempts thirty seconds apart.
  A pool's `extra_vars` may set `vm_setup_wait_attempts` and
  `vm_setup_wait_interval_seconds`, each a positive integer, defaulting to 10 and 30.
  A value that is not a positive integer fails the create before any host effect. A
  wait that runs out fails the create, naming the bound, as it does today; no setting
  reports a guest ready that has not confirmed its setup. Like the opt-in, these come
  only from the pool's operator-owned provider configuration.
- **Autostart.** Every created guest is set to start on host boot. A pool's
  `extra_vars` may set `vm_autostart: false`, and the create then leaves the guest's
  autostart off; absent, it is true, as today. Teardown is unaffected either way. A
  lane whose host passes through its only GPU sets it false, so a guest a teardown has
  not yet removed cannot reclaim the GPU when the host reboots.

Defaults reproduce today's behaviour exactly, so a pool that sets none of these creates
guests as before. Both are subsystem behaviour, stated as a requirement in the
`physical-provisioning` delta, "A GPU guest's readiness wait and autostart are set by
its pool's operator", not only operator documentation.

### D14. The real-host bare-metal scenario drives the buyer commands as they ship

`e2e_bare_metal_deal` is the repository's scripted path to the live bare-metal lane's
evidence. As written it cannot run (`reviews/03-implementation-external.md`, F3). It is
corrected, as test code only, before that lane runs:

- **The commands.** `market bare-metal result`, `access`, and `teardown` each take
  `--run-id <id>`, the id `buy` prints and records, and print JSON with no flag. They
  take no `--from` and no `--json`, and `teardown` has no `request` or `status`
  subcommand.
- **Teardown is one idempotent command.** Its first call asks the site to end the lease
  and answers the lifecycle's `state`, `terminating`. Each later call re-reads the
  lifecycle and answers its state as provisioning reports it. `released` is the only
  terminal success; the storefront records it only on the site's capacity-released
  callback. `teardown_failed` is a failure. The scenario repeats `teardown --run-id`
  until `released`, failing at once on `teardown_failed` with the state and its
  `failure_reason`, and failing when its bounded wait runs out with the last state. It
  reads `state`, and the configurable terminal status setting is removed, since the
  terminal state is the storefront's, not the scenario's.
- **The run id.** The harness's run-id resolver recognizes `--run-id <id>` and
  `--run-id=<id>`, and `--from=<id>` beside `--from <id>`, so a command reading a run
  is bound to it.
- **Fresh SSH.** Every access attempt is a new SSH process that reads no configuration
  file (`-F none`) and shares no connection (`ControlMaster=no`, `ControlPath=none`),
  offers only the role's key, and allows public-key authentication alone. It checks
  the host's key strictly against a known-hosts file the operator supplies with the
  role's inputs; the scenario skips without one, as it does without the key. An
  attempt succeeds only by exiting 0 with the expected output. Revocation is proven
  only by an authentication refusal from that pinned host: SSH exiting 255 with
  "Permission denied" for the public key. Any other failure — a refused or timed-out
  connection, an unreachable host, or a host-key mismatch — fails the scenario, never
  counted as revocation.
- **No new framework.** The scenario keeps the installed `market` command, the
  harness's buyer CLI, and the run log, and adds only what these corrections need.

The scenario stays in no lane. Its regression tests are at the lowest level that can
prove each correction, in `e2e-tests`' unit suite: the real Typer parser of the
installed bare-metal commands reading each argument list the scenario builds, the
resolver, the teardown wait over a scripted sequence of answers, and the SSH argument
list and its outcome classification. None of them runs a purchase. The scenario
itself runs only in an authorized live run, on the round's validated candidate.

## The x86-64 GPU guest

The recipe changes are D9, D11, D12, and D13, and nothing else. Mock lanes run no
playbook, so no mock scenario's result is evidence for any of them. Its host prerequisites
are installed by an operator, not by a playbook:

- an x86-64 QEMU system emulator with KVM;
- UEFI firmware for it;
- libvirt and its client;
- `virt-install`;
- an ISO image writer;
- the `default` libvirt network;
- for a GPU guest, the host's GPU capability inventory, listing the GPU as available for
  passthrough once it is bound for it.

The host-setup playbook (`playbooks/host-kit/vm-setup.yaml`) is never run on a host whose
management access must be preserved. It enables a default-deny firewall, adds bans,
edits SSH configuration and the boot loader, and reboots unconditionally. The VM README
says so beside the prerequisites.

The guest is reached through the recipe's existing access paths, a relay or a forwarded
port. This change adds no networking, and which path a lane uses is operational.

On the relay path, a create waits until the host's tunnel client reports the guest's
proxy `running`. The client's status API answers a JSON body labelled `text/plain`,
and Ansible's `uri` decodes only a body labelled JSON, so the wait as first written
never saw a ready proxy (S3, found by an unpaid create on the VM lane's host, after
Section 14). The wait parses the body itself, whatever its label, and still requires
the exact proxy `vm-<guest>` reported `running`. A failed request, another status, or
an empty body is retried within its bound; a body that is not the client's status
document ends the create as an error; nothing else is ready. No networking changes.

## Live qualification

The two live lanes are outside this change's sections and gated separately. Each is a
test-mode purchase through the buyer commands, under its own spending cap and terms,
on its own physical host, and the two may run in parallel (D10). A blocked lane is
recorded as blocked, never as passed by a mock lane, a container, or a guest without
the GPU.

- **Bare metal.** The normal buyer identity buys the whole machine, recovers the run
  through `access`, and connects over SSH on the tenant route. As the tenant it runs a
  bounded computation on the GPU and checks its result; a driver listing the GPU is
  not qualification. Teardown reaches `released`, a fresh SSH attempt is refused by
  authentication, and the machine's capacity is restored. `e2e_bare_metal_deal` (D14)
  is the scripted path; the GPU computation is the operator's check on the delivered
  access, with no new API.
- **VM.** A GPU guest is created on the x86-64 host from the pinned image (D11), its GPU
  passed through, by the boot-GPU opt-in where that GPU is the host's only one (D12),
  under a readiness wait and autostart the pool sets (D13). The buyer connects over
  SSH, runs a bounded computation on the GPU inside the guest, and checks its result.
  The normal release tears the guest down, removing only its own artifacts (D9); a
  fresh SSH attempt is refused; the GPU returns to the host's driver baseline; and the
  capacity is restored. Preparing the host's GPU and restoring it are operator
  procedures, reviewed before physical work.

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
- the dead administrator surfaces removed from the VM storefront's administrator
  controller. The reservation response's `gpu_count`, which D7's slice would have
  changed there, is no longer this change's, so this change edits nothing in that
  controller.

The site's reservation states also changed under D10. The provisioning service
migrates the retired `provisioning` state to `unmanaged` and `provisioning_failed` to
`force_released`. The states that hold capacity are therefore `reserved`, `leased`,
`releasing`, `release_failed`, and `unmanaged`, and D10's read-backs in the runbook use
those (the closeout's promotion).

## Coordination with `gpu-optional-compute-shapes`

`dev` advanced after Round 2's candidate froze, by three commits:
`gpu-optional-compute-shapes`, a change-workflow command following a change's clone, and
a CI change running each of `make test`'s targets as its own job. This branch merged
`dev` at `1f157a17d` before any live run, so both lanes qualify code that holds both
changes. The merge changed no decision above:

- **Host records.** `dev` retired the host record's `gpu_count` and `gpu_model` from the
  host API, the INI inventory format, and the database. D3's `public_port=` sits beside
  them in the INI parser, which keeps D3's rule, a malformed `ansible_port=` or
  `public_port=` rejecting its entry, and reads no GPU variable. The host requests in
  the validation runbook, the issue-discovery tool's local phase, and the e2e helpers
  state `ssh` version 2 and no GPU field.
- **The VM listing-shapes scenario.** `dev` added a stage buying a shape without GPUs,
  whose create rule printed a fixed create fact naming a guest that is not the job's
  and stating no status, in the JSON `var:` form. Under D1 that create yields no
  evidence. The rule keeps its match and identity and drops the output, as D1's
  "The VM pipeline scenarios use that default" requires, so the create reads the
  per-job default.
- **Specifications.** `dev` changed "Host inventory is connection identity" and "Host
  writes declare no capacity" in `physical-provisioning`, and added "A host record
  describes no hardware". This change's delta modifies none of them, and every
  requirement it modifies is unchanged on `dev`, so the delta needed no edit and the
  archive keeps both changes' text.
- **Versions.** Both branches had taken the same next minor of
  `arkhai-compute-provisioning-ansible` (0.5.0), `arkhai-compute-provisioning` (0.22.0),
  the provisioning service (0.20.0), and the VM storefront (0.24.0), for different
  work. Measured against `dev`, as `RELEASING.md`'s versioning policy measures a bump,
  this change's bump of each is the next minor above `dev`'s: 0.6.0, 0.23.0, 0.21.0,
  and 0.25.0. Floors that need this change's behaviour rise with them: both adapters'
  and the service's on the Ansible kit to `>=0.6.0`, for `read_fact` and `public_port`,
  and the service's on the family kit to `>=0.23.0`, for compensation. The fulfillment
  kit (0.6.0) and the two adapters (0.12.0 and 0.16.0) were already above `dev`'s and
  are unchanged.

## S5: the bare-metal storefront's registry bearer token

A registry may gate writes behind a bearer token, which a storefront sends beside its
signed request, never in its place. The VM storefront reads `[registry.auth]`, a map
from registry URL to token, and passes it to publication's client and its status
probe. The bare-metal storefront read no such key: its typed `[registry]` section had
none, so the loader ignored a token stated in the Secret overlay, and neither its
publication nor its status client was given one. A registry that gates writes would
refuse every listing of the live bare-metal lane. Found from a synthetic overlay,
after Section 14, and accepted as necessary preflight.

- **Configuration.** `[registry].auth` is typed, secret, and kept out of the settings'
  representation; the chart's generated values schema refuses it in public
  configuration, so it is stated in the Secret overlay. Its URL keys are normalized as
  `[registry].urls` are. A token naming no configured registry, or one registry twice,
  refuses startup, naming the URL and never the token: a mistyped key would otherwise
  drop the token silently, which is this defect again. An empty token is no token.
- **Composition.** The resolved map reaches the registry configuration the runtime
  builds, kept out of its representation. Publication's fan-out passes it to the
  shared multi-registry client, which already sends each registry its own token by
  normalized URL; status's signed health read sends each registry its own.
- **Unchanged.** Request signatures, the registries' response pins, every registry's
  policy, and the VM storefront.
- **The normative home.** A storefront's refusals to start are enumerated by cause in
  `storefront-publication`'s "A storefront that cannot publish refuses to start". The
  change's delta modifies it, keeping all of it, with a sentence and a scenario for the
  bare-metal storefront alone: a registry pin or `[registry.auth]` token naming no
  configured registry, or one registry's token stated twice, refuses startup naming the
  table and the URL and never the token. The pin case predates S5 and had no scenario.
  The VM storefront, which ignores a token for no configured registry, gains no
  obligation.
- **Status and publication resolve a token alike.** Status's health read looks a token
  up through the shared normalizing lookup publication's fan-out uses, so the two agree
  whatever spelling a key arrives in, not only for the normalized map the runtime builds.

A focused independent review of the frozen S5 diff raised both of the last two points,
F1 and F2, and found it otherwise sound. The supervising session accepted both under the
owner's delegated judgement, and judged that the narrow corrections need no further
review round; `tasks.md` 14.18 records them.

Alternatives rejected:
- *Ignore a token naming no configured registry, as the VM storefront does.* That
  keeps the silent drop for a mistyped URL, the failure this fixes.
- *A token in public configuration.* The values schema already refuses it, as for VM.

## Compatibility, migration, and rollback

- **No schema migration.** `public_port` lives in the connection envelope's public
  fields, and the compensation marker is a value of the existing `failure_reason`
  column. Each host row already records its connection's version, and no automatic
  migration rewrites it. A host stored at `ssh` version 1 is moved to version 2 by an
  explicit data update, a host update or an inventory import, as D3 says.
- **Wire.**
  - The fulfillment status and result reads are unchanged in shape. A compensated
    aggregate reads `torn_down` with `failure_reason` `create_compensation`.
- **Rollback.**
  - No downgrade of `ssh` connections to version 1 is provided or qualified (D3).
  - An older service treats a compensating teardown already recorded as an ordinary
    teardown. Its teardown-failure write replaces the marker with
    `provider_reported_failure`, so an in-flight compensation completes and is still
    proven by `torn_down`, without its marker.
  - A `failed` aggregate not yet compensated is left for an operator, as before.
- **Packaging.** Each changed package bumps its minor version once, against its
  version on `dev`. Dependants' floors rise only where they use the new behaviour, and
  the locks are refreshed with `make lock` under the repository's uv minimum. The VM
  and bare-metal roles ship in no Python package, so a role-only section bumps
  nothing.

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
- **Round 2, the preflight candidate:** compensation of a failed dispatched create
  (D4) — the fulfillment kit's operation and marker, the compute-owned seam and
  release paths, the convergence write, the VM resume reader, and the idempotent
  bare-metal reclaim — then the real-host bare-metal scenario's corrections (D14),
  the pinned x86-64 image (D11), the VM teardown repairs (D9), and the GPU recipe
  prerequisites (D12, D13).
- **Closeout.**

Round 2 was planned as D4 alone, with a Round 3 for the CPU-only slice and an
`aarch64` recipe. The scope revision replaced Round 3's content and folded it, with
D14, into Round 2, so the round's sections are 7 to 14 and one frozen candidate
carries both lanes' preflight work. Both live lanes then run, in parallel, on that one
validated candidate; neither runs on a partial or unreviewed one, and a live run never
uses a checkout or environment that is being changed.

Round 1's merge of `dev`, between Sections 4 and 5, was resolved in a session of its
own, by the same role. The writer session that had implemented Sections 2 to 4 could
not also hold the full read of the guidance that the merge requires. Its sections
stay as they were recorded. Section 5 continues from the merge.

From that merge on, the owner set the test cadence, per frozen round:
- Focused suites and packaging gate each intermediate commit, sections and merges
  alike. No intermediate commit owes the full suite, a review, or validation.
- Once a round's last section is committed, its candidate is frozen. One full
  `make test`, one independent implementation review, and one validation (local,
  Helm, and the pipeline) run on that frozen candidate. Round 1's ran after Sections
  5 and 6; Round 2's run after Section 14, before any live purchase.
- A passing result is reused while its candidate is unchanged; a fix commit makes a
  new candidate.
- The live lanes remain required, and each runs only on a validated candidate.

Round 2's frozen candidate, Section 14's commit, passed its full local run and its
pipeline, and was reviewed. Before its Helm part ran, `dev` advanced
("Coordination with `gpu-optional-compute-shapes`"). The merge of `dev` and the fixes
for the review's accepted findings are made in one writer session, gated by focused
suites and packaging, and together make Round 2's new candidate. That candidate takes
the round's one full `make test`, the review's amendment, and validation again before
either live purchase; the earlier candidate's passes are not reused for it.

## Open questions

None. D7's open items, the resource type of a declaration without GPUs and the
registry filter's advisory `required` list, returned with it to
`gpu-optional-compute-shapes`, which settled them when it landed. D10 is decided above; its operational conditions are
live read-backs, not open design.

## Design promotion record

Spec deltas are merged by the archive. Every other destination is written at
closeout, under the heading named.

| Accepted decision | Permanent location |
|---|---|
| D1 fact reading, block boundaries, and linkage | `openspec/specs/physical-provisioning/spec.md` ("A create succeeds only with readable delivery evidence", and "A bare-metal reclaim's printed fact is a diagnostic" for the reclaim's result and the job status's authority over teardown, by the archive); rationale in `openspec/specs/physical-provisioning/architecture.md` under "Durable jobs, transient workers" |
| D2 mocks print the shipped form, rendered for the job, and pipeline scenarios use it | `docs/development/TESTING.md` under "4. System Integration Tests (End-to-End)", beside its paragraph on the compute lanes' mock profile |
| D3 tenant-facing port | `openspec/specs/physical-provisioning/spec.md` ("The tenant-facing host address falls back to the connection address", for the fallback and the delivery endpoint, and "Host registry records the connection port", for the INI `public_port=` rule, rendering, and the record stored without the field; both by the archive); `openspec/specs/physical-provisioning/architecture.md` under "The host registry owns the connection"; `docs/development/DEPLOYMENT_AND_CONFIG.md` under "Definition documents", in its host-inventory paragraph (`public_port=`; every `ssh` host connection, through the API or an inventory, at version 2; and a host stored at version 1 moved forward by an update or an import, never on its own); `ssh` served at version 2 alone, other versions refused, and a re-registration keeping a protected key: `openspec/specs/physical-provisioning/spec.md` ("Host connections are typed by their implementation's codec", by the archive) and `openspec/specs/physical-provisioning/architecture.md` under "The host registry owns the connection". `docs/development/VALIDATION_RUNBOOK.md`'s host requests state version 2 already (task 3.11). The bare-metal operator's route: `docs/bare-metal-seller-quickstart.md` under "Define the selected site", whose inventory example gains `public_port=` and whose sentence on `public_host` says the buyer's endpoint is the host record's `public_host` and `public_port`, each falling back to the connection's. The VM operator's: `docs/seller-quickstart.md` under "4. Prepare your KVM hosts", step 2, which says a VM guest's port is its forwarded or relay port, never the host's `public_port`. `docs/development/RELEASING.md` is unchanged |
| D4 compensating teardown, its marker, and the compute seam | `openspec/specs/fulfillment/spec.md` and `openspec/specs/physical-provisioning/spec.md` (by the archive); `openspec/specs/fulfillment/architecture.md` under "Durable persistence and recovery"; `openspec/specs/physical-provisioning/architecture.md` under "Proof-driven release"; `docs/development/ARCHITECTURE.md` under "Release", whose table's `failed` row splits into compensable and not |
| D5 run-log round trip | None: a test that qualifies the producer's existing form. No behaviour changes |
| D6 an exhausted teardown job is not re-run | `openspec/specs/physical-provisioning/architecture.md` under "Proof-driven release", whose `teardown_failed` requeue sentence is corrected |
| D7, withdrawn | None. Nothing was implemented, its two deltas are removed, and its slice is `gpu-optional-compute-shapes`'s again. That change delivered it and is archived; its archived proposal and index row, from `dev`, do not name this change |
| D8 VM lane terms | None: operational configuration, set before a live purchase |
| D9 VM teardown | `openspec/specs/physical-provisioning/spec.md` ("A VM teardown removes only what its guest created", by the archive) |
| D10 lanes on separate machines in parallel; on a shared machine, sequential lanes, pause, drain conditions, and the pause's precondition | `docs/development/VALIDATION_RUNBOOK.md`, a new generic section on running live lanes: lanes on separate machines run in parallel while source, build, and environment changes stay serialized; lanes sharing a machine run in sequence under the freeze, the pause, read-backs in the site's own states, full projection availability, and the precondition that a refresh or reopen under the same identity keeps the pause; `docs/development/ROADMAP.md` "Payment qualification boundaries", for the pause's limits and coverage gaps |
| D11 a pinned, verified x86-64 guest image | `openspec/specs/physical-provisioning/spec.md` ("A VM guest is created from a pinned, verified image", by the archive); `domains/vms/provisioning/iac/README.md` under "Prerequisites", for the x86-64 host prerequisites, the `vm-setup.yaml` warning, and how an operator moves the pin; `docs/seller-quickstart.md` under "4. Prepare your KVM hosts", step 3, for the host prerequisites |
| D12 boot-GPU detection, the opt-in, and the live passthrough-binding check | `openspec/specs/physical-provisioning/spec.md` ("A host's boot GPU is passed through only by an operator's opt-in", by the archive); `domains/vms/provisioning/iac/README.md` under "VM Management Operations (vm-management role)", beside the passthrough variables, including that the inventory alone never makes a GPU eligible |
| S3 the relay proxy wait reads the client's status body whatever its label | `domains/vms/provisioning/iac/README.md` under "VM Management Operations (vm-management role)": the wait's readiness rule and what it retries or refuses |
| S5 the bare-metal storefront's `[registry.auth]` | `openspec/specs/storefront-publication/spec.md` ("A storefront that cannot publish refuses to start", by the archive: a bare-metal registry pin or token naming no configured registry, or a token stated twice); `docs/development/DEPLOYMENT_AND_CONFIG.md` under "Storefront startup and site trust", whose list of refusals gains that one for bare metal, and under "Bare-metal role configuration": `[registry.auth]` in the Secret overlay, one token per configured registry URL, sent beside the signature on publication and status alike |
| D13 the readiness wait and autostart | `openspec/specs/physical-provisioning/spec.md` ("A GPU guest's readiness wait and autostart are set by its pool's operator", by the archive); `domains/vms/provisioning/iac/README.md` under "VM Management Operations (vm-management role)", beside the passthrough variables: the three `extra_vars`, their defaults, and why a host passing through its only GPU sets `vm_autostart` false |
| D14 the real-host bare-metal scenario | `docs/bare-metal-seller-quickstart.md` under "Release-qualified deal evidence": the role inputs, the pinned known-hosts file among them, `--run-id`, teardown to `released`, and revocation proven only by an authentication refusal. `docs/development/TESTING.md` is unchanged: its sentence on `e2e_bare_metal_deal` stays true |
| The role's task files parsed by the repository's syntax check (Round 2 review F1, `tasks.md` 14.8 and 14.14) | `docs/development/TESTING.md`, beside "Chart Render Tests", and `domains/vms/provisioning/iac/README.md` under "Validation": `validate-playbooks` parses the `vm-management` task files, a capacity check's included, through a parse-only playbook importing them in the role's context, what a syntax check does not show, and that a free-form `shell` string's unbalanced quote fails its task file as it loads |
| Live qualification of both lanes | None: external evidence, recorded at closeout as live evidence or named blockers (`tasks.md`, the closeout's end-to-end part) |
| Roadmap currency | `docs/development/ROADMAP.md` "Goal 1 — Consolidate physical-resource authority in the provisioning service" (the real runner's evidence row) and "Payment qualification boundaries". Goal 2 is unchanged: this change no longer sells VM shapes without GPUs |
| Campaign index currency | `openspec/changes/README.md`: this change's row. The dependency line to `gpu-optional-compute-shapes` and that change's `Depends on` entry were removed with D7's withdrawal |
