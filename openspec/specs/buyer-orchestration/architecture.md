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

A run also records what its selected settlement entry needs to know about the listing it negotiated, as one opaque `listing_record`. Core writes and reads it without naming its contents: the entry supplies it through the `accepted_listing_record` hook, and for Alkahest it is `kit/alkahest`'s record of the listing's advertised release conditions (`release_conditions_record`, read back by `recorded_release_conditions`). `market buy` writes it when negotiation starts and in an agreed completion; the negotiate commands write it at run start and at run end, whatever the outcome. A resume reads the record of the listing it resumes, per listing, so a run that negotiated several listings cannot fund one under another's conditions. A resumed escrow is derived from the run's recorded accepted proposal and that record, at the amount taken exactly from the recorded Agreement — the run-log's `agreed_amount` passes through a float — and must still equal the seller's recorded plan. Deriving against the listing as the registry now serves it was rejected: it adds a registry read to resume and refuses correct runs whose listing has since changed. A run accepted before release conditions were recorded is refused before funding, naming the reason, so a new run is needed; a run whose escrow exists derives nothing and resumes.

## Aggregation

Aggregation is buyer-local policy over discovered offers. Settlement-specific aggregation mechanisms may come from kit packages, but core does not assume a particular escrow, token, or market-domain score. Aggregation output is converted through domain codecs before entering negotiation.

## Identity-first execution

The composition root gives buyer orchestration one marketplace signer. The signer exposes an exact `{scheme, identifier}` principal; matching identifier text under another scheme is a different credential and cannot authorize the buyer. Discovery-authenticated calls, negotiation, storefront settlement, heartbeats, and recovery use that scheme-neutral operation, so core never receives a raw private-key field, infers a principal from wallet material, or branches on the signer's scheme.

Marketplace identity and transaction credentials have independent lifetimes. Wallet and chain settings are optional until domain and settlement selection identifies an EVM effect. A Arkhai payment path therefore uses the same buyer lifecycle with an Ed25519 signer and without wallet derivation, balance or gas checks, RPC or chain configuration, or an Alkahest client. An Alkahest path separately resolves and validates the EVM wallet and chain inputs owned by that adapter; even when marketplace signing and transaction signing use the same underlying EIP-191 key by explicit configuration, core does not infer that coupling.

Run logs persist the canonical public principal, signature-contract version, accepted obligation and operation identities, and domain state required to resume. They do not serialize credential material. Recovery checks the complete recorded principal and permits a different credential only when a completed rotation authorizes it as an active replacement, before submitting another authenticated or settlement mutation.

A protocol `signer` field is public evidence only when it is exactly the canonical
`{scheme, identifier}` mapping validated by the identity codec. Run-log validation
preserves that evidence unchanged while refusing signer objects, private fields,
noncanonical or extended mappings, and secret/provider carriers at every nesting
level. The field name alone grants no exception.

Settlement polling sends only public status to progress observers. The complete
authenticated delivery result returns through its private result boundary, so
credentials cannot enter a run log through a progress callback. Retained journals
remain recovery evidence; reading or resuming them does not rewrite their events.

## Configured mechanism choice and buyer actions

The buyer intersects installed, enabled registration compatibility with its
explicit buyer-role stage table before applying ordered clauses or priority.
Registration does not imply execution support. Accepted work resolves only
`Agreement.settlement.mechanism`, including after a priority change; a missing
entry is an actionable refusal before effects.

`make_settle_hook(stages=..., invoke=...)` invokes the selected opaque stage
with the unchanged `NegotiationResult`. The domain supplies the invoker and
entry-specific acceptance validator. The validator receives the exact
`NegotiationOutcome` after generic Agreement/party/option checks and before
accepted-round observation or persistence. Alkahest-only artifact requirements
belong there. An entry can bind `make_escrow_settle_hook` explicitly; neither
proposal presence nor absence selects it.

What an Agreement and its listing determine the buyer derives for itself, and the
seller's copy is compared, never used: the accept reply carries no escrow terms,
and the buyer materializes its escrow through `kit/alkahest` from its accepted
proposal or selection and the listing's advertised release condition. The plan
check runs where funds move. `make_escrow_settle_hook` takes a required
`check_escrows_fund_plan` port, which each buyer fills with `kit/alkahest`'s
`require_escrow_terms_fund_plan`, run over the buyer's own derivation before any
escrow is created; an acceptance carrying no seller plan is refused before
funding as `seller_plan_missing`, since a seller accepts an escrow only with its
plan. Every resume path derives through `kit/alkahest`'s
`derive_accepted_escrow_terms`, which holds the derivation to the recorded plan.
The selection-branch validator, `AdvertisedPlanValidatorFn`, checks the
selection branch at acceptance; the plan check is a separate port rather than a
widening of it because API credits opens with escrow
proposals, which that validator never sees. The plan that stays in the reply is
the seller's committed copy the buyer compares against, which also exposes
derivation skew between buyer and seller before funds move. `core/buyer` imports
no `kit/alkahest`.

Prerequisites are late-bound: Arkhai payments uses trusted service policy and
owner-scoped credentials, while Alkahest resolves its own EVM inputs.
Mechanism-specific continuations stay with the selected entry, not a common
buyer-first sequence. Buyer recovery uses the recorded settlement reference,
exact Agreement bytes and domain settlement data; the buyer keeps no
SettlementEvidence. Seller delivery is authorized only by the storefront's
verified evidence.

The buyer preserves exact Agreement bytes and opaque settlement data in accepted run state. Its `payer_account` travels in selection params, independently of the profile signer. It validates the seller-derived mandate against that Agreement and local policy, approves and polls the same transaction ID, then calls compute seller `commit` (API credits uses settle) with only the negotiation ID. Resume does not reconstruct the Agreement or use current priority to fail over.

VM `market negotiate` and API-credit `market credits negotiate` use their
respective buyer tables for selection enrichment, accepted artifacts,
pricing/prerequisite resolution and proposal construction. Interrupted rounds
retain the recorded selection, provision terms and scaled opening/ceiling
rather than applying fresh admission or token scaling. Fresh VM
acceptance requires an explicit advertised settlement selection; accepted
recovery uses the exact Agreement and persisted concrete Alkahest proposal when
applicable, not current publication policy.

Normal buy and accepted-run settlement commands derive mechanism details from advertised and accepted state. Arkhai payments has no Stripe payer-profile, instrument setup, browser funding, or off-session automation command.

## Bare-metal accepted authority

The installed bare-metal contribution preserves the selected profile signer, exact advertised option, Agreement, settlement data, and registry/storefront trust. Payment approval and seller settlement retain those identities. Physical result and access calls address the accepted selected-site authority; current configuration and caller-supplied URLs cannot redirect them. Buyer-only access coordinates are transient and absent from durable run logs.

## Compute terms before approval

Both compute buyers — `market buy` and `market negotiate` for VM, `bare-metal buy` — check and show a compute option's terms before the buyer approves anything, and they share the same pieces from `kit/settlement-runtime` so the two cannot drift.

**Checking the horizon.** The seller resolves a recurring horizon at acceptance, but the seller's resolver protects only against the seller's own mistakes; what holds against a counterparty that signs other terms is the buyer's own check. One pure function beside the seller's `resolve_horizon`, sharing its bound arithmetic, refuses a signed `duration_seconds` above either listing bound at the Agreement's start, holds an explicit horizon to the buyer's request and an omitted one to the default bound. The check needs the listing the buyer selected, which core's acceptance guard never sees, since the guard receives only the outcome. Core's negotiate hook therefore takes an optional per-listing `acceptance_validator`, a factory from the candidate listing to a check of the accepted outcome, run after the stage's own acceptance check and before the acceptance is observed; core knows nothing of bounds, and the domain binds them. A buyer that named no horizon compares a provision duration with the Agreement's only where it asked for one, because the seller keeps the buyer's signed provision terms, which carry none, beside the resolved duration. A resumed VM run checks against the bounds its acceptance record kept, what was advertised when it negotiated, never a current listing; a record kept without bounds holds the duration to the buyer's request, and an omitted horizon without bounds refuses, which no released run reaches because a released VM run always named a duration.

**The numbers come from the mechanism.** A buyer never parses a mechanism's payment fields. Each installed registration's `present_payment` returns the quote, the separate setup once charge and the initial reserve in the quote's asset and minor units — zero meaning none, null undetermined rather than a guessed zero — and the registry checks the basis and asset and that an accepted quote comes back unchanged. The buyer renders those beside the derived class, the price's unit, the asking rate, both bounds, the horizon and the lifecycle rows the shared codec decodes, on stderr even when no prompt is shown, so bare metal's JSON stdout stays usable. A fresh display reads the listing's bounds and the requested horizon; an accepted display reads only the Agreement, never a current listing, so an accepted horizon cannot be shown as extendable. VM's public price bounds stay hourly and are scaled to one period for a recurring option and to the requested span for a reserved one, through a per-match unit-count hook core calls without knowing the units.

**What the display claims.** It shows only what an authority enforces. Reserve is reserved funds, not spend and not a cap on a dishonest seller's billing. The penalty is a ceiling, taken from what the seller has earned and not yet been paid — at the start of a deal the setup charge, and nothing when nothing is held. A filed case shows the authority's per-part `held` or `not_held` answer, never a pending refund. A setup charge is owed from approval, kept by the seller if the buyer stops, and returned only when the seller never delivered. An option whose mechanism has no lifecycle adapter, Alkahest today, is shown as making no delivery promise rather than refused for lacking one. A setup charge and a refusal to deal with churners are the seller's pricing and policy, so neither buyer asks for a minimum-spend term.

**One policy, one waiver per term.** The shipped default policy, `default_buyer_refusals`, refuses an option with a lifecycle adapter that has no delivery deadline, an on-demand option with no positive penalty, and a payee stop or term end that keeps the started period; both buyers compose it over the deal-lifecycle `AuthoritySelection`, refusing before ranking, and the seller's publication diagnostic reads the same policy and wording. Each refusal has its own waiver, and one table in `buyer_terms` holds the four with their flags, help and the shorthand `--allow-unprotected-terms`, so all three commands declare the same flags; only the deadline's waiver sets the deal-lifecycle allowance for a missing deadline. A single blanket waiver was rejected because it made a caller waive four protections to pass one. The waivers in force are recorded in run metadata as `compute_term_waivers` and named, with the refusal each waives, in both pre-approval disclosures. Payment approval applies the same run's policy: both buyers hand their run's `BuyerTermsPolicy` to the payments kit's `PaymentApproval`, which refuses at approval exactly the default refusals the run did not waive. Approval reads the waivers, not the policy's authority ranking: selection ranked the dispute authority against the listing's registry, which approval cannot see, and the exact mandate check binds it to the accepted option. A resumed or recovered VM run reads its waivers from that record, the ones its selection was made under, and refuses waiver flags given to the resuming command, as it refuses a new shape or clause: a resume that could add a waiver would accept an option the run never chose under it.

**Duration.** A recurring purchase may omit its horizon; a reserved one names it, and `bare-metal buy` alone supplies its configured `default_duration_seconds` for a reserved option that names none. Whether an option is reserved is the mechanism's billing projection, a `total` unit, never a payment field the buyer reads, and the run records that the default applied. VM's commands take `--duration-seconds` beside `--duration-hours` and refuse both together before any identity or registry read.

`bare-metal buy` purchases only the hosted options its installed payments stage supports. Its shared rights policy and disclosure still admit an Alkahest peer on the same listing, as making no delivery promise, without a fabricated purchase stage.

## API-credit payment recovery

API-credit buys preserve the accepted option, exact Agreement, and mandate rather than reconstructing a partial listing. Approval and polling retain transaction identity, and seller settle calls identify only the negotiation. Seller receipt verification precedes recoverable, idempotent credits issuance. Credentials use the private buyer result channel; a missing credential response is not permission to charge or issue again.

## Delivery-only ends and case evidence

The canonical `end` verb, VM `market end` and `market bare-metal end`, is registered
from the `kit/deal-lifecycle-buyer` half for both domains (`market bare-metal
teardown` is its deprecated alias, keeping the progress-only output and exit 0 its
callers parse), and a once-only deal's end composes the signed canonical client
`end_delivery(negotiation_id)`. They require an accepted settlement-stage run and
address its retained storefront, not a current listing. No caller-supplied `at`
is allowed. The storefront signs its own durable receipt instant; same-key retry
keeps it and an earlier selected final request still controls. A once-only or
current Alkahest end is delivery surrender, not a fabricated payment stop/refund.
The lifecycle read keeps physical progress available even when authority state
is unsupported or unavailable.

The buyer verifies the seller's acknowledgement through the foundation's neutral
binding verifier and retains exact request/response bytes under the negotiation.
If surrender is selected, its embedded mediation `SignedDeliveryEndClaim` binds
payer cause, delivered=true and the receipt instant. The buyer can file that
claim as concurrence with exact Agreement and evidence. An uncertain response is
resolved by same-key surrender retry before fixing the claim; an earlier seller
end suppresses automatic payer filing. Original case ownership/adoption and
separate pending/unknown progress survive restart. Payment and dispute calls
report their own authority's answers; the storefront is no payment-command relay.

A rate deal's `end` is the buyer's own stop, then a hint, keeping service through
any priced notice and retrying a stop the payment authority could not receive under
its same key
([deal-lifecycle, "Buyer surrender and cases"](../deal-lifecycle/architecture.md#buyer-surrender-and-cases)).
The display separates delivery acknowledgement, payment effect and case protection,
and `end` exits nonzero when the governing outcome is not accepted.

The buyer keeps signed acceptance before commitment, peer/site/authority bytes and
its own delivery/access observations separately from seller assertions. It verifies
a site report directly only with independent site trust; otherwise it keeps the
report for adjudication. Prune refreshes each deal's records before applying the
frozen Agreement window; unavailable/incomplete observations and adapter-less
deals retain evidence. Export preserves exact bytes and superseded commitments.
API credits checks full authority identity at selection/approval but composes no
buyer lifecycle evidence/filing path. See
[buyer surrender and cases](../deal-lifecycle/architecture.md#buyer-surrender-and-cases).

## The buyer's watchdog

If a rate deal's resource is lost while the seller's storefront is down, the buyer is
charged until its own stop lands. The watchdog bounds that from the buyer's side, in
the process the buyer already runs: there is no buyer daemon, so `buy --watchdog`
stays in the foreground instead of returning at commit. Once the deal is available it
probes, every `--watchdog-interval` seconds, whether the deal's disclosed SSH endpoint
accepts a connection, and after `--watchdog-threshold` consecutive failed probes it
sends the buyer's ordinary entitled stop and hint through the rate end above,
journals the probe evidence it acted on, and exits. It also exits when the deal ends
by any other path or the buyer stops it. The opt-in, interval and threshold are
persisted per deal in the buyer's profile before commit, so resuming the
run — VM's `market buy --from <run>`, bare metal's `market bare-metal buy --from
<run>` — re-enters the loop after a restart where the deal is still running. The probe
loop lives in the buyer half, and each domain injects its probe, so the kit learns no
credential format.

**The probe uses no credential.** It asks only whether the disclosed endpoint accepts
a connection; an endpoint that accepts connections while refusing the buyer's key
passes, so the watchdog covers one failure, the endpoint no longer accepting
connections, not the buyer's workload or login. An authenticated probe was rejected:
the stop the watchdog sends cannot be undone, and an authenticating probe would turn a
key the buyer rotated, an exhausted connection limit or a slow login into that stop,
and bring the buyer's credential into the loop.

**The bound is conditional, and stated as one wherever the watchdog is described.**
Only while the command runs, the loss of that endpoint is detected within at most
`interval × threshold + probe timeout`; the authority's acknowledgement and any priced
notice come after that, and billing runs until the stop lands. The bound holds
because each probe starts on schedule: a probe and the loop's check that the deal has
ended run side by side, each cut off at the probe timeout, the probe timeout never
exceeds the interval (an opt-in with a shorter interval shortens the default timeout
to it), and the schedule runs on a monotonic clock, so a wall-clock step cannot
postpone a probe. The defaults are conservative — a 60-second interval, five probes
and a 10-second timeout — because a transient outage must persist before an
irreversible stop. The watchdog sends nothing the buyer could not send by hand and
asks nothing new of the authority.

**The status rests on the last probe.** Every probe, passed or failed, records its
wall-clock instant per deal beside the opt-in. The buyer's deal read — `market
delivery` in VM and `market bare-metal delivery` in bare metal, registered from the
buyer half beside `end` — shows `monitored` while `now − last probe ≤ interval + probe
timeout` plus a small fixed grace, `stopped` once the watchdog has journaled its stop,
and `unmonitored` otherwise, a deal never opted in included. So a crashed, killed or
hung loop reads as unmonitored, never as protected; the opt-in alone says only that
the buyer asked for a monitor. The status is the buyer's knowledge of its own process:
the buyer half computes it when it composes the read and the CLI displays it beside
the lifecycle read; no lifecycle wire model carries it and the storefront neither sees
nor reports it. The freshness rule compares a kept instant with the reader's wall
clock, which a backward step makes look fresher by the step, an accepted limitation
since the reader is another process.

A stop the authority refuses is final under its operation key and leaves the deal
billing: the watchdog exits with a `rejected` outcome, never `stopped`, names
immediate surrender (`end --end-now-regardless`) as the buyer's remaining route
without taking it, and `buy` exits nonzero, as `end` does for a stop the authority did
not accept. The read still shows `stopped`, meaning the watchdog journaled its stop,
beside the lifecycle read's payment state.

While end service refuses every rate deal's commit no rate deal reaches `available`,
so the loop, its stop and its status are proven without a delivered deal; the
delivered-deal cases — the real `buy` probing from `available`, access lost with the
storefront stopped yielding a single buyer stop, a killed command reading
`unmonitored` once its last probe goes stale, and a resumed run reading `monitored` —
run once rate servicing delivers rate deals.

## Current limits

The core buyer application refuses at startup a root command name two installed domains register, naming both, because with two domains installed one domain's command would otherwise run as the other's, decided by entry-point discovery order. That check covers root names only; the plugin boundary and shipped export contracts do not prove that every arbitrary third-party command composes without collision. Persisted recovery covers documented stages; it is not a universal exactly-once transaction spanning registries, storefronts, and settlement mechanisms.

## Related contracts

- [Marketplace identity](../marketplace-identity/spec.md)
- [Market composition](../market-composition/spec.md)
- [Registry discovery](../registry-discovery/spec.md)
- [Negotiation protocol](../negotiation-protocol/spec.md)
- [Settlement servicing](../settlement-servicing/spec.md)
