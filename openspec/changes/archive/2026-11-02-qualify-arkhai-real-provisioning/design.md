# Design

## Context

See proposal for motivation. Existing real pytest lanes are payment-specific at import/setup time; importing their complete deal drivers pulls chain-specific configuration. The shipped buyer already supports Arkhai purchases. Shared real SSH and bare-metal bounded-data helpers provide independent reusable observations.

## Goals / Non-Goals

Provide an explicit ordinary-client proof method and exact mapping to unfinished owning tasks. Preserve original driver coverage and completed history. Keep deployment profiles, raw results and operator orchestration private; public instructions describe repository interfaces generically.

No wholesale mock-stage rewrite, private-service imports, new funding API, allocator, payment policy or default lane. Conditional helper factoring must demonstrate an actual reuse obstacle first.

## Decisions

1. Use an operator-run procedure driving the shipped buyer CLI and typed operator APIs, rather than importing full Alkahest pytest modules or writing a second scenario engine. Reuse successful ordinary Arkhai workflows and current neutral helpers. A small external adapter may coordinate CLI output and observations; its mere existence is not qualification.
2. Every new rental uses `arkhai.payments.v1` in TEST mode. Genuine hosted-provider credit is separately proven at its authority and correlated with attributable rental debits; existing unexplained credit is not funding proof. Financial observations are serialized or independently attributable even when physical lanes overlap.
3. Preserve all original physical observations in the mapping below. Alternative methods change the payment driver, not required proof. Do not report the old named markers passed. Existing source tests and accepted frozen validation remain scoped evidence only.
4. Distinguish controlled campaign admission from general publication. Infrastructure and negative-admission preflight precede a real tenant. Claims about customer identity and credentials, agreed privilege, a valid grant, GPU work, payment, paid delivery, ordinary teardown, fresh access denial, and restored capacity come from actual shipped-buyer Arkhai TEST-paid journeys. General admission waits for those paid observations; this prevents a tenant-before-tenant-proof dependency cycle.

   A separate operator-only CPU guest may supplement only finite shared host-network-policy evidence when its pinned guest base, actual default bridge and virtio NIC, and loaded policy structure are bound to the paid deployment. The same-path packet test can establish the observed bridge/source-CIDR/destination/port/connection-state rules because those selectors do not depend on payment identity, VM UUID/MAC, GPU, or grant. Keep this result distinct from customer proof: it establishes none of the paid tenant's identity, credentials, privilege, grant, GPU workload, payment, delivery, or lifecycle outcomes, and it does not prove universal network isolation.

   The supplemental observation showed the configured finite TCP management targets refused, while DNS over UDP/TCP and the configured TLS path succeeded. The guest had only an IPv6 link-local address and no default route, so an unreachable result is not attributed to an IPv6 firewall drop. The unprivileged guest could not create raw packets; source-guard behavior was checked with separately operator-injected packets, which says nothing about buyer privileges. One external relay-SSH probe row was excluded from the aggregate assertion and remained disconnected, so every recorded endpoint result must be reviewed instead of relying on the aggregate pass. The supplemental fixture cleanup is complete: the owned guest lease and fixture state were removed, while unrelated lease/service state and the guest base and host policy remained unchanged. This closes only the supplemental fixture cleanup, not a paid-customer lifecycle or a broader cleanup claim.
5. Preserve canonical resource and pool identities. Do not rename real resources to match fixed Alkahest fixtures. Drain before mode changes; keep UID consumption history, protected host policy and relay holdings through recovery. Recovery is exceptional and limited to the campaign's own jobs/leases; no routine rollback or duplicate backups.
6. SDK compatibility gates funding and affected consumer rollout; it does not require the independent SDK change to archive before preparation. Freeze/review the actual applicable source candidate before destructive qualification, reusing unchanged component evidence.

## Accepted method mapping

| Owning item | Arkhai method and required observation |
|---|---|
| Relay 16.1 | Actual frpc/frps negative admission per lane with refusal logs and no backend connection; reuse only with unchanged relevant inputs. A real paid grant later proves valid admission. |
| Relay 16.2 | Two CPU-only VM deals via the shipped buyer, first SSH heartbeat across second create and teardown, delivered shape and wrong-key refusal, ordinary natural expiry and independent guest/access removal. |
| Relay 16.3 | Management-client generation and authenticated connectivity before, during and after those operations; no restart or lost control. |
| Relay 16.4 | Equivalent two-VM direct cycle in a drained controlled pool over an operator-routable test path; no public management exposure and no claim of external relay proof. |
| Relay 16.5 | Real Arkhai bare-metal rental, pinned relay endpoint, nonroot delivered user, checked GPU work and wrong-key refusal, ordinary bounded reclaim, access denial and capacity restoration. |
| Relay 16.6 | Repeat supported canonical registration and listing adoption on the same stack; no new physical allocator or unrelated state changes. |
| Relay 16.7 | Bind source, artifacts, configuration, run, payment, reservation, job and grant evidence privately; record sanitized outcomes for sibling obligations and quarantine-correct release. |
| Cleanup 4.1 | Normal bare-metal cycle with existing probe/observer: active shell/process/schedule, home/scratch/path/SystemV/POSIX objects; ordinary cleanup removes covered activity/account/private group/data/IPC and preserves sentinels. Successor gets fresh UID/key and cannot access predecessor data. |
| Cleanup 4.2 | Successor cycle with one nonce-scoped foreign descendant: observe actual refusal, queued retry, held capacity and notification; repair only that fixture before exhaustion, observe same ordinary job complete and final inventory clean. Terminal failures remain failures with audited recovery. |
| Cleanup 4.3 | Freeze and independently review/validate applicable integration source before destructive cycles; existing unit/native/mock results do not stand in for hardware. |

A normal bare-metal GPU cycle and successor/refusal cycle may cover several rows. Do not add an automatic third rental when the clean cycle's candidate and relevant inputs are unchanged. Relay port availability follows expiry/quarantine, while compute capacity follows verified teardown. No immediate port-reuse assertion overrides the contract.

## Risks / Trade-offs

Procedure evidence can omit an assertion that a fixed test driver supplied → require per-row evidence and explicit unproven dispositions. Private orchestration can carry stale source or destructive IDs → bind every attempt to fresh inventory, current candidate and its own lease before mutation. Concurrent hardware lanes share a payer → correlate or serialize financial observations. Imports can silently require a development chain → reuse neutral helpers without importing complete chain-specific drivers.

## Migration Plan

Only this branch's planning acceptance methods change; preserve original branch and completed task history. Update relevant helpers only when required and verify their consumers. Prepare restricted paid cycles, then general external GPU acceptance, then remaining recovery and closeout. No product or database migration is introduced by this method change.

## Implementation cadence

Section 1 reconciles proof ownership and prepares executable inputs. Section 2 records actual qualified cycles and exceptional recovery. Section 3 promotes only verified reusable instructions and closes out. Focused tests/packaging apply to any helper changes; one full review/validation per frozen implementation round.

## Design promotion record

| Decision | Permanent destination | Status |
|---|---|---|
| Payment-specific proof equivalence and observation/recovery boundaries | `openspec/specs/test-compatibility/spec.md#requirement-arkhai-physical-qualification-uses-ordinary-buyer-settlement`; `openspec/specs/test-compatibility/spec.md#requirement-equivalent-physical-proof-preserves-lifecycle-invariants` | Merged at archive |
| Procedure, supplemental network-method limit and evidence ownership | `openspec/specs/test-compatibility/architecture.md#payment-evidence-ownership` | Promoted in this closeout |
| Reusable buyer/operator preparation and scenario procedures | `docs/development/TESTING.md#accepted-arkhai-purchase-qualification`; `docs/development/VALIDATION_RUNBOOK.md#29-qualify-an-ordinary-arkhai-purchase` | Promoted from completed observations |
| No new repository-wide authority or dependency boundary | `docs/development/ARCHITECTURE.md#authority-boundaries` | No-impact disposition confirmed |
