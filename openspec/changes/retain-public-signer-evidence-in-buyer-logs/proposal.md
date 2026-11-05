# Proposal

## Why

An ordinary VM delivery end can be accepted and physically executed, then fail
locally because its signed acknowledgement contains a public `signer` identity.
The run-log secret guard must preserve public protocol evidence while refusing
private signing material.

## What Changes

- Permit only the canonical public identity shape in a protocol `signer` field.
- Continue refusing raw signers, secret/provider carriers and noncanonical or
  extended identity objects, including nested values.
- Cover signed end evidence through run-log persistence and the VM end command.
- Emit only public status in settlement-poll callbacks; private delivery remains
  available from the authenticated result and never enters new progress events.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `buyer-orchestration`: public signer evidence remains loggable without
  weakening private-material rejection.

## Impact

Core buyer run-log validation, settlement-poll observation and focused core/VM
buyer tests. No wire, database,
configuration, dependency or signing-protocol change is intended. Changing end
effects, rewriting old run logs and relaxing response verification are non-goals.

## Permanent documentation impact

- [x] Existing subsystem specification and companion: `buyer-orchestration`.
- [ ] Repository-wide architecture: authority and dependency layers are unchanged.

### Knowledge to promote

Secret isolation distinguishes a validated canonical public identity from a
signer object or secret-bearing carrier, without deleting signed evidence.
