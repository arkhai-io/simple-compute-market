# Design

Design phase; not planned.

## Context

- `kit/capacity-publication` owns the common listing binding, event-driven
  reconciliation, registry fan-out, publication result recording, and close/reopen
  mechanics for publication-driven changes. Seller-initiated close, pause, and reopen
  are per-domain services over that binding.
- `kit/settlement-runtime` owns the per-obligation operation journal and servicing
  worker; what each domain reimplements is the step after settlement — resuming an
  accepted obligation across restarts and converging it with the executor's report.
- `site_projection_cache` (VM) and the capacity/publication kit's per-site projection
  state (bare metal) hold the same thing by two routes.

## Questions to settle before planning

- **Whether fulfillment convergence is a new kit package or part of
  `kit/settlement-runtime`.** It reads the settlement journal but drives executor
  state; a separate package keeps the settlement kit free of fulfillment vocabulary.
- **What the successor-identity rule is generically.** VM carries a seller's close or
  pause onto the listing that succeeds a pre-shape listing; bare metal's derivation
  key includes the pool. The kit needs a domain hook that says "this candidate
  succeeds that listing" without knowing why.
- **Where the divergences are.** API credits' fulfillment is issuance, not
  provisioning; the convergence mechanism must fit it without a provisioning-shaped
  no-op.
- **Whether settlement-started delivery, evidence publication, verification, and access
  belong in this change or in one of their own.** "Input from
  `bare-metal-mock-provisioned-deal` (2026-10-07)" below proposes them here, as the step
  this change's convergence starts from; a split would put them in a sibling change this
  one depends on.

## Decisions

None yet.

## Input from `bare-metal-mock-provisioned-deal` (2026-10-07)

Planning that change's settlement section audited how every domain gets from a ready
settlement obligation to a bound fulfillment. Its maintainer first chose to unify the path
there, then moved the unification here after a design review, because this change
already owns restart-safe fulfillment convergence and the unification overlaps two other
active changes. The audit, the proposed direction, and the review's corrections are
recorded below as input to this design; none of it is decided here yet.

### What the audit found

| Finding |
|---|
| The kit starts fulfillment two ways. `SettlementJobCoordinator` (`kit/settlement-runtime`, `jobs.py`) runs fulfillment in an in-process asyncio task nothing makes durable; the servicing worker's ready hook is durable and retried. Every domain uses both |
| VM, Alkahest: the settle route starts the coordinator, whose task runs `fulfill_vm_settlement`; the domain's fulfillment hook provisions and then publishes `connection_details` (host, port, user) on chain as a string obligation. Deferred or interrupted work is finished by VM's resume pass (`services/fulfillment_resume_runtime.py`), which refuses to resubmit evidence it cannot prove |
| VM, hosted: the worker's `on_ready` calls `ensure_hosted_fulfillment`, which runs the same `fulfill_vm_settlement` with the hosted evidence client |
| API credits: Alkahest through the coordinator (`fulfill_api_credit_settlement`); hosted through `on_ready` and its own `ensure_hosted_fulfillment`, which publishes signed, secret-free issuance evidence through the portable resolver. The hosted condition verifies that evidence field by field (`verify_api_credits_issuance_evidence`; `openspec/specs/api-credits/spec.md`, "Hosted issuance evidence is signed, portable, and secret-free") |
| Bare metal: hosted through `on_ready` and the hosted lifecycle's `fulfill`, publishing lease-ready evidence through the portable resolver. Its Alkahest path is an interim domain step on the worker (that change's Section 7C): it publishes the evidence's digest through `kit/alkahest`'s `AlkahestFulfillmentPublisher` and parks an unknown submission outcome for an operator |
| The port `publish_fulfillment(condition_anchor, evidence)` is declared three times: `kit/hosted-settlement`'s adapter, `arkhai_vms_settlement.fulfillment`, and API credits' `services/issuance_evidence.py` |
| VM's `prepare_vm_settlement` verifies the escrow and then registers obligations rebuilt from current configuration (the seller wallet and chain paths), not the plan committed at acceptance. Bare metal verifies its committed plan. Escrow verification is written in each domain |
| The registration's `settlement_verifier` has a mechanism-specific signature (`configuration.py`): the Alkahest verifier takes the escrow, seller wallet, amount, duration, listing, chain client, chain name, address configuration, and proposal |
| Delivery: VM puts host, port, and user on chain and stores them on the escrow row and the listing's fulfillment resource; it stores the tenant password on the escrow row; settle status (`serialize_settlement_job`) returns both, and VM's buyer prints them. API credits keeps its bearer secret in a private result store behind an authenticated route, since no authority can issue it again. Bare metal serves coordinates live through its authenticated `/access` and stores none. Provisioning serves an active fulfillment's credentials live and uncached, so VM's stored copies are not needed |
| VM's composition omits a configured but disabled mechanism's client when its resources are missing, which abandons the obligations under it; so does API credits' (`server.py` builds Alkahest clients only for an enabled section). Bare metal now requires a configured mechanism's recovery resources |

### Proposed direction

1. **One start path.** The worker's ready step serves every mechanism, composed in kit
   from contributions: a mechanism declares whether its fulfillment is domain-started,
   with an evidence publisher, or self-binding (contact exchange, whose reveal binds its
   own obligation); a domain supplies `deliver(record)` (pending, or delivered with its
   public evidence) and `end_service(record, reason)` for an obligation that ends
   uncollected after delivery started. Settle verify and the hosted start route step the
   obligation once; every retry is the worker's. Retired: `SettlementJobCoordinator`, VM's
   resume pass, every domain's `ensure_hosted_fulfillment` and hosted `fulfill` body, and
   bare metal's interim Alkahest step. VM's physical-resumption rules ("Physical
   fulfillment resumption") stay, as properties of VM's `deliver`.
2. **Mechanism-owned publishers behind one port**, in `kit/settlement-runtime`;
   `kit/alkahest`'s publisher (with its four outcomes: published, not submitted, outcome
   unknown, rejected) and the hosted adapter implement it; the domain declarations go.
3. **A layered evidence envelope.** A kit envelope binds the agreement, obligation,
   condition anchor, fulfillment identity, and the digest of a domain-owned public
   evidence projection; it wraps that projection and never replaces it, because a
   condition may verify the projection's fields (API credits' does). No envelope or
   projection carries an endpoint, credential, or secret. What goes on chain is the
   envelope's digest, never a body naming principals.
4. **A mechanism-neutral verification contract.** The registration exposes a
   verification contribution taking a neutral accepted-plan and claimed-settlement
   context with its configured resources and returning a typed result; the Alkahest
   registration adapts it to its verifier. The kit step loads the accepted agreement
   through a domain hook, verifies, registers the committed plan, adopts, and steps once.
   This fixes VM's plan rebuild: VM registers its committed plan and refuses a thread
   with none.
5. **One access rule.** Buyer access material reaches only the authenticated buyer: live
   where an authority can serve it again (VM, bare metal), persisted privately where none
   can (API credits). The kit owns access orchestration; each domain owns its typed access
   result and its route models, under the five-piece route pattern. VM stops storing and
   returning `connection_details` and `tenant_credentials`; VM's buyer reads them from
   the access route. What VM already published on chain stays public.
6. **Recovery resources are required while configured, and startup refuses abandonment.**
   VM and API credits require a configured mechanism's recovery resources, as bare metal
   does; all three refuse to start while unfinished obligations exist under a mechanism
   with no configured section.
7. **Ambiguous submissions stay safe-pending.** The publisher's unknown outcome parks the
   obligation; `add-alkahest-attestation-reference-query` owns automatic reconciliation.

### Corrections from the design review, to carry into planning

- VM's cutover needs scenarios for deals in flight: physical delivery done with no
  fulfillment bound; stored access material; a checkpoint the old resume pass wrote. The
  worker must be proven to discover and continue them, and stored credentials may be
  cleared only once every active row can fetch them live.
- Validation: settlement-runtime integration tests against its real repository for
  durable ready, terminal, and retry behaviour; VM and bare-metal application integration
  through their canonical clients for settlement, delivery, evidence, and access; API
  credits' application integration proving its real composition still publishes and
  resolves the signed evidence its condition verifies; recovery across VM's cutover; and
  every domain lane available.
- Coordination: `add-api-credits-hosted-settlement` (its evidence is what the envelope
  wraps) and `add-alkahest-attestation-reference-query` (its lookup plugs into the
  Alkahest publisher's unknown outcome).
