## RENAMED Requirements

- FROM: `### Requirement: A relay binding is fixed for a VM's life`
- TO: `### Requirement: A relay binding is fixed for a lease's life`

## MODIFIED Requirements

### Requirement: Relays are administered resources

A relay is a durable resource, not pool configuration. The provisioning service MUST record each relay's rendezvous address, rendezvous port, port allocation window, admission token, and grant-signing key as one row, and resource pools MUST reference a relay rather than restating its address, window, token, or key.

A relay's rendezvous address and port taken together MUST be unique, so that one rendezvous cannot be recorded twice under different identities. Because a `tcp` proxy's remote port binds a listening socket on the relay itself, two pools referencing one relay draw from a single port namespace; recording the window on the relay is what prevents two pools from allocating within that namespace under different bounds.

A relay MUST be creatable, readable, and updatable through the provisioning API without redeploying the service, so that adding a rendezvous is an operator action against a running system.

#### Scenario: Two pools reference one relay

- **WHEN** two resource pools reference the same relay
- **THEN** both draw allocations from that relay's single recorded window, and neither pool can configure a different window for it

#### Scenario: A duplicate rendezvous is recorded

- **WHEN** a relay is created with an address and port already recorded by another relay
- **THEN** the request is rejected rather than creating a second identity for one rendezvous

#### Scenario: A relay moves to a new address

- **WHEN** a relay's recorded address is updated
- **THEN** every port lease held against that relay remains associated with it, rather than becoming unreferenced

#### Scenario: A relay is added after deployment

- **WHEN** an operator creates a relay through the API against a running service
- **THEN** a pool may reference it and allocate against it without the service being redeployed

### Requirement: A relay binding is fixed for a lease's life

The relay a delivery reaches its buyer through MUST be recorded on its port lease at allocation, and that record — not the pool's current configuration — MUST be the authority for which relay that delivery uses, for a VM guest and a bare-metal grant alike. Teardown, reclaim, and reconciliation MUST read the lease. Resolving the relay from pool configuration at teardown would target the wrong relay after any rebinding, releasing a port that was never bound there and leaving bound the one that was.

A pool's relay reference determines which relay a newly created delivery receives. It MUST NOT change the relay of a delivery that already exists.

A host's pool assignment, a pool's relay reference, and a relay's address or port MUST NOT change while any affected host holds an active lease, unless the relay is the same on both sides of the change. The buyer holds a rendezvous address and a port; both are delivered, and a remote port is not portable between relays, so a rebinding that moved existing deliveries would strand every buyer on the affected hosts and request ports the new relay may already have leased.

Rebinding is therefore drain-then-change: disabling a pool already excludes it from new scheduling without invalidating existing workloads, so an operator disables, waits for leases to clear, rebinds, and re-enables.

#### Scenario: A pool's relay reference is changed while VMs are running

- **WHEN** an operator changes a pool's relay reference and a host in that pool holds an active lease
- **THEN** the change is rejected, naming the host and the lease it holds

#### Scenario: A bare-metal pool's relay reference is changed during a lease

- **WHEN** an operator changes the relay reference of a bare-metal pool whose host holds an active grant's lease
- **THEN** the change is rejected, naming the host and the lease it holds

#### Scenario: A pool's relay reference is changed after draining

- **WHEN** the same change is made once no host in the pool holds an active lease
- **THEN** it is accepted, and subsequently created deliveries are allocated on the new relay

#### Scenario: A host moves between pools sharing one relay

- **WHEN** a host is reassigned to a pool referencing the same relay as its current pool, whichever provider each pool uses
- **THEN** the move is accepted regardless of active leases, because no delivered connection string changes

#### Scenario: A relay is repointed while it carries leases

- **WHEN** a relay's address or port is updated and it holds an active lease
- **THEN** the update is rejected

#### Scenario: A VM is torn down after its pool was rebound

- **WHEN** teardown or reclaim runs for a delivery whose pool now references a different relay
- **THEN** the relay recorded on the delivery's lease is used, and the port is released against it

### Requirement: Relay port leases are unique per relay

The provisioning service MUST allocate a delivery's relay port from the referenced relay's window before dispatch, record the allocation against that relay, the host, and the owning reservation, and pass the port to the job as an input. The playbook MUST apply the port it is given and MUST NOT select one.

Fulfillment preparation MUST allocate through the acceptance transaction's
session. The port lease, accepted fulfillment, and prepared operation MUST commit
or roll back together. It MUST NOT allocate through an independent write
transaction while acceptance is open. Standalone allocation remains available to
callers that own no acceptance transaction.

A port lease MUST be unique on the relay and the remote port. The host is recorded as an attribute of the lease and MUST NOT form part of its uniqueness, because the listening socket is bound on the relay rather than on the host, and two hosts sharing a relay share one port namespace.

Only released lease rows may be reused, and a released port MUST NOT be reissued until the expiry of the grant signed for its last lease plus the configured reuse margin has passed, so that a copied grant cannot register a port another host now holds. The margin MUST be read when a port is selected, so that a changed margin applies to leases already released. A relay checks a grant's expiry on its own clock with no leeway, so the relay's and the provisioning service's clocks MUST be kept synchronised, with skew below the margin. A stale free-port observation MUST NOT reassign an active lease; allocation MUST retry a conflicting claim without rolling back other writes in the caller's transaction.

A lease MUST be released with its reservation's capacity, in the transaction that releases it, whatever path releases it, and MUST NOT be released on a fulfillment state alone. A failed creation may leave a guest running with its tunnel bound, so its port is held with its capacity: until a compensating teardown reaches `torn_down` and the capacity is released, or until an operator verifies the host and forces the release. A periodic reconciliation MUST release leases whose reservation has been released beyond a grace period, as a backstop rather than as the primary mechanism.

Allocation MUST be idempotent for one owner: allocating twice for the same fulfillment MUST return the lease already held rather than issuing a second port.

A pool whose referenced relay has no usable allocation window MUST be rejected before dispatch rather than producing a delivery with no external route.

#### Scenario: Two hosts share a relay

- **WHEN** a port is leased for a delivery on one host and a delivery on a second host requests an allocation from the same relay
- **THEN** the second allocation selects a different port, rather than reissuing a port already bound on that relay

#### Scenario: A VM creation fails before teardown would run

- **WHEN** a VM's fulfillment fails, including after its provider reported the create succeeded
- **THEN** its port lease is held with its capacity, and is released only in the transaction that releases that capacity, after a compensating teardown or an operator's forced release

#### Scenario: A release path is missed

- **WHEN** a lease's reservation has been released beyond the grace period and the lease is still held
- **THEN** reconciliation releases it

#### Scenario: An accepted fulfillment allocates twice

- **WHEN** allocation runs a second time for a fulfillment that already holds an active lease
- **THEN** the existing lease is returned and no second port is issued

#### Scenario: Validation is requested

- **WHEN** a fulfillment request is validated rather than accepted
- **THEN** no port is leased and no durable state is written

#### Scenario: Preparation rejects after leasing a port

- **WHEN** fulfillment preparation leases a relay port and a later check rejects the request
- **THEN** no port lease, accepted fulfillment, or prepared operation is committed
- **AND** a corrected request may be accepted without an orphaned port

#### Scenario: A stale scan names an occupied port

- **WHEN** allocation attempts to claim a port another owner already holds
- **THEN** that owner's lease remains intact and allocation selects another free port
- **AND** the caller's other pending writes remain committable

#### Scenario: A relay is configured with no usable window

- **WHEN** a fulfillment is requested against a pool whose relay has no usable allocation window
- **THEN** the request is rejected before dispatch rather than creating a delivery with no route

#### Scenario: A lease is cut short

- **WHEN** a lease ends before its scheduled end and its port is released
- **THEN** the port is not issued to another lease until the released lease's grant expiry plus the reuse margin has passed, and allocation meanwhile selects another free port

#### Scenario: The reuse margin is raised

- **WHEN** the reuse margin is raised after a lease was released
- **THEN** that lease's port is held until its grant expiry plus the raised margin

### Requirement: A bare-metal reclaim tolerates an account its grant never created

A bare-metal reclaim MUST succeed, reporting the tenant account absent, when the tenant
account it names does not exist on the host, whatever its reclaim policy, and MUST NOT
create the account. Where the account exists it MUST remove the lease's key, end the
account's activity as "A bare-metal reclaim ends the tenant's activity" requires, and
then keep, lock, or delete the account as its policy says.

#### Scenario: A grant failed before creating its account

- **WHEN** a compensating teardown reclaims access for a grant whose tenant account was never created
- **THEN** the reclaim succeeds reporting the account absent, and no account is created

#### Scenario: A grant created its account and installed its key

- **WHEN** a reclaim under the default policy runs for an account holding the lease's key
- **THEN** that key is removed, the account's activity ends, and the account and its files otherwise remain

### Requirement: Bare-metal inventory binds an existing provider pool

The compute provisioner MUST import configured Resource Pool definitions before
seeding inventory. A bare-metal inventory host MAY name its exact pool through
`pool_id`; the seed MUST reject an unknown pool and MUST preserve that binding
on create and update. A capacity declaration's explicit `bare_metal_publication`
view MUST carry the declaration's own pool. The `bare_metal.ansible` provider accepts no pool-local
playbook, inventory-group, credential, or executor-target configuration; the one
field its pool configuration accepts is `relay_id`, the compute family's relay
reference: execution uses service-owned configuration and the scheduler-selected Physical
Resource, and a bare-metal job's stored parameters carry the service's
`bare_metal_playbook_path` as configured when the job is prepared. The operator MUST register that Physical Resource and its explicit
`bare_metal_publication` view through the authenticated capacity administration
surface before the host is publishable.

#### Scenario: Fresh selected-site inventory binds to a bare-metal pool

- **WHEN** startup imports a `bare_metal.ansible` pool and then seeds a host whose inventory row names that pool
- **THEN** the durable host row retains the exact pool id and an unknown pool id fails the seed rather than leaving the host unplaced or assigning another pool

#### Scenario: Publication retains the inventory pool binding

- **GIVEN** a bare-metal inventory host is bound to a configured provider pool
- **AND** the capacity declaration naming that host is in the same pool
- **WHEN** the compute service projects its explicit `bare_metal_publication` view
- **THEN** the view's `pool_id` is that pool, taken from the declaration

#### Scenario: Publication carries the declaration's pool

- **GIVEN** a capacity declaration with an enabled `bare_metal_publication` in a configured provider pool
- **WHEN** the compute service projects its explicit `bare_metal_publication` view
- **THEN** the view's `pool_id` is the declaration's pool

#### Scenario: Pool-local executor configuration is supplied

- **WHEN** a `bare_metal.ansible` pool's `provider_config` contains any field other than `relay_id`
- **THEN** validation rejects the pool before it can authorize or dispatch fulfillment

#### Scenario: The bare-metal playbook setting changes after a grant is prepared

- **WHEN** `bare_metal_playbook_path` changes after a grant or reclaim job is prepared
- **THEN** the job runs the playbook its stored parameters carry, and a job prepared afterwards carries the new one

## ADDED Requirements

### Requirement: Provider variables preserve relay role authority

Provider extra variables MUST NOT replace the accepted proxy action, exact proxy
identity, local or remote target, or runtime client and helper selection. VM
preparation and execution MUST reject these names even when a direct job emits
no relay input, and execution MUST recheck stored provider variables. Bare-metal
preparation and execution MUST continue refusing undeclared provider variables.
Operator inventory and host-preparation configuration remain available outside
provider extras; raw operator Ansible invocation retains Ansible's precedence.

#### Scenario: A provider attempts to redirect a proxy

- **WHEN** provider extras name a proxy operation, identity, endpoint, or runtime client control
- **THEN** preparation rejects acceptance and stored malicious extras are refused before Ansible execution

#### Scenario: A direct job receives relay inputs through provider extras

- **WHEN** provider extras attempt to introduce a relay target or cleanup operation into a direct job
- **THEN** the extras are refused rather than changing the accepted access mode


### Requirement: Relay machinery belongs to the compute family

Relays, their port leases, allocation, release, reconciliation, administration, definition import, rebinding refusals, grant signing, and execution-time resolution MUST be owned by the compute family kit, not by any one domain, and every domain whose deliveries a relay carries MUST use that one implementation. A pool's relay reference MUST be stored once for every provider. Every provider whose deliveries may use a relay MUST accept the reference as `provider_config.relay_id` and write it through the family's reference, so that the rebinding rule applies to every pool alike. The provisioning service MUST register the release effect, the reconciliation worker, and the relay definitions document once, for every domain.

#### Scenario: A bare-metal pool references a relay

- **WHEN** an operator writes a bare-metal pool with `provider_config.relay_id` naming a relay
- **THEN** the reference is recorded where a VM pool's is, and the same rebinding rule governs it

#### Scenario: A pool names a relay that does not exist

- **WHEN** a pool of either provider is written with a `relay_id` no relay has
- **THEN** the write is rejected naming the relay, and no reference is recorded

#### Scenario: VM and bare-metal deliveries share a relay

- **WHEN** a VM pool and a bare-metal pool reference one relay and each allocates a port
- **THEN** both allocations come from the relay's one window through one allocator, and never collide

### Requirement: A bare-metal grant on a relay-backed pool delivers a leased port

A bare-metal grant on a pool referencing a relay MUST lease a port from the relay's window, add one proxy from the host's `127.0.0.1:22` to that port in the host's buyer-facing tunnel client, and deliver the relay's address, the leased port, and the tenant account. A reclaim MUST remove that proxy, and the port MUST be released with the reservation's capacity. Neither MUST read, write, or restart the host's management tunnel client. A bare-metal grant on a pool with no relay MUST deliver the host's buyer route as it does without relays: its `public_host` and `public_port`, each falling back to its connection's own.

#### Scenario: A relayed grant succeeds

- **WHEN** a grant runs for a bare-metal host whose pool references a relay
- **THEN** the delivered access is `ssh -p <leased port> <tenant>@<relay address>`, and the proxy is registered with the relay

#### Scenario: A relayed lease is reclaimed

- **WHEN** the reclaim for that grant succeeds and the lease's capacity is released
- **THEN** the proxy is gone from the host's buyer-facing client, the delivered access no longer connects, and the port's lease is released

### Requirement: Every relay proxy carries a signed grant

Every proxy the buyer-facing tunnel client registers MUST carry, in its own metadata, a grant the provisioning service signed with the relay's active grant-signing key, conforming to the grant specification the relay admission plugin publishes: an EdDSA JWT of type `frp-grant+jwt` whose key identifier is the signing key's RFC 7638 thumbprint, naming the relay as its audience, the leased port, an expiry no earlier than the lease's scheduled end plus a grace period, as a JSON integer of seconds equal to the grant expiry recorded on the lease, the host as its subject when the lease records one, and the lease's owning reservation as its identifier, the subject and identifier each a string, with a header of exactly `alg`, `kid`, and `typ`, and its header and claims serialized as RFC 8785 JSON. The grant MUST NOT carry an issued-at or not-before time, which a relay whose clock lags the service's would refuse. The grant MUST be signed immediately before the job's variables are written, on every attempt of the job, and MUST NOT be written into an accepted operation's persisted parameters. Neither the grant, the relay's admission token, nor the buyer-facing client's admin password MUST appear in a job read, its logs, its error, or its result: every playbook task that renders, writes, sends, or reads one of them MUST set `no_log`, and every codec whose jobs carry them MUST name their variables among the secret fields the executor redacts. The lease MUST record the grant's expiry and the identifier of the key that signed its latest grant.

#### Scenario: A relayed create is executed

- **WHEN** a create or grant job runs for a delivery holding a relay port lease
- **THEN** its proxy carries a grant for exactly that relay and port, signed with the relay's active key, and the job's persisted parameters carry no grant

#### Scenario: A relayed job's lease records no host

- **WHEN** a grant is signed for a lease that records no host
- **THEN** the grant carries no subject, its identifier is the lease's owning reservation as a string, and its expiry is an integer

#### Scenario: A port is leased again after quarantine

- **WHEN** a released port is leased to another reservation and a grant is signed for it
- **THEN** the grant's identifier is the new reservation, not the one the port's previous grant named

#### Scenario: The signer is checked against the plugin's vector

- **WHEN** the family signer signs each signing case of the plugin's published test vector with the case's key, header, and claims, and derives the key identifier of its thumbprint case
- **THEN** it produces exactly each case's token and identifier

#### Scenario: A key is rotated between acceptance and execution

- **WHEN** a relay's grant key is activated after a job is accepted and before it executes
- **THEN** the job's grant is signed with the newly active key

#### Scenario: A relayed job succeeds

- **WHEN** a relayed create or grant job succeeds and its job is read
- **THEN** the read's logs and result contain neither the grant, the relay token, nor the host's admin password

#### Scenario: A relayed job fails after writing its proxy

- **WHEN** a relayed create or grant job fails after its proxy block is written, and its job is read
- **THEN** the read's logs and error contain neither the grant, the relay token, nor the host's admin password

### Requirement: Each relay holds its own grant-signing key

Each relay MUST hold its own Ed25519 grant-signing private key, encrypted at rest under the deployment's configured encryption key. A relay definition entry MUST name the secrets-profile key holding it, read only when the relay is created; a relay created through the API with no key MUST be given one the service generates. A profile key's value MUST be the single-line standard base64 of an Ed25519 key's PKCS#8 DER, read after stripping surrounding whitespace; a value that is not MUST fail the import before any relay is created, naming the relay and the profile key and not disclosing the value. A key's identifier MUST be its RFC 7638 JWK thumbprint, the identifier the admission plugin derives from the public key. No read path MUST return a private key: relay reads MUST return the active key's identifier and public half, any staged key's, and each retired key's identifier with the time its grants remain valid until, each public half as the single-line base64 of its DER SubjectPublicKeyInfo, the form the plugin's configuration takes. Rotation MUST be two explicit operations: staging takes a private key supplied in the request, in the profile's form and under the same checks, or generates one when none is supplied, and returns its public half without signing with it; activating makes the staged key sign every later grant. A supplied private key MUST NOT appear in an access log, an error body, or the response. A retired key's grants MUST be reported valid until the latest grant expiry among the relay's unreleased leases allocated before the key was retired, since a lease whose job was retried across a rotation may hold grants signed by more than one key.

#### Scenario: A relay is read

- **WHEN** a relay is retrieved through the API
- **THEN** the response carries its active key's thumbprint and its public key as base64 SubjectPublicKeyInfo, and no private key material

#### Scenario: A key is staged

- **WHEN** an operator stages a new grant key for a relay
- **THEN** the service returns the new public key, and grants continue to be signed with the active key until the staged one is activated

#### Scenario: A job is retried across a rotation

- **WHEN** a job's attempt installs a grant signed with key A, key B is then activated, and a retry of the job signs its grant with B
- **THEN** the relay read reports A's grants valid until that lease is released or its grant expires, whichever is first

#### Scenario: A definition entry names a malformed grant key

- **WHEN** the profile key a relay definition entry names holds a value that is not base64 PKCS#8 DER of an Ed25519 key, apart from surrounding whitespace
- **THEN** the import fails naming the relay and the profile key, without the value, and no relay is created

#### Scenario: A supplied key is staged

- **WHEN** an operator stages a private key supplied in the request
- **THEN** the response carries that key's public half and thumbprint, and neither the response, an error body, nor an access log carries the private key

#### Scenario: A definition entry names no grant key

- **WHEN** a relay definition entry names no grant-key profile key
- **THEN** the import fails naming the entry, and no relay is created without a key

### Requirement: A relay without an active grant key is refused before dispatch

Fulfillment preparation MUST refuse a pool whose referenced relay holds no active grant-signing key, naming the relay and what is missing, as it refuses a relay with no admission token. A relay serving buyer access MUST run the admission plugin configured with an issuer for the relay — its audience, a port range containing the relay's window, and the relay's public keys; that is the operator's installation, which the service does not observe or verify. The operator's runbook check, an ungranted proxy refused by the deployed relay, is the evidence that a relay enforces admission, run before a relay-backed pool first serves buyers and after any change to the relay's plugin configuration.

#### Scenario: A relay has no active key

- **WHEN** a fulfillment is requested against a pool whose relay holds no active grant key
- **THEN** the request is rejected before dispatch, naming the relay and the missing key

### Requirement: A host's management route does not use its pool's buyer relay

A host MUST NOT be placed in a relay-backed pool when its connection address equals that relay's address, and a relay's address MUST NOT be set to the connection address of a host placed in a pool referencing it. Management proxies carry no grant, and a relay enforcing admission would refuse them; admitting them by a static list would let a token holder bind a dropped host's management port. The comparison is of normalized addresses and does not detect aliases.

#### Scenario: A host reached through the buyer relay is placed

- **WHEN** an operator places a host whose connection address is the address of the relay its new pool references
- **THEN** the placement is refused, naming the host and the relay

### Requirement: Relay holdings are readable by the administrator

The provisioning service MUST serve, to the administrator only, the leases a relay holds: for each, its port, host, owning reservation, release time if released, grant expiry, and signing key identifier. It MUST NOT return any credential.

#### Scenario: A torn-down delivery's port is read

- **WHEN** the administrator reads a relay's holdings after a delivery on it was torn down and its capacity released
- **THEN** that delivery's lease is shown released with its grant's expiry, and no other lease holds its port

### Requirement: The buyer-facing tunnel client is hardened on every host

Host preparation for a VM host and for a bare-metal host MUST install the buyer-facing tunnel client from one shared family role, with its configuration readable only by root, and its admin API bound to a loopback port below 1024 and protected by a password generated for that host at preparation. Every task that reloads the client or reads its status MUST authenticate with that password. The client's configuration belongs to the host, which is sold either as VM slices or as a whole host, never both at once. Adding or removing a proxy MUST reload the client and MUST NOT restart it; the client MUST be restarted only when its relay baseline changes.

#### Scenario: An unauthenticated call reaches the admin API

- **WHEN** a process on the host calls the client's admin API without the host's admin password
- **THEN** the call is refused, and neither the configuration nor the relay token is disclosed

#### Scenario: A bare-metal host is prepared for relay access

- **WHEN** bare-metal host preparation runs with a relay address and admission token
- **THEN** the host runs the buyer-facing client from the same role a VM host uses, with the same protections

### Requirement: Hosts and relays run frp from one verified pin

The buyer-facing tunnel client and a relay's frps MUST be installed from one pinned frp version, the version the admission plugin is tested against, from a release archive whose SHA-256 is pinned beside the version and checked before anything is extracted. Each binary MUST be installed at a path naming its version, and an install MUST be skipped only when that path exists, so that a changed version is installed and a binary placed elsewhere, such as a management client's, is never run in its place or replaced. A version or platform with no pinned digest MUST be refused. The pin MUST equal the version and digest the admission plugin's pins file records.

#### Scenario: A host already holds an frp client binary

- **WHEN** buyer-facing client preparation runs on a host whose management client installed an frp binary at the common path
- **THEN** the pinned archive is downloaded, verified, and installed at its versioned path, the buyer-facing client runs that binary, and the management client's binary is untouched

#### Scenario: A downloaded archive does not match its pin

- **WHEN** the archive's SHA-256 differs from the pinned digest
- **THEN** the install fails and no binary is installed

### Requirement: A relay prepared by the family role runs admission and discloses no secret

Relay preparation MUST install frps with the admission plugin as a plain program from a wheel and hash-pinned requirements it is given, MUST refuse to run without a relay admission token supplied to it, and MUST NOT print, write outside the relay, or return the token or any other credential. It MUST check the plugin's configuration with the plugin before installing it, MUST reload the plugin on a configuration change without restarting frps, and MUST configure frps to consult the plugin for every new proxy.

#### Scenario: Relay preparation runs

- **WHEN** relay preparation runs with a token, the plugin's wheel and requirements, and a valid plugin configuration
- **THEN** frps consults the plugin on `NewProxy`, the plugin runs from the given wheel, and the run's output and the controller's disk carry no token

#### Scenario: An invalid plugin configuration is supplied

- **WHEN** relay preparation is given a plugin configuration the plugin does not load
- **THEN** preparation fails before replacing the running configuration

### Requirement: A bare-metal reclaim ends the tenant's activity

Where the tenant account exists, every reclaim policy MUST, after removing the lease's key, end the account's sessions and lingering, kill its remaining processes, and remove its cron and `at` jobs, before keeping, locking, or deleting the account. A lock or delete that fails, or a process of the account still running afterwards, MUST fail the reclaim rather than be reported as success. The reclaim's fact MUST report what was ended, and remains diagnostic.

#### Scenario: The tenant left a process running

- **WHEN** a reclaim runs for an account with a process still running and a crontab entry
- **THEN** the process is killed, the crontab entry removed, and the reclaim succeeds only once neither remains

#### Scenario: A delete fails

- **WHEN** a reclaim under the `delete_user` policy cannot delete the account
- **THEN** the reclaim fails, and the teardown is not recorded as complete

### Requirement: A relayed create reports its relay under one block

Every variant of a VM create's printed fact MUST report relay access under a block named `relay`, and the VM codec MUST read a relayed create's delivery evidence from that block.

#### Scenario: A relayed create without a buyer key

- **WHEN** a relayed create prints its generated-key variant of the fact
- **THEN** its relay block is read like the buyer-key variant's, and delivery evidence names the relay's address and the leased port
