# Design: qualify-per-period-bare-metal-and-setup-charges

## Context

**What a seller declares.** A seller offers on-demand and spot options by writing a
recurring publication clause and a table, `[Settlement.rate_servicing.<mechanism>]`,
naming the partial-period treatments its storefront services and whether it services a
setup charge (`kit/settlement-runtime/src/market_settlement_runtime/rate_servicing.py`).
The table is absent by default. Publication, acceptance and materialization read it and
refuse what it does not list (`settlement-configuration`'s "Rate servicing is a
composition capability"). Nothing restricts it by domain or by what an authority has
been shown to do: a bare-metal storefront reads it as a VM storefront does, and the
bare-metal lane's storefront declares `charged` and `returned`
(`domains/bare_metal/storefront/storefront.dev.toml`). This repository holds no
production composition of its own; it ships examples and documents.

**What is documented as supported.** On-demand and spot VM, with no setup charge. The
seller quickstart's "Offering on-demand and spot" describes it, the VM storefront
chart's production example declares it
(`helm/charts/storefront/examples/production-values.yaml`; `deployment-state`'s "The VM
storefront chart ships a production example offering on-demand and spot"), the buyer
quickstart says a seller "may offer a VM by the period", and the operator handbook's
"Serving rate deals" speaks of a VM storefront and lists leases with
`offering_mode=vm`. The bare-metal chart's production example settles through Alkahest
only (`helm/charts/bare-metal-storefront/examples/production-values.yaml`), and
`docs/bare-metal-seller-quickstart.md` has no recurring section.

**Setup charges.** The payments kit derives a setup `once` part beside the rate part
when a recurring clause prices one (`recurring.setup_amount`), and the three doors
refuse it unless the table says `setup = true`. `deal-lifecycle`'s "Setup returns by
delivered for either cause" says setup-bearing presets "MUST remain disabled until a
hosted dispute authority is qualified on the vendored delivery_end revision". Nothing
enforces that sentence but the table's default: the payments helper reports that it
supports a setup charge's delivery end
(`kit/arkhai-payments/src/market_arkhai_payments/presets.py`). No lane declares
`setup`, no shipped example prices one, and no live observation involves a setup part.
The dispute authority returns a setup charge only when a `delivery_end` claim says the
resource was never delivered, for either cause
(`openspec/specs/deal-lifecycle/architecture.md`, "External authorities").

**The lanes.** Each compute lane delivers a recurring purchase ended by the buyer's own
stop, and runs funds running out, a spot preemption with notice, the maximum term and
the buyer watchdog's cases, on lane time against both doubles (`test-compatibility`'s
"A recurring purchase is delivered end to end in each compute lane", "Rate deals are
qualified in both compute lanes on lane time" and "The buyer's watchdog is qualified
against a delivered deal"). The VM lane also rules a seller's filing and a buyer's
contested case on rate deals ("A dispute on a running rate deal is qualified in the VM
lane"). `converge-ongoing-compute-leases` holds the remaining rate rows, and which lane
runs each and whether a lane declares a setup charge are open in its design.

**Live verification.** A live verification scenario gives a hosted authority the input
its lane twin gave the double, produced by this repository's own client code, and holds
the authority's output to the twin's shared assertion. It runs no stage after that
output. It states in prose what a topology must provide and names no infrastructure;
the deployment prepares the topology, runs the modules and supplies a sanitized summary
(`docs/guidance/engineering/system-tests.md`, "Locally verifiable and external-topology
scenarios"; `test-compatibility`'s "A live verification scenario compares a producer's
outputs with a lane's expectations" and "Each live verification scenario states its
topology requirements"). Six VM scenarios exist, with their requirements in
`e2e-tests/README.md`, "Live verification". No bare-metal scenario exists.

**What has been observed live.** The VM run of 2026-11-23
(`docs/attachments/switch-on-hosted-per-period-vm/live-verification.md`), on mock
provisioning against hosted payments in test mode and a hosted mediation authority
serving the vendored contract, made five observations: the buyer's stop, funds running
out, a spot preemption returning the unstarted remainder, the term end, and a seller's
filing ruled without a person, with the part protected by an extension, the authority's
stop through the `chosen` entry, the capped penalty and the extension lifted. Its buyer
changed no acceptance setting. The buyer's contested case was filed and contested, and
its ruling is unproven: the topology applied no ruling policy.

**The dispute authority.** SCM files, appends, reads the respondent listing and reads
records; it calls nothing the authority's public client lacks, and how an operator's
decision reaches payments is the authority's side to qualify
(`docs/development/ARCHITECTURE.md`, "Authority boundaries"). The vendored
`arkhai.mediation.v1` contract fixes, as constants of an authority's description, how
it treats repeated and concurrent cases, when it dismisses one, that its record key and
origin stay valid through a deal's life, its dispute window and any open case, and that
it rules a payee-endorsed `delivery_end` automatically, once per Agreement
(`kit/arkhai-mediation/src/market_arkhai_mediation/contract_data/mediation.schema.json`:
`CaseConcurrencyPolicy`, `CaseDismissalPolicy`, `RecordRetentionPolicy`,
`automatic_rulings`). SCM reads none of those fields. For the deals a production
seller's options name today, Arkhai operators rule by hand.

**Released.** `marketplace-v0.4.0` carries all of the above. On 2026-11-26 the
development branch differs from that tag in no file under `domains`, `kit`,
`provisioning`, `core`, `helm`, `e2e-tests` or `tools`.

## Decisions

### D1 — The change qualifies and documents; it adds no gate, flips no switch and changes no default

This change makes per-period bare metal, and a setup charge, supported seller
configurations. Supported means what it means for on-demand and spot VM: a shipped
chart example that renders and passes the storefront's startup check, seller, buyer and
operator documents that describe it, and live evidence that the hosted authorities emit
what the lanes' doubles emit. One requirement's wording changes, the sentence that keeps
setup-bearing presets disabled. The change also makes the live observations Goal 8
still lacks, and its closeout records them.

No code gate is added, no default changes, and nothing is declared in production. A
seller can declare both configurations on marketplace 0.4.0; what this change adds is
the repository saying so, and on what evidence. Withdrawal stays the seller removing
the table.

Rejected:

- A gate that refuses a treatment or a setup charge until a hosted authority has been
  shown to execute it. It would key behaviour to a deployment this repository does not
  know, and the same gate was rejected for VM.
- Moving the bare-metal documents and the setup requirement into sibling changes and
  keeping only a closing qualification. Each piece is small, they wait on one live run,
  and one topology preparation serves them together.
- Closing Goal 8 from the roadmap alone. Bare metal and the setup charge would stay
  undocumented and unobserved.

### D2 — Live evidence is made in the live verification form, against a topology the deployment prepares

Every live observation of this change is a live verification scenario: the twin of a
lane row, sharing that row's stages up to the input and its assertion on the output,
on wall time, with its topology requirements in prose beside it in
`e2e-tests/README.md`. This change names no target and prepares none. The deployment
prepares a topology meeting the requirements, runs the modules, and records one
sanitized summary; a requirement the topology does not meet leaves the observations
needing it unproven, naming the requirement.

What the topology must provide, beyond what each scenario adds: Arkhai payments in test
mode executing rate parts; a hosted mediation authority serving the vendored
`arkhai.mediation.v1` contract against that payments target; this repository's
storefronts, provisioning service and registry on mock provisioning; and a ruling
policy standing in for an operator's decision on a contested case (D6).

The live run is a pause inside implementation. Nothing external holds the design.

Rejected:

- This change preparing a hosted target, its personas, funding and readiness. That
  needs knowledge the repository lacks and is the deployment's.
- Complete deals run live, with restart and lost-response recovery exercised against
  the hosted authorities. What a storefront does after an authority's output is its
  lane twin's evidence, and the hosted authorities offer no fault control.
- Verifying the authorities' own arithmetic and their interaction with each other:
  holds, extensions, partial reversals. The lanes' doubles prove this repository's
  handling of each, and the rest is the authorities' own to qualify.

### D3 — The live scenarios run on mock provisioning; a real-host run is owed only when the Ansible layer changes

The bare-metal live scenarios run on mock provisioning, as VM's do. No observation of
this change needs a real bare-metal host, and Goal 8's completion needs none.
Real-host qualification is `complete-real-provisioning-qualification`'s, which states
the rule below too (its design, D1); whichever of the two changes lands first writes it
to `docs/guidance/repository/qualification-evidence.md`.

A real-host run verifies the Ansible layer and how each provisioning adapter executes
it. It is owed again when a change touches either, and not otherwise. Real hosts were
exercised for the 0.3.0 and 0.4.0 releases, so the question for this change is whether
anything since the last release changes what such a run would verify. Nothing does:

- The development branch differs from `marketplace-v0.4.0` in no Ansible, IaC or
  provisioning path.
- No open Goal 8 change touches a playbook or a role.
- Machine timing is not an input to billing, stops, penalties, disputes, the payout
  hold or the funded end. The lanes hold a provisioning job at a gate under lane time,
  so every instant those depend on is one a scenario sets.
- Nothing in Goal 8 reads a GPU result.

Both compute domains deliver a rate deal through the path they deliver a once-only deal
through, so a real host shows nothing particular to a deal paid by the period.

Rejected:

- One complete bare-metal rate deal on a real host as a completion criterion. It would
  make the goal wait on hardware to repeat what the last release's run showed.
- A note in `complete-real-provisioning-qualification` asking its real-host module to
  buy a per-period option. The rule above already says when a real-host run is owed.

### D4 — Only `converge-ongoing-compute-leases` gates this change, and it gates the design

This change depends on `converge-ongoing-compute-leases` alone, and that change gates
this one's design. A live verification scenario extends a lane row and shares its
assertion, so this design is, at its core, the list of which landed lane rows get a
live twin, and it cannot be written before those rows are.

No other Goal 8 change gates it, because none adds a lane row that reaches an authority
with an output this change would compare:

| Change | Why it does not gate this one |
|---|---|
| `end-delivery-when-funding-runs-out` | Funds running out is already compared live; a funded instant the authority cannot confirm cannot be made live |
| `renewable-compute-lease-deadlines` | The site is this repository's own service; no external party is involved |
| `discover-open-ended-compute-listings`, `filter-listings-by-capacity-bounds` | No live scenario reads a class or a bound |
| `offer-a-seller-chosen-payout-hold` | It makes its own live observation of its hold shape, once the dispute authority maps one |

Goal 8's order is the roadmap's: its "Done when" names each closeout the goal waits
for, `offer-a-seller-chosen-payout-hold`'s among them. Whichever of those changes
closes out last records the goal complete in its closeout's roadmap part.

Rejected:

- Every Goal 8 gap owner as a dependency, so that this change closes last. A dependency
  that gates nothing makes the goal's order a property of one index row, and every
  rewrite of a sibling then has to edit this change.
- Goal 8 completing without the payout hold. The goal waits for it; what its
  implementation waits on is a publication the dispute authority's side makes.
- This change verifying the payout hold's shape live. It would import that change's
  external wait into this one.

### D5 — An observation is live only where a prepared topology can produce the authority's output

A buyer-recovery or dispute observation is made live only where a prepared topology can
produce the authority output it compares. Three are:

- a case over money already paid out, which the authority accepts and answers per part
  as not held, with no money moved;
- a payer's stop sent again under its original operation key, which the payment
  authority answers as the stop it already recorded;
- an operator's ruling of a contested case, made by a topology's ruling policy (D6).

The others are lane rows of `converge-ongoing-compute-leases`: a buyer's stop with the
storefront stopped, a seller that never files, a seller's timely `available` weighed
against the buyer's kept observation, a buyer's end while the payment authority is out
of reach. The storefront's state is not an input to an authority, so a payer's stop
sent while the storefront is stopped is, to the payment authority, the buyer's stop
already observed; and a hosted authority cannot be made unreachable.

The dispute authority's published policy is not a gate of this change. The vendored
contract fixes its treatment of repeated and concurrent cases, its dismissal policy and
its record-key and origin retention as constants of every `arkhai.mediation.v1`
authority's description, so an authority serving that contract states them. The
payments receipt key's retention stays an accepted limitation of the goal, stated in
the roadmap.

This restates two earlier decisions recorded in this change's ledger (lines 5 and 6):
that the authority's published policy and key retention are gates, and that the buyer's
independent recovery is five live observations, each a blocker if unrun.

Rejected:

- Keeping every recovery observation live. Most cannot be produced against a hosted
  authority, and a criterion that cannot be met holds the goal open for nothing.
- A policy document hosted or checked here. The authority's procedures are its own.

### D6 — An operator's ruling of a buyer's contested case is an acceptance criterion

This change owns the live observation that a buyer's contested `delivery_end` case on a
rate deal is ruled by an operator: the buyer files, the storefront contests, and the
ruling — a delivery end, a stop of the part returning its period, and a reversal — is
read from the authority's signed record and the payment snapshot. The scenario and its
assertion exist (`e2e_vm_live_dispute`); the ruling has never been made live.

It is an acceptance criterion of Goal 8, and this change does not close out with it
unproven. What it waits on is a topology that applies a ruling policy, deciding as an
operator would once the payee has answered. That is a capability the dispute
authority's side provides: SCM calls no operator interface.

Rejected: closing with the ruling recorded unproven, as the VM switch-on did. That was
right for an earliest form whose required observations were the other five; the goal's
completion claims a buyer's remedy against a seller that contests, which this
observation is the only live evidence of.

### D7 — Mechanical remedies stay a Goal 8 acceptance criterion, and what blocks them is a capability the hosted dispute authority owes

The full form of Goal 8 includes mechanical remedies: the hosted dispute authority
ruling a seller's `delivery_end` filing without a person, for the deals a production
seller's options name. Arkhai operators rule by hand today. A hosted authority on the
vendored contract has made that ruling on a topology prepared for live verification,
which shows that SCM's filing is one the authority can rule mechanically; it does not
show what the authority production options name does.

SCM builds nothing for this criterion. The storefront already files the claim the
authority may rule without a person, sends no stop or reversal of its own, and services
whatever the ruling does. The roadmap states the criterion and names the capability as
what blocks it, and says nothing of how or when the authority provides it.

The criterion sits in this change's row of the roadmap's gap table, so this change's
closeout records it met, in the form Q4 settles, and waits for the capability as it
waits for the ruling policy of D6.

Rejected:

- Dropping mechanical remedies from the goal because one topology has shown one.
- Stating the dispute authority's delivery plan in this repository. The roadmap states
  SCM's acceptance criteria and what blocks them, and is not a roadmap for another
  service.

### D8 — The servicing declaration gains no further role

This change adds nothing that reads `[Settlement.rate_servicing.<mechanism>]` or that
gives it a further meaning: no qualified-treatments gate, no key, no check beside the
three doors. The bare-metal example declares it as the VM example does, because that is
what a 0.4.0 storefront requires in order to publish a recurring option.

The table is a second statement beside the recurring publication clause, and its
`setup` a second switch beside the clause's `setup_amount`. Retiring it, or moving what
genuinely varies to the resource pool, is recorded as unowned work under Goal 8 in the
roadmap. It is not this change's: the table is released in 0.4.0, the requirements of
several capabilities rest on it, and retiring it owes the sellers who set it a
compatibility path.

Rejected: retiring the table here, which would put a released configuration key's
compatibility question inside a change that otherwise alters no released form; and
recording nothing, which would leave a seller-wide switch shipped absent unremarked.

## Live scenarios

The form of the table the design session completes. Rows marked settled follow from the
decisions above; the rest depend on the open questions and on the rows
`converge-ongoing-compute-leases` lands.

| Live scenario | Lane twin | Input to the authority | Output compared | State |
|---|---|---|---|---|
| Buyer's stop, VM | The recurring purchase's buyer end | A payer stop | Cause `payer`, `charged`, the started period charged | Made 2026-11-23; Q7 |
| Funds running out, VM | The funds-exhausted row | A balance of N periods | A `terms` stop at the funded boundary, N periods settled | Made 2026-11-23; Q7 |
| Spot preemption, VM | The preemption row | A payee stop with notice | Pending, then final at receipt plus notice, `returned`, the remainder refunded | Made 2026-11-23; Q7 |
| Term end, VM | The maximum-term row | The part's end | Ended at the Agreement's end, `returned` | Made 2026-11-23; Q7 |
| Seller's filing, VM | The rate-dispute row | The storefront's payee filing | Each part protected; the authority's stop `returned` with its reversal, the capped penalty, extensions lifted, the case closed | Made 2026-11-23; Q7 |
| Buyer's contested case, VM | The rate-dispute row | The buyer's filing, contested | The topology policy's ruling: the authority's stop `returned` with its reversal, and a reversal | Filing and contest made; the ruling is owed (D6) |
| A case over paid-out money | Converge's row 13, on a rate part | The buyer's filing after the part is paid out | The filing accepted, the part not held, no money moved | Settled live (D5); feasibility in Q3 |
| The same-key stop replay | Converge's row 1 | The payer's stop sent again under its operation key | The stop already recorded, no second stop | Settled live (D5); feasibility in Q3 |
| Bare metal, through the bare-metal buyer | The bare-metal lane's rows | Open | Open | Q1 |
| A setup-bearing deal | A converge row with a setup part, or one added here | Open | Open | Q2 |
| The remaining rows that reach an authority | Converge's rows, once landed | Open | Open | Q3 |

## Open Questions

Each is decided in this change's design session.

### Q1 — What bare-metal live evidence is enough

A mode earns a live scenario of its own only where it makes the external party run
different code (`system-tests.md`). Both compute domains derive the mandate, send stops
and file through the same kits; what differs is the bare-metal buyer's commands and
each storefront's composition. The roadmap's "Done when" asks for a buyer that has
changed no acceptance setting taking on-demand and spot live in both domains.

- (a) Bare-metal twins of all six VM live scenarios.
- (b) Two: a default buyer's on-demand deal bought through `market bare-metal buy` and
  ended by its own stop, and a spot deal preempted with the remainder returned. That is
  the "Done when" sentence and nothing more.
- (c) None. Bare metal rests on its lane rows and VM's live evidence, and the "Done
  when" is reworded to say so.

Recommended: (b). It runs the bare-metal buyer's and storefront's client code against
a live authority once each way and repeats no dispute scenario whose input the shared
kits produce. It would move to (a) if the bare-metal lane's dispute twins, which
`converge-ongoing-compute-leases` leaves open, turn out to run bare-metal code on the
filing path.

### Q2 — How a setup charge becomes supported

The requirement to change, as it reads today:

> Setup-bearing presets MUST remain disabled until a hosted dispute authority is
> qualified on the vendored delivery_end revision.

A seller's configuration with a setup charge, which a 0.4.0 storefront accepts:

```toml
[Settlement.rate_servicing.arkhai_payments]
treatments = ["charged", "returned"]
setup = true

[[pricing.settlements]]
mechanism = "arkhai.payments.v1"
asset = "USD/6"
rate = "4.00"
per = "hour"

[pricing.settlements.recurring]
period = "PT1H"
reserve_ahead_seconds = 3600
setup_amount = "50000000"   # USD 50.00, charged once at the Agreement's start
```

- (a) One live scenario: a setup-bearing rate deal whose seller files a
  `delivery_end` saying the resource was never delivered, and whose ruling returns the
  setup part. Once it is made, the sentence is replaced by what a setup-bearing option
  requires — the declaration's `setup` and a dispute authority that returns setup by
  delivery — and the bare-metal example prices a setup charge.
- (b) The sentence is replaced on lane-double evidence alone. The return is the
  authority's own arithmetic, which a live scenario compares but SCM does not compute.
- (c) Setup charges leave the goal, and the sentence stays.

Recommended: (a). A buyer's remedy for a setup charge on a deal never delivered rests
wholly on that one ruling. Its lane twin is a row of `converge-ongoing-compute-leases`
if that change's lanes declare a setup charge; otherwise this change adds the twin.

### Q3 — Which of converge's landed rows get a live twin

The design names them once `converge-ongoing-compute-leases` has landed. The candidates
are its rows whose outcome is an authority's output: a spot seller's filing; a seller's
filing on an undelivered deal, at the Agreement's start; a buyer's surrender whose
signed receipt carries the seller's concurrence, ruled without a person; a revised
`delivery_end`, which the authority sends to an operator; and the two D5 names.

Two of D5's observations have feasibility to settle:

- **Paid-out money.** A rate part is paid out only after its stop, the dispute window
  and the payments service's payout delay. On wall time that needs a topology whose
  dispute authority advertises a minimum filing window, and whose payments target a
  payout delay, short enough to pass within a run. Whether a topology can offer that is
  the deployment's to say.
- **The same-key replay.** The buyer retries a stop under its original key only after
  an unknown result. Whether the buyer's own command can be made to send the replay
  against a hosted authority, without a fault control, is not verified.

The alternatives:

- (a) Every candidate gets a twin.
- (b) A twin only where the authority runs code no made observation has run: a
  concurrence ruling, an undelivered claim, a part not held, a replay. A spot seller's
  filing differs from the on-demand one only in the penalty the Agreement states.
- (c) Only D5's and D6's observations.

Recommended: (b), by the rule Q1 applies.

### Q4 — What shows the mechanical-remedy criterion met

D7 keeps the criterion and names its block. Open is what this repository records as
showing it met. The vendored contract cannot show it: every authority's description
states the same constant for automatic rulings.

- (a) The deployment's summary of the seller's-filing scenario states, by a public-safe
  alias, that the topology's dispute authority is the one production sellers' options
  name, at the revision it runs.
- (b) The roadmap records the criterion met when the authority's side says it is, and
  this repository holds no evidence of it.

Recommended: (a). It is the form every other live claim of the goal takes.

### Q5 — The shape of the bare-metal production example

The VM chart's example is payments-only. The bare-metal chart's is Alkahest-only, and
its render test asserts on the wallet Secret that Alkahest needs.

- (a) One example carrying both mechanisms, abridged:

  ```yaml
  Settlement:
    schema_version: 1
    priority:
      - arkhai.payments.v1
      - alkahest.v1
    alkahest:
      enabled: true
    arkhai_payments:
      enabled: true
      service_url: https://payments.example.com
      fee_bps: 250
      livemode: true
    rate_servicing:
      arkhai_payments:
        treatments: [charged, returned]
        setup: true
  pricing:
    default_max_duration_seconds: 86400
    settlements:
      - mechanism: alkahest.v1
        asset: "0x00000000000000000000000000000000000000bb"
        rate: "10"
        per: hour
      - mechanism: arkhai.payments.v1
        asset: USD/6
        rate: "4.00"
        per: hour
        recurring:
          period: PT1H
          reserve_ahead_seconds: 3600
          setup_amount: "50000000"
        mechanism_input:
          payee_account: "00000000-0000-4000-8000-0000000000aa"
          asset: USD/6
          approval_window: PT10M
          delivery_deadline_seconds: 3600
          dispute_window_seconds: 1296000
  ```

- (b) A second example file beside the first, payments-only, as VM's is.
- (c) The one example becomes payments-only, and the Alkahest example is dropped.

Recommended: (a). A bare-metal seller reads one file, and the render test goes on
covering Alkahest. It would move to (b) if the two mechanisms' readiness checks cannot
both pass on one rendered configuration. Whether the example prices a setup charge
follows Q2.

### Q6 — `prorated`

The declaration admits a third treatment, `prorated`, which no shipped preset uses: a
seller's stop and the term end default to returning the period, and a default buyer
refuses anything else at either.

- (a) A non-goal, revisited when a preset or a seller offers it.
- (b) One live scenario under `prorated`, since it is a code path at the payment
  authority no observation has run.

Recommended: (a). Whether a prorated preset is anticipated is the owner's to say.

### Q7 — Whether VM's observations are made again

Five VM observations were made on 2026-11-23, at a source revision that precedes every
change Goal 8 still waits for.

- (a) Re-run only where the authorities' revision the topology runs has changed.
- (b) Re-run all six in the closing run, beside the new ones. The modules exist, the
  topology is prepared anyway, and one summary then states one source revision and one
  authority revision for everything the goal claims.
- (c) Never: the summary of 2026-11-23 stands.

Recommended: (b). `converge-ongoing-compute-leases` and
`end-delivery-when-funding-runs-out` both change the servicing code on those scenarios'
input path.

### Q8 — The advisory time to rule

`openspec/specs/deal-lifecycle/architecture.md`, "External authorities", says an
advisory expected time to rule, "if the authority publishes one, is shown as advisory".
No code shows one, and the vendored contract has no field for it: the description's
response and inactivity bounds are constant null.

- (a) This change corrects the sentence, since it rewrites that passage at promotion.
- (b) The display is built. It would need a contract field first.
- (c) The sentence is tabled as an unowned row.

Recommended: (a).

### Q9 — Provisional answers

Each follows from something settled or from the nearest precedent, and is confirmed or
moved in the design session.

- **Requirements this change modifies**, their deltas written once Q1 to Q3 and Q5
  settle. `deployment-state`: a requirement beside "The VM storefront chart ships a
  production example offering on-demand and spot", for the bare-metal chart.
  `deal-lifecycle`: "Setup returns by delivered for either cause". `test-compatibility`:
  "Rate deals and dispute filings are verified live against a prepared topology".
  `settlement-configuration`'s requirements are unchanged; its configuration companion
  is corrected.
- **Documents a seller, buyer or operator reads.** `docs/bare-metal-seller-quickstart.md`
  gains a section on offering on-demand and spot, with the recommendation that a
  bare-metal seller price a setup charge, since provisioning a host costs the seller
  whatever the deal's length. `docs/buyer-quickstart.md`, "7. On-demand and spot",
  speaks of both domains and of a setup charge. `docs/operator-handbook.md`, "Serving
  rate deals", speaks of both storefronts.
- **The example's checks.** The bare-metal example is rendered, passes the storefront's
  startup check and publishes its recurring options under a representative dispute
  authority advertisement, as the VM example's render test checks
  (`docs/guidance/repository/chart-render-tests.md`).
- **Evidence.** The deployment's sanitized summary, one file under `docs/attachments/`
  in a directory named for this change, per observation made, failed or unproven, with
  public-safe provenance. Raw logs stay in the deployment's storage.
- **Test levels.** The example's checks are chart render tests. Each live scenario's
  assertion is unit tested on outputs of the payments kit's engine, as the VM ones are.
  The live modules are in no lane.
- **Compatibility.** As the proposal's "Impact" states it against `marketplace-v0.4.0`.
- **Diagrams.** This change promotes none. The scenario diagrams the roadmap's "Done
  when" names are promoted by the changes that own the scenarios.

### Q10 — Implementation cadence

Recommended: two rounds. First, internal: the bare-metal example with its render test,
the documents, the live modules with their requirements and their assertions' unit
tests, one or two sessions. Then live verification: the round waits for the deployment
to run the modules and record the summary, and the requirement on setup charges is
reworded and the companions corrected from what the summary shows.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 bare metal and a setup charge as supported configurations | `docs/bare-metal-seller-quickstart.md`; `docs/buyer-quickstart.md`; `docs/operator-handbook.md`, "Serving rate deals"; `openspec/specs/settlement-configuration/configuration.md`; `openspec/specs/deployment-state/spec.md` |
| D2 live evidence in the live verification form | `e2e-tests/README.md`, "Live verification"; `docs/development/TESTING.md`, "Live verification"; `openspec/specs/test-compatibility/spec.md` |
| D3 mock provisioning, and when a real-host run is owed | `docs/guidance/repository/qualification-evidence.md` |
| D4 one dependency, the goal's order in the roadmap | `docs/development/ROADMAP.md`, Goal 8's "Done when" |
| D5 which observations are live | `openspec/specs/test-compatibility/architecture.md`, "Payment evidence ownership" |
| D6 the contested case as an acceptance criterion | `docs/development/ROADMAP.md`, Goal 8; `openspec/specs/test-compatibility/spec.md` |
| D7 mechanical remedies and their block | `docs/development/ROADMAP.md`, Goal 8; `openspec/specs/deal-lifecycle/architecture.md`, "External authorities" and "Current limits" |
| D8 no further role for the servicing declaration | `docs/development/ROADMAP.md`, Goal 8's unowned work |
