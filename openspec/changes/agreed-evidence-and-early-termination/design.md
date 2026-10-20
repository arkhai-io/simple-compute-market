## Context

What exists today (evidence for the decisions below, not a specification):

- **Agreement and authentication.** Negotiation is buyer-driven signed rounds. The seller's responses authenticate the seller principal, and accepted terms keep the exact buyer and seller parties (`negotiation-protocol`, "Principal-bound negotiation history"). The accepted settlement plan carries opaque `service_terms`, documented as the place for heartbeat cadence, oracle identity, and evidence format. The buyer client deliberately does not compare `service_terms` with the advertised option. The VM terms carry the buyer's `ssh_public_key` as a required field.
- **Per-mechanism evidence regimes already exist, implicitly:**
  - Alkahest obligations carry an arbiter and demand bytes. Under the default recipient-arbiter plan, delivery is decided by trusting the seller. Under oracle-gated plans, the oracle approves at lease end unless a dispute is raised; this default is stated only in code documentation.
  - `arkhai.payments.v1` mandates fix funding, holds, and per-event authorities, and carry the agreement's deal hash. The service evaluates no condition beyond its own funding and hold schedule.
  - Buyer-signed heartbeats are peer evidence (`settlement-servicing/architecture.md`, "Heartbeat evidence"); nothing yet presents them to an arbiter.
- **No link between negotiation and the on-chain commitment.** Nothing in core, kit, or domains puts a digest of the negotiated agreement into an Alkahest demand. An arbiter sees amount, recipient, and condition, not the negotiated terms.
- **Interruption today.** An interruptible listing makes the VM storefront build a `vms.interruptible.v1` term, inside the Alkahest kit, with a splitter whose trusted oracle is the seller's own wallet. The term carries only `refund_authority: seller_declared`. The interrupt endpoint is operator-only (admin API key plus an administrator principal), shortens the capacity lease, and returns `splitter_declaration_pending` for the money side. Terminal hosted settlement shortens the lease in the other direction (`truncate_lease_for_terminal_settlement`). Both exist only in the VM domain.
- **Hosted payments service** (the `arkhai.payments.v1` mechanism):
  - **Commitment.** The seller builds the mandate. The payer commits by approving it with an authenticated request. The payee commits implicitly by building it. The mandate carries the deal digest `sha256(JCS(agreement))`, which the service stores and signs without interpreting. The agreement itself can be stored with the transaction as an attachment and read back by digest.
  - **Events.** Lifecycle events (`start`, `stop`, `reverse`) are authenticated requests from accounts listed for that event kind in the mandate's authorities. Nobody has an implicit right, the payee included. A recorded stop names its cause: payer, payee, authority, or terms.
  - **Funded-through.** Under the rate-parts contract that `spot-deals-through-arkhai-payments` builds on, the signed snapshot carries a funded-through time, and each part reserves at least the seller's teardown time ahead.
  - **Partial settlement.** Rate parts earn a period when it begins. A stop ends every part, keeps the period in progress as earned, and returns later reservations to the payer. A one-time part is not prorated; an authorized `reverse` returns part of it while the money is still held.
  - **Funding exhaustion.** The service stops the transaction itself at the last paid boundary, with cause "terms".
  - **Records.** Any party can read a signed snapshot holding every event, the stop record, and per-part settled amounts. Events carry opaque payloads, which may hold evidence references. There are no notifications; parties poll.
  - **Default outcome.** Held earnings release to the payee when the hold matures or at stop. After that the service can no longer reverse them.
  - **Gaps.** A stop takes effect when received; it can be neither backdated nor future-dated. There are no settlement rules that depend on who initiated the stop. The dispute authority that the mandate already lists as allowed to reverse does not exist yet.

## Decisions

### D1. The protocol ends at agreement and settlement

The market protocol is discovery, negotiation to a mutually authenticated agreement, and settlement. Exchanges after that are between the parties and outside the protocol. Core carries the agreement and the settlement plan as opaque, domain- and mechanism-defined content, and gains no interruption, notice, or access verb. The operator interrupt operation currently in the core storefront client moves to kit.

*Why:* core already holds only what is common to every listing type. Post-agreement behavior differs per domain and per mechanism.

### D2. The agreement is the demand

The agreement contains everything needed to decide a dispute about it, in the form `arbitrate(demand, evidence)`. For each clause it names:

1. the **evaluator** — the arbiter, oracle, authority, or hosted condition kind that decides it;
2. the **evidence regime** — what evidence that evaluator accepts and where it comes from;
3. the **default outcome** — what happens when no evidence is submitted by a deadline.

The existing mechanisms are instances of this model. The change makes the model explicit; it does not replace them. The default outcome is what lets an undisputed deal finish with no arbitration messages, and it decides which party must keep evidence.

### D3. Later information is evidence, not protocol

Information exchanged after agreement does not need to be committed into the agreement or carried by the protocol unless a dispute arises. The agreement's regime defines which of it can become evidence and from where. Each party is responsible for keeping what the regime expects it to submit.

### D4. A clause is admissible only if it can be enforced

- **Decidable.** Its regime can produce evidence that decides it. "Buyer received a working VM" cannot be proven with peer evidence alone. Such a clause needs a trusted monitor or gateway, or must be weakened to something provable.
- **Reachable.** Before accepting, each party checks that it can take part in the regime the agreement names. This requires the buyer client to validate `service_terms` against the advertised option instead of passing them through.
- **Negotiable.** The choice of regime is a negotiable, and possibly priced, part of the terms.

### D5. Early termination is one clause family

One clause family covers every early end:

- **Permitted initiators:** seller reclaim, buyer stop, payer exhaustion, or a named authority.
- **Notice period** before the end takes effect.
- **Settlement rule** for used and unused service, stated in the mechanism's own settlement units and possibly differing by initiator. "Paid through the period in progress" is a valid rule for per-period billing; the agreed period length sets its granularity. Settlement at an arbitrary instant is not required.
- **Evidence** of the early end.

"Spot" and "interruptible" are parameter choices within this clause. The clause is a kit-owned type; a payment-mechanism kit does not define VM-named terms. A mechanism that cannot settle under the agreed rule is not offered with this clause.

**Notice must be provable.** A notice period must leave evidence a neutral arbiter can check (D13). Waiting silently and sending the stop at T is not acceptable, because the buyer could not prove whether notice was given. The proposed form is the mechanism recording a stop dated in the future. `spot-deals-through-arkhai-payments` currently forbids future-dated stops, so this is open (see open questions).

**Initiator-dependent rules belong in the agreement terms.** A rule that depends on who initiated is a term of the mechanism's agreement that the mechanism applies. It is not an intermediary that sends a compensating refund, because that would reintroduce a trusted third party.

### D6. One storefront operation executes the service side of an early end

"End service at T" is one storefront operation in shared kit.

- **Triggers:** a seller decision, a buyer stop the storefront relays, and a stop or exhaustion the mechanism reports.
- **Effects, each retried and resumed independently:**
  - Capacity side: shorten the lease through the site authority. Capacity is released only after provisioning proves teardown.
  - Trigger detection: the storefront enforces locally from the authority's last signed record — for hosted payments, deliver until funded-through and tear down unless it moves — and reads the authority to make teardown prompt. A courtesy notice only brings the next read forward.
  - Money side: when the seller initiated, call the mechanism's `end_early(obligation, at, initiator)` beside collect and reclaim. When the buyer or the mechanism initiated, observe the stop instead of sending one.
- **Durable record:** each early end is kept as a durable record holding the trigger, the initiator, and the evidence references.

It replaces the VM-domain interrupt endpoint and terminal-settlement truncation, so bare metal gets the same behavior. The storefront is the only role holding both the capacity reservation and the settlement plan; provisioning must not learn about deals or settlement.

### D7. Ending early is a party action sent to the authority the agreement names

An early end is performed by a party allowed to perform it, through its own credentials, at the authority the agreement names. That authority's record is the only authoritative statement that the deal ended early. Holding a handle (obligation reference, transaction id, status URL) grants no permission.

- **Hosted payments:** the initiator sends a stop from its own account, which the mandate's stop authorities must list.
- **Alkahest splitter:** the storefront is the authority while the seller is the oracle (D11). The buyer sends a signed stop to the storefront, authenticated like settlement requests. The storefront ends service and declares the split, and keeps the signed stop as evidence of the request.
- **Asynchronous peer-to-peer:** the signed stop message is both the action and the evidence.

**Our implementation also sends a courtesy notice.** After a stop is recorded at the authority, the initiator tells the counterparty: a buyer that stopped on the hosted service tells the storefront, and a seller that reclaims tells the buyer. Under D12 this notice is only a hint. It makes the receiver check the authority sooner and changes nothing by itself.

The operator interrupt route remains an operator tool acting for the seller. It is not the seller's or buyer's interface.

### D12. Design for the adversarial worst case; default to cooperation

The protocol is separate from this repository's software. A counterparty may run any implementation, and each party may act only in its own interest. Therefore:

- **Safety depends only on authority records.** Each party's protection depends only on the record at the authority the agreement names, plus its own kept records. It never depends on a message the counterparty may choose not to send.
  - The seller must observe the authority itself, by polling or subscription, and act on what the authority recorded. If it relied on the buyer's notice, a buyer could stop at the authority, never tell the seller, and keep using the machine.
  - The buyer reads the authority to learn of a seller reclaim and when it takes effect, rather than trusting a notice that may never come.
- **Each party's exposure is bounded by the terms it agreed.** Prefer terms that let a party enforce locally from the authority's signed record. On hosted payments, the seller serves until the signed funded-through time and tears down unless it moves. Reservation ahead covers teardown, so a silent stop or exhaustion leaves no unpaid service, and reading the authority only makes teardown prompter. Where no such term exists, the required check cadence follows from the settlement rule and is stated next to it.
- **Defaults cooperate.** Our implementations send courtesy notices, end service promptly when told, and do not exploit the window the worst case allows.
- **Courtesy messages are hints, never a second path to the same result.** They are idempotent and safe to ignore. They trigger a check of the authority rather than acting on their own content, so a forged or mistaken notice does nothing.
- **Choose message flows for the worst case.** When deciding who sends what, prefer the flow that keeps the adversarial case simple and practical: one authority, one record, a bounded exposure window. Do not choose a flow that is only smoother when everyone cooperates.

### D8. Message sequence and information placement

1. **Discovery.** The buyer queries the registry, which replies.
2. **Negotiation.** Rounds run until the seller's authenticated acceptance. In the shortest case the buyer sends a complete proposed agreement and the seller signs an acknowledgement.
3. **Commitment and funding.** Done in the mechanism's commitment form (D9). This involves no exchange with the seller.
4. **Post-agreement exchange.** The buyer sends the funding reference and the information the seller needs that is not in the agreement. The seller replies, possibly asynchronously, with access details and action handles.

| Information | Placement |
|---|---|
| Known before agreement, must bind both parties | Agreement |
| Known before agreement, not sensitive, acceptable to hold for unfunded deals | May ride in the agreement to save an exchange (for example an SSH public key) |
| Personal or secret | Revealed after acceptance, never in the agreement |
| Created by settlement | Settlement receipt or status |
| Created by fulfillment | Fulfillment result |

### D9. Commitment form follows the arbitration mechanism

Each settlement mechanism declares how parties commit to an agreement. That commitment must bind the parties to everything its evaluator decides. Every form binds the same canonical agreement digest, `sha256(JCS(agreement))`, so one agreement identity spans every mechanism:

| Form | Commitment | Agreement binding |
|---|---|---|
| Hosted payments | Authenticated approval of the seller-built mandate | Mandate deal digest; agreement stored as an attachment |
| On-chain escrow | Funding transaction | The demand carries the agreement digest |
| Asynchronous peer-to-peer | Exchanged signed messages | The signed negotiation record, which each party keeps |

Alkahest demands do not yet carry the digest; adding it is required.

### D10. Dispute data is organized as one case payload

No dispute authority exists yet, but every data format must be designed so that a dispute is **one self-contained payload** sent to one evaluator. Evidence must not be scattered across mechanism-specific stores that an authority would have to discover and reconcile.

- **Case.** A dispute case contains:
  - the agreement, or its digest plus where to fetch it;
  - the commitment reference under D9;
  - the clause in dispute;
  - the claim and the requested outcome;
  - an ordered list of evidence items.
- **Root.** The agreement digest is the root. Every evidence item names the digest it relates to.
- **Evidence envelope.** All evidence items share one envelope:
  - kind;
  - producer identity;
  - time;
  - content digest and content or location;
  - the producer's signature, or the attestation of the record that holds it (for example a mechanism's signed snapshot or an on-chain event).

  Each mechanism and each domain contributes evidence kinds within this envelope; it does not invent its own container. Examples of kinds: heartbeats, stop requests, oracle declarations, mechanism snapshots, fulfillment results.
- **Assembly.** Each party can assemble a case from its own kept records plus records it can read from the mechanism. Mechanism records that already exist, such as the hosted signed snapshot and event payloads, are referenced from the case rather than copied into a parallel format.
- **Producing records.** Records produced by this change carry the agreement digest and use the envelope: the early-end record (D6), relayed buyer stops (D7), and seller decisions from `automate-seller-spot`.

### D11. A mechanical dispute authority is deferred

A mechanical dispute authority is built together with a managed metering gateway, because the gateway is what produces delivery evidence such an authority could decide on. Until then:

- the Alkahest splitter oracle is the seller itself, which is trusted rather than secure (D13);
- the hosted mandate's reverse authority stays as it is.

D10 keeps the data ready for that authority, so adding it requires no format change.

### D13. Hosted payments is the production path; every decision must admit a neutral trustless alternative

- **Production first.** The hosted payments mechanism is the first implementation to make complete and production-quality: the clause, the end-service operation, observing the authority, courtesy notices, and the case records.
- **Alkahest is maintained, not hardened.** Alkahest keeps the architecture decentralized: for every centralized or managed component, a trustless alternative must be *possible*. It need not be available in production at the same time. The current Alkahest path, with the seller as splitter oracle, is not meant to be secure. It works only if the buyer trusts the seller, and that is accepted.
- **The test for a new decision** is whether a properly neutral, trustless alternative could be implemented under it — another party as oracle, or a signature-based rather than oracle-based arbiter — not whether the current Alkahest path is secure. A decision fails this test if it:
  - lets only a managed service hold the evidence or perform the action;
  - makes the evaluation need data only a managed party can produce or read;
  - uses a commitment that cannot be expressed on-chain or as exchanged signatures.

  Applying the test to the decisions above:
  - D9's single agreement digest and D10's signed or attested evidence envelope make a neutral evaluator possible.
  - D7's buyer-signed stop is exactly the evidence a signature-based arbiter would consume.
  - D5's notice and initiator rules must be expressible as terms a neutral arbiter evaluates, not as hosted-service behavior only.

## Dependencies on the hosted payments service

- **Provable notice** (D5; form open).
- **Funded-through and reserve-ahead**, as in `spot-deals-through-arkhai-payments`, for local enforcement (D12).
- **Settlement rules that depend on the initiator**, as a mandate term (D5).
- **Push notification** of stops and funding exhaustion is optional. Polling is enough for D6 and D7.

## Alternatives considered

- **Interruption as a core protocol verb.** Rejected (D1).
- **Interruption entirely inside a payment service.** Rejected (D6). The payment service has no knowledge of leases.
- **Commit every later message by hash in the agreement.** Not required in general (D3).
- **A two-way receipt exchanged as a protocol step.** Unnecessary. The two directions are step 4 of D8.
- **Notice by waiting before sending the stop.** Rejected (D5). It leaves no record.
- **Initiator-dependent refunds by an intermediary reversing funds.** Rejected (D5). It adds a trusted third party.
- **Per-mechanism dispute evidence formats.** Rejected (D10). A future authority would have to reconcile them.
- **The seller learns of buyer stops only from the buyer's notice.** Rejected (D12). A buyer that stops at the authority and stays silent would keep the service without paying for it.

## Open questions

- **Representation.** Do clause evaluator, regime, and default outcome belong in domain terms, per settlement option, or in a kit-owned clause carrier inside `service_terms`?
- **Notice delivery to the buyer.** Should it be status polling only, a buyer-supplied address, or the `kit/delivery` sink contract?
- **Defaults.** Must every agreement state a default outcome explicitly, or may a mechanism declare its default once?
- **Naming.** Should the family be called early termination, interruption, or something else, and are "spot" and "interruptible" kept as user-facing names for parameter presets?
- **Notice periods on hosted payments.** Should the payments service accept future-dated stops, contrary to the current `spot-deals-through-arkhai-payments` contract? Or is notice expressed another way that still leaves provable evidence, for example a signed notice event in the transaction journal with the stop following at T?
- **Stop settlement point.** The `spot-deals-through-arkhai-payments` contract says a stop at t settles usage to t; the payments service describes rate parts as earning a period when it begins. D5's rule must name which one applies.
- **Case transport.** Where a case is submitted, and how evidence that a party holds privately is disclosed only to the authority, are deferred with D11. The envelope must not assume either.

## Status

Proposal level. Implementation order follows D13: hosted payments end to end first, through `spot-deals-through-arkhai-payments`; Alkahest receives the agreement digest and the clause type, so the decentralized path stays representable, without hardening its seller-as-oracle behavior. Next: spec deltas and `tasks.md`, and rescoping `automate-seller-spot` to the seller decision runner, with its decision evidence in the D10 envelope.
