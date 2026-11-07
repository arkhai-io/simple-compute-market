# Physical Provisioning Architecture

The [normative contract](spec.md) defines executor dispatch, jobs, and release. This document explains how the compute service composes generic lifecycle machinery with domain adapters.

## Compute composition

The compute service owns transport, persistence, job execution infrastructure, lease lifecycle, and registration of concrete adapter bundles. Domain adapters own infrastructure-specific request validation, invocation, result interpretation, and credentials.

```text
compute service composition
    ├── generic jobs and lease lifecycle
    ├── site and resource-pool authorities
    ├── fulfillment scheduler/registry
    └── VM, bare-metal, or future adapter bundles
```

The offering-mode-neutral composition root lets generic services dispatch by recorded executor or provider identity without importing a concrete domain implementation.

The mock mechanism is a worked instance of the five-piece route pattern (`docs/development/ARCHITECTURE.md`, "Route contracts and their HTTP binding") in which the family owns every piece but the binding's location. `compute_provisioning_contracts.mock_rules` holds the route-contract template, `MockRouteMount`, a path prefix and an operation-name prefix whose `route_declarations()` yields the rule add, list, delete, and resume routes and the evaluate-job route, and the wire models those routes answer with (`MockRuleAdded`, `MockRuleView`, `MockRuleDeleted`, `MockRuleResumed`, `MockJobEvaluation`, and the request `MockRuleCreate`). The family kit's `MockRuleRouteService` (`compute_provisioning.jobs.executor_mock`) answers with them, and `compute_provisioning_client`'s `MockRuleClient` and `SyncMockRuleClient` sign each call from a mount's declarations and return the same models. A domain states only its mount: VM's is `VM_MOCK_ROUTE_MOUNT`, `("/test", "provisioning_test")`, in `vm_provisioning_operator.routes`; bare metal's two values, `"/test/bare-metal"` and `"provisioning_test_bare_metal"`, live in `arkhai_bare_metal.provisioning_routes`, so `arkhai-bare-metal` keeps no compute dependency and its adapter builds the mount. Each adapter binds the route service under its mount's prefix and contributes the mount's declarations to the service's table. The evaluate-job request stays each domain's, since its fields are the domain's job parameters. A further compute domain mounts the mechanism by stating its two values.

The service's database holds VM's tables, so its metadata (`db/database.py`) and its one migration history (`db/migrations.py`) name them: the history is the record of how those tables were created and evolved, including VM's pool-configuration table and VM's legacy lease conversion. `deployment-state`'s "Service-owned migration history" still gives the migration entrypoint only its database; nothing injects VM's schema. A single chain is adequate while one compute domain owns provisioning-side tables. When a second domain needs its own, each adapter would own its chain, run in an order the contributions declare, which amends that requirement.

The resource-pool projection a site serves is neutral, and a domain that publishes more — a view of a whole machine it sells, or a pool's configured defaults — contributes an `InventoryViewProjection` from `compute_provisioning.inventory_views`, which owns the protocol and its composer. The service merges what each projection returns and never names a domain's view, attribute, or provider configuration. A resource view is built with its pool's context, an `InventoryPoolContext` of pool ID, provider, and the pool's resolved declarations, because what a view may carry depends on them: a bare-metal view carries its delivery terms only where the pool's backing delegate passes them through (see the [resource-pool management architecture](../resource-pool-management/architecture.md#advertisement-delivery-and-backing)). The provisioning service, as the composition root, reads the pool rows in its own resource pass, resolves each pool once through the shared resolver, and hands each declaration its pool's context, interpreting none of it; the pool pass reads raw tags and the provider from the same column, so the two passes cannot drift on a pool's provider. A stored pool whose declarations do not resolve, which startup refuses and no write path produces, gives its members no context, so they project with no views and no problems, and the service logs a warning. The declarations the service hands the composer are the site ledger's offered read, whose `enabled` already says whether the site offers each one, so a view that reports availability, such as bare metal's, reports a declaration with no usable host as unavailable without the service or the view reading a host (see the [site-capacity architecture](../site-capacity/architecture.md#declared-capacity-and-connection-identity)). Building the context is compute-family work, so it sits at the contributed-view seam and nothing above the compute family learns of it: `kit/site` copies the per-resource result into its projection without reading it, and `kit/resource-pools` and core do not see it.

A contributed projection never raises on a declaration's content. Declarations reach the site over its API from any client, and one a view builder could not handle would otherwise fail the site's whole resource-pool projection, every pool and every domain with it. `resource_views` returns a `ResourceViews` of the views it built and, per declared view it could not build, the reasons, which the projected resource carries as `publication_view_problems` keyed by view identifier. A backed bare-metal declaration naming no host or no access methods, a missing or invalid `allocation_mode` or `physical_host_id`, and a private-looking capacity or capability key are such cases. A storefront reads a resource with problems as an unreadable declaration and holds its listing (see the [storefront publication architecture](../storefront-publication/architecture.md#reconciliation)). Refusing a malformed attribute when the declaration is written was rejected: its backing-dependent rules need a site read of pool state that the site may not take while its edge into the pool authority stands, so a write-time check would be partial and the projection would still have to tolerate what it missed.

## Registration boundary

Adapters register executor actions and FulfillmentProviders explicitly. Duplicate identities fail during startup because silent replacement would make persisted records execute under a different implementation. Provider and executor registration remain independent: fulfillment create/status/teardown and lease-release actions have different contracts and may evolve separately.

## Durable jobs, transient workers

A persisted job gives accepted work a durable identity, status, request snapshot, result, and diagnostic history. The in-process queue is only the execution mechanism. It does not become the database, retry authority, or provider policy engine.

This distinction makes accepted work observable while avoiding false recovery promises. A process restart does not by itself prove that every queued or running action is safely resumed; recovery must be explicit where required.

The job record is also where delivered credentials live. A job's executor reports the credentials it generated as `CredentialEnvelope`s, and the job authority stores them with the transition that reports them. The fulfillment aggregate, its provider metadata, and the fulfillment result hold none: a result query for an active fulfillment reads its create job's credentials from the job record each time. Keeping them there is a necessity, not a cache — the create job generates VM tenant credentials on the host, and nothing can read them back from it afterwards.

A job's result is read from the fact its role prints, and one reader in the shared Ansible kit, `compute_provisioning_ansible.read_fact`, reads it for every compute domain. Under the packaged configuration's YAML callback format a role's `debug: var:` fact prints as YAML, which the kit does not parse, beside the JSON document its `debug: msg:` task prints as a literal block; under the JSON format the `var:` form is JSON. The reader takes either, reads each `msg:` block alone so it never runs into a later task's output, and keeps only a document naming the action the job expects. Judging that document belongs to the domain's codec, which owns what a result means: it yields delivery evidence only when the fact names the job's own action, target, tenant account (and, for bare metal, machine), and success. That guards against adopting the wrong document from one run's output, not against provenance across runs. A bare-metal reclaim's fact is checked the same way but decides nothing: a fact that does not match is recorded as a mismatch for an operator, and the reclaim job's status alone decides its teardown.

Two limits follow. An operator's VM password reset runs as its own job, whose new credentials are stored against that job; the fulfillment result still reads the create job's, so after a reset it delivers the superseded password. And the envelopes are stored as plain JSON, unlike a relay's admission token, which is encrypted with the deployment's key, and nothing deletes job rows; anyone who can read the provisioning database can read every credential a job has reported, including those of workloads since torn down.

## Selected-resource execution

Concrete providers operate on the Settlement Resource selected by fulfillment scheduling. The VM Ansible adapter resolves pool/provider configuration, validates it, and snapshots prepared inputs at dispatch. Administrative pool edits therefore affect later operations rather than rewriting the accepted execution.

Operational inventory is authoritative service state, not a checked-in Ansible inventory. A host definitions document or an INI submitted to the import route may register hosts, and an adapter may render transient execution inventory, but operator mutations and job-history references remain tied to persisted resources.

### Bare-metal storefront pull boundary

The bare-metal storefront is a client of the accepted POOLS-7 scheduling and fulfillment contracts, not a second job repository or convergence worker. It derives one `SettlementResource` request from the immutable accepted listing/site/Physical Resource and agreed bare-metal terms, submits it to the provisioning authority bound to that site, and persists only returned reservation, settlement-resource, and fulfillment correlations.

The storefront's seller table binds payment, Alkahest and contact stages;
its purchase table binds payment only. A payment or Alkahest seller persists one
`bare_metal.settlement-evidence.v1` payload in negotiation-keyed
`bare_metal_settlement_records`, bound to the exact Agreement digest and an
immutable established reference. Verified source/delivery cannot be replaced.
Physical lifecycle correlations, progress and private results remain separate.
A contact-exchange deal records no settlement evidence: it completes by its
introduction, whose reveal is the contact-exchange kit's own record, and it has
no settlement or fulfillment to load. No escrow row or payment chain-name
sentinel is alternative authority.

Common begin, recovery/status, access/result and teardown load verified evidence
through the accepted entry. Payment rechecks the mandate and trusted signed
receipt. Alkahest requires an active journal (pending reclaim/collection and
ready mechanism status) and rechecks chain evidence against the persisted
proposal, amount/duration, selected chain and exact obligation index, on every
drive of a deal. Local materialization is adoption history, not current chain
authority.

Delivery enters through core's `fulfill_domain` hook, as VM's does: payment
settle and the Alkahest ready step build a `StorefrontFulfillmentContext`, and the
registered hook builds the compute delivery path from the clients in `ports` and
the storefront's lifecycle in `domain_input`, refusing before any call when the
lifecycle is absent. There is therefore one registered entry, and it always admits
and commits the Agreement's window, and core's identity check runs on every
bare-metal delivery. No core type changed for this: `ports` and the opaque
`domain_input` already carry what the hook needs. The hook drives under the deal's
lock, drives the physical end after releasing it, and returns the lifecycle row as
`domain_result` with a public result naming the outcome, its fulfilled, deferred
or failed disposition, and whether the deal is available.

`bare_metal_fulfillment_lifecycle` is the path's progress port for bare metal
([compute delivery](../compute-delivery/architecture.md)), its step read from the
activation instant, the fulfillment, a recorded `dispatch` state, then a
reservation; its row is created only while the settlement record is verified, in
the admission's transaction, so a seller refund that won the start refuses it. The
domain port reserves the whole-machine claim with `escrow_uid` beside the
`:settlement` placement key, so recovery replays by key rather than scanning the
site's reservations, and schedules and records the assigned resource before
building the materialization over the Agreement window, since the request names
that resource. The lifecycle cycle drives waiting and pending deals. A status read
drives a deal whose fulfillment is active and not yet available before answering,
so the administrator's settle wait and a buyer's status read reach availability;
the access read does not drive, reaching no payment authority, and goes through the
path's access check. `access` and `status` are declared credential-capable.
Migration `bare-metal-storefront-0016-delivery-activation` adds the activation
column, marks a row an earlier storefront left with a saved materialization and no
fulfillment as dispatched, so it is adopted rather than released, and removes
`host`, `port` and `username` from every recorded replay body whose `method` is
`ssh`.

The scheduler's recorded resource kind, provider, and executor selection remain authoritative for begin, status, result, and teardown. The storefront never substitutes a process-global provisioner, buyer-supplied URL, or guessed adapter. It pulls normalized status and the versioned result envelope through the same recorded site client after restart; provisioning remains the authority for jobs, provider metadata, execution credentials, and teardown convergence.

### Signed payment receipt boundary

Arkhai payment acceptance stores the seller-derived mandate in shared negotiation `settlement_data` beside exact Agreement bytes. The seller verifies the service-signed receipt against that mandate before selected-site reservation, scheduling, or fulfillment. Pending payment cannot create access or renew capacity. Equivalent retries reuse the accepted site, durable reservation, and fulfillment identity; recovery rechecks receipt evidence before physical effects.

VM retains negotiation-scoped settlement evidence and independent delivery
progress/convergence claims without a chain escrow or payment obligation.
Bare metal retains independent evidence and its selected-site lifecycle/public
result. Neither common delivery path dispatches from a mechanism ID. Lease expiry and revocation use provisioning-owned teardown convergence; capacity stays quarantined until authoritative release, independently of payment hold release or refund.

### Explicit storefront database reset

Incompatible disposable bare-metal storefront databases require explicit reset
while effects and recovery are quiesced. Confirm database ownership, use a new
owned path or remove only that disposable database, bootstrap current migrations,
then republish and renegotiate. Old receipt-only evidence and escrow-named
lifecycle shapes fail startup; there is no silent copy/adoption or sentinel
fallback. Rebuild `.dist` and reinstall consumers before use. Controlled HTTP
settlement/contact entries use fresh pytest-owned SQLite and clean it afterward;
this is not live hardware access/revocation qualification.

## Lease-end report delivery

The site forms immutable `lease_ended` evidence when it intends to end a lease,
before teardown. Explicit termination, expiry, direct release without dispatch,
release failure and force release all have durable event identity. Payloads bind
reservation/site, effective instant, cause/source state, caller/failure reason
and applicable deadline phase. The ledger ending transition and separately
acknowledged report outbox commit atomically; retries reuse the original event.

The compute wire codec frames canonical payload bytes under
`arkhai.site.lease-ended.v1`. The service persists the original signed wrapper,
so retries and `LeaseView.end_reports` return the same bytes after signer changes.
Push targets only the owning storefront peer. A 404/unsupported receiver parks
that peer's push, transient failures retry, and a changed peer cannot redirect
old events. Explicit resumption after receiver upgrade re-enables parked push.
Authenticated lease reads recover reports independently of the push channel.

VM/bare-metal ingress verifies the configured selected-site binding, retains the
exact wrapper idempotently, and records source/actor/cause in end service. Buyer
lifecycle reads expose that same evidence, not a storefront re-signing of it.
The site knows no payment transaction, dispute policy or payee credential.
Seller end classification/filing belongs above provisioning.

Due delivery ends terminate immediately; future ends truncate rather than extend
the accepted horizon at second precision. Pre-dispatch release stays behind the
site's guard; create-in-flight is adopted before termination. The intended-end
report has its own acknowledgement, distinct from the existing capacity-released
outbox. A report, failed release or queued teardown proves no hardware stop and
returns no capacity; normal release remains proof-driven below.

## Proof-driven release

Release is proof-driven and split across two cooperating owners. Lease lifecycle decides when a reservation should release and owns the final capacity-return decision; it never dispatches a second teardown operation. Fulfillment convergence (see `openspec/specs/fulfillment/spec.md#fulfillment-convergence-worker`) owns teardown dispatch, provider polling, and recovery through `torn_down`/`teardown_failed`. A kind-routed `ReleaseJobPort` connects the two: VM-backed reservations resolve release status by reading the fulfillment aggregate's teardown state; other offering modes continue reading the shared job queue. The site authority releases capacity only after the fulfillment aggregate reaches `torn_down`, or an operator explicitly force-releases. Failure retains the reservation and records a retryable release state (`teardown_failed`), which convergence requeues without an operator prompting it. A requeue re-observes the teardown's job, whose identity is fixed per reservation; it does not run a job whose own retries are exhausted again, so such a teardown stays failed and its capacity held until an operator verifies the host and force-releases it. An explicit force release is an operator override with distinct audit meaning, not fabricated proof of executor success.

A create that was dispatched and then failed has host effects nothing proved removed, so it is not left to an operator by default. When its provider reported the failure and its job metadata names its create job, release compensates it: it begins the domain's ordinary teardown from the `failed` aggregate, marked `create_compensation`, and capacity returns only when that teardown reaches `torn_down`. Each domain's teardown is safe after a partial create: bare metal's reclaim reports an account its grant never created as absent rather than failing, and a VM teardown removes only what its own guest created, finding each artifact by the guest's name when its cleanup script is missing and failing on one it cannot attribute. Compute provisioning alone decides eligibility, through one predicate the release decision, status, and teardown ports share; a failed row it cannot compensate — quarantined, with unreadable metadata, or with its create job missing — still waits for an operator.

Readiness checks use local service dependencies. Slower outbound provider or storefront diagnostics belong to operator surfaces so an external failure does not unnecessarily make a healthy API/worker process unready.

## Authenticated service boundary

### Exact role and authority selection

The provisioning boundary authorizes complete scheme-tagged principals, not
addresses or credential-shaped strings. Each authenticated route selects its
required `seller` or `admin` role, and the durable provisioning principal
authority resolves the active principals for that role. Bootstrap configuration
seeds an empty role binding but never overwrites persisted generations, so
configuration drift cannot silently replace a rotated authority.

The provisioning service has its own configured public principal and injected
signer. Client composition supplies the provisioning endpoint and expected
service authority trust set independently of request content. The same
provisioning composition resolves the storefront counterparty for inbound
requests and outbound lifecycle callbacks. Consequently, a valid proof by a
different role or principal has no authority, and neither a request body nor a
private credential can choose the identity against which it is checked.

### Canonical requests, durable replay, and signed responses

`arkhai.market-request-signature.v2` binds the caller role and complete
principal, HTTP method, semantic operation and resource, request identity,
timestamp, and canonical body hash. Route metadata supplies the operation and
resource independently of proxy path spelling. This makes body mutation,
cross-role replay, principal substitution, and retry with changed content fail
before a handler or infrastructure effect runs.

The authority durably reserves `(principal, request_id)` with the canonical
request digest before dispatch. A completed exact retry recovers the recorded
status and body and returns them under a fresh signed response. A concurrent
exact retry is rejected while the dispatch lease is active; after expiry, one
caller can atomically claim the unfinished reservation and resume it. Reuse
with any different signed content remains a replay conflict. Durable outcome
classification is therefore the recovery authority rather than process memory.

Mutation responses use the distinct shared response domain to bind the status,
originating request identity, provisioning authority principal, timestamp, and
canonical response body. Clients verify every field against the expected
authority before accepting an acknowledgement. This distinguishes an
authenticated authority outcome from an unsigned status code or a correctly
signed response produced by the wrong service.

A route that fails after the caller was authenticated still answers signed: a
500 with a fixed, non-revealing detail, the error itself going to the service's
log. An unsigned 500 would reach the caller's typed client as missing response
authentication rather than as the authority's failure. The provisioning
service's middleware records that answer as the request's outcome, as it
records any, so an exact retry replays the same signed 500 instead of finding
the reservation in progress until its dispatch lease expires. `kit/site`'s
middleware, which the API-credits service composes, keeps reservations but no
outcomes, so it answers the signed 500 and records nothing; an exact retry is
handled as its route's retry contract says. Neither middleware catches a failure
after a route has started its response: the body stream ends and the error is
re-raised only once the status is sent, so the middleware would sign, and the
provisioning service record, a truncated body under the original status. No
route streams its response, so the limit is latent; a streaming route needs the
middleware to detect that failure or to refuse streamed responses.

A request that resolves to no route contract is answered before authentication,
by what failed to match, and unsigned: 404 for a path no contract names, 405
with `Allow` for a path named only under other methods, 400 for a route whose
body resource cannot be bound. Route resolution reports the case through a
typed error (`ProvisioningRouteNotFound`, `ProvisioningRouteMethodNotAllowed`,
`ProvisioningRouteResourceUnbound` in `compute_provisioning_contracts.routes`;
`SiteRouteNotFound`, `SiteRouteMethodNotAllowed`, `SiteRouteResourceUnbound`
in `market_site.auth` for `kit/site`'s middleware). Such an answer cannot be
signed meaningfully: a response proof binds the method, operation, resource,
request identity, status, and body, and a client verifies it against its own
operation and resource, while the server knows no operation for an unknown path
or a wrong method and no resource for an unbindable body, and a request carries
a signature over its operation rather than the operation itself. Signing "not
served" over the caller's claimed operation needs a request envelope that states
its operation, which the current version does not; until then the answers stay
unsigned. The family client and the site client refuse an unsigned answer as
they refuse any unverifiable one, but report it distinctly
(`ComputeProvisioningUnauthenticatedResponseError`,
`SiteCapacityUnauthenticatedResponseError`), by its status alone: an unsigned
answer is also what anything between client and authority may give, so nothing
it says is repeated. The family client resolves its own table before sending,
so it meets these answers only when its table and the service's differ.

The route table can answer by cause, and can refuse ambiguity, because a route
contract's pattern is restricted: literal segments, `[^/]+` named captures,
finite alternations of literal segments, and an optional terminal `/?`. Building
a contract refuses any other pattern, and so does a pattern compiled with a
flag, since the comparison reads only the pattern's text. Over that grammar,
overlap is decidable segment by segment, so `ProvisioningRouteTable` refuses,
when it is composed and before the service accepts traffic, two contracts of
different contributions that one method and path could both match: neither
owner can say which signature such a request means. Within one contribution the
first matching contract decides, in the order its owner gave. Detecting
ambiguity per request instead would let a mis-composed service start and fail on
exactly the overlapping requests. The grammar is hand-written only while it
stays this small: a route needing more, such as a tail capture or a typed
segment, is a reason to adopt an established path-template grammar and its
matcher, and rebuild the overlap comparison on it, not to widen this one.
`kit/site`'s middleware has no ambiguous case: it resolves first-match over the
one ordered table its composition root gives it, which the API-credits service
extends with its own routes, and it takes no contributions.

One such failure is refused at startup instead: the service does not start
while a stored pool names a provider no registered handler serves. Handlers are fixed by
the build and every write refuses an unknown provider, so such a row comes only
from outside the service's write paths, no pool document can repair it, and
every read of it would fail; startup names each pool and provider, beside its
refusal of stored pools whose declarations are invalid. Unreadable own state
stops startup because waiting does not repair it, where an unavailable
dependency starts the service degraded.

### Scheme, credential, and package boundaries

Ed25519 and EIP-191 use the same canonical request, response, replay, and
rotation models. Verifier-registry dispatch changes only the cryptographic
operation and remains local in both cases. Ed25519 provides a wallet-free
service profile; selecting EIP-191 for marketplace identity does not by itself
require an RPC endpoint, while any chain effect receives separately validated
wallet and chain settings.

Ordinary configuration contains public service, storefront, and administrator
principals and trust pins. The provisioning credential enters through the
service's secret boundary, constructs a signer whose public principal must
match configuration, and does not enter settings, persistence, request bodies,
responses, logs, or diagnostics. Service, storefront, and administrator
authority inputs are independent, and optional chain-wallet credentials do not
implicitly supply any of them.

The shared identity package owns principal normalization, signer and verifier
contracts, canonical request and response models, proof-scheme dispatch, replay
classification, and rotation proof validation. Compute provisioning packages
own only their route semantics, durable replay and principal-authority adapters,
and service/client composition. Keeping that dependency direction prevents a
second signature protocol and keeps raw private keys and signature encodings
out of generic provisioning orchestration.

### Rotation and disablement

Counterparty rotation changes the principal generation attached to a stable
role binding, not the role subject itself. Both the active and replacement
principals sign one authority- and subject-bound statement. The registry
records the replacement and audit history, accepts both principals only for the
bounded overlap, and rejects the old principal after expiry or retirement.
Disablement removes authorization without assigning it to a replacement and
does not erase the binding or rotation history.

## Explicit authority boundaries

Provider-to-executor linkage and universal multi-storefront event routing are
not inferred. Optional notification adapters are delivery mechanisms, not
ownership authorities.

## Host preparation cannot cost the machine

Two rules govern how a rented host is prepared for passthrough, and both exist
because the failure they prevent is unrecoverable in band.

**No configuration change that can remove the host's network path may require a
reboot to take effect, or a reboot to be undone.** Enabling the IOMMU is exempt:
it claims no device. Every decision about which devices go to guests is applied
from userspace, so a wrong decision fails an operation on a running machine
rather than producing one that cannot be reached to correct it. A host that has
lost its network interface cannot be recovered by any in-band mechanism — a
tunnel, a second SSH daemon, an agent, or a self-healing loop all require the
interface that was taken.

**A rollback target must be a state that cannot fail, not the most recent state
that has not yet failed.** A configuration that boots correctly by winning a
driver race is an unobserved failure, not a known-good baseline, and reverting
to it delivers the machine into a coin flip at the moment reliability matters
most. The rescue boot entry therefore binds no device at all: its correctness
follows from what it does rather than from history. For the same reason a
binding is not made to persist across reboots until it has been applied and
verified on that machine.

Refusing an ambiguous topology is preferred to working around it. An IOMMU group
is the hardware's unit of DMA isolation, so a GPU grouped with a network or
storage controller cannot be assigned without assigning that controller too. The
ACS override patch would split such a group by asserting an isolation property
the hardware does not have, and its failure mode is silent cross-guest DMA. In a
marketplace renting isolation to strangers, the correct outcome is an accurate
report that the device is unavailable.

## The host registry owns the connection

Address, user, key material, and port are one descriptor and live together in
the host registry, because a rendered inventory must be reproducible from the
registry alone. Splitting any part into service configuration would make the
connection unreproducible and would express one value for every host, which is
wrong as soon as two hosts sit behind different tunnels.

Beside the provisioner's route, a connection may name the direct buyer route:
a tenant-facing `public_host` and `public_port`, each falling back to the
connection's own address and port. A bare-metal buyer uses this route when the
pool has no buyer relay; for a relay-backed pool, the leased relay endpoint is
delivered instead. A VM guest is reached at its own forwarded or relayed port,
never the host's `public_host` or `public_port`.

The `ssh` connection is served at version 2 alone, and a submission stating no
version, or another, is refused. A host stored at version 1 is refused before
any inventory is written, and runs nothing until it is submitted again at
version 2 by an update or an inventory import. An update restates every stored
public field. A protected key it neither resubmits nor replaces with a key file
is carried forward from the stored row as ciphertext, never read or decrypted.
Nothing rewrites a stored row on its own.

The port renders explicitly even at its default, so an inventory line states
what the registry holds rather than leaving the default implied by an absent
one. A malformed port fails its entry rather than degrading to a default: an
unreachable host is not a degraded host, and a substituted value turns an
operator's typo into a failure that resembles a network fault.

## Hosts are a reconciled declaration

Hosts reach the registry through the host API, the Ansible INI import route, or
a host definitions document. The document follows the rule every definition
document follows: a process start is not a submission and a changed document
is. Startup applies it only when its digest differs from the one recorded under
the kind `hosts`, recording the digest in the apply's own transaction, so an
edited and rolled document is applied and a restart against an unchanged one
leaves API edits alone. A site must be establishable from configuration alone,
since a deployment applies a chart with no operator API call in it, which is why
hosts keep a startup document at all. Seeding only an empty registry was
rejected because an edit to the file then did nothing and said nothing.

The document is YAML with the registration API's field names, not the Ansible
INI. The INI cannot state `enabled` or a connection's kind or version, always
names a key path, and reads an absent pool as "leave it", so reconciling it
would be a merge rather than a declaration. The YAML form is format-neutral:
the compute family library owns its parsing, validation, equality, session-scoped
apply, and export beside the host authority, and the service gates it as it
gates capacity, after the stored-pool check so every pool a host names exists.
The Ansible distribution keeps the INI parser and its import route, which
upserts as it always has; an operator who prepares hosts with Ansible keeps that
INI as a separate list.

An entry declares its whole host. Omitting `pool_id` unplaces the host and
omitting `enabled` enables it, so deleting a line from an entry means what it
says, as it does for capacity and relay entries; merging would bring back the
omitted-versus-null distinction a declaration exists to avoid. The cost is the
capacity document's: a host disabled or moved through the API is restored by the
next change to the document unless the document restates it. Equality is taken
after the connection's codec, with the stored connection as `previous`, so an
entry omitting a field the codec defaults equals a host stored with the default,
and an equal entry writes nothing and runs no pool-change hook. The codec types
the public fields strictly for every submission, because they are the values an
operator types by hand.

A host the document does not name is retained and reported, not disabled. Hosts
registered through the API, as every end-to-end lane registers them, must
coexist with the document, and disabling every host a document does not name
would take them out of service. Disabling a host keeps new deliveries off it
(["Disabling a host keeps new deliveries off it"](spec.md#requirement-disabling-a-host-keeps-new-deliveries-off-it)),
so a document that disabled the hosts it stopped naming would close their
listings on an edit to an unrelated entry.

A document that cannot be applied fails whole. The apply writes into the
caller's session and continues past a pool-change hook's refusal so that every
refusal is reported, then rolls back on any problem; whatever a refusing hook
wrote is discarded with the rest, so the hook contract needs no savepoint. A
refused move at startup keeps the service down until the edit is reverted,
because the leases that refuse it cannot drain while it is down; validating a
changed document through the import route before the release reports the same
refusal against live state without an outage.

The document names key material by `key_path`, or keeps a stored protected key
by naming none, and never carries it: registering key material stays an API act.

An existing site's first document comes from the canonical export, which
reproduces pools and enabled states set through the API, where converting an INI
would reproduce the file rather than the site. A site with no recorded `hosts`
digest applies its first document like any changed one. The export omits a host
it cannot state as an entry, one whose connection kind or stored version no
codec serves; such a host already runs nothing until it is submitted again, and
a document built from the export retains it and reports it as not named.

## Related contracts

- [Fulfillment](../fulfillment/spec.md)
- [Site capacity](../site-capacity/spec.md)
- [Resource-pool management](../resource-pool-management/spec.md)

## Provider operation correlation

A provider job identifier is the durable correlation point for an in-flight
Ansible run. Losing that correlation does not prove that creation failed or
never occurred, so recovery MUST NOT compensate by launching another create
playbook. The adapter remains the owner of provider metadata interpretation and
teardown-envelope construction.

## Buyer access to provisioned hosts

A provisioned host has an operator management connection and may also carry a
buyer route. They are separate authorities. The host registry stores the
management connection needed to render provisioning inventory. A direct
bare-metal route uses the host's buyer-facing `public_host` and `public_port`,
each falling back to the connection address and port. A relay-backed
bare-metal grant instead creates a per-lease TCP proxy from the host to a leased
relay port. A VM guest is reached through its own forwarded or relayed port; the
host's buyer-facing route is never the VM endpoint.

### Buyer SSH uses a leased TCP port

SSH sends no `Host` or SNI header and exchanges its version banner immediately,
so an HTTP-style subdomain cannot select a buyer's SSH session. A TCP proxy
uses a distinct remote port, which is the route the lease can allocate and
reclaim.

### Port allocation is not a relay-dashboard lock

A relay dashboard is a monitoring surface, not a distributed lock: querying it
for a free port adds relay credentials, reachability and a race to allocation,
and asking the relay whether a client registered its own proxy adds a roundtrip
to a third party about client-owned state. The provisioning service allocates
from its durable lease authority; the registering client verifies its proxy.

### Relay admission is local to the relay

The compute-family service allocates a port and signs one short, lease-bound
grant for it. The relay plugin verifies the grant locally; neither the plugin
nor the relay calls the provisioning service. The grant binds its audience,
port and expiry, and admission requires a TCP proxy on that exact port, inside
the configured issuer range and before expiry. The plugin and signer conform to the published grant protocol and vectors
([tool documentation](../../../tools/frp-grant-admission/README.md)); the shared
FRP role owns the verified 0.61.1 binary pin. Admission has no effect on an already registered proxy, so teardown
removes the proxy and a released port remains quarantined through grant expiry
plus the configured reuse margin. Keep service and relay clocks synchronized
well below that margin; the plugin checks expiry on its own clock without
leeway.

The versioned `frp-grant+jwt` carries a JCS-canonical compact token with `aud`,
`exp`, `jti`, and `port`, plus `sub` when a host is recorded; its `kid` is the
signing key's JWK thumbprint. `jti` names the owning reservation. The token has
no `iat` or `nbf`; issuer keys are configured in the plugin's published public
key format, and the signer is checked against the plugin's conformance vector.

### Relay credentials stay on the host and in the service

The buyer client runs on the host, never in a buyer-controlled VM. VM
guest-root control does not expose host-held relay credentials. On bare metal,
this boundary depends on the tenant remaining nonroot, the root-only client
configuration, and the authenticated admin API on a privileged port. The host's
buyer client uses a generated per-host admin password; binding below port 1024
prevents a nonroot tenant from impersonating it while the client is stopped. The management
client and management relay stay separate. Tasks that render, read or send the
grant, relay token or admin password use Ansible `no_log`, and each domain's
codec marks these values as secret fields for job redaction. Provider extras
cannot override the client baseline, proxy targets or task controls.

The `grant_key_secret_key` profile value is one-line standard base64 encoding
of an Ed25519 PKCS#8 DER private key; surrounding whitespace is stripped, and
invalid or missing values fail relay creation without echoing the secret. It is
read when a relay is created; later API rotation remains authoritative over
definitions reconciliation. Keep a
controlled private-key value in the deployment profile when an empty-database
reinstall must reproduce the plugin's trust. The relay stores its private key
encrypted and returns public key and lifecycle metadata only. Rotation stages a
new key, adds its public half to the plugin, then activates it; retain retired
keys until their outstanding grants expire. Service-generated keys survive only
with the service database. No live operation reissues existing grants or rotates
a shared client token across hosts.

### Relay installation and reload boundaries

The family `relay-server` role accepts the plugin wheel, hash-pinned runtime
requirements and configuration as operator inputs; it does not fetch or build
them. The native installer checks candidate configuration before publication,
uses a protected root-owned configuration (0640 under a protected 0750
directory) and a dedicated nonroot service identity with no login or extra
groups, and selects immutable fingerprinted program releases. A changed
program restarts the plugin; a configuration-only change reloads the same
program. The plugin keeps its listener bound across reload, so a native listener
change requires explicit drained maintenance and coordinated reinstallation.
Changes to frps version or configuration also require draining because frps
restart interrupts its sessions. These are operator deployment boundaries; the
service cannot prove a relay has admission configured. The [validation
runbook](../../../docs/development/VALIDATION_RUNBOOK.md#28-prepare-and-operate-buyer-relays)
contains the installation and deployed refusal procedures.

### Relay sharing and containment

A relay is shared routing state, not pool configuration. One host client has one
rendezvous and token, so pools on that host cannot choose independent relay
baselines. A shared relay can separate provisioning authorities with
nonoverlapping issuer ranges and keys, but still shares its token and sessions;
one operator's frps restart affects every user. A separate relay per operator
is recommended. For a compromised signing key, remove it immediately and deny
its next reconnects, or retain it until its leases end with the signing risk
limited to its issuer. A leaked client token requires stopping admission,
draining every lease sharing it, then rotating the token and host baselines.

If teardown cannot reach the host, a relay operator must block the leased port
and end established sockets in the relay namespace; where firewall control is
unavailable, removing the port from `allowPorts` and restarting frps interrupts
the shared relay. Keep containment until expiry and registration removal are
verified. Relay containment closes the route only; reclaim still needs host
activity termination and verified cleanup.

### Rebinding requires draining

A host's relay binding cannot change while any affected lease remains active.
The host authority composes the compute-family relay mechanism's pool-change
check; it refuses a relay-changing move while relay leases exist. Disablement
stops new scheduling but leaves existing leases to drain before rebinding.

## Bounded bare-metal working data

Bounded cleanup is an opt-in bare-metal policy; legacy key-removal, account-lock
and home-deletion policies keep their existing semantics. Trusted deployment
configuration selects the bounded policy and its identifier before grant, and
the accepted reservation carries that selection through reclaim. Buyer input
cannot select the UID, group, paths, or policy. Existing unreceipted accounts
and grants cannot be adopted into it.

A root-only host helper and protected host-local ledger own identity history.
The helper durably consumes a fresh UID/private primary GID pair before either
account object is created, retains consumption for the policy lifetime, and
returns the recorded numeric identity for cleanup even after NSS no longer
names the account. Retries of the same reservation reuse its receipt; another
reservation never reuses consumed IDs. Service database restore, image
redeployment and campaign reset preserve this ledger. A valid older ledger copy
cannot detect its own rollback, so known or suspected rollback requires host
quarantine until history is verified or the host is decommissioned.

The policy's protected home, scratch and path-backed IPC roots define the whole
deletion boundary. The helper binds root identity, device, inode and Linux mount
identity; it walks without following symlinks or mounts, rejects root/policy
aliases and overlap, and refuses foreign descendants, identity drift, unreadable
inventories or mutation races instead of broadening cleanup. A selected entry's
containing directory and ancestors must be controlled by trusted root or the
quiesced tenant; a foreign-owned ancestor or group/other-writable directory
without the sticky bit refuses cleanup. Effective POSIX ACL write masks are
reflected in those mode bits. The helper retains the checked descriptor during
removal and rechecks parent authority, so a concurrent replacement is a refusal. It removes only
attributable entries inside selected roots. System V IPC uses owner and creator
identity together, rechecks the object before removal, and verifies inventory
afterwards; a recycled numeric kernel object ID alone is not attribution.
Data outside covered roots is not deleted. Copies transferred to another UID
and hard-linked copies outside those roots remain outside this policy.

Reclaim removes the buyer proxy and revokes the bounded key through fixed-path,
descriptor-safe helper operations before the existing activity barrier. The
barrier verifies sessions and scheduled activity have ended; the helper separately
checks that no process retains the numeric UID. It then cleans attributable
scratch and IPC and validates the home. The role deletes the account without
recursive home removal, calls the helper's descriptor-verified `remove-home`,
removes only the receipted unused private group, then calls `verify-complete` to
independently verify absence and record completion. A refused step fails
teardown and keeps capacity held; retry re-reads the receipt and remaining
state. Grant operations accept only a `reserved` receipt: once `clean` marks it
`cleaned`, the account may already be deleted, so a grant that starts after
cleanup is refused rather than recreating the account and its key while
teardown is unproven. The helper's lock covers one call, not a grant's several
role steps; a grant already past `reserve` when cleanup starts is refused at
`verify-identity` or `install-key`, so no key is installed and reclaim's retry
recovers. The SSH key helper pins the home and `.ssh` through no-follow descriptors
and replaces or removes only the validated `authorized_keys` entry, avoiding
path traversal through tenant symlinks. This bounded key path does not change the
legacy policy's behavior. Neither policy promises erasure of transferred data,
external links or data outside the declared boundary.
