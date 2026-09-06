## Why

The whole-host lifecycle has never run against a real host. This change carries
only what a single controlled demonstration on one reserved development host
needs: publish, purchase, reserve, grant access by Ansible, connect as the
unprivileged tenant, request teardown, observe the buyer key refused, and see
the released capacity published again.

## What Changes

- Admit the tenant account against the derivation the domain already performs,
  before a grant or reclaim job is dispatched. This keeps the demonstration off
  any operator account; it is not tenant-isolation hardening.
- Read the buyer CLI's actual listing envelope, so released capacity can be
  observed at all.
- Classify a post-teardown SSH attempt instead of accepting any failure, and
  restrict the buyer session to its own key.
- Allow a scenario to give the buyer subprocess an explicit environment.
- Render chain and signing-key configuration for the whole-host storefront when
  Alkahest is enabled, so the demonstration can settle on a development chain
  without money.
- Add a test target for the bare-metal provisioning adapter, whose suite had no
  way to run.

## Scope limits

This is a controlled demonstration, not production tenancy support.

Explicitly out of scope, and not claimed: hostile-tenant isolation, filesystem
path hardening against a tenant that rewrites its own home, destructive reclaim
policies, natural lease expiry, host wipe or reimage, account sanitation, and
generalized evidence machinery. The demonstration uses exact-key-only reclaim, a
fixed harmless remote command, a known dedicated account, and a host whose state
is checked by an operator preflight beforehand. Unsafe host state stops the run
rather than being repaired or defended against.

## Capabilities

### Modified Capabilities

- `physical-provisioning`: the executing authority admits the operating-system
  account a whole-host access action may name, and a host row persists a
  tenant-facing endpoint distinct from the one the provisioner connects
  through.

## Permanent documentation impact

- [x] Existing subsystem specification

### Knowledge to promote

Three changes here are durable production behaviour, not demonstration
scaffolding, and are owed a permanent home once reviewed:

1. **Account admission.** Grant and reclaim admit the account against the
   derivation the domain performs, before dispatch. Destination:
   `openspec/specs/physical-provisioning/spec.md`.
2. **Stored buyer-facing endpoint.** `public_port` joins the existing
   `public_host` as persisted host state, and the access result returns the
   tenant-facing endpoint rather than the provisioner's. Destination:
   `openspec/specs/physical-provisioning/spec.md`.
3. **Whole-host storefront chain configuration.** The chart renders chain and
   signing-key configuration under Alkahest and nothing when it is disabled.
   Destination: `openspec/specs/deployment-state/spec.md`.

Deliberately **not** promoted: anything about hostile-tenant isolation,
destructive reclaim policies, or a demonstrated live run. An earlier revision
promoted requirements that overstated the implementation; those were reverted
and are not reinstated here.

## Impact

No shipped caller supplies a tenant account name, so account admission changes
no current path. The buyer environment input defaults to today's behaviour.
