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

### Hosted funding and public lease evidence

For a hosted obligation, the storefront invokes the selected-site reservation and fulfillment ports only after the shared route service reports authoritative `funded`. The accepted binding fixes site, resource constraint, buyer, seller/claimant, access mode, deadline, and deterministic fulfillment identity. Equivalent retries resume the same reservation and job; a conflicting site, resource, or result fails closed. A buyer-safe physical result exists only after committed capacity, a live lease, and authoritative access-ready state agree. Its content-addressed evidence binds the accepted agreement/obligation and physical references without credentials, provider data, unrestricted topology, or an SSH private key.

Financial return before collection blocks further collection and starts convergent physical cleanup; post-collection loss is an incident and never releases capacity. Lease expiry and revocation call the same provisioning-owned teardown convergence. Capacity remains quarantined until authoritative teardown and release, independently of hosted reclaim status.

## Proof-driven release

Release is proof-driven and split across two cooperating owners. Lease lifecycle decides when a reservation should release and owns the final capacity-return decision; it never dispatches a second teardown operation. Fulfillment convergence (see `openspec/specs/fulfillment/spec.md#fulfillment-convergence-worker`) owns teardown dispatch, provider polling, and recovery through `torn_down`/`teardown_failed`. A kind-routed `ReleaseJobPort` connects the two: VM-backed reservations resolve release status by reading the fulfillment aggregate's teardown state; other offering modes continue reading the shared job queue. The site authority releases capacity only after the fulfillment aggregate reaches `torn_down`, or an operator explicitly force-releases. Failure retains the reservation and records a retryable release state (`teardown_failed`), which convergence requeues on its own without an operator prompting it. An explicit force release is an operator override with distinct audit meaning, not fabricated proof of executor success.

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

The port renders explicitly even at its default, so an inventory line states
what the registry holds rather than leaving the default implied by an absent
one. A malformed port fails its entry rather than degrading to a default: an
unreachable host is not a degraded host, and a substituted value turns an
operator's typo into a failure that resembles a network fault.

A bare-metal host's tenant-facing endpoint is recorded separately from the
management endpoint because the two answer different questions: the management
endpoint is how the provisioner reaches the host, and the tenant endpoint is what
a buyer is told. A host serving both from one endpoint falls back to the
management values rather than publishing a second, invented endpoint.

## Pinned access to the selected host

A bare-metal access action is privileged execution on a machine the provider does
not otherwise touch, so it is pinned twice: the host key must match the
operator-supplied pin file for the selected management endpoint, and the
connection must reach that endpoint rather than another host the same file
happens to pin. Reaching *a* pinned host is not the same as reaching *the*
selected one, and only the second makes the action safe to perform.

Expressing this as a preference would not hold. The automation layer resolves
connection settings from several sources of differing precedence, and OpenSSH
honours the first value given for an option, so the enforced settings are
supplied from the highest-precedence source and placed ahead of anything an
inventory or an inherited environment can add. The connection plugin, its
client executables and the destination are fixed for the same reason: trust
expressed as OpenSSH options constrains nothing if another transport is chosen,
a different binary is executed, or the connection is aimed elsewhere. A
legitimate operator proxy route to the selected endpoint still applies, because
it describes how that endpoint is reached rather than which endpoint it is.

Deletion of a lease account is confirmed by reading the host's own account
database rather than by a name-service lookup, whose unsuccessful result cannot
distinguish an absent account from an unavailable backend. That read certifies
the current database only. A snapshot ending after a complete record is
indistinguishable from one that legitimately ends there, so it establishes that
the account is absent now, not that the host's other accounts were preserved;
preservation rests on the action mutating only the named account.

## Lease-storage custody has one live owner

The storage-preparation seam treats a TPM resource handle as authority only
inside the ESAPI connection that returned it. Creation, policy evaluation,
load, public verification, unseal and checked cleanup therefore stay in one
process lifetime. This avoids composing several command processes around a
saved or observed number whose resource may already have disappeared or whose
number may have been reassigned to another TPM owner. Cleanup names only
resources returned to the live executor; there is no inventory-wide flush or
resource-difference inference.

The durable recovery boundary is the verified parent identity, counter policy,
sealed public/private blobs and fsynced manifest, not a runtime context or
numeric handle. The manifest records ownership before each creation or load and
records close-pending before cleanup. If the process ends before confirmed
closure is durable, a later process cannot distinguish a remaining orphan from
a handle that has been reused. It quarantines without attempting stale cleanup
or repeating the counter mutation. This deliberately prefers an unavailable
host to deleting a resource another TPM user may now own.

The provider supervision seam accepts a canonical, content-addressed request
without secret material and dispatches the helper from a non-restarting
systemd oneshot. Its fixed profile selects the request root, state root,
qualified cryptsetup path and version, and qualified direct TPM device. The
unit is explicitly placed in `system.slice`, matching the exact cgroup the
executor admits. Both the unit directives and the executor's live
cgroup/resource-limit checks participate in the boundary: rendering a directive
does not prove that the running process received it. A zero hard core-size
limit is inherited across fork and exec and cannot be raised by descendants,
but it does not constrain a piped kernel core handler. The executor therefore
reads the effective policy from the fixed procfs location and refuses before
backend loading when the policy is missing, unreadable, malformed or piped.
It does not alter the host policy or rely on no-new-privileges or filesystem
restrictions to contain a handler. A durable `running` record
is deliberately one-way on abnormal exit; the next invocation quarantines
instead of treating a new process or a reused TPM handle as continuation.
Systemd owns the whole process cgroup, so stopping the unit covers descendants
rather than only the main process.

The implementation remains a controlled preparation and qualification seam.
The host role does not install or activate these artifacts, and its ordinary
prepare action still refuses before state or key creation while persistent-path,
mapping, mount and reboot-recovery prerequisites are absent. Access grant also
remains refused. A disposable systemd 249 run of the synthetic storage unit
established inherited zero hard and soft core limits and manager-owned removal
of a sleeping child after its main process exited. A separate disposable-guest
run composed the real request submission, systemd unit, live runtime admission,
storage helper and same-process ESAPI custody against a private software TPM and
a regular-file LUKS target. It completed preparation and prepared retry,
preserved durable foreign TPM sentinels, refused mismatched runtime controls
before custody, and quarantined abrupt execution. The qualification transport
and storage target were test-only. The bounded native-guest qualification
establishes the narrower downstream prerequisite for an owned synthetic
fixture: explicit loop attachment, device-mapper open, fixed ext4 formatting,
native PID 1 mount, identity readback and checked reverse cleanup. It also
establishes its selected denial paths, while controlled tests separately cover
mapper-timeout and cleanup-mismatch quarantine. The profile retains
`CAP_SYS_ADMIN` and device-mapper class access. Those controls are broader than
mapping-specific authority; no ioctl allowlist or tracing was established. The
result therefore does not establish a production activation producer,
consumption of the prepared TPM-sealed secret, provider-device preservation,
active-lease reboot recovery, release, or physical-host qualification.

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
