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

The executor-neutral composition root lets generic services dispatch by recorded executor or provider identity without importing a concrete domain implementation.

## Registration boundary

Adapters register executor actions and FulfillmentProviders explicitly. Duplicate identities fail during startup because silent replacement would make persisted records execute under a different implementation. Provider and executor registration remain independent: fulfillment create/status/teardown and lease-release actions have different contracts and may evolve separately.

## Durable jobs, transient workers

A persisted job gives accepted work a durable identity, status, request snapshot, result, and diagnostic history. The in-process queue is only the execution mechanism. It does not become the database, retry authority, or provider policy engine.

This distinction makes accepted work observable while avoiding false recovery promises. A process restart does not by itself prove that every queued or running action is safely resumed; recovery must be explicit where required.

## Selected-resource execution

Concrete providers operate on the Settlement Resource selected by fulfillment scheduling. The VM Ansible adapter resolves pool/provider configuration, validates it, and snapshots prepared inputs at dispatch. Administrative pool edits therefore affect later operations rather than rewriting the accepted execution.

Operational inventory is authoritative service state, not a checked-in Ansible inventory. Bootstrap inventory may import hosts, and an adapter may render transient execution inventory, but operator mutations and job-history references remain tied to persisted resources.

### Bare-metal storefront pull boundary

The bare-metal storefront is a client of the accepted POOLS-7 scheduling and fulfillment contracts, not a second job repository or convergence worker. It derives one `SettlementResource` request from the immutable accepted listing/site/Physical Resource and agreed bare-metal terms, submits it to the provisioning authority bound to that site, and persists only returned reservation, settlement-resource, and fulfillment correlations.

The scheduler's recorded resource kind, provider, and executor selection remain authoritative for begin, status, result, and teardown. The storefront never substitutes a process-global provisioner, buyer-supplied URL, or guessed adapter. It pulls normalized status and the versioned result envelope through the same recorded site client after restart; provisioning remains the authority for jobs, provider metadata, execution credentials, and teardown convergence.

## Proof-driven release

Release is proof-driven and split across two cooperating owners. Lease lifecycle decides when a reservation should release and owns the final capacity-return decision; it never dispatches a second teardown operation. Fulfillment convergence (see `openspec/specs/fulfillment/spec.md#fulfillment-convergence-worker`) owns teardown dispatch, provider polling, and recovery through `torn_down`/`teardown_failed`. A kind-routed `ReleaseJobPort` connects the two: VM-backed reservations resolve release status by reading the fulfillment aggregate's teardown state; other executor kinds continue reading the shared job queue. The site authority releases capacity only after the fulfillment aggregate reaches `torn_down`, or an operator explicitly force-releases. Failure retains the reservation and records a retryable release state (`teardown_failed`), which convergence requeues on its own without an operator prompting it. An explicit force release is an operator override with distinct audit meaning, not fabricated proof of executor success.

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
