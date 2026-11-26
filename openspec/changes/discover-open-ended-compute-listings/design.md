# Design: discover-open-ended-compute-listings

## Context

**What an option states.** A settlement option carries `price`, `settlement` and, where
its mechanism has a lifecycle adapter, `lifecycle` terms the shared codec owns. The codec
projects seven common query fields from those terms
(`kit/deal-lifecycle/src/market_deal_lifecycle/projections.py`), among them
`early_termination.payer` and `early_termination.payee`. An entitlement the option does
not state projects false, including on an option with no lifecycle terms at all; a notice
or delivery deadline it does not state is missing, not zero. The codec refuses
`early_termination` on an option with no stoppable part, and Alkahest has no lifecycle
adapter, so an option billed once, and every Alkahest option, states no entitlement
(`kit/deal-lifecycle/src/market_deal_lifecycle/terms.py`). Every recurring preset grants
the payer a stop and grants the payee one only for spot
(`kit/settlement-runtime/src/market_settlement_runtime/rate_publication.py`). The codec
also admits a recurring option that entitles the payee alone, or nobody; no shipped
preset produces either.

**Where the fields are evaluated.** A settlement clause is one conjunction over one
option, evaluated by the buyer
(`kit/settlement-runtime/src/market_settlement_runtime/clauses.py`). The common fields
match every mechanism's options; a field a registration contributes, such as
`arkhai_payments.billing_kind`, matches only that mechanism's. The grammar has no
disjunction. The registry separately declares the same lifecycle projections as resource
filters, correlated to one option (`core/registry/src/core_registry/filter-spec.yaml`), so
a buyer may write them in a resource query; no settlement clause is sent to a registry.

**How the class is read today.** The buyer's display calls an option whose billing
projection is `total` reserved, and a per-period option spot when the payee is entitled
and on-demand otherwise
(`kit/settlement-runtime/src/market_settlement_runtime/buyer_terms.py`).
`docs/development/ARCHITECTURE.md`, "Discovery and negotiation", and the
`storefront-publication` and `buyer-orchestration` companions state the same reading.
Several requirements say "reserved" where their rule depends on billing by a total, such
as `buyer-orchestration`'s "Recurring purchase may omit a horizon".

**How each buyer selects.**

| Buyer | Query surface | How it chooses | How it carries the choice |
|---|---|---|---|
| VM: `market buy`, `market negotiate`, `market listing list` | `--resource`, repeatable `--settlement`, `--explain` | `BuyerSettlementPolicy.select_listings` (`core/buyer/src/core_buyer/settlement.py`): each listing's first compatible option of the first surviving clause; then only listings on the earliest clause any listing matched; then the most-preferred mechanism any listing offers; then the best option preference. It reads nothing but the listing; each mechanism's preparation follows per kept listing | A copy of the listing with `settlement_options` narrowed to the chosen option and `_selected_settlement` added (`domains/vms/buyer/src/arkhai_vms_buyer/buy_cli.py`) |
| API credits: `market credits buy` | `--resource`, `--max-matches` | Per listing in discovery order, each enabled mechanism's stage in priority order, stopping once the match limit's worth are usable, because a stage's choice may prompt or read a wallet (`domains/apicredits/buyer/src/arkhai_apicredits_buyer/buy_cli.py`) | A copy with `settlement_options` and `accepted_escrows` narrowed and `_selected_buyer_proposal` added |
| Bare metal: `market bare-metal list`, `market bare-metal buy` | `list`: `--resource`, printing the response. `buy`: a listing and `--option-id` | An exact lookup of the option ID among the listing's options, then the stage's and the dispute-authority checks (`domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py`) | The option itself, passed to negotiation |

Under the VM and API-credit paths, `kit/settlement-runtime`'s
`select_settlement_candidates` admits installed, enabled, compatible options and applies
clauses in order. Buyer orchestration resolves a domain hook's selection to the
advertised option through `selected_settlement_artifact`
(`core/buyer/src/core_buyer/orchestration.py`,
`kit/policy/src/market_policy/scalar_policies.py`). `option_id` is already a common
clause field, so an exact option is expressible as a clause. Recovery never selects: a
resumed run reads its accepted option.

## Decisions

### D1 — A class is read from the option's entitlements

A reserved lease is prepaid and non-interruptible: neither party may end it early. Who
may end the lease is what tells the products apart, so the class is read from the
option's early-termination entitlements and nothing else:

| Payer entitled | Payee entitled | Class |
|---|---|---|
| no | no | reserved |
| yes | no | on-demand |
| yes | yes | spot |
| no | yes | committed spot |

Spot is defined, as buyers know it from every cloud, by the seller's right to take the
capacity back; the buyer's right to stop goes with it there and is never part of its
definition. Reserved is capacity the seller does not take back during the term. A
committed spot lease is one the seller may end while the buyer is committed for the
term. No provider sells that under an adopted name, so its label composes two words
buyers know: "spot" places the option where a buyer expects reclaimable capacity, and
"committed" names what is unusual about it. Spot keeps the cloud meaning, both parties
entitled, so a buyer asking for spot never commits to a term; committed spot is asked
for by its own name.

How the option is billed does not enter: a lease paid by a downpayment, with further
payment due before the rate consumes it, is reserved while neither party may stop it. The
buyer's display, the shorthand of D2 and the permanent definition use this one reading.

For every option published today the reading agrees with the display: an option billed
once states no entitlement, and every recurring preset entitles the payer. No preset
publishes a committed spot option.

Rejected:

- Reserved as the billing projection's `total`, which the permanent documents state
  today. It makes the class a fact about payment, cannot name a reserved lease billed in
  parts, and needs a billing predicate no common field carries.
- Calling an option that entitles the payee alone spot. A buyer asking for spot could
  commit to a term without meaning to.
- "Interruptible reserved". It puts "reserved" on capacity the seller can take back,
  against this decision's own reserved.
- "Interruptible" alone. GPU marketplaces use it for spot.
- No label. The display and the shorthand would have no name for an option the codec
  admits.

### D2 — The shorthand expands to the two entitlement predicates

A class shorthand on a compute buyer's command expands to predicates on the common
fields alone:

```text
reserved        early_termination.payer=false early_termination.payee=false
on-demand       early_termination.payer=true  early_termination.payee=false
spot            early_termination.payer=true  early_termination.payee=true
committed-spot  early_termination.payer=false early_termination.payee=true
```

The expansion is conjoined with every explicit settlement clause and never forms an
alternative of its own; with no explicit clause it is the one clause. Because the fields
are common, one expansion holds across mechanisms and for any mechanism added later. The
explanation shows the expansion as the predicates it evaluated. No match is an empty
result: it does not relax the class, enable a mechanism or permit a substitution after
acceptance. The quickstart's recipes are these predicates, so the shorthand and the
recipe a buyer writes by hand cannot differ.

Rejected:

- A mechanism's billing field, as the quickstart's recipe uses. It matches one
  mechanism's options, so reserved across Arkhai payments and Alkahest cannot be one
  conjunction, and the grammar has no disjunction.
- A common billing field beside the entitlements. D1 leaves billing out of the class.
- A class applied outside the clause grammar. The recipes and the shorthand would then
  be two things to keep equal.

### D3 — An interruptible Alkahest option is a recorded gap

An Alkahest option states no lifecycle terms, so every one reads as reserved, the
interruptible splitter included, though its seller can interrupt it. Under D1 the answer
is that such an option states its payee entitlement in the common terms, and so reads
as committed spot, which needs a lifecycle adapter Alkahest does not have. This change adds no release projection and no
Alkahest clause field; the roadmap tables the gap under Goal 8's unowned work.

Rejected: a release-condition projection in the Alkahest registration. An option carries
an arbiter address and demand data, and telling the splitter from the oracle-gated
arbiter needs the chain's address book, which a clause projector does not receive and
`settlement-configuration`'s "Mechanism clause projections are public and observational"
keeps out of a projection.

### D4 — One selection serves the three buyers, and the listing stays as advertised

One kit-owned selection chooses, caches and resolves the advertised settlement option for
the VM, bare-metal and API-credit buyers. It carries its choice explicitly beside the
listing: the listing a buyer holds after selection is the listing the registry served,
with every option it advertised, and pricing, negotiation and revalidation read the
chosen option from the choice. The class of D2 is compiled once, in that selection.

Rejected: adding the shorthand to each buyer's own selection. The VM and bare-metal
storefronts are to become one storefront, so their buyers' commands are kept alike, and
three selections would each need the expansion, the explanation and their tests.

### D5 — The bare-metal buyer takes the VM buyer's query surface

`market bare-metal list` and `market bare-metal buy` take the resource query, the
settlement clauses, the class shorthand and the explanation mode that the VM buyer's
commands take, with the same meaning, through the selection of D4. The bare-metal buyer
still purchases hosted options only: an option it has no stage for is never chosen.

Rejected: a class filter on `market bare-metal list` alone, leaving `buy` to an exact
option ID. It would add a second way to narrow by class and keep the two compute buyers
apart.

### D6 — The registry's bound filters are another change's

Filtering listings by `max_duration_seconds` and `available_until_utc` is
`filter-listings-by-capacity-bounds`. It needs a filter-grammar extension and an answer
on released buyers that nothing here depends on.

## Open Questions

Each is decided in this change's design session.

### Q1 — The selection rule the three buyers share

The VM rule ranks across the whole discovered set and reads only listings; the API-credit
rule decides per listing and stops at the match limit, because its stages prompt or read
a wallet while choosing. `buyer-orchestration`'s "Credit purchases stop selecting at the
match cap" states the second for `market credits buy`.

- (a) The VM rule for all three, with the choice made from listings alone and each
  mechanism's preparation run only for the listings kept, up to the match limit. A credit
  buyer is still never prompted for a listing past its limit; which listings it keeps may
  change where an earlier clause or a preferred mechanism appears later in discovery
  order.
- (b) The API-credit rule for all three. The VM buyer would stop at the first usable
  listings and lose its clause and mechanism ordering across listings.
- (c) One selection with the rule as a parameter each buyer sets. Nothing changes for
  either buyer, and the two rules stay.

Recommended: (a). Clause order and mechanism priority are stated as properties of a
purchase, not of one listing (`cli-query-language`, "Settlement clauses are correlated
ordered alternatives"), and the match-cap requirement's purpose survives. It would change
if a credit stage cannot separate choosing from preparing.

### Q2 — The selection's interface and its package

Callers and what each needs of it:

| Caller | Needs |
|---|---|
| `market buy`, `market credits buy`, `market bare-metal buy` | Compile the clauses and the class; choose across discovered listings; a choice per kept listing naming the option, its registration and the clause it matched; the reasons options were refused |
| `market negotiate`, `market credits negotiate` | The same for one named listing |
| `market listing list`, `market bare-metal list` | The compatible options per listing and the chosen one, with no mechanism preparation |
| Explanation mode on each of the above | The same stages as selection, counted, with the class expansion, and no mutation |
| Buyer orchestration's negotiate step | The chosen advertised option for one listing, for the negotiation policy and revalidation, without resolving it again from a selection |
| Each mechanism's buyer stage | The choice to prepare from: the API-credit Alkahest stage picks an escrow entry and may replace the option; the payments stages add the payer account |
| The acceptance record and plan validator (`domains/vms/buyer/src/arkhai_vms_buyer/settlement_composition.py`) | The choice for a listing, which they read from `_selected_settlement` today |
| Introduction requests | An exact option by ID |
| Resume and recovery | Nothing: they read the accepted option |

A caller that reads the choice out of a rewritten listing today needs it passed. The
candidates for its home:

- (a) `kit/settlement-runtime`, beside `select_settlement_candidates`, with
  `BuyerSettlementPolicy` and `selected_settlement_artifact` reduced to it.
- (b) `core/buyer`, extending `BuyerSettlementPolicy`. Role implementations are
  compositions (`docs/development/ARCHITECTURE.md`, "Repository layers"), and the
  recorded item places the selection in kit.

Recommended: (a).

### Q3 — What the bare-metal purchase keeps of its exact form

`market bare-metal buy <listing> --option-id <id>` is what the bare-metal lanes and
`request-introduction` use. With clauses, `--option-id <id>` equals the clause
`option_id=<id>`.

- (a) Keep the listing argument and `--option-id` as an exact form beside the query
  surface, `--option-id` compiled to the clause.
- (b) Remove both; a buyer names an option by clause, as the VM buyer does.

Recommended: (a) for the listing, which `market negotiate` names too, and (b) for
`--option-id` once the lanes use the clause, so the two compute buyers have one spelling.
A purchase by query also needs a rule for several surviving listings; the VM buyer tries
up to `--max-matches`.

### Q4 — Whether the API-credit commands take settlement clauses and explanation

The shared selection gives them for free, and the two permanent requirements named in the
proposal already ask them of every domain's commands. The class shorthand is compute's
alone. Recommended: yes, in this change, since the selection the credit buyer moves onto
takes clauses already.

### Q5 — What the default buyer asks of a recurring option the buyer cannot end

D1 names both such options: a recurring option entitling nobody is reserved, and one
entitling the payee alone is committed spot. Neither is published today. Under either the
buyer has no stop: it is charged each period until the term ends, its balance runs out
or, for committed spot, the seller ends the lease. Selection without a class may choose
such an option like any other. A recurring purchase may omit its horizon, which then
resolves to the seller's whole bound. The default buyer refuses four terms a buyer should
not accept unknowingly, each with its own waiver; none concerns the payer's entitlement.

- (a) Nothing more: the display names the class and the term, and the buyer reads them.
- (b) The buyer names the horizon. An omitted horizon is refused for a recurring option
  that does not entitle the payer.
- (c) (b), and a default refusal of a recurring option that does not entitle the payer,
  with its own waiver. Naming the class does not waive it.
- (d) (b), and such an option is refused unless the buyer asked for its class by name.

Recommended: (c). A buyer should not be bound for a term by an option it did not ask
for, and payment approval applies the run's waivers, not what selection was asked, so a
consent given by naming the class would not reach approval. It would change if these
options are to be bought as freely as a prepaid reserved one.

### Q6 — Requirements that say "reserved" for a rule about billing

`buyer-orchestration`'s "Recurring purchase may omit a horizon", `negotiation-protocol`'s
"Compute horizons bind both seller bounds" and `storefront-publication`'s "Unbounded
recurring candidates close independently" and "Recurring publication checks servicing"
pair "reserved" against "recurring" where the rule depends on whether the option is
billed as a total. They hold for everything published today; a reserved or committed
spot lease billed by the period would fall on their "recurring" side. Open: whether this change
rewords them to name the billing unit, or leaves them until a reserved lease billed in
parts exists. Recommended: reword the `buyer-orchestration` requirement here, since the
buyer's duration default is code this change touches, and leave the rest.

### Q7 — Options the default refusals rule out

A purchase whose options the default buyer's refusals alone ruled out prints "No listings
matched" and exits 0 (`docs/development/ROADMAP.md`, Goal 8's unowned work). A class
makes this likelier: a spot option that charges the started period on a seller's stop is
refused by default, so `spot` can match nothing while spot options exist.

- (a) Take the item: record each default refusal among the selection's refusals, which
  the shared selection reports for all three buyers.
- (b) Leave it unowned.

Recommended: (a), now that one selection reports refusals for every buyer.

### Q8 — The shorthand's spelling and commands

Provisional conventions. `--class reserved|on-demand|spot|committed-spot`: the display,
the quickstart and `ARCHITECTURE.md` write "on-demand", and the fourth value follows it. On every compute command that takes
`--settlement`, as the per-term waivers are declared on all of them from one table.

### Q9 — Implementation cadence

Recommended: two rounds, one session each. First the shared selection, with the three
buyers moved onto it and the bare-metal query surface, changing no other behaviour.
Then the class reading, the shorthand, the display, the quickstart and the lanes.

## Verification

Provisional levels, for planning and review to confirm. The entitlement projections and
the class expansion are unit-tested in `kit/deal-lifecycle` and `kit/settlement-runtime`.
The selection's rule and its unchanged listing are unit-tested in its package, and each
buyer's commands in that buyer's CLI tests. Each compute lane's recurring purchase selects
its option by class, as the system-level proof.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 class read from the entitlements | `docs/development/ARCHITECTURE.md`, "Discovery and negotiation"; `openspec/specs/storefront-publication/architecture.md`; `openspec/specs/buyer-orchestration/spec.md` and `architecture.md` |
| D2 shorthand and its expansion | `openspec/specs/cli-query-language/spec.md`; `docs/buyer-quickstart.md` |
| D3 interruptible Alkahest option | none — a row of `docs/development/ROADMAP.md` |
| D4 shared selection | `openspec/specs/buyer-orchestration/spec.md` and `architecture.md` |
| D5 bare-metal query surface | `openspec/specs/buyer-orchestration/architecture.md` |
| D6 boundary with the bound filters | none |
