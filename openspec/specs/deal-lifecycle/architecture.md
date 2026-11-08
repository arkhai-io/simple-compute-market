# Deal Lifecycle Architecture

## Commitment and authority

Discovery, negotiation and the selected mechanism's commitment act are protocol.
After commitment, peer exchanges and fulfillment are lifecycle: a refusal to
continue leaves evidence of an obligation, not an incomplete negotiation.
The negotiated Agreement is input to the mechanism's committed form. Hosted
payments commits a mandate bound to the JCS hash of that Agreement; Alkahest
commits arbiter and DemandData. The buyer derives and checks the form before
committing. No universal cross-mechanism agreement digest exists.

A deal's dispute authority is independent of its payment authority. The accepted
option pins interface, origin, account, record key and interface-owned params.
Configuration selects new offers, not authorities for running deals. Full identity
matching prevents a real account from being paired with an attacker-controlled
origin or signer. Registry recommendations are operator-authored discovery data;
buyers opt in explicitly, while local full-identity preferences and vetoes prevail.
Credentials bind separately by that identity, so preference changes cannot redirect
servicing. Missing accepted-authority credentials are visible repair state.

## Parts and terms

An option separates commercial `price`, schema-tagged mechanism `settlement` and
codec-owned `lifecycle`. Canonical option identity includes all present groups;
selection mirrors the schema with buyer-owned parameters. Common lifecycle query
projections match the same option and asset as the price predicate: missing
notice/deadline remains missing, absent entitlement is false and absent penalty
is integer zero. The Agreement's start and duration define the absolute horizon;
there is no second maximum term in an option.

Payment adapters translate deal commands into per-part operations at the
mechanism's actual joints. Hosted once parts have no start or stop. Their
prepaid-service end is the Agreement term end; setup encodes Agreement start,
effectively clamped to approval by the payment service. Holds derive from the
part's own end plus the agreed dispute window, independently of approval expiry.
Only the accepted dispute authority receives extend/lift permission and its cap
is carried into every part (null means unbounded). Party stop entries derive only
from entitlements; notice and partial-period treatment cannot be waived locally.
The codec maps started_period/last_boundary/stop to charged/returned/prorated.
Rate execution is not supplied by the once-only adapter.

The dispute authority advertises its minimum window as a nonnegative safe integer;
the consumer does not substitute a fixed duration for that policy. Compute terms
cover the delivery deadline plus the advertised minimum, and the payment hold
uses that complete accepted window. A shorter advertised minimum does not shorten
the delivery allowance, relax the buyer's timing checks or change the authority
and terms pinned by an existing Agreement.

Premature-stop penalty is a canonical nonnegative decimal string in the option's
asset minor units, absent/zero meaning none. A bond is reserved seller stake
beyond reversible held payment, not another name for that penalty. Hosted
builders refuse bonds. Alkahest releases whole escrows or declares a split; it
has no lifecycle adapter and emits no lifecycle terms. Its release-model options
are recipient, oracle_gated or interruptible where the domain supports them.

## Package and counterpart boundaries

| Package | Responsibility |
|---|---|
| `kit/deal-lifecycle-contracts` | Commands/outcomes, per-part payment and per-agreement dispute events, peer messages, routes and evidence carriers |
| `kit/deal-lifecycle` | Terms, adapter protocols/tables, evidence interface, neutral response acknowledgement binding/verifier |
| `kit/deal-lifecycle-client` | Typed signed storefront lifecycle transport |
| `kit/deal-lifecycle-buyer` | Buyer dispatch, file-backed evidence, end retry plans, prune/export; client and Agreement projection injected by the domain |
| `kit/deal-servicing` | Seller dispatch/read/list, observation cursors, end/admission journal, evidence/retention and respondent answers |
| `kit/arkhai-payments` | Stateless once-only payment adapter, published resources/models/vectors and shared clock-injected fixture engine |
| `kit/arkhai-mediation` | Stateless dispute adapter/client, claim framing/signing, published resources/models/vectors and contract fixtures |
| `kit/alkahest` (`market_alkahest.payment_adapter`) | Once-only payment adapter for `alkahest.v1`: no financial action after the composition's commitment validator accepts the selected stage's evidence |

Current Alkahest authorizes delivery through `AlkahestOnceAdapter`, which composes
`OnceDeliveryPolicy` as `kit/arkhai-payments`' adapter does. It refuses evidence
naming another deal or commitment before the injected validator runs, supports no
payment command, so `submit_payment` refuses every one, makes billing start a
no-op only with activation evidence, and answers a read as rejected naming
`alkahest.v1`, so a lifecycle read of an Alkahest deal shows delivery with no
payment account. Each compute storefront supplies its own validator, since its
commitment differs: VM's is the escrow reference, bare metal's the Agreement
digest. The adapter sits in the mechanism kit, not the compute delivery library,
which knows no mechanism. A missing table entry still never implies allow, and an
Alkahest deal's `delivery_end` filing stays unsupported.

Mechanism and dispute kits depend on foundation/contracts, not either role's
orchestration. A dispute kit names one interface, never a payment mechanism;
compatibility arrives as authority advertisement data. Domain roots inject both
adapter families. Core buyer binds no lifecycle kit. Storefront loops are hosted
by the shared loop controller; the site has no payment dependency or credential.

| Actor/action | Counterpart whose answer is reported |
|---|---|
| Buyer negotiate, commit, hint, end_delivery | Storefront |
| Buyer approve or an entitled payment command | Payment authority |
| Either party file, append, read cases | Agreement's dispute authority |
| Seller voluntary reverse and supported entitled payment commands | Payment authority |
| Seller end physical delivery | Its own storefront/end service |
| Dispute authority extend, lift and remedy effects | Payment authority, outside SCM |

Commands have stable operation keys and accepted/rejected/pending/unknown outcomes.
Unknown is not failure or success: read and same-key retry resolve it. Payment and
dispute records have separate sequence/cursor domains; no global order is inferred.
Exact signed records are retained separately from each refresh's current outcome.
Snapshot verification checks mode, deal/mandate/receipt binding, identity validity
windows and the durable minimum sequence before state consumption. A failed refresh
does not turn an old verified view into current successful observation.

## One end instant, transactional admission

End service retains every final request: stable source identity, actor, cause,
instant, evidence and controlling source, including equal-time/superseded requests.
Earliest instant wins; stable identity orders ties (buyer-surrender/payment-stop
sources sort before site-event echoes). There is one delivery end, not separate
local financial and physical end decisions. Ruling attribution uses the pinned
dispute-record signer; payment account-to-principal mapping is injected from
accepted identities and never inferred from account syntax.

Caller-session revision/CAS admission orders reserve, dispatch, activation/start
and disclosure against end recording. A stale admission retries without effects.
Authority I/O runs outside write transactions; a bounded local apply callback may
share admission's transaction. Async database units run on workers, including
negotiation capture and report ingress; borrowed-session methods remain synchronous
for their transaction owner. Constructors do not initialize databases.

`record_end` atomically keeps the request and required filing or pending
classification slot. Classified lawful ends include verified entitled stops,
terms, rulings and surrender. Seller failures include unentitled withdrawal and
established non-delivery. Ambiguity remains pending without delaying physical work.
The compute-family pure classifier correlates retained physical command identities;
a site echo adopts its controller's classification/filing rather than creating a
second fault. `resolve_correction` validates and adopts that controller in the same
journal without rewriting the immutable report. A later source is only evidence
once the selected end is classified; a pending selected report cannot discharge an
independently established seller failure's filing.

Non-delivery is established at the earlier of term end and the accepted delivery
deadline after max(commitment, Agreement start), without durable timely available
evidence. Site activation is not buyer delivery. Never-delivered correction fixes
Agreement start as its basis: journal now, wait until start if future, and never
future-date or recompute a filing. A later lawful stop cannot erase prior failure.
A seller exceptional end journals a cause=payee case and sends no stop/reverse for
that remedy. Physical teardown does not wait for filing, classification or ruling.

Due ends terminate now; future ends truncate at second precision or finer.
Before dispatch, release only behind the site's guard; in-flight create is adopted
then terminated. Queued teardown is never reported as released. Billing-start
intent/key/evidence belongs to end service; delivery retains its reference. The
neutral phase/evidence protocol exists, but once billing start is a validated
no-op, and activation/rate/funding-timer consumers remain separate work.

## Background readiness adoption

Seller servicing owns progress after a compute commitment, even when the buyer
disconnects. It observes an already dispatched fulfillment through the domain's
validated delivery path, preserving selected-site/resource identity, evidence,
deadlines and end-service admission. Site activation alone is not proof that the
buyer received delivery. Repeated servicing keeps the same fulfillment and the
original availability instant; it can complete missing result or receipt writes
without dispatching another create.

Readiness observation, site-end recovery and physical teardown are independent
attempts. A failed observation waits for a later servicing cycle without blocking
cleanup. A selected end or expired delivery admission prevents late readiness
from exposing access or reopening delivery. Buyer status and access reads may
observe progress, but they are not required to drive it.

## Buyer surrender and cases

`market end --from <run>` and `market bare-metal teardown` use the same lifecycle
client through the buyer half, with recorded profile signer and storefront trust.
end_delivery has no supplied at: the seller signs its durable receipt time and
preserves it on retry. It ends delivery immediately, even before fulfillment or
without a financial adapter. Once-only/Alkahest surrender invents no refund or stop;
outside-settlement introductions refuse it. Reads return delivery evidence even
when the authority view is explicitly unsupported or unavailable.

When surrender is the selected end, its receipt embeds the dispute adapter's
SignedDeliveryEndClaim(cause=payer, delivered=true) for that receipt instant.
The buyer verifies/keeps it and can file it as concurrence. A payee-signed claim is
the one assertion the authority rules on without a person, and only because of its
direction: signing "the buyer surrendered at T" or "I never delivered" can only
cost the payee, so there is nothing to weigh; an assertion the seller could gain by
is evidence a person weighs against the buyer's own records, and silence rules
nothing. An uncertain surrender
is retried under the same key before a claim is fixed; a selected earlier seller
end suppresses automatic payer filing. Delivery acknowledgement, payment command
and case protection are distinct outcomes. Rate stop-then-hint, notice-preserving
service and outage retry execution require a rate adapter; the storefront is never
a buyer payment-command relay.

Case payloads include exact Agreement, commitment, terms, fixed claim and ordered
exact evidence; no payment attachment is required. The mediation adapter alone
owns interface requests and claim framing. Online/operator callers reserve one
original semantic filing in caller-owned storage; others adopt one equivalent
signed filed record. Unresolved ownership is pending. Ambiguous originals and
unsupported linked revisions require repair, not a fresh key or append-as-amendment.
Initial missing history permits the original filing only, not a verified empty
ordinary read or an acknowledgement without a signed filed entry.

An existing case read preserves the authority's protection outcome envelope.
Accepted protection must name the requested case, Agreement and transaction;
pending protection must name the requested case and stays pending. Neither
answer is signed filing evidence: adoption still verifies the original signed
record, and a pending or mismatched answer never authorizes another filing.

Either party appends evidence while a case is open; only the payee appends
concurrence. The window matters because triage has no response bound and the
respondent contests with evidence of its own: a buyer that could not answer in the
same case would open a second one to rebut. A closed case takes nothing, and later
evidence is a new case the authority nets against the first. Respondent discovery
journals exact signed concurrence for matching durable facts,
or contesting evidence, before advancing its account cursor. Foreign commitments
are skipped and local unresolved rows retry fairly. Deal watch uses the same
case-keyed answer, waits rather than replacing it, and may advance on confirmed
closure. Discount-only rulings do not end delivery. SCM preserves signed aggregate
penalty answers without inventing per-part monetary decomposition.

## Site evidence and retention

The site records intended-end payload and separately acknowledged event outbox
atomically with its ending transition, before teardown. Stored signed wrappers
survive retries and signer changes; authenticated lease reads recover the same
bytes. Both parties retain obtained reports. The site report is independent
signed evidence, not a payment stop, delivery attestation or proof of free capacity.
A buyer verifies it directly only with independent trust in the site signer;
otherwise it keeps the bytes for adjudication. A seller can withhold a report,
so buyer protection cannot depend on receiving it.
See [site capacity](../site-capacity/architecture.md#intended-end-evidence) and
[physical provisioning](../physical-provisioning/architecture.md#lease-end-report-delivery).

Evidence is keyed by negotiation because acceptance precedes commitment. Both
parties keep the counterparty's signed acceptance-path message, peer envelopes,
obtained authority records, site reports and end requests/effects separately from
replay state. Administrative acceptance retains its author. Seller assertions,
buyer observations and independent records are distinct classes; seller available
is not conclusive proof against a buyer's access-failure evidence.

Retention eligibility is one frozen Agreement window after the latest observed
delivery end/physical recovery, every part's final payout and every case close.
Incomplete or unavailable observations retain evidence; first observed completion
instants do not slide on refresh. Uncommitted acceptances use acceptance expiry.
Buyer prune refreshes before deletion; seller watch composes the observer and
refresh-before-prune API, but production storefronts invoke no prune trigger and
therefore retain evidence indefinitely. Deals without terms/adapters are retained.

## External authorities

The following is context from the published authority contracts, not requirements
that SCM implements or a claim that a particular hosted deployment runs them.
Only those authorities decide/apply money; SCM derives authorized inputs, verifies
and reports their records, and ends delivery from a recorded delivery ruling.

Payments is a per-part ledger: reverse can partially/repeatedly return held money;
release/fees are its own. A case protects only money for which payments accepted
the authority's idempotent extend, before payout. Extensions have independent refs;
lifting one case cannot release another case's hold. Normal end-plus-window payout
and agreed finite/unbounded caps constrain extensions. Late cases cannot recover
paid-out money. Funding and scheduled rate stops are authority behavior, not local
clock-derived corrections.

Mediation verifies the case-carried Agreement against mandate.deal. Its one claim
is delivery_end {ended_at, delivered, cause=payee|payer}. Signed concurrence binds
the Agreement digest, exact claim and Agreement seller, framed through identity
under arkhai.mediation.delivery-end-claim.v1 for ed25519/eip191. Mechanical rulings
require payee filing or valid seller concurrence, clean Agreement mapping,
non-prestart time and no prior mechanical delivery-end ruling. Other cases remain
human-triaged; silence never rules. Signed basis is payee_filed/payee_signed/operator.
No response bound is asked of the authority and none is a gate: a binding bound ends
cases filed faster than they can be ruled in default judgements against someone, and
one large enough to avoid that is no bound. Parties agree to their authority before
the deal, and a seller mistreated by one chooses another for its next deals; the
marketplace does not protect a party from its own chosen mediator. An advisory
expected time to rule, if the authority publishes one, is shown as advisory.

For cause=payee the authority stops rates now returned, reverses held earnings
since the fixed end and non-setup once unserved share, then caps the penalty at
remaining held earnings in mandate order: a 2400 minor-unit penalty with only 900
of earned amounts still held after refunds reverses 900, not 2400 or money already
paid out. A never-delivered rate deal whose billing started before the deadline
has everything earned since the Agreement start reversed, so its buyer's net charge
is zero. For cause=payer it preserves priced
notice/treatment, nets prior accepted/pending stops/effects, keeps non-setup once
and applies no penalty. Missing/chosen payer entry goes to an operator. Past
remedies use present stop plus held-money adjustment, never a backdated stop.
Setup is once with encoded end at/before Agreement start and returns iff
delivered=false for either cause. Effects/extension lifts belong to the authority.
Its filing response reports each part's protection or its own pending/error,
not a payments response passed through. No SCM computed remedy substitutes.

## Current limits

- The Agreement pins dispute origin and record key for deal/case life, potentially
  unbounded. No mid-deal address/key rotation is followed: a new origin is not
  redirected to and a new signer fails verification. Payments receipt identity
  overlap does not solve dispute identity history or signed successor hand-off.
- VM caches respondent pollers by accepted authority/account; bare metal constructs
  them per cycle. Both persist cursor/answer state, but lifetimes differ. Bare metal
  records local term-end final requests after checking admission; VM's recovery
  sweep observes missed availability deadlines and otherwise relies on site lease
  expiry/report recovery for term-end evidence. These are not domain requirements.
- An unresolvable unanswered counterparty case holds that deal's dispute cursor;
  account discovery continues and repair rows rotate, but later per-deal events
  wait for its answer journal or confirmed closure.
- Storefront retention has no production prune trigger. No real bare-metal host
  access/revocation qualification is established by mock/in-process passes.
- Hosted development mediation is on an older revision than the vendored contract.
  Isolated local real-authority runs do not upgrade or qualify that hosted target.
- Production rate start/stop and stop/hint retry belong to rate servicing;
  funding timers, revised-remedy execution and consolidated rate/ruling execution
  qualification are later Goal 8 work. Current foundations and once-only case
  filing/observation do not claim those outcomes.
- API-credit options carry authorities/holds and validate authority identity, but
  their roles compose no lifecycle evidence/watch/respondent or buyer filing path.
  Reversal consequences for already-issued credits are unspecified.
- Hosted bonds, specialized Alkahest arbiter/adapter, independent delivery
  attestation and broader automatic adjudication are not implemented. Alkahest is
  used at the user's own risk; current claims remain enforceable only at the
  authorities their committed mechanisms support.
