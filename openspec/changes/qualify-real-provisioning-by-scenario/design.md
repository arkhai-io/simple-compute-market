# Design

Drafted on `dev` at `a958f4bd7`. This is a starting design for the change's own
design phase: the decisions below are proposals, and the open questions are the
owner's.

## Context

The runbook owes six observations
(`docs/development/VALIDATION_RUNBOOK.md#observations-the-qualification-owes`).
Two are out of scope here:

- Observation 1, negative relay admission, is the relay operator's probe (§28).
- Observation 3, direct access, needs an operator-routable test path that a
  relay-only deployment does not have.

This change covers observations 2, 4, 5 and 6, which need a paid purchase through
the shipped buyer.

What exists:

- **Real-provisioning modules.** `test_real_provisioning_deal.py`, under `vms/` and
  `bare_metal/`. They read `REAL_PROVISIONING_TARGET` version 2, register or
  reconcile their own host, and deal through the typed driver with stages
  05a–08b: negotiate, force-accept, escrow on Alkahest, settle. Their physical
  stages from 08b3 on key only on fulfillment and negotiation identifiers. The
  bare-metal module runs the bounded working-data cycles through
  `working_data_qualification.py` when the target's bare-metal host has
  `cleanup_qualification`. It back-dates the lease before an ordinary reclaim.
- **Payment scenarios.** `test_vm_payment_deal.py` and
  `test_bare_metal_payment_deal.py` buy through the buyer CLI, settled in
  `arkhai.payments.v1`, with receipts verified, against mock or controlled
  delivery. `roles/helpers/payments.py` reads the `PAYMENTS` settings and writes the
  buyer's payments table. A run with no target is a blocked skip; a configured run
  missing a setting fails, naming it.
- **Operator reads:** `SyncComputeProvisioningClient` for hosts, leases, jobs and
  job logs; the relay lease reads; the site, storefront and registry clients for
  pools, resources, allocators and listings.
- **The accepted method** (`qualify-arkhai-real-provisioning`, design decisions 1–6
  and its method mapping): the shipped buyer for every customer action, TEST
  payment correlated with attributable debits, buyer and operator credentials kept
  apart, and the original physical observations preserved. This change keeps all of
  that except where the procedure lives.

## Goals / Non-Goals

**Goals:**

- Scenarios that make observations 2, 4, 5 and 6 as §29 states them, against any
  conforming deployment.
- Correlation and an outcome record per observation.
- The configuration contract a deployment builds to.

**Non-Goals:**

- Funding the buyer: that is the deployment's step.
- Deploying anything, or naming any deployment.
- Observations 1 and 3.
- A default pipeline lane.
- Changing payment or provisioning behaviour.

## Proposed decisions

### P1. Scenarios join the operator procedure as the repeatable method

Each observation is a scenario module marked in no lane. It skips, reporting the
unmet prerequisite, without both a real-provisioning target and a payments target.
It asserts every §29 criterion itself or through an existing helper.

The operator-procedure method is retained as an accepted alternative (owner
decision): it stays useful. The scenarios are the method a candidate's qualification
reaches for first, because they are repeated more easily and run deterministically,
with their criteria reviewable here.

### P2. Reuse the real modules' physical stages behind a buyer purchase

The new scenarios buy through the shipped buyer and then reuse the real modules'
physical stages from 08b3 on, which key only on the fulfillment and negotiation
identifiers. The design phase decides between two shapes:

- **(a)** A buyer-purchase mode of the existing modules, replacing stages 05a–08b.
- **(b)** New modules that import the shared stages.

Lean (b). The Alkahest modules stay as they are and remain the cheap regression run,
and the qualification scenarios read as the runbook's observations rather than as
variants of a deal.

### P3. Every observation is read through a typed client

The owner's direction: observability an observation needs is added to this
repository's typed clients, not taken over a side route the deployment supplies.
Two reads are known to be missing:

- **Observation 2:** the management client's and libvirtd's process generations on a
  VM host, before, during and after the second deal.
- **Observation 6:** the bare-metal host's consumed-UID history.

The design phase confirms which service owns each read. A first lean is
provisioning, which already reaches the host over its management session. That
service gains signed admin reads, and the typed client gains the matching calls.
This is product code, with tests at the levels that own it.

The bare-metal `cleanup_qualification.operator` route stays as it is. It is the
existing working-data helper's independent observer.

### P4. The scenario uses only the payments interface this repository imports

The scenarios use the payments kit's client and only that. Its calls cover
approvals, transaction snapshots and balance reads. Anything else a run needs is
the deployment's topology: funding the buyer, the proof of that funding, and any
ledger read the kit does not expose.

The scenario attributes from what it can read:

- the buyer's balance before its first purchase and after its last debit;
- each transaction's signed debit parts.

It requires every debit to belong to one of its own transactions. Observation 2's
two concurrent purchases share an account, so their split comes from each
transaction's signed parts. Joining the funding proof to the outcome records is the
deployment's work, outside this repository.

### P5. Grant admission is read from the admission plugin's log

The relay's admission plugin is this repository's tool, and its decision log is a
documented contract (`tools/frp-grant-admission/README.md#the-log`): one JSON line
per decision, with `event`, `remote_port`, `kid`, `jti` and `verified`.

The scenario requires an `admit` line for each delivered lease:

- `verified` true;
- `jti` equal to the reservation;
- the leased port;
- the relay's grant key ID.

The log lives wherever the relay runs, which only the deployment knows. So each
relay the target names gains an `admission_log` setting. It is an absolute
harness-local path to a file of the plugin's log lines, which the deployment keeps
current for the run, referenced the same way key paths are. Without that setting the
scenario records admission as unproven rather than inferring it from delivery.

### P6. Outcomes are written outside the repository

Each scenario writes one record per observation: made, failed or unproven, the
criteria checked, and the correlation identifiers. Each record is bound to the
candidate revision, the scenario module and the target digest. Records go to an
operator-supplied directory, and the scenario refuses one that lies inside a Git
work tree. Only sanitized outcomes reach `ROADMAP.md`.

### P7. Review and validation

- **Independent review:** Codex, through the change workflow's review steps.
- **Validation:** the change's validation step runs everything the pipeline and CI
  can.
- **Hardware observations:** the scenarios' runs against a real-provisioning
  deployment are made by the deployment's operator. They are submitted as
  validation evidence, sanitized for this repository, before closeout.
- **The candidate:** the change's validated `HEAD` is the frozen candidate those
  runs are bound to. A source change after a run invalidates that run for
  qualification.

### P8. The bare-metal scenarios: no GPU check, and the scenario ends the lease

Observation 4 is made here without its GPU part, and the scenarios never check for
a GPU. A GPU host's qualification is a different scenario (owner decision). The
outcome record says that the GPU part of observation 4 is not this scenario's.

The scenario ends each bare-metal lease itself, through the buyer's ordinary
`bare-metal teardown`, and records that this started the reclaim. It neither
back-dates the lease nor waits for natural expiry. §29 excludes only a forced
release, a manual retry or a consumed-UID reset.

### P9. In-cluster payments over HTTPS with a deployment's CA

A deployment may run its payments service inside the cluster. Storefronts then
reach it at a service DNS origin, `https://<service>.<namespace>.svc.cluster.local[:port]`.
The kit already accepts that origin: `ArkhaiPaymentsConfig.service_url` and
`PaymentsClient` require an HTTP(S) origin without a path, and HTTPS outside
loopback. That rule stays, following `add-arkhai-payments-lane-double`'s accepted
transport decision: HTTPS origins, a development CA trusted explicitly through
`SSL_CERT_FILE`, and no verification bypass or origin relaxation. The client builds
non-loopback connections with `trust_env`, so httpx 0.28 verifies against
`SSL_CERT_FILE` when it is set.

This change adds:

- a kit test that pins this. A cluster-service HTTPS origin is accepted, and the
  same origin over HTTP is refused.
- a chart option on the storefront and bare-metal storefront charts that mounts a
  deployment-supplied CA bundle (a Secret or ConfigMap key) into the storefront
  container and sets `SSL_CERT_FILE` to it. The bundle holds the deployment's CA
  plus the public roots; the option names no CA itself.

### P10. A pinned dispute authority, and no dispute-authority double

An `arkhai.payments.v1` listing publishes no payment option unless a dispute
authority advertising the mechanism is accepted, and every mandate names that
authority's payments account as the one that may stop, reverse and extend the
payment. That is why these purchases need a dispute authority although the Alkahest
real-provisioning modules never did: there, the escrow's oracle releases at lease
end unless a dispute is raised, and no separate authority appears in the Agreement.

None of observations 2, 4, 5 and 6 exercises a dispute. The deployment therefore
supplies only what each Agreement pins: an authority identity (interface, origin,
account and record key) whose account is a real account at the payments target,
accepted by the storefronts' and the buyer's existing dispute settings. This change
deploys no dispute authority and builds no double (owner decision). Nothing has to
answer at the authority's origin for these observations.

The scenarios then account for the authority's absence:

- The buyer's teardown stops the payment, has the surrender acknowledged, and then
  files a delivery-end case (`kit/deal-lifecycle-buyer/src/market_deal_lifecycle_buyer/ending.py`).
  With no authority answering, the case outcome is not accepted. The scenario
  records the case filing as outside its observations, never reads it as delivery,
  access-end or refund evidence, and does not fail on it.
- The seller's servicing watch reads the authority's records while a deal is open
  (`kit/deal-servicing/src/market_deal_servicing/watch.py`). Whether an unanswered
  authority stalls servicing or the reclaim is not yet established (open question 3).

A hosted deployment with a controllable dispute authority is an unowned gap,
recorded in `docs/development/ROADMAP.md` Goal 1. `add-arkhai-payments-lane-double`'s
mediation double serves the local lanes only, and production configuration refuses
its fixture identities.

## Open questions

1. **Lease durations.** Observation 2 needs both leases to expire naturally, with the
   heartbeat spanning the second guest's life. Is the shortest duration that covers
   this a scenario setting, or the listing's own?
2. **Owners of the missing reads** (P3): provisioning, or another service, for each
   read.
3. **An unanswered dispute authority** (P10). Does the seller's servicing watch, or
   anything on the storefronts' teardown and reclaim path, stall or fail when the
   pinned authority does not answer and no dispute credential is configured? If it
   does, design picks the smallest remedy, such as tolerating the unanswered read
   for a deal with no case. A deployed dispute-authority double stays out of scope.

## Owner answers

- Observability an observation needs is added to this repository's typed clients
  (P3).
- The scenarios exercise only the payments interface already imported here; the
  rest is the deployment's topology (P4).
- The scenario reads the admission plugin's log, since the relay and its plugin are
  this repository's (P5).
- Independent review is by Codex. The deployment's operator runs the hardware
  validation the pipeline cannot and submits its evidence before closeout (P7).
- The bare-metal scenarios do not check for GPUs. GPU hosts are a different
  scenario (P8).
- The scenario ends the bare-metal lease itself (P8).
- The operator-procedure method is retained beside the scenarios (P1).
- The kit supports an in-cluster `https://<service>.<namespace>.svc.cluster.local`
  payments origin and keeps requiring HTTPS. The deployment supplies a development
  CA (P9).
- No programmable dispute-authority double this round. The deployment pins an
  authority identity with a real payments account, and the hosted double is
  recorded as an unowned gap (P10).
