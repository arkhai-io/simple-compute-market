# Buyer Orchestration Architecture

The [normative contract](spec.md) defines buyer plugin and recovery behavior. This document explains how a schema-opaque CLI hosts domain behavior without owning market meaning.

## Plugin-host model

The core `market` CLI owns command discovery, stable orchestration inputs, persistence of run state, and progression through shared role protocols. Domain entry points contribute commands, listing interpretation, provision intent, terms codecs, and result presentation.

```text
core CLI
  ├── domain command and vocabulary
  ├── buyer policy and aggregation
  └── shared discovery, negotiation, and settlement clients
```

This keeps one buyer executable useful across shipped domains while ensuring installation of a domain package—not an import from core—introduces that domain's vocabulary.

## Ownership of buyer inputs

Buyer behavior has three owners:

- the domain defines what is being requested and how listings and terms are interpreted;
- policy selects payment choices, opening positions, aggregation, and round decisions;
- core supplies authenticated identity, stable orchestration context, persistence, and protocol sequencing.

The split prevents generic orchestration from acquiring pricing semantics and prevents policy middleware from constructing malformed domain messages.

## Settlement preference

Settlement compatibility remains an authoritative orchestration constraint, while preference is buyer-local policy. Resource filtering completes first. The buyer then removes options whose registrations are absent, disabled, or incompatible. Repeatable explicit settlement clauses are ordered alternatives across listings: all comparisons inside one clause must match the same advertised option, and the first clause with survivors wins before configured mechanism priority.

Only a noninteractive choice with several survivors reaches the optional preference hook. The hook receives frozen scalar views with opaque identities instead of mutable listing or orchestration state. Core invokes it twice with identical inputs and accepts only one identity or an ordered tuple of unique identities drawn from that input set. Exceptions, unknown or duplicate identities, and inconsistent results produce a warning and retain the constrained fallback path. A valid preference precedes deterministic option identity fallback; explicit interactive user choice bypasses preference entirely.

This split lets policy express payment choice without acquiring authority to make an incompatible settlement mechanism selectable. It also distinguishes “resources matched but settlement did not” from an empty registry result.

## Persisted runs

A buy run records selected domain, policy parameters, discovered candidates, accepted terms, deal references, and later lifecycle state as applicable. Persisting the selected policy and its inputs prevents recovery from reinterpreting an existing negotiation under newly changed configuration.

Recovery starts from the latest authoritative persisted handoff. If negotiation already produced accepted terms or settlement produced a deal reference, recovery inspects or resumes that stage rather than silently renegotiating and risking a second commercial commitment.

## Aggregation

Aggregation is buyer-local policy over discovered offers. Settlement-specific aggregation mechanisms may come from kit packages, but core does not assume a particular escrow, token, or market-domain score. Aggregation output is converted through domain codecs before entering negotiation.

## Identity-first execution

The composition root gives buyer orchestration one marketplace signer. The signer exposes an exact `{scheme, identifier}` principal; matching identifier text under another scheme is a different credential and cannot authorize the buyer. Discovery-authenticated calls, negotiation, storefront settlement, heartbeats, and recovery use that scheme-neutral operation, so core never receives a raw private-key field, infers a principal from wallet material, or branches on the signer's scheme.

Marketplace identity and transaction credentials have independent lifetimes. Wallet and chain settings are optional until domain and settlement selection identifies an EVM effect. A hosted-fiat path therefore uses the same buyer lifecycle with an Ed25519 signer and without wallet derivation, balance or gas checks, RPC or chain configuration, or an Alkahest client. An Alkahest path separately resolves and validates the EVM wallet and chain inputs owned by that adapter; even when marketplace signing and transaction signing use the same underlying EIP-191 key by explicit configuration, core does not infer that coupling.

Run logs persist the canonical public principal, signature-contract version, accepted obligation and operation identities, and domain state required to resume. They do not serialize credential material. Recovery checks the complete recorded principal and permits a different credential only when a completed rotation authorizes it as an active replacement, before submitting another authenticated or settlement mutation.

## Configured mechanism choice and buyer actions

The buyer receives installed and enabled mechanisms through the shared settlement configuration registry. With no explicit settlement clause, canonical configured priority is policy input among compatible pre-acceptance choices. Mechanism prerequisites are late-bound after resource and settlement selection: hosted fiat does not resolve wallet, chain, RPC, token, or gas inputs; an EVM selection resolves them through its owning adapter.

Transient buyer actions use one mechanism-neutral `open`, `print`, or `fail` policy on fresh and resumed runs. An action URL may be opened or printed for the current invocation but is never written to the run log. Raw setup and inspection utilities live below `market settlement <mechanism>`; normal buy, settle, resume, and service commands derive mechanism details from advertised or accepted state.

Priority and explicit clauses never authorize recovery-time failover. Accepted Terms, the obligation reference, and stable operation identities remain authoritative even if current priority, readiness, enablement, or command inputs change. Generated buyer configuration therefore contains shared selection vocabulary but omits seller account, onboarding, publication, authority-administration, and provider fields.

## Persistent payer binding and exact authorization

The marketplace buyer profile and hosted payer profile are separate identities. Owner-restricted local profile metadata keeps only the authority/environment binding, opaque payer reference, bound canonical marketplace principal, and safe lifecycle state. Payer create/setup/instrument administration calls the hosted authority directly through the released client under `market settlement stripe payer`; escrow status, reclaim, fulfillment, and collection remain storefront-mediated.

After accepted terms are durable, the buyer constructs one authorization from the immutable obligation hash, accepted amount/currency/destination/profile/expiry, deterministic marketplace operation identity, and the user-selected interactive or saved-instrument mode. Only the operation-scoped authorization reference is durable run state. Saved instrument references and transient setup, payment, confirmation, or bank-instruction details remain invocation-local.

Off-session policy evaluation never grants blanket charging authority. A qualifying accepted obligation may be signed without another prompt, while a refusal or hosted `requires_action` continues the same exact obligation through the common transient action policy. Restart re-fetches provider-neutral status/reason/deadline/action metadata and reuses accepted identities rather than persisting a URL or selecting another profile.

## Bare-metal accepted authority

The installed bare-metal contribution performs authenticated discovery, selects one exact advertised option, validates the option against the trusted physical listing, signs domain terms from buyer-owned duration and SSH public-key input, and stores the accepted option, parties, plan, obligation, and storefront authority under the persistent run identity. Hosted start/status/reclaim then use the core schema-opaque transport with that recorded signer and trust. CLI projections redact transient URLs; physical reclaim never implies lease termination after collection.

## API-credit hosted recovery

Fresh API-credit buys use the shared settlement registry to choose one
compatible listing option and preserve the accepted plan in the run log.
Hosted authorization is prepared from that plan and the selected persistent
profile; core transport sends only accepted negotiation/obligation identifiers
and the safe authorization reference to the storefront. Status, transient
actions, resume, and reclaim reuse the recorded signer and storefront trust.
The domain CLI returns buyer-authenticated credentials separately from public
settlement state and never treats absence of a returned secret as permission to
reauthorize or reissue.

## Current limits

The plugin boundary and shipped export contracts do not prove that every arbitrary third-party command composes without collision. Persisted recovery covers documented stages; it is not a universal exactly-once transaction spanning registries, storefronts, and settlement mechanisms.

## Related contracts

- [Marketplace identity](../marketplace-identity/spec.md)
- [Market composition](../market-composition/spec.md)
- [Registry discovery](../registry-discovery/spec.md)
- [Negotiation protocol](../negotiation-protocol/spec.md)
- [Settlement servicing](../settlement-servicing/spec.md)
