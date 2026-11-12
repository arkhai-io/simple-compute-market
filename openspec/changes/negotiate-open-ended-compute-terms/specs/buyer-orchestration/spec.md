## ADDED Requirements

### Requirement: Buyers approve explicit compute price and end terms

Both compute buyers MUST display the derived product class, quote with unit,
separate setup once charge, initial reserve, maximum term/end, selected horizon,
the delivery deadline as seconds after approval within which the resource is available to the buyer,
payer/payee entitlements, notices, per-stopper and term-end `settles_through`, premature-stop penalty amount/asset/cap, and adjudication/retention terms
before approval.

#### Scenario: On-demand approval

- **WHEN** a buyer approves a payer-only recurring option with a setup once part
- **THEN** the display says on-demand, separately shows setup and recurring charge, and states payer notice and started-period treatment without granting the payee an entitled reclaim right; the display does not claim the mandate enforces that the seller will not preempt, since on-demand gives the seller no stop entry and the buyer's remedy is the penalty and a case over held money
- **AND** it explains stop-then-hint with service through the effective stop, receipt-only immediate surrender, that the storefront cannot stop billing and the buyer's journaled, retried authority stop does, and the optional delivery_end case, automatic with matching receipt concurrence and guards, otherwise triaged

#### Scenario: Payee treatment is displayed faithfully

- **WHEN** a buyer selects an interim spot option with `settles_through: started_period` for both parties
- **THEN** the display says both stops charge the started period, not that seller preemption returns it
- **AND** the display states that the setup charge is owed from approval, not reversed by a payment stop alone, and returned iff delivered=false for either cause in a qualified delivery_end claim

### Requirement: Buyer display separates billing guarantees from cooperation

Both compute buyers MUST distinguish reserve from spend, billing start from observed delivery, and authority guarantees from cooperative seller behavior. A filed case MUST be shown by the authority's per-part `held` / `not_held` answer and MUST NOT be shown as a pending refund. They MUST NOT present reserve-ahead as a dishonest-seller billing cap.

#### Scenario: Reserve is displayed

- **WHEN** a buyer views the selected option's initial reserve
- **THEN** display identifies reserved funds, not a spend floor or a cap on dishonest-seller billing

### Requirement: The buyer refuses seller ends that keep the started period

The buyer's acceptance policy MUST by default refuse an option whose payee entitlement or term end has a `settles_through` other than `last_boundary`, and MUST let the buyer configure the treatments it accepts. The refusal MUST name the term.

#### Scenario: A spot option charges the started period on a seller stop

- **WHEN** a buyer with the default policy is offered a spot option whose payee entitlement settles through `started_period`
- **THEN** the buyer refuses the option, naming the payee entitlement's `settles_through`

#### Scenario: A buyer accepts charged seller stops

- **WHEN** a buyer configures its policy to accept `started_period` on payee stops
- **THEN** the same option is acceptable

### Requirement: Default acceptance requires an on-demand seller penalty

Buyer acceptance policy SHOULD refuse an on-demand option without positive early_termination.premature_stop_penalty and a compute option whose mechanism has a lifecycle adapter without `delivery_deadline_seconds`, and MUST expose an explicit buyer waiver for each, as "Each default refusal has its own waiver" gives them; an option without a lifecycle adapter MUST be shown as making no delivery promise rather than refused for lacking one.

#### Scenario: The full policy is enforced

- **WHEN** a default buyer evaluates the on-demand option before approval
- **THEN** Buyer acceptance policy SHOULD refuse an on-demand option without positive early_termination.premature_stop_penalty and a compute option whose mechanism has a lifecycle adapter without `delivery_deadline_seconds`, and SHOULD expose explicit buyer opt-out for each; an option without a lifecycle adapter MUST be shown as making no delivery promise rather than refused for lacking one. Before approval of a setup-bearing option it MUST state that the setup charge is owed from approval, is kept by the seller if the buyer stops, and returns only when the seller never delivered — by the seller's own filing, its signature on the buyer's claim, or a person's ruling on the buyer's evidence. It MUST display the selected value as a ceiling and explain that an unentitled seller end forfeits at most earned amounts still held after unearned-money refunds — at the start of a deal the setup charge, and nothing when nothing is earned and held; it MUST NOT present the penalty as an assured amount; an entitled notice stop pays none. A buyer claim uses the same remedy, mechanically with payee agreement and guards, otherwise through an operator.

#### Scenario: An on-demand option has no penalty

- **WHEN** the buyer uses the recommended default acceptance policy and the on-demand penalty is absent or zero
- **THEN** selection refuses it by name rather than claiming the mandate prevents preemption

### Requirement: Recurring purchase may omit a horizon

Compute buyers MUST permit omitted duration for recurring selections and use the
seller-bound horizon returned in the final accepted terms. Reserved selections
MUST carry a duration: the buyer's, or, for `bare-metal buy` alone, its configured
`default_duration_seconds`, 3600 unless configured. Both domains MUST permit recurring purchases without a
protocol minimum-spend term; setup fees and churn refusal MUST be represented as
seller pricing/policy.

#### Scenario: Unnamed bare-metal horizon

- **WHEN** a buyer selects a bounded bare-metal recurring option without naming duration
- **THEN** the buyer can proceed using its finite bound without a minimum-spend gate

#### Scenario: Missing reserved duration

- **WHEN** a fresh reserved VM selection omits duration
- **THEN** the buyer refuses rather than substituting an hour or listing maximum

#### Scenario: A bare-metal reserved purchase names no duration

- **WHEN** `bare-metal buy` selects a reserved option without a duration
- **THEN** it uses its configured `default_duration_seconds`, 3600 seconds unless configured, shown in the disclosure as the buyer's default, and never applies that default to a recurring option

### Requirement: Both buyer CLIs take a duration in seconds

`market buy`, `market negotiate` and `bare-metal buy` MUST accept `--duration-seconds`; the VM
commands MUST also keep `--duration-hours`. Giving both MUST be an error naming the conflict.

#### Scenario: Both duration flags are given

- **WHEN** a buyer runs `market buy --duration-seconds 3600 --duration-hours 1`
- **THEN** the command refuses before selection, naming both flags

### Requirement: Each default refusal has its own waiver

Both compute buyers MUST offer one waiver per default refusal — `--allow-no-delivery-deadline`,
`--allow-no-penalty`, `--allow-charged-preemption` and `--allow-charged-term-end` — each waiving
exactly its term, with `--allow-unprotected-terms` as shorthand for all four. The foundation's
missing-deadline allowance MUST be set only by the deadline waiver or the shorthand. Every
waiver used, singly or through the shorthand, MUST be recorded in run metadata and named in
the pre-approval disclosure. Codec, capability and authority checks MUST NOT be waivable.
A resumed or recovered run MUST use the waivers its run metadata recorded, and MUST refuse
waiver flags given to the resuming command.

#### Scenario: One term is waived

- **WHEN** a buyer passes `--allow-no-penalty` and selects an on-demand option with no penalty and a charged term end
- **THEN** the penalty refusal is waived, the charged term end is still refused by name, and the run's metadata and disclosure name the one waiver

#### Scenario: A resumed run keeps its waivers

- **WHEN** a VM run started with `--allow-no-delivery-deadline` is resumed with `market settle --from`, and another resume passes `--allow-no-penalty` with `market buy --from`
- **THEN** the first resume's accepted disclosure names `--allow-no-delivery-deadline` from the run's metadata, and the second is refused before any negotiation, naming that waivers apply only to fresh runs

### Requirement: The mechanism supplies the numbers a buyer is shown

Each installed mechanism registration MUST supply
`present_payment(option, requested_duration, accepted_quote)`, returning the quote, a separate
setup once charge and the initial reserve in the quote's asset and minor units, zero meaning
none and null undetermined. The registry MUST check the billing basis and asset and that an
accepted quote is returned unchanged, and MUST refuse a registration with no presenter. Buyers
MUST render these values and MUST NOT parse a mechanism's payment fields themselves.

#### Scenario: A presenter changes accepted money

- **WHEN** a mechanism's presenter returns a quote different from the accepted accessor quote
- **THEN** the registry refuses the presentation before any display or approval

### Requirement: The bare-metal buyer purchases hosted options only

`bare-metal buy` MUST purchase only the hosted options its installed stages support; its shared
rights policy and disclosure MUST still admit an Alkahest peer on the same listing as making no
delivery promise, without a fabricated purchase stage.

#### Scenario: A mixed bare-metal listing

- **WHEN** a default bare-metal buyer views a listing with a hosted on-demand option carrying a delivery deadline and an Alkahest reserved option
- **THEN** the hosted option is checked for its terms and can be bought, and the Alkahest option is shown as making no delivery promise but is not offered for purchase
