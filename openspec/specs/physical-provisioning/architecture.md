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

The resource-pool projection a site serves is neutral, and a domain that publishes more — a view of a whole machine it sells, or a pool's configured defaults — contributes an `InventoryViewProjection` from `compute_provisioning.inventory_views`, which owns the protocol and its composer. The service merges what each projection returns and never names a domain's view, attribute, or provider configuration. A resource view is built with its pool's context, an `InventoryPoolContext` of pool ID, provider, and the pool's resolved declarations, because what a view may carry depends on them: a bare-metal view carries its delivery terms only where the pool's backing delegate passes them through (see the [resource-pool management architecture](../resource-pool-management/architecture.md#advertisement-delivery-and-backing)). The provisioning service, as the composition root, reads the pool rows in its own resource pass, resolves each pool once through the shared resolver, and hands each declaration its pool's context, interpreting none of it; the pool pass reads raw tags and the provider from the same column, so the two passes cannot drift on a pool's provider. A stored pool whose declarations do not resolve, which startup refuses and no write path produces, gives its members no context, so they project with no views and no problems, and the service logs a warning. Building the context is compute-family work, so it sits at the contributed-view seam and nothing above the compute family learns of it: `kit/site` copies the per-resource result into its projection without reading it, and `kit/resource-pools` and core do not see it.

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

Operational inventory is authoritative service state, not a checked-in Ansible inventory. Bootstrap inventory may import hosts, and an adapter may render transient execution inventory, but operator mutations and job-history references remain tied to persisted resources.

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
proposal, amount/duration, selected chain and exact obligation index. Local
materialization is adoption history, not current chain authority.

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

Beside the provisioner's route, a connection may name the route a buyer takes:
a tenant-facing `public_host` and `public_port`, each falling back to the
connection's own address and port. A bare-metal buyer's endpoint is that route.
A VM guest is reached at its own forwarded or relayed port, never the host's
`public_port`.

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

## Buyer access to rented VMs

A host participating in this system holds two reverse tunnels, and they are
routinely confused. The **management tunnel** is the operator's path to the host
itself: static for a whole provisioning service, established when the host is
prepared outside this repository, and never written or restarted by a VM
operation. The **VM tunnel** carries buyer access to rented VMs, with one proxy
per VM added and removed continuously. They cannot share a process — a tunnel
client carries exactly one rendezvous address and one admission token at the top
level, and a proxy cannot override either — so two clients follow as a
consequence rather than as a choice. Only the second is modelled here.

### A relay's management surface is not a coordination interface

Discovering a free port by querying the relay's dashboard makes a monitoring
surface into a distributed lock, and requires every relay to run one, publish a
DNS name for it, hold a certificate, and distribute a second credential. Port
allocation belongs to an authority that can also reclaim what it issued, and
proxy verification belongs to the client that registered the proxy: asking the
relay whether our own registration succeeded is a round trip to a third party
about our own state.

### Buyer access is port-based

A buyer receives a host and a port. Subdomain routing cannot serve SSH: FRP's
`subdomain` option belongs to its `http` and `https` proxy types, which
demultiplex on the `Host` header, while SSH sends no SNI and no `Host` header
and exchanges version banners immediately on connect. A `tcp` proxy binds a
distinct port whatever the key says, so the wildcard DNS record and certificate
that subdomain routing implies serve nothing.

### The relay token never reaches buyer-controlled hardware

The tunnel client runs on the host rather than inside the VM. A buyer has root
in their VM and would therefore hold the token, and a relay's `allowPorts` spans
the management window as well as the VM window — so a buyer holding a token
could bind a management port freed by a dropped tunnel and answer, as that host,
the connections the provisioning service makes to administer it. Per-VM or
per-host tokens do not address this: the relay still admits the holder to
whatever `allowPorts` permits. The property worth holding is that the token
never lands on buyer-controlled hardware at all.

### A relay is a resource, not pool configuration

A relay's address, allocation window, and admission token are shared by every
pool that points at it. Held per pool they can diverge: two pools referencing
one rendezvous would allocate from a single listening namespace under
disagreeing bounds, and each would hold its own copy of one credential, making
rotation one write per pool with a missed one failing asynchronously in a tunnel
client's log.

Relay uniformity across a host is a limit of running one VM tunnel client per
host, not a limit of the model. A lease records its relay, so a per-VM relay is
already representable; what forbids it is that one client dials one rendezvous.
A topology of one client per VM would remove the limit without a schema change.

### Rebinding requires draining

A VM's relay is fixed for its life. The buyer holds an address and a port, both
delivered, and a remote port is not portable between relays — a port number on
one rendezvous says nothing about the same number on another, which may already
be leased. Moving an existing VM would strand its buyer and request a port the
new relay may not have free. So a relay binding changes only while no affected
host holds a lease, and disabling a pool — already a draining operation that
excludes new scheduling without disturbing running workloads — is how an
operator reaches that state.
