# Design

**Rewritten 2026-08-06.** The original design proposed a 2×2 storefront-to-site topology
and recorded "Keep one market domain per storefront process" as an accepted decision.
Both are superseded. The original is in Git history.

## Context

Verified by inspection 2026-08-06; re-verify before implementing.

- `AggregateCapacityClient.reserve` takes an explicit `site` and, when given, reserves at
  exactly that site with no fallback — its docstring records why: trying another site on
  refusal "would silently satisfy the claim from a site the buyer never negotiated with."
  Already promoted as `storefront-publication`'s "Site-pinned claim routing".
- A listing's site mapping is read from durable storefront state
  (`site_id_for_listing`), so selected-site ownership survives a restart by construction
  rather than by cache.
- `kit/site` implements cross-mode conflict through `ALLOCATION_MODE_EXCLUSIVE` /
  `ALLOCATION_MODE_SHAREABLE` and `_allocation_mode`; `site-capacity`'s "Cross-mode
  physical accounting" is normative.
- `compute_provisioning_service.container` composes `vm_adapter_bundle` and
  `bare_metal_adapter_bundle` into one service through `compose_adapter_bundles`.
- Two implicit `"vm"` executor fallbacks exist — the ledger's inference from a `vm_host`
  attribute, and `deal_event_sink`'s `or "vm"`. Both are removed by
  `pool-declared-offering-modes`.
- No end-to-end scenario references bare metal or API credits, and none exercises more
  than one authority. Every proven deal path is a single-site VM deal.

## Goals / Non-Goals

**Goals:** prove the shipped capabilities hold together across two authorities and two
domains, under restart and under conflict.

**Non-Goals:** implementing any of them, many-to-many ownership, push delivery, new
domains.

## Decisions

### The topology is domain × authority, not storefront × site

The original 2×2 was (storefront × site) with the domain implied by which storefront ran.
Under multi-domain composition there is one compute storefront, so that framing has one
storefront and nothing to multiply.

The lifecycle edges that matter are unchanged in number and in what they prove:
VM-at-A, VM-at-B, bare-metal-at-A, bare-metal-at-B. Shared provisioning is demonstrated
by two domains reaching both authorities, which is exactly what the original four edges
demonstrated — the second storefront was never what made the proof work.

```text
compute storefront [VM, bare metal] ─┬──► authority A [VM, bare metal adapters]
                                     └──► authority B [VM, bare metal adapters]
```

### Many-to-many ownership is removed, not deferred

The original justified 2×2 as "the smallest topology that proves both
one-storefront/many-sites and one-site/many-storefronts." The second is removed on
repository-owner direction: there are no plans to support it.

It would also not have proven what it claimed. One authority binds to one storefront
today — a single `storefront_url` and one shared `storefront_admin_key` that both gates
inbound requests and signs the outbound callback — so two storefronts against one
authority would share a secret with no isolation. The original design conceded the
adjacent point, describing the callback path as "not a trusted ownership model" and using
pull reconciliation to avoid relying on it. What remained provable was that two
storefronts can poll one authority, which is a weaker claim than the topology implied.

Recorded at length because a future reader will find the 2×2 in history and reasonably
ask why it shrank.

### This change proves; it no longer implements

Everything the original would have built has shipped or moved. Site pinning, cross-mode
rejection, and concurrent adapter composition are implemented and normative; explicit
executor identity belongs to `pool-declared-offering-modes`.

That reduces the change to a `test-compatibility` delta, which is the honest shape. It
also means a defect this proof exposes is a defect in an existing capability and gets
fixed there — not patched in the harness, and not absorbed here.

### The legacy-row migration moves out

The original's task 3.2 was the only plan in the repository for durable reservation rows
with no recorded executor identity. `pool-declared-offering-modes` removes the fallback
those rows currently rely on, so it should own the migration for what depended on it. A
proof change should not gate a production data migration.

### Reuse the per-domain fixtures rather than building a parallel harness

`bare-metal-and-credits-domain-stacks` generalizes the end-to-end fixtures away from VM
assumptions and adds a complete deal path per domain at one authority. This change adds
one dimension to that: a second authority.

Building a separate multi-authority harness would duplicate the fixture work and
guarantee the two drift. If the generalized fixtures cannot be extended to two
authorities, that is a finding about those fixtures rather than a reason to fork.

## Risks / Trade-offs

- **[The proof is expensive to run]** → Deterministic in-process or containerized
  services with controlled adapters; observable barriers rather than sleeps; real-backend
  suites stay separate.
- **[Prerequisite contracts evolve underneath it]** → This change stays blocked until its
  prerequisites are accepted, and adds no proof-only production API.
- **[A defect is patched in the harness]** → Named above; the harness reports, the owning
  capability fixes.
- **[Textually equal identities across authorities are conflated]** → An explicit
  scenario. The routing key is the configured authority binding plus the
  authority-issued identifier, since authority-local identities are not globally unique.
- **[Pull polling conceals push defects]** → Push correctness is not claimed here.
- **[Overlap with the per-domain deal paths becomes duplication]** → Mitigated by reusing
  their fixtures; the marginal content of this change is the second authority.

## Migration Plan

1. Extend the generalized end-to-end fixtures to a second authority.
2. Stand up the deterministic topology.
3. Exercise the four domain-to-authority edges.
4. Prove restart, isolation, cross-mode rejection, and executor-identity strictness.
5. Promote the topology map.

No production behavior, persisted state, or wire surface changes. Rollback is removing
the scenario.

## Open Questions

- **Should the multi-authority scenario run in CI or on demand?** Two authorities plus a
  storefront is heavier than the per-domain paths. Deferrable: it is a scheduling
  decision that changes no requirement, and this repository has previously recorded
  end-to-end work validated only statically for want of a live stack — which argues for
  deciding it deliberately rather than by default.
- **Does a third authority prove anything a second does not?** Two is the smallest
  topology exposing cross-authority fallback and identity collision. Deferrable, and
  probably no.
