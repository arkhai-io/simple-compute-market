# Proposal

## Why

Ending tenant activity and deleting an account does not prove that its working data has gone: UID-owned shared scratch and IPC can survive, and a later account can inherit the UID. A bounded cleanup policy must prove removal before the host returns to service.

## What Changes

- Add an opt-in `bounded_working_data` bare-metal policy for temporary nonroot accounts. Grant records a reservation-bound UID before account creation; reclaim removes the account, its home, identified UID-owned shared scratch and tenant IPC after activity is verified ended.
- Add a protected host-local UID ledger: the same reservation retries its UID, another reservation consumes a fresh UID, including after a failed create, and consumed UIDs are never recycled during the policy lifetime.
- Derive deletion targets from root-owned host policy and the ledger, refuse ambiguity, unsafe filesystem topology and identity drift, and retain capacity on any incomplete cleanup.
- Keep the existing reclaim policies available. Refine absent-account behavior only for the new policy: account absence alone cannot establish cleanup.
- Add meaningful bare-metal IaC tests, lifecycle integration coverage and deployed qualification. A helper test pass is not evidence that a host is ready for another tenant.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `physical-provisioning`: bounded tenant working-data cleanup, durable UID consumption, protected target policy and receipt-backed reclaim retries.

## Impact

- `domains/bare_metal/provisioning/iac/`: a stdlib host-local helper, protected policy and ledger installation, later access-role integration, and a non-distributable uv test project wired into aggregate validation.
- `domains/bare_metal/provisioning/adapter/`: later reservation correlation through grant/reclaim preparation and codec inputs; no arbitrary target paths in request parameters.
- Provisioning integration tests and the existing protected bare-metal qualification path; no new public API, no service database schema migration, no default-policy change.
- The provisioning image packages the helper as an Ansible asset; it is not a new runtime Python distribution. Internal project discovery, locks and CI must include the IaC test project.

## Dependencies and ownership

`prove-relay-provisioning` section 9 owns removal of keys, termination of sessions/processes/lingering and scheduled activity, and failure propagation. This change does not duplicate that implementation. Its independent helper and tests start immediately; only role/adapter integration and deployed qualification wait for section 9 to be available and verified. This partial dependency belongs in the index Notes, not a whole-change gate. Integration must reconcile the absent-account contract against that section without editing its accepted history.

## Non-goals

Exporting or saving data before teardown; persistent tenant storage; operator logs, service artifacts, backups or forensic erasure; globally scanning or cleaning the host; adopting historical unreceipted accounts; implementing activity termination; providing root or sudo to tenants; changing relay allocation or generic release state machines.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` (no new repository-wide authority; confirm at closeout)
- [x] Existing subsystem specification: `openspec/specs/physical-provisioning/spec.md`
- [x] Companion: `openspec/specs/physical-provisioning/architecture.md`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

UID consumption, bounded target ownership and retry/absence rules go to physical provisioning's spec and architecture. Policy setup, finite UID capacity, limitations, recovery and qualification go to `docs/bare-metal-seller-quickstart.md` and `docs/development/VALIDATION_RUNBOOK.md`. Test ownership and invocation go to `docs/development/TESTING.md`; readiness/gap status goes to `docs/development/ROADMAP.md` and the campaign index.
