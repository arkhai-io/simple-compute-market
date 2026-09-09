# Design

## Context

The implemented change spans the controlled actual-host path, shared Alkahest
integration, exact accepted-settlement validation, and same-identifier
publication refresh/reopen. Publication lifecycle sequencing is split by
authority: core owns typed transport, `kit/capacity-publication` owns confirmed
refresh/reopen ordering and current-intent recovery, and domain adapters own
candidate meaning and local persistence. The bare-metal CLI only composes and
reports that path; it no longer owns a parallel lifecycle implementation.

## Current source facts

### Registry request and readback shape

- `core/registry-client/src/registry_client/models.py` defines
  `ListingRequest`. `to_dict()` emits `listing_id`, `offer_resource`,
  `accepted_escrows`, `settlement_options`, `demands`,
  `max_duration_seconds`, and `storefront_url`. Optional `status` occupies a
  trailing backward-compatible constructor position and is omitted when unset.
- `core/registry/src/api/listing_routes.py:71` updates an existing listing under
  the same identifier. Lines 78-90 replace non-`None` advertised fields and
  change status only when the request body contains the `status` key. Lines
  94-104 default a new listing's absent status to `open`.
- `core/registry/src/api/utils.py:232` returns the discovery/readback wire shape.
  Its publisher-owned advertised projection is `publisher_principals`,
  `storefront_url`, `offer_resource`, `accepted_escrows`,
  `settlement_options`, `demands`, and `max_duration_seconds`; it also returns
  listing identity and lifecycle status. Numeric `publisher_id`, timestamps,
  and `oracle_address` are not fields authored by `ListingRequest`.
- `core/registry-client/src/registry_client/models.py:233` normalizes readback
  aliases into `ListingSummary`: `listing_id`/`id` becomes `id`,
  `offer_resource`/`offer` becomes `offer`, absent collection fields become
  empty lists, and `max_duration_seconds`/`maxDurationSeconds` becomes
  `max_duration_seconds`. Publisher principals are parsed into
  `TrustedIdentitySet`.

Readback comparison uses those typed DTO properties after normalization,
not invented wire keys. It compares listing `id`, lifecycle `status`, canonical
publisher ownership (the authenticated signer must be in
`publisher_principals`), `storefront_url`, `offer`, `accepted_escrows`,
`settlement_options`, `demands`, and `max_duration_seconds`. Mapping key order is
irrelevant under canonical JSON; list order remains significant because the DTO
does not define set semantics. Numeric publisher ID, timestamps, `extra`, and
`oracle_address` are excluded.

### Existing multi-registry consumer semantics

- `core/storefront/src/core_storefront/multi_registry_client.py:20` documents the
  write contract: fanout succeeds when at least one configured registry accepts
  the write, with partial failures logged. Lines 271-289 implement the aggregate
  methods by selecting the first successful response.
- `core/storefront/src/core_storefront/multi_registry_client.py:302` exposes
  per-registry publish/update methods. Lines 357-434 return one ordered
  `PublishResult` for every requested URL, including the exact safe payload,
  response or error, and assigned identifier.
- `core/storefront/src/core_storefront/registry_publication.py:38` sends one
  request per configured registry and records every result. Lines 90-105 return
  aggregate `published` when any result succeeds; lines 107-116 return `error`
  only when none succeeds or orchestration raises.
- `kit/capacity-publication/src/market_capacity_publication/publication.py:246`
  persists every per-registry result as `published` or `failed`.
- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/cli.py:72`
  prints the round before testing its existing `failed` collection at lines
  73-78; any failed candidate already produces exit code 1.

This at-least-one aggregate success behavior is an existing consumer contract.
The change will preserve it. There will be no configurable quorum abstraction.
Partial failure must nevertheless be returned to the caller and retained in the
publication records instead of being hidden behind the aggregate status.

### Current ordering

- `kit/capacity-publication/src/market_capacity_publication/publication.py:153`
  currently marks a listing locally open at lines 159-162 and only then calls
  remote publication. This is not safe for the bare-metal reopen contract.
- `domains/bare_metal/src/arkhai_bare_metal/storefront_publication.py:360`
  performs refresh publication first, then persists new terms while preserving
  the open/paused lifecycle state. Its reopen path at lines 387-412 publishes
  first and only then stores terms, marks status open, and clears paused state.
- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/publication_cli.py:210`
  currently republishes terms, sends a separate authenticated status update,
  and reads identity/status back before reporting success.

Refresh and reopen are distinct operations. Refresh must not unpause or reopen a
listing. Reopen may do so only after the accepted remote result is confirmed.

## Decisions

### 1. Extend the existing publication request with optional status

`ListingRequest` will gain `status: str | None = None`. `to_dict()` will include
`status` only when it is not `None`.

- New publication and refresh leave it unset, preserving their existing wire
  body and the status already held for an existing record.
- Reopen supplies `status="open"` in the same authenticated publication request
  as the refreshed terms.
- The separate `UpdateListingRequest` remains available to existing callers;
  this change does not remove or redefine it.

This requires a later normative amendment to
`openspec/specs/storefront-publication/spec.md`: republication MAY carry an
explicit lifecycle status; omission MUST preserve an existing registry record's
status; refresh MUST omit status; reopen MUST carry `open`; and no local mutation
may occur until authenticated readback confirms the request's canonical
publisher-owned advertised fields, identity, and status. The permanent spec is
not edited in this documentation-only submilestone.

### 2. Put the lifecycle seam in the capacity-publication module

`PublicationRuntime` remains the external interface. It exposes distinct
refresh and reopen operations over a `PublicationCandidate`; callers do not
orchestrate remote publication, confirmation, local persistence, or retry
target selection themselves.

The existing domain hook interface is deepened with one publication-commit
operation carrying an explicit refresh/reopen transition. The bare-metal
adapter implements that operation:

- refresh replaces local advertised terms without changing status or paused;
- reopen replaces terms, sets status open, and clears paused.

The hook is invoked only after the runtime has at least one successful,
confirmed registry result. This strengthens the bare-metal local-commit gate
without changing the shared transport aggregate, which still reports
`published` after any accepted write. Failed target results remain stored and
returned as partial failure.
Partial convergence is not full candidate success: the bare-metal command
projection also places that candidate in its existing `failed` collection so
the current JSON evidence and nonzero-on-failed-candidate behavior remain
unchanged. The CLI exit condition and exit code are not redesigned.

Core retains schema-opaque registry transport and fanout. The kit owns lifecycle
ordering and interpretation. Bare metal owns domain candidate validation,
durable physical binding, and local persistence. The bare-metal CLI becomes a
composition/reporting adapter and no longer carries a parallel lifecycle
implementation.

#### Core reuse slice before lifecycle integration

The first implementation slice does not change the kit or a domain. Core
storefront exposes one narrow helper for a caller that already holds an opened
`MultiRegistryClient`. The existing factory-opening wrapper and that helper
share request construction, ordered fanout, callback handling, aggregate
projection, receipt preservation, and safe exception categorization. The
opened-client helper may select an exact target subset, but it validates the
complete subset before I/O, rejects unknown or duplicate normalized URLs, and
emits payloads in configured order. An explicitly empty subset is a targeting
failure with no writes; it cannot mean all configured targets or a successful
no-op. Omitting lifecycle status preserves the legacy request-factory call
shape, while an explicit status is forwarded to the typed request.

`MultiRegistryClient` also exposes immutable public configuration metadata:
the publisher's public signer identity and, in configured order, each target's
configured and normalized URL plus its configured authority/trusted principal
set. This view is derived from constructor-validated configuration, not a
remote response, and excludes authentication tokens, signer material, clients,
and mutable internal configuration. It supplies identity inputs for a later
intent without making core interpret domain terms or lifecycle policy.

This slice deliberately adds no recovery state, retry loop, confirmation
policy, or domain adapter. Existing factory-wrapper callers retain their normal
enabled/disabled and at-least-one-success behavior.

### 3. Preserve visible partial failure and target retries narrowly

The transport aggregate remains compatible: one registry accepting the write is
`published` for existing shared consumers even if later confirmation is
unavailable. The lifecycle result also carries the ordered per-registry outcomes
already produced by `MultiRegistryClient`. Bare-metal local mutation requires at
least one confirmed target. A result with any intended failed or unconfirmed
target is explicitly partial, not fully converged. The bare-metal command
reports that candidate through its existing `failed` collection while retaining
confirmed target details in the round; its existing
`if result.get("failed"): exit 1` rule therefore continues to apply.

One publication intent is identified by all of:

- listing identifier;
- current authenticated publisher principal;
- canonical requested `ListingRequest` body, including whether `status` is
  omitted or explicitly `open`;
- transition semantics (`new`, `refresh`, or `reopen`);
- target identity: normalized registry URL and its configured authority/trust
  identity.

A newly invoked publication, refresh, or reopen is a new intent and addresses
every intended configured target. A prior `published` row does not filter those
targets: it may describe older terms, another publisher context, a refresh
without status, or a different registry authority. Preflight may prove that a
target already matches the new intent and avoid an unnecessary write, but old
aggregate success never satisfies the new intent by itself.

Retry-only target filtering is allowed only inside the exact same in-flight
intent. The implementation retains that intent and its ordered target outcomes
in the current operation result. Confirmed targets are not rewritten merely
because another target failed. Known failed-write targets may be retried with
the identical request. A write-success/readback-unknown target is reconfirmed by
authenticated read only; uncertainty alone does not authorize another write.

Existing persisted request payloads and publication rows remain audit and
preflight inputs. They do not currently bind every intent dimension, especially
transition and current publisher/target authority, so this change does not use
them as a cross-operation retry token and does not add a generic intent journal.
If the operation ends, a later invocation follows the new-intent rules above.
Configured target order remains deterministic.

This is implemented as an immutable `PublicationLifecycleResult` carrying its
`PublicationIntent`; callers must pass that result explicitly to `recover()`.
There is no mutable runtime current-intent slot. It remains a current-operation
target-selection rule, not automatic reconciliation policy or a generalized
retry framework.

### 4. Confirm each successful registry through the typed DTO

POST publication returns identity/status metadata but not the advertised terms.
Each successful target therefore requires an authenticated GET against that
same registry, parsed as `ListingSummary`. A first-hit fan-in read is
insufficient because it cannot confirm which registry accepted which terms.

Before any refresh network operation, the domain adapter proves that the
candidate is tracked, locally eligible and open, and present in the current
available candidate set. Remote preflight then reads each target
authentically. Only authenticated not-found is a create case. Timeout,
authentication failure, malformed response, authority mismatch, and every
other error are `unknown`; the runtime sends no create or update to that target.
A confirmed 404 never bypasses the local untracked, closed, or unavailable
candidate refusals.

For a found refresh target, the runtime retains its lifecycle status before
publishing. A remotely closed target is a mismatch requiring explicit reopen,
not a refresh write. An eligible found record must have the same status after
publication; omitting status is therefore checked rather than assumed. A
confirmed 404 may be created under the registry's existing default-open rule,
and post-write readback must then be open. Reopen needs no pre-write status
equality because it explicitly asks for `open`, but it still requires
same-target post-write confirmation.

The GET/POST/GET sequence is not atomic. If status changes concurrently, the
post-write observation is a mismatch/failure for that target. The design claims
detection at the observed seams, not preservation against every intervening
race.

The remote result is confirmed only when the typed DTO matches:

- requested listing ID;
- expected publisher principal set;
- expected storefront URL;
- requested offer;
- requested accepted escrows;
- requested settlement options;
- requested demands;
- requested maximum duration;
- requested `open` status for reopen, the pre-existing status for a found
  refresh target, or `open` for a refresh target first created after a 404.

Every target ends in one of these explicit result states:

1. `confirmed`: authenticated readback matches the exact current intent;
2. `write_unconfirmed`: the write returned success but authenticated readback is
   unavailable or invalid;
3. `write_failed`: an authenticated response proves the write was rejected;
4. `write_unknown`: a transport interruption leaves the write outcome unknown;
5. `confirmation_mismatch`: authenticated readback returns a record that does
   not match the exact current intent.

Preflight uncertainty is separately represented as `preflight_unknown`. A 4xx
response other than request-timeout is treated as a definitive rejected write;
5xx, request-timeout, and transport failures remain ambiguous `write_unknown`
outcomes. Lifecycle persistence records only safe error type/status categories,
never raw exception text. A context, receipt-persistence, event, or local-commit
failure preserves every already-known target receipt and reports its own stage.
Confirmed preflight matches also require durable receipts before local commit.
The immutable result records whether receipt persistence and publication-event
delivery completed, so recovery retries only the outstanding side effect and
does not reinterpret remote confirmation as durable local evidence. Repeated
persistence or event failure continues to block local commit without repeating
an already-confirmed registry write.

Before lifecycle validation can open a registry client or apply disabled-mode
local policy, the candidate identifier must exactly equal the identifier in its
serialized payload. Fanout receives the canonical request built by that check,
preventing a candidate bound as one listing from transmitting another listing
identity.

`write_unconfirmed`, `write_unknown`, and `confirmation_mismatch` are not known
failed writes and do not authorize another write. Recovery first performs
read-only authenticated reconfirmation within the same intent. A mismatch
includes a safe mismatch category and is never silently converted to confirmed.
Only `write_failed` is eligible for identical-request write retry inside that
intent. Local state is not advanced solely on an unconfirmed response.

### 5. Required publication regressions

The later implementation must prove at least these cases:

- **Changed terms after prior success:** a new refresh intent addresses all
  intended targets; an older `published` row cannot skip them. A preflight exact
  match may avoid a write only after authentic confirmation of the new terms.
- **Reopen after refresh:** the prior refresh omitted status and cannot satisfy
  the later reopen intent carrying explicit `open`.
- **Interrupted readback:** a successful write followed by unavailable readback
  becomes `write_unconfirmed`; retry reconfirms by GET and does not blindly POST.
- **Failed-subset retry:** within the same intent, confirmed targets are not
  rewritten, known failed targets receive the identical request, and partial
  results remain in the CLI round's `failed` collection so its existing exit-1
  rule applies.
- **Refresh preflight uncertainty:** a non-404 read error performs no write.
- **Concurrent status change:** a differing post-write status is reported as a
  mismatch/failure; no atomic preservation claim is made.

### 6. Keep settlement consolidation as required later work

Shared payment ownership already exists:

- `kit/alkahest/src/market_alkahest/settlement_config.py:573` owns the accepted
  obligation builder and resolves the advertised recipient with the injected
  seller wallet as fallback.
- `create_alkahest_registration()` registers that builder and the shared
  verifier.
- Bare-metal negotiation calls the mechanism-owned builder, then adds the
  domain-owned `bare_metal.v1` physical service terms.
- Bare-metal settlement validates the accepted plan, obligation, selection,
  mechanism terms, and repeated physical representations before chain access.

Later consolidation must remove duplicate construction/interpretation across
negotiation, buyer, and settlement paths by reusing the mechanism-owned accepted
artifacts. It must retain domain-owned physical validation and must not silently
change the accepted plan/envelope, hosted envelope, seller payout fallback, or
legacy escrow-proposal path.

### 7. Preserve test and execution topology

- Existing deterministic default development-environment values remain aligned
  with the single bare-metal E2E scenario and the VM scenarios that share the
  development chain fixtures.
- `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_deal.py`
  remains the single cross-service scenario. No new harness dependency is added.
- Actual-host access/account mutation remains the documented exception that is
  exercised only through the operator-controlled actual-host lane; package and
  default E2E tests stay deterministic and host-independent.
- The downstream VM consumer of `kit/capacity-publication` is part of
  qualification because earlier evidence could not exercise that consumer with
  the changed kit installed.

## Rejected alternatives

### Configurable registry quorum

Rejected as scope expansion. Existing callers already use at-least-one write
success. A quorum setting would add configuration, migration, documentation,
and operational policy unrelated to the narrow consolidation.

### Keep lifecycle sequencing in the bare-metal CLI

Rejected because ordering, result interpretation, and retry targeting would
remain duplicated and unavailable to other capacity-publication consumers.

### Compare raw registry JSON

Rejected because the typed DTO already normalizes supported aliases and absent
collections. Raw comparison would bind callers to incidental wire spelling and
server-owned fields.

### Remove repeated settlement fields while consolidating

Rejected. The repeated representations currently support cross-binding checks.
Their removal would be a wire change, not a refactor.

### Treat persisted `published` as a reusable retry token

Rejected. The existing row and payload do not bind every current intent
dimension. Treating them as sufficient would allow stale terms or a prior
refresh transition to satisfy a later intent. This change keeps exact retry
state within the current operation instead of adding a journal platform.

## Remaining policy choice

The implementation will support explicit current-intent recovery: known failed
writes may receive the identical request, while unconfirmed or unknown outcomes
receive authenticated read-only reconfirmation. Whether a future reconciliation
loop invokes recovery automatically is unresolved. This change adds no
scheduler, retry interval, backoff configuration, or background reconciliation
policy. Until a separate decision is accepted, recovery remains an explicit
caller/operator action.

The cross-consumer and concurrency choices are resolved. VM and API-credit
adapters explicitly retain their existing disabled-publication behavior: reopen
commits locally, while their unsupported refresh transition is rejected during
lifecycle validation. Bare metal requires the confirmed enabled path and skips
local mutation when publication is disabled.
Recovery accepts an explicit immutable operation result bound to publisher,
configured target trust, canonical request, transition, and capacity binding;
concurrent calls share no mutable intent state.
Bare-metal recovery also receives whether the same intent already committed
locally. A partial reopen that advanced the local listing to open therefore
expects that open state during recovery, while fresh reopen still rejects an
already-open listing. Both paths reload durable binding, derivation, and current
availability before registry I/O.

Qualification after that later interface change must include both downstream
VM and API-credit consumers of the capacity-publication kit.

## Design promotion record

| Material decision | Permanent destination | State |
|---|---|---|
| Optional-status omission, exact-target preflight/readback, immutable intent recovery, safe partial results, and local commit ordering | `openspec/specs/storefront-publication/spec.md` | Promoted for publication milestone review |
| Core transport, kit lifecycle, and explicit domain-adapter ownership | `openspec/specs/storefront-publication/architecture.md` | Promoted for publication milestone review |
| Repository-wide capacity-publication ownership | `docs/development/ARCHITECTURE.md` | Updated for publication milestone review |
| Roadmap currency | `docs/development/ROADMAP.md` | No edit: the roadmap already names the kit publication runtime and all three composed consumers; this submilestone does not complete its goal |
| Campaign index currency | `openspec/changes/README.md` | No edit: the encompassing change remains under review with settlement and final qualification still incomplete, so no dependency is newly unblocked |
| Settlement construction ownership and physical authority | `openspec/specs/settlement-configuration/spec.md`; `openspec/specs/negotiation-protocol/spec.md` | Deferred until the separately reviewed settlement consolidation |
