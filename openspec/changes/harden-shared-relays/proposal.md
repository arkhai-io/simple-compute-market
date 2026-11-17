# Harden relays shared between operators

## Why

An Arkhai relay serves hosts that all belong to operators Arkhai trusts. Three gaps
in Goal 1 of `docs/development/ROADMAP.md` are safe today only because of that, and
each names the condition under which it stops being safe:

- **A shared relay has one client token and doesn't check who logs in.** Port
  grants stop a host from registering a port it wasn't granted, but they don't stop
  its hosts from opening client connections. Operators use separate issuer keys
  and port ranges that don't overlap. *Trigger:* the first site Arkhai doesn't
  control joins an Arkhai relay.
- **An emergency rotation interrupts every session.** Rotating the signing key
  means reissuing every active grant under the newly active key. Rotating the shared
  client token means reconnecting every attached host. Either may interrupt every
  affected session once. *Trigger:* before serving buyers whose operator can't
  accept that choice on each incident, or at the first credential compromise.
- **The relay role installs the admission plugin without checking it.** The role
  takes the plugin wheel on the operator's word rather than checking its digest
  (`provisioning/compute/iac/ansible/roles/relay-server/tasks/plugin.yml`).
  *Trigger:* the plugin publishes a distributable release whose version and digest
  can be pinned.

They're grouped because they are one theme, a relay that operators share without
trusting each other, and the first two have triggers that are likely to arrive
together.

## What Changes

- **A relay admits a client at login by its own credential.** Each host or operator
  logs into a shared relay with a credential of its own, checked by the admission
  plugin, rather than the shared client token.
- **An emergency rotation reaches live hosts without dropping every session.** The
  service reissues active grants under the newly active key, and the client
  credential is rotated per host or per operator. Only the compromised party's
  sessions are interrupted.
- **The relay role pins the plugin's release.** The role installs the admission
  plugin from its published release at a pinned version and digest, and refuses a
  wheel whose digest differs.

### Decided by the owner

- **D1: one change for shared relays.** Goal 1's unowned gaps are grouped by theme.
  This change takes admission at login, emergency rotation, and the plugin's
  digest.
- **D2: deferred until a trigger.** No work starts until one of the triggers above
  holds. The plugin's digest may be done on its own as soon as the plugin has a
  release.

### Open for design, not decided here

- **The login credential.** Per host or per operator. Signed like the port grants,
  or a token the service issues. How frp's login plugin hook carries it.
- **Grant reissue on rotation.** Whether a live host picks up a reissued grant
  without reconnecting. How a rotation is ordered across relays.
- **What existing hosts do.** How hosts on a shared token move to their own
  credentials without a drain.

## Capabilities

### Modified Capabilities

Provisional; settled in design.

- `frp-grant-admission`: admission at login, and the plugin's release.
- `physical-provisioning`: grant reissue and credential rotation for relays.

### New Capabilities

None.

## Non-Goals

- Host-key checking and host credential protection.
  `harden-provisioning-trust-boundaries` owns these.
- Moving an existing delivery between relays.

## Impact

- `tools/frp-grant-admission` (the admission plugin).
- `provisioning/compute/src/compute_provisioning/relays/` (grants, keys, and
  rotation).
- The `relay-server` role and the host-side tunnel client configuration in each
  family role.
- `VALIDATION_RUNBOOK.md` section 28 and the operator handbook.

## Dependencies and Related Changes

- None.
- `harden-provisioning-trust-boundaries` hardens the host half of the same
  boundary.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `frp-grant-admission`,
  `physical-provisioning`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion. Expected destinations: the
`frp-grant-admission` and `physical-provisioning` specifications and architecture
companions, `VALIDATION_RUNBOOK.md` section 28, and `docs/development/ROADMAP.md`'s
Goal 1 current state.
