## Why

The whole-host lifecycle needs one coherent, reviewable path from publication
through accepted settlement, fulfillment, unprivileged access, teardown, and
same-identifier republication. The controlled actual-host demonstration proved
that path on one reserved development host and exposed two pieces of follow-up
work: bare metal still owns publication sequencing that belongs in the shared
capacity-publication module, and accepted settlement is constructed and checked
at several seams that should share one mechanism-owned derivation without
weakening domain-owned physical validation.

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
- Drive the Alkahest rail through the shared mechanism registration and accepted
  obligation builder, while keeping the hosted envelope and seller payout
  fallback compatible.
- Decode and re-materialize accepted Alkahest payment terms through that
  mechanism's plan codec, while retaining domain-owned party, selection and
  physical validation.
- Bind settlement to the committed accepted plan and its exact physical terms,
  rather than reinterpreting mutable listing terms during settlement.
- Refresh and reopen a tracked listing under the same identifier, with registry
  success confirmed before local terms or lifecycle state changes.
- Move refresh/reopen sequencing into `kit/capacity-publication` behind a small
  domain-delegate seam. Core registry fanout keeps its existing at-least-one
  success contract; callers retain the per-registry outcomes needed to expose
  partial failure and safely retry failed targets only within the exact same
  publication intent. A later invocation is a new intent and addresses every
  intended configured target; stale success never satisfies changed terms or a
  different lifecycle transition.
- Extend the existing listing publication request with optional explicit status.
  The key is omitted when unset. Reopen requests `open`; refresh omits status and
  therefore preserves the state already held by the registry.
- Compare same-target readback against the canonical publisher-owned fields
  exposed by the typed listing DTO before committing local state. Distinguish a
  confirmed success, a known failed write, and a successful write whose readback
  is unknown.
- Make the three affected installed-wheel qualification targets lock-stable
  while retaining explicit same-version artifact reinstall, and place offline
  production-scenario orchestration under the integration test level.

## Scope limits

This remains a controlled demonstration and compatibility-preserving
consolidation, not production tenancy support or a generalized registry-policy
platform.

Explicitly out of scope, and not claimed: hostile-tenant isolation, filesystem
path hardening against a tenant that rewrites its own home, destructive reclaim
policies, natural lease expiry, host wipe or reimage, account sanitation, and
generalized evidence machinery. The demonstration uses exact-key-only reclaim, a
fixed harmless remote command, a known dedicated account, and a host whose state
is checked by an operator preflight beforehand. Unsafe host state stops the run
rather than being repaired or defended against.

Also out of scope: a configurable publication quorum, automatic reconciliation
policy, a new E2E harness, changed accepted settlement envelopes, removal of the
wallet-derived seller payout fallback, and a new machine-lease wire
discriminator. Multi-registry writes preserve their current compatibility rule:
one accepted write remains aggregate transport success. Bare-metal local commit
requires at least one confirmed readback, every target's result remains visible,
and partial convergence remains an operator-visible candidate failure. Whether
recovery is invoked only by an explicit operator action or by a later
reconciliation loop remains a separate policy decision.

vLLM serving, model-cache preparation or persistence, GPU allocation or
qualification, and GPU-specific host configuration are deferred. They are not
prerequisites for this bare-metal publication/settlement consolidation and no
capacity in this change is reserved for them.

## Capabilities

### Modified Capabilities

- `deployment-state`: whole-host deployment renders Alkahest chain material only
  when enabled, carries optional write-scoped registry authentication safely,
  and makes strict provisioning host-key pinning an explicit opt-in.
- `physical-provisioning`: the executing authority admits the operating-system
  account a whole-host access action may name, and a host row persists a
  tenant-facing endpoint distinct from the one the provisioner connects
  through.
- `settlement-configuration`: bare-metal Alkahest acceptance and settlement use
  the mechanism-owned accepted obligation and accepted-term projection, bind it
  to the exact committed agreement, and avoid duplicate payment parsing without
  changing accepted envelopes or payout fallback.
- `negotiation-protocol`: trusted seller inventory and binding remain the
  authority for physical terms; buyer input cannot supply physical access
  authority.
- `storefront-publication`: refresh preserves listing identity and lifecycle
  state, while reopen sends an explicit optional `open` status and confirms the
  canonical publisher-owned advertised record before local mutation. Shared
  lifecycle sequencing moves into the capacity-publication module through
  domain persistence delegates.

## Permanent documentation impact

- [x] Existing subsystem specification

### Knowledge to promote

The following changes are durable production behaviour, not demonstration
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
4. **Optional provisioning host-key pinning.** Pinning is off by default; where
   enabled, the deployment mounts an operator-managed `known_hosts` Secret and
   sets the strict Ansible environment together, and refuses to render without
   the Secret reference. Destination:
   `openspec/specs/deployment-state/spec.md`.
5. **Accepted settlement ownership.** Mechanism-owned accepted-obligation
   construction and domain-owned agreement validation remain distinct, with
   accepted envelopes and payout fallback preserved. Destination:
   `openspec/specs/settlement-configuration/spec.md` and, for physical selection,
   `openspec/specs/negotiation-protocol/spec.md`.
6. **Publication lifecycle.** The capacity-publication module owns
   refresh/reopen ordering and delegates domain persistence; optional status is
   omitted for refresh and explicit for reopen; canonical remote confirmation
   precedes local mutation; existing at-least-one registry success remains
   compatible while partial failures remain visible. Destination:
   `openspec/specs/storefront-publication/spec.md` and
   `openspec/specs/storefront-publication/architecture.md`.
7. **Qualification ownership.** Lock-stable same-version wheel refresh for the
   three affected targets belongs in `docs/development/ARCHITECTURE.md`; offline
   production-scenario orchestration belongs in
   `docs/development/TESTING.md`; the distinction between offline qualification
   and actual-host evidence belongs in
   `docs/development/DEPLOYMENT_AND_CONFIG.md`.

Deliberately **not** promoted: anything about hostile-tenant isolation,
destructive reclaim policies, or a demonstrated live run. An earlier revision
promoted requirements that overstated the implementation; those were reverted
and are not reinstated here.

## Impact

No shipped caller supplies a tenant account name, so account admission changes
no current path. The buyer environment input defaults to today's behaviour.
Optional publication status is omitted by default, so existing request bodies
remain unchanged. The shared publication consolidation is intended to replace
bare-metal sequencing, not layer a second path over it. The downstream VM
consumer of `kit/capacity-publication` must qualify before completion because an
earlier environment could not exercise it.
The accepted Alkahest projection is in-process only; accepted-plan, funding and
verification wire payloads remain unchanged, as do hosted and legacy settlement.
The three affected locked refresh targets do not imply that every repository
environment has been converted, nor that one distribution target builds every
wheel an installed environment may reinstall.
