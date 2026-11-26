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
The codec maps started_period/last_boundary/stop to charged/returned/prorated,
which the payment authority prices; the payments transaction adapter composes rate
behaviour in only for a mandate with a rate part.

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
| `kit/deal-servicing` | Seller dispatch/read/list, the servicing cycle's step order and page position, observation cursors, end/admission journal, evidence/retention and respondent discovery and answers |
| `kit/arkhai-payments` | Stateless payment adapter composing once and rate parts, published resources/models/vectors and shared clock-injected fixture engine |
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

**The kit owns each deal's servicing order.** Each compute storefront's
`deal-servicing` loop runs `ServicingCycle.cycle` (`market_deal_servicing.servicing`),
which services one page of deals per cycle in one order. It first runs respondent
discovery once per dispute authority on the page, since the respondent listing is
scoped by the authority's one credential: a `RespondentPoller` built per cycle over its
durable cursor, whose record is derived from the authority's identity alone. A deal
with no dispute authority, or whose authority's credential is unusable, is left out,
its credential repair already showing it. The kit's one `resolve` maps a listed case to
its local deal and dispute adapter by commitment; a case naming no local deal is
skipped, and one whose Agreement digest differs from the local deal's raises, so it
stays a respondent repair naming the mismatch. Then, for each deal in order: the
authorities read, the domain's recovery steps, the physical end, local reconciliation,
site-report correction, filing dispatch and the physical end again, run twice because
reconciliation, correction and filing can record an end the first drive could not see.
Every step, each authority's discovery included, runs in its own error handler and is
logged naming the domain, the step and the deal or authority, so a failed step skips
nothing after it. A domain contributes only its steps — its site-report recovery and
its site-report correction, which applies the compute family's site classifier — and
a respondent port of two operations, `credential_available(authority)` and
`dispute_adapter(binding)`, with its signer and clock beside them.

Every registered deal is paged, committed or not, so an uncommitted surrender still
gets its physical end; the payment and dispute authorities are read only for a
committed deal, and filings are sent only in the filing step. Local reconciliation
admits a missed delivery deadline and then, once admission is not awaiting a payment
observation and the Agreement's end has passed, records the deal's own term-end final
request at that end, classified `terms`, in both domains; a payment authority's own
stop at the same instant sorts before it by source. The cycle keeps its page position
in the kit-owned `servicing_page_position` table (`market_deal_servicing.schema`), one
row per loop, saved once a page is serviced, so a restarted storefront resumes from it
and one stopped mid-page services that page again.

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

**One compute-family classifier for every payment stop.** `classify_payment_stop`
(`arkhai_compute.end_classification`), beside the site classifier and `payment_actor`,
classifies every verified payment final stop the watch records, once-only deals'
included. Both storefronts' watch factories pass it through
`DealWatch(classify_payment_end=...)`, bound to the deal's accepted entitlements and the
Agreement's end, its start plus its duration in whole seconds:

| Cause | Classification |
|---|---|
| `payer` or `payee` | `entitled_stop` when the accepted entitlements name that party, else pending |
| `authority` | `ruling` |
| `terms` | `terms` when effective at or after the Agreement's end, `exhaustion` before it |
| anything else | pending |

The payment authority records funds running out and the term end under the one cause
`terms`, so the stop's effective instant tells them apart; the recorded cause stays the
authority's. When the watch reads a stop it recorded earlier with its classification
pending, and the classifier classifies it on that read, it keeps the recorded end and
resolves only the pending slot, once, through `EndSession.resolve_correction`. Each
compute buyer passes the same classifier to the buyer half for its own read.

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
intent/key/evidence belongs to end service; delivery retains its reference. A
once-only deal's billing start is a validated no-op.

**A changed authorization answer holds a phase back.** `EndService.authorize_delivery`
asks the deal's payment adapter for every phase of every deal, whatever its parts; a
servicing declaration enables rate offers and does not decide their delivery. End
service journals one authorization answer per phase and admission revision, and the
first `allow` or `refuse` journaled for a phase at a revision stands for that revision;
a `pending` answer is journaled without completing, so it stands for nothing. A
once-only adapter's answer depends only on stored evidence, but a rate adapter reads a
fresh signed snapshot each time, so its answer can change while the revision stands
still: an `allow` turns `pending` while the payment authority is slow or unreachable or
its snapshot is stale, or turns `refuse` once the authority shows a stop the watch has
not yet recorded. When the adapter later answers a phase differently at the same
revision, end service returns `pending`, its reason naming the journaled answer and the
changed one, and journals nothing; the delivery path drives a pending phase again later.
Answers are compared by status alone, since a fresh read's evidence references differ
every time. A changed answer can therefore only hold a phase back, never advance one, as
financial evidence only narrows admission. The watch's record of an end moves the
revision, and admission then answers `ended`; an end already due by now is admission's
own refusal and is returned as it is, not as a changed answer. Teardown follows the end
the watch records, never an authorization.

**The deadline barrier.** An undelivered rate deal waits until the deadline rule above
classifies non-delivery and files `delivery_end(cause=payee, delivered=false)`, which
returns a priced setup part. A rate buyer ends at the payment authority, and its hint
is a courtesy lost while the storefront is down, so end service learns of the stop
only when the payment watch
records the authority's final stop. For a deal that is not once-only, admission's
missed-deadline branch therefore acts only on a successful payment observation made
at or after the deadline that shows no lawful end effective at or before it. Until
one is made admission answers `awaiting_observation` at the unchanged revision; end
service keeps an answer that admits nothing and turns an allow into pending, so
nothing is recorded or filed. The servicing cycle reads the payment authority before
its local reconciliation admits a deadline. The observation instant is the
storefront-clock instant taken before each successful payment read, kept in
`servicing_payment_observations` in the transaction that records what the read showed.
An authority outage delays the setup's return while the buyer's money stays held at
the authority. Once-only deals keep the rule without the barrier, since their buyer
ends at the storefront and nothing earlier can go unobserved.

**When a deal is ended.** A recorded end is physical and local, so the seller's `list`
shows a deal with a recorded end `ended` only when it has ended physically, at the
payment authority and at the dispute authority: its physical progress is `released`; every payment part in its saved payment view has a
final stop or an `end_at` at or before now, and a deal that is not once-only, whose
rate parts the payment authority's view lists started or not, is still billing when
that view lists no part or none is saved; and, when it names a dispute authority, a
view of that authority is saved and shows no case open. Otherwise it is `ending`, and
`DealSummary.ending` names each outstanding condition from the closed codes
`release_pending`, `payment_running`, `case_open` and `case_unobserved`.
`kit/deal-lifecycle-contracts` carries each code's text in `ENDING_TEXT`, which
`DealSummary.ending_reasons` pairs with the codes, so every reader renders the same
words and a new code arrives with its text. A repair-required deal is listed
`repair_required` with no codes, and the single-deal `read` carries none. The list
reads the views the servicing cycle's authorities read saves, so a case filed after a
deal is listed `ended` returns it to `ending` with `case_open` once the next read saves
it.

A view is saved only from an accepted read. The authority learns an Agreement from its
first filing, and the mediation adapter (`kit/arkhai-mediation`) takes its first-page
`404 invalid_request` as an accepted read of an empty record, no dispute and no case;
so a deal nobody filed on is observed with no case, in the seller's list and read and
the buyer's read alike, and `case_unobserved` remains for an authority that has not
answered or for which the storefront composed no adapter. That read is not verified.
The authority gives a reader who is no party the same `404`, and no published route
says which account a credential authenticates, so the read rests on a premise the
contract gives no way to check: that the credential authenticates the Agreement's
party. A seller whose mediation credential authenticates another account sees every
unfiled deal, and any case filed against it before its first accepted read, as no
case, so a released, paid deal with a case open can be listed `ended`. That
misconfiguration also shows as its filings refused `filer_not_party` and its
respondent listing empty.

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

The buyer's canonical `end` verb, `market end` and `market bare-metal end`, is
registered from the buyer half (`register_end_command`) and uses the same lifecycle
client in both domains, with recorded profile signer and storefront trust;
`market bare-metal teardown` is its deprecated alias, printing a notice naming `end`.
For a once-only deal `end` is the surrender below.
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
and case protection are distinct outcomes.

A rate deal's normal end is the buyer's own stop: `end` journals the payer's stop at
the payment authority, then sends a stable-key `hint`. With a nonzero payer notice it
sends no `end_delivery`, and delivery continues until watch observes the effective
stop and end service acts. A hint or read failure never changes the stop's outcome.
When the payment authority cannot be reached, the buyer half keeps the journaled stop
and retries it under the same key, and billing runs until it lands; the storefront is
never a buyer payment-command relay and cannot stop the buyer's billing.
`end --end-now-regardless` sends `end_delivery` after the stop, surrendering service
before the paid notice expires, and escalation reuses the original stop. The buyer's
watchdog sends the same stop
([buyer orchestration, "The buyer's watchdog"](../buyer-orchestration/architecture.md#the-buyers-watchdog)).

Case payloads include exact Agreement, commitment, terms, fixed claim and ordered
exact evidence; no payment attachment is required. The mediation adapter alone
owns interface requests and claim framing. Online/operator callers reserve one
original semantic filing in caller-owned storage; others adopt one equivalent
signed filed record. Unresolved ownership is pending. Ambiguous originals and
unsupported linked revisions require repair, not a fresh key or append-as-amendment.
Initial missing history permits the original filing, never an acknowledgement without
a signed filed entry; an ordinary read takes it as an accepted, unverified empty record
("When a deal is ended" in
[One end instant, transactional admission](#one-end-instant-transactional-admission)).

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
journals exact signed concurrence for matching durable facts, or contesting evidence,
before advancing its cursor, kept per dispute authority. Foreign commitments are
skipped and local unresolved rows retry fairly. Deal watch uses the same
case-keyed answer, waits rather than replacing it, and may advance on confirmed
closure. Discount-only rulings do not end delivery. SCM preserves signed aggregate
penalty answers without inventing per-part monetary decomposition.

## Seller notice and administrator interruption

A spot seller's notice is one command at the payment authority. It runs through the
seller-authenticated, negotiation-keyed lifecycle `submit` as kind `notice`, admitted
only when the accepted Agreement — never today's listing — grants the payee a stop
entitlement and its adapter supports rate stops. It submits the stop at once with the
explicit affected parts and an optional future `at`, which cannot shorten the
authority's notice. The authority hosts the pending stop and its `partialPeriod`, so
nothing schedules a stop locally and the storefront need not resume for it to take
effect; the command returns the authority's pending stop and effective time, or
pending, unknown or rejected, and a lost response is resolved by `read`. An earlier
buyer stop wins at the authority, and repeating the notice cannot postpone it.
Lifecycle `read` and `list` expose each part's pending and final stops
(`authority.parts`). A stop request stays distinct from a final stop and never ends
delivery. The read and list carry every field of their models, defaults included, and
the client shipped with the storefront reads every deal shape they serve. The operator
verb is `deals preempt <negotiation-id>` in both storefront CLIs, through the typed seller
lifecycle client, printing the authority's outcome unchanged. An on-demand refusal
names `delivery_end` as the path for actual seller non-delivery only, and files
nothing.

Administrator interruption states its cause, `interruption_kind = preemption |
failure`, beside a free-text reason. `kit/deal-servicing`'s seller half classifies it,
and both compute storefronts mount the administrator route over that classification:
preemption is `notice`, refused without a payee entitlement; failure journals the
operator end, then files `delivery_end(cause=payee)` and drives physical teardown side
by side. A rate deal, recognised by the committed `SellerDeal.once_only`, must state
its kind; a once-only deal defaults to failure, as the released route's callers
expect. The operation key is derived from the request when the caller sends none, and
a same-key retry changing the administrator or reason is refused.

## Site evidence and retention

The site records intended-end payload, its `site.lease_ended` event and the signed
report atomically with its ending transition, before teardown, and the report's
push to the storefront is a separately acknowledged consumer of that event. Stored
signed wrappers
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

The published per-part contract carries authorities per part — `{stop: [{account,
notice, partialPeriod}], reverse, extend, start}`, `start` on rate parts — and
`partialPeriod` ∈ `charged | returned | prorated | chosen` on stop entries, on every
part end and on the pending and final stop records. An entitled stop takes effect at
`max(at ?? now, now + senderNotice)` at authority receipt and is never backdated; the
earliest pending stop wins and cannot be withdrawn; no stop privilege is implied by a
role, and there is no payee waiver of payer notice or payer early release. Approval
reserves the first batch; periods begin at the payee's `start` but stay reserved until
the period ends or the part stops. Exhaustion stops every co-funded part at
`fundedThrough`, and a part's `end` stops it, each with cause `terms`, even if no party
acts. A stop's `settled` figures are not restated after a later reversal, so
reconciliation reads the recorded reversals, and approval answers
`409 insufficient_funds` when the payer cannot cover the first reservation. Declaring
any rate treatment presupposes that the payment authority executes the dispute
entry's `chosen` stop, which no double can establish. SCM's VM live verification
compared the hosted authorities' outputs with the lane doubles': a payer's stop under
`charged`, exhaustion at `fundedThrough`, a payee's stop with notice and a part's end
under `returned`, and the mechanical ruling of a payee's `delivery_end` filing, whose
authority stop through the `chosen` entry returned its period beside the capped
penalty; an operator's ruling of a contested case is unproven live, since no
topology applied a ruling policy
([live verification summary](../../../docs/attachments/switch-on-hosted-per-period-vm/live-verification.md)).
The producer's stop-retry vectors are fixed-clock fixtures.

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
  redirected to and a new signer fails verification. SCM assumes each environment's
  payments receipt key stays stable for a deal's life, since the payments service
  publishes no retention commitment or rotation announcement; a key change is a
  drained cutover, run from the operator handbook, and addresses neither dispute
  identity history nor a signed successor hand-off.
- How the dispute authority dismisses and rules cases, its advisory time to rule and
  its continuity are its own published policy and procedures; SCM's operator
  handbook states what SCM relies on and points to that policy rather than
  restating it.
- An unresolvable unanswered counterparty case holds that deal's dispute cursor;
  respondent discovery at its authority continues and repair rows rotate, but later
  per-deal events wait for its answer journal or confirmed closure.
- The mediation read of an Agreement nobody filed on is unverified: under a seller
  credential authenticating another account, a released, paid deal with a case open
  can be listed `ended`
  ([One end instant, transactional admission](#one-end-instant-transactional-admission)).
- Storefront retention has no production prune trigger. No real bare-metal host
  access/revocation qualification is established by mock/in-process passes.
- Which hosted targets run a mediation authority, and at which revision, is the
  deployment's and the authority's maintainers', outside this repository. Isolated
  local real-authority runs do not upgrade or qualify a hosted target.
- A storefront runs no funding timer: a running rate deal's funding stop reaches end
  service only as the payment authority's recorded stop. Rate deals' delivery and
  servicing, rate commands, the rate buyer end and seller notice are proven against
  in-process authorities and the lane doubles; against deployed authorities only
  VM's payment outputs and dispute filings are compared live, in mock provisioning,
  each a boundary comparison testing nothing downstream of the authority's output.
  Revised-remedy execution, bare metal and the consolidated rate and ruling matrix
  are not qualified against a deployed authority.
- API-credit options carry authorities/holds and validate authority identity, but
  their roles compose no lifecycle evidence/watch/respondent or buyer filing path.
  Reversal consequences for already-issued credits are unspecified.
- Hosted bonds, specialized Alkahest arbiter/adapter, independent delivery
  attestation and broader automatic adjudication are not implemented. Alkahest is
  used at the user's own risk; current claims remain enforceable only at the
  authorities their committed mechanisms support.
