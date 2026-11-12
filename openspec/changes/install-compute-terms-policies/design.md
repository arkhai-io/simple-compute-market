## Context

What the code does today, read before designing:

- `default_buyer_refusals` (`market_settlement_runtime.rate_publication`) is the buyer's whole rights policy: for a mechanism with a lifecycle adapter it refuses an option with no delivery deadline, an on-demand option with no positive premature-stop penalty, and a payee stop or term end that charges the final partial period.
- `BuyerTermsPolicy` (`market_settlement_runtime.buyer_terms`) raises those refusals unless `allow_unprotected_terms`, then asks `AuthoritySelection` to admit and rank the option's dispute authority, which runs `validate_terms`.
- `validate_terms` (`market_deal_lifecycle.terms`) repeats one of the refusals: a compute buyer context refuses a missing deadline unless `TermContext.allow_missing_delivery_deadline`. The flag sets both.
- `PaymentApproval.check` accepts a `terms_policy` no composition passes, so a recurring option always meets the default refusals at approval, whatever selected it.
- Seller: a storefront publishes what its operator's publication clauses derive. Its own choices are two constants in each composition's publication step: `default_penalty_periods=24`, and publishing every derived option while reporting the default buyer's refusals as `default_buyer_refusal` diagnostics. At negotiation the buyer's proposal selects an advertised option by identity (`selected_settlement_artifact`); lifecycle terms are never countered, and `SellerRoundHook` decides price alone through the named negotiation middleware chain.
- Plugins: `core_buyer.plugins`, `core_storefront.domain_plugins` and `market_delivery.discovery` each read one `importlib.metadata` entry-point group. The storefront loader is the one that resolves a configured name: it refuses a name two distributions provide, names the installed alternatives when the configured one is absent, checks the exported type, and takes an injected `installed` sequence for tests.

## Goals / Non-Goals

**Goals:** a buyer and a seller each install a policy package and select it in configuration; with no configuration every decision is today's; the flag keeps working; the checks that are not policy stay outside a policy's reach by construction.

**Non-Goals:** as the proposal lists.

## Decisions

### D1 The protocols live in the settlement runtime kit

`market_settlement_runtime.terms_policy` holds both protocols, the loader and the packaged policies. The kit already owns `default_buyer_refusals` and preset derivation, both compute compositions of both roles depend on it, and its scope is empty, as a policy over `SettlementOption` and `LifecycleTerms` needs.

Alternatives: `core/buyer` beside the domain loader cannot serve a storefront and cannot import `LifecycleTerms`, which a kit owns. `kit/deal-lifecycle` owns the terms but not publication or the refusals, and the payments kit would gain nothing by the lower placement. `kit/policy` is the negotiation middleware kit, which neither buyer composition's selection path imports. A protocol per domain would make a policy package choose a domain, and the refusals are schema-independent.

### D2 One loader, two groups, the storefront contribution loader's conventions

Groups `market.buyer_terms_policies` and `market.seller_terms_policies`, registered as plugin groups owned by `arkhai-kit-settlement-runtime`, which registers the packaged policies without becoming a plugin (as `kit/delivery` does its built-in sinks). `load_terms_policy(role, selection, installed=None)` follows `discover_storefront_domain_registry`: only the selected entry point is loaded; a name two distributions provide is refused; an absent name is refused naming the installed ones; the export is type-checked. A selected policy that fails to load or build is an error, never a fall back to `default`, since a fallback would change decisions silently.

Alternative: the aggregation policies' loader (decorator registry, then files under the user's configuration directory, then entry points). Rejected: three sources with precedence is the second loader the task forbids, and a file under a configuration directory is not an installed package.

### D3 Selection is a root `terms_policy` key

`terms_policy = "name"`, or a `[terms_policy]` table whose `name` selects and whose other keys are the policy's settings. Absent means `default`. It sits at the document root beside `[[Dispute]]` and `use_registry_dispute_authorities`, read case-insensitively the same way, in the buyer's configuration and the storefront's. A process has one role, so one key serves both.

An entry point resolves to a factory called with the settings mapping. A policy with thresholds needs somewhere to state them, and handing it the whole document would hand it credentials. The packaged policies take no settings and refuse any.

### D4 A buyer policy returns refusals

```python
class BuyerTermsPolicy(Protocol):
    def refusals(self, offer: BuyerTermsOffer) -> Sequence[str]: ...
```

`BuyerTermsOffer` carries the option, its decoded lifecycle terms, whether the mechanism has a lifecycle adapter, and the source registry URL. An empty result accepts. `default` returns `default_buyer_refusals`; `permissive` returns nothing.

Ordering is a separate method (D10), so a policy implements either.

### D5 A policy can only refuse

The line: a policy states which valid, serviceable, authority-accepted options this party declines. Everything else runs whether or not a policy is installed, and a policy has no return value that skips it:

- decoding and `validate_terms`: the adapter, the dispute interface, the authority's advertisement and minimums, the dispute window against the delivery deadline, the case-hold cap, a stoppable part, supported partial periods, the reserved bond;
- dispute-authority acceptance, which has its own configuration;
- mechanism compatibility, installed stages and rate servicing declarations: what the composition can service;
- the accepted Agreement equalling the selected option, exact mandate re-derivation, and receipt, signature and pin verification.

The protocol enforces this by shape. `refusals` and `review` return reasons to decline; the admission that calls them runs every other check regardless of the answer. A policy that raises refuses the option on the buyer side and aborts publication on the seller side.

One refusal changes sides. A missing delivery deadline is refused twice today, by the default refusals and by `validate_terms` under `TermContext.allow_missing_delivery_deadline`. The specification calls it the default buyer's refusal, waivable by opting out, so it is policy: the flag and the check leave `validate_terms`. Under `default` the refusal is the same and carries the same message, because the policy's refusal already ran first. `validate_terms` still adds a stated deadline to the minimum dispute window.

### D6 Approval asks the same policy

`PaymentApproval` takes a `BuyerTermsPolicy` and asks it about the accepted Agreement's option; with none it applies `default`, as now. Both compute buyers pass their selected policy. Approval does not re-run authority ranking: that is per source registry and was decided at selection, and the mandate check binds the accepted authority. This is the one decision that differs from today, and only under `permissive`: see the proposal.

### D7 The seller seam is at publication

```python
class SellerTermsPolicy(Protocol):
    def default_penalty_periods(self) -> int: ...
    def review(self, offer: SellerTermsOffer) -> SellerTermsReview: ...
```

`default_penalty_periods` is the premature-stop penalty, in periods of the quoted amount, for an on-demand preset whose clause names none. `review` sees each derived option before it is published and returns refusals, which withhold it with a `seller_terms_policy_refusal` diagnostic, and diagnostics, which are reported and do not withhold. `default` returns 24 and the `default_buyer_refusal` diagnostics the compositions emit today, and refuses nothing.

The policy does not rewrite an option: an option's encoding and identity are the mechanism's, and a rewrite after derivation would skip the validation derivation ran. What a seller offers beyond these two choices is already its own, as publication clauses per listing.

Publication cannot see who is buying or when, so a seller also decides at selection (D9).

### D8 The flag is shorthand in the buyer command

`--allow-unprotected-terms` selects `permissive` for that run. With a configured policy other than `default` or `permissive` the command refuses the combination, since replacing a policy the buyer installed with one that refuses nothing is not what a convenience flag should do unasked. The compositions take a selection, not a boolean.

### D9 The seller admits a selection last, and can only refuse it

```python
class SellerTermsAdmission(Protocol):
    def admit(self, selection: SellerTermsSelection) -> Sequence[str]: ...
```

`SellerTermsSelection` carries the listing's own copy of the selected option and its decoded terms, the buyer's identity, the listing record, and the time. The call sits at the end of each compute domain's round evaluation, the hook the negotiation runtime calls for every seller decision:

- The buyer is the one the runtime authenticated: `start` and `continue_negotiation` refuse an actor that is not the claimed buyer before any hook runs.
- VM: after the selected option's rate-servicing check, the shape checks, the reserved-duration check and the seller round hook, whose middleware chain holds the opening guards; the policy is asked only when that chain did not reject and the opening selects something the listing offers. Bare metal: at the end of exact-selection evaluation, after the mechanism, exact-match, servicing, admission, plan and amount checks; and, for an escrow opening, after the listing authorizes the escrow.
- Everything after the round's decision still runs whatever the policy answers: the runtime's own listing-source enforcement, the Agreement, the artifacts, the capacity hold.

A refusal becomes the round's `reject` decision with reason `seller_terms_policy_refusal: <the policy's reasons>`. The runtime already carries a reject: at an opening as `OfferUnfulfillableError`, which both storefronts answer with 409 `{"error": "offer_unfulfillable", "reason": …}`, and at a continuation as a terminal `reject` response with its `reason`. The reason field is free text on that wire and existing reasons are a code, sometimes followed by a colon and detail (`pinned_option_withdrawn: …`, `shape_exceeds_advertised: …`, `listing_not_open (status=…)`), so the refusal follows that form and adds no message type or field. The policy's text therefore reaches the buyer; a policy that raises refuses with a fixed text and its exception is logged, not sent.

An escrow opening selects an accepted escrow and no settlement option, so the selection's option is absent there. The policy is asked each round, since the time and its own state may have changed; a refusal mid-negotiation ends the thread as any seller rejection does.

Alternatives: a middleware in the negotiation chain. Rejected: the chain is operator-ordered and file-loadable, sees no verified buyer identity, and a policy placed in it could run before the guards. A new refusal error or status. Rejected: the buyer and any client reading `offer_unfulfillable` already handle this one.

### D10 A buyer preference orders one listing's acceptable options

```python
class BuyerTermsPreference(Protocol):
    def prefer(self, offers: Sequence[BuyerTermsOffer]) -> Sequence[BuyerTermsOffer]: ...
```

The core buyer's selection gains `option_order`: after the clause filter, compatibility and the admission's refusals, one listing's survivors are sorted as today (mechanism priority, dispute-authority rank, option identity) and handed to the preference; the core selects the first of what it returns. The packaged policies return their input, so the default rule is unchanged. Ordering cannot refuse or introduce: an offer left out follows the returned ones, an offer not given is an error, and a preference that raises fails the command, since a silent fallback would buy something the buyer's policy did not choose.

A policy implements any of its role's methods and the packaged default answers for the rest; the loader requires at least one. That keeps refusing and ordering separate without making an author write both.

What it does not order: listings. Across listings the first matching clause, then the highest-priority mechanism any listing's selection uses, then the best authority rank still filter, and the aggregation policy orders what remains and moves to the next listing when one fails. A preference for an option of a lower-priority mechanism therefore holds within a listing and can lose the listing to that filter when another listing selected a higher-priority mechanism. The bare-metal buyer buys one option by its identity and consults no preference.

### D11 A buyer is told when its own policy is why nothing matched

The admission keeps what the policy refused and what it admitted. When `market buy` finds no listing, or `market negotiate` no option, and the policy refused at least one option while admitting none, the command prints each refused option with the policy's reasons.

## Risks / Trade-offs

- A policy package runs in the buyer's or storefront's process with its privileges. That is what installing a package means; the protocol hands it no credentials.
- A seller policy's refusal reasons are sent to the buyer. The authoring guide says so.
- `validate_terms` no longer refuses a missing deadline for a caller that sets `buyer=True, compute=True` and consults no policy. No such caller exists; API credits is not compute.
- The `lifecycle_disclosure` rows named "Default buyer policy" still show the default's view, whatever policy is selected. They are disclosure, not a decision.

## Open questions

- Whether a preference should also reach across listings, which means deciding its precedence against mechanism priority and the aggregation policy (D10).
- Whether disclosure should show the selected policy's refusals beside the default's.
