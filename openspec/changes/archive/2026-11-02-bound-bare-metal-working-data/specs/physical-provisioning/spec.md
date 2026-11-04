# Spec Delta

## ADDED Requirements

### Requirement: Bounded working-data cleanup is an explicit bare-metal policy

The selected-site operator SHALL explicitly select bounded working-data cleanup before granting a temporary nonroot account. The policy SHALL remove the account, its home, attributable UID-owned shared scratch and tenant IPC within protected configured boundaries. Requests SHALL NOT select deletion targets or privileged identities. Existing reclaim policies SHALL retain their data semantics.

#### Scenario: A request supplies a cleanup target

- **WHEN** a buyer or job request attempts to override the protected cleanup roots, home, UID or policy
- **THEN** bounded grant or cleanup refuses before any destructive effect

#### Scenario: An existing policy is used

- **WHEN** a host uses key removal, account locking or ordinary account deletion
- **THEN** bounded working-data removal is not implicitly enabled

### Requirement: Tenant UIDs remain consumed for the policy lifetime

A bounded grant SHALL durably consume a fresh local UID and same-number private primary GID before group/account creation, bound to its reservation and tenant account. Equivalent retries SHALL reuse that identity; another reservation SHALL never reuse it, including after failure or completed cleanup. Allocation SHALL exclude root, system, operator, service and conflicting NSS user/group identities, and SHALL fail closed on exhaustion or invalid history.

#### Scenario: Creation fails after UID consumption

- **WHEN** account creation fails after its UID was recorded
- **THEN** a retry of that reservation uses the same UID and another reservation consumes a different UID

#### Scenario: Cleanup completed and another tenant arrives

- **WHEN** a new reservation requests access after a prior reservation completed cleanup
- **THEN** it receives a UID not consumed by any prior reservation in the policy lifetime

#### Scenario: A private group identifier conflicts

- **WHEN** an otherwise eligible numeric UID has an NSS group or consumed GID collision
- **THEN** allocation excludes that UID/GID pair before either account or group creation

#### Scenario: Concurrent reservations allocate

- **WHEN** independent helper processes allocate concurrently
- **THEN** durable serialization prevents duplicate UID issuance

#### Scenario: An account already exists without a receipt

- **WHEN** bounded grant finds an existing account with no matching protected reservation receipt
- **THEN** it refuses without adopting or modifying that account

#### Scenario: Established ledger state is missing or invalid

- **WHEN** normal operations find established consumption history missing, corrupt or mismatched
- **THEN** no new bounded grant or cleanup proceeds, no history is initialized from current NSS state, and the host stays unavailable pending operator recovery

#### Scenario: Service state is restored or redeployed

- **WHEN** the operator restores a service database, redeploys its image or resets a campaign
- **THEN** the protected host consumption ledger is preserved independently and unchanged

#### Scenario: Valid older host history may have been restored

- **WHEN** the operator knows or suspects that a structurally valid older host ledger was restored
- **THEN** the operator keeps the host unavailable until complete consumption history is verified or the host is decommissioned
- **AND** the host-local ledger does not claim to detect its own valid rollback

### Requirement: Cleanup targets are protected and bounded

Bounded cleanup SHALL derive targets from protected host policy and reservation receipts. It SHALL NOT traverse symlinks, cross unexpected mounts, delete root/operator/service targets, or recursively remove foreign-owned descendants. Unreadable state, policy drift, identity mismatch or unsafe topology SHALL fail cleanup. Other owners' non-selected shared-root entries SHALL remain intact.

#### Scenario: A tenant symlink points outside a covered root

- **WHEN** cleanup finds a tenant-owned symlink to an operator file
- **THEN** it may remove the link itself and leaves the target untouched

#### Scenario: A candidate directory contains foreign data

- **WHEN** a selected tenant directory contains a descendant owned by another UID
- **THEN** cleanup refuses recursive removal and reports failure without deleting that foreign entry

#### Scenario: A covered root contains a bind mount

- **WHEN** traversal encounters a mount not authorized by protected policy
- **THEN** cleanup refuses rather than traversing it

#### Scenario: A containing directory permits foreign replacement

- **WHEN** a selected entry lies beneath a foreign-owned directory, even one currently read-only, or beneath a nonsticky directory with effective group/other write authority including an ACL mask
- **THEN** cleanup refuses the entire candidate preflight before deleting any candidate and does not record completion
- **AND** root-owned sticky shared roots remain supported when foreign UIDs cannot replace the selected root/tenant-owned entries

### Requirement: Tenant IPC cleanup requires unambiguous ownership

Bounded cleanup SHALL remove attributable path-backed IPC within protected roots and System V shared memory, semaphores and message queues whose owner and creator both match the recorded UID. An object with only one matching identity SHALL cause refusal. Unavailable inventories or unsupported kernel interfaces SHALL fail cleanup; completion SHALL require verified absence of covered tenant IPC.

#### Scenario: System V ownership differs from creation

- **WHEN** an IPC object's owner matches the tenant but its creator does not, or the reverse
- **THEN** cleanup fails without deleting that object

#### Scenario: A tenant account is gone but IPC survives

- **WHEN** the protected receipt identifies a UID whose account is absent and whose covered IPC remains
- **THEN** cleanup removes only unambiguously attributable IPC and verifies absence before completing

### Requirement: Bounded cleanup checks quiescence without owning termination

Bounded cleanup SHALL independently verify no process references the recorded UID after the access role verifies termination of sessions, lingering and scheduled activity. It SHALL NOT implement or duplicate those termination barriers or trust a caller’s assertion of quiescence. New execution SHALL remain excluded through cleanup; unreadable process state or a surviving UID process SHALL fail cleanup.

#### Scenario: A process retains the UID after account deletion

- **WHEN** an account is absent but a process still references its recorded UID
- **THEN** bounded cleanup fails and the host's capacity remains held

### Requirement: Bounded cleanup completes only after verified absence

Bounded reclaim SHALL succeed only after verifying account, recorded private primary group, home, attributable covered scratch and IPC absence and committing a protected completion receipt. Retries SHALL resume safely after partial deletion, including an absent account, without recreating it or releasing consumed UIDs. Missing attribution SHALL fail closed. Receipt contents SHALL remain diagnostic; helper or role failure SHALL fail the reclaim job and retain capacity through ordinary lease release.

#### Scenario: Account deletion succeeds before a crash

- **WHEN** reclaim retries after the account was removed but before completion was recorded
- **THEN** it uses the protected UID receipt to remove remaining covered data and verifies every covered absence before success

#### Scenario: A reserved account was never created

- **WHEN** reclaim finds a valid reservation receipt but no account ever created for it
- **THEN** it verifies the covered UID, home, scratch, IPC and activity absent and completes without creating an account

#### Scenario: An absence claim has no receipt

- **WHEN** bounded reclaim finds no account and no protected reservation attribution
- **THEN** it fails rather than treating account absence as proof of cleanup

#### Scenario: A completed reclaim is repeated

- **WHEN** reclaim repeats for a complete receipt
- **THEN** it re-verifies covered absence and preserves the consumed UID

#### Scenario: Cleanup fails before account removal

- **WHEN** helper cleanup refuses a remaining object or cannot verify an absence
- **THEN** the reclaim job fails, teardown is not proven, and capacity remains unavailable until successful retry or a separately audited operator override

## MODIFIED Requirements

### Requirement: A bare-metal reclaim tolerates an account its grant never created

A bare-metal reclaim MUST succeed, reporting the tenant account absent, when the tenant
account it names does not exist on the host under an existing reclaim policy, and MUST NOT
create the account. Where the account exists it MUST remove the lease's key, or lock or
delete the account, as its policy says. Under bounded working-data cleanup, account
absence alone MUST NOT establish success: protected reservation attribution and verified
absence of all covered data, IPC and activity are required.

#### Scenario: A grant failed before creating its account

- **WHEN** a compensating teardown under an existing reclaim policy reclaims access for a grant whose tenant account was never created
- **THEN** the reclaim succeeds reporting the account absent, and no account is created

#### Scenario: A grant created its account and installed its key

- **WHEN** a reclaim under the default policy runs for an account holding the lease's key
- **THEN** that key is removed and the account is otherwise unchanged

#### Scenario: A bounded grant failed before creating its account

- **WHEN** bounded reclaim has its protected reservation receipt and finds no account
- **THEN** it succeeds only after verifying absence of the receipt's covered data, IPC and activity without creating an account
