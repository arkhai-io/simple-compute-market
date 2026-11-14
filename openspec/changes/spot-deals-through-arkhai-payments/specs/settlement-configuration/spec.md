## ADDED Requirements

### Requirement: Hosted rate parameters are explicit and unit-safe
SCM MUST admit period and reserve_ahead_seconds together or neither and require positive fixed-unit values. Rate options MUST have a finite maximum term. Materialization MUST reject fractional Agreement starts. Optional setup_amount MUST be a disclosed positive minor-unit amount in the selected asset; omission MUST mean no setup part. Approval expiry and dispute holds MUST remain separate.

#### Scenario: Only one rate parameter is set
- **WHEN** an option supplies period without reserve_ahead_seconds or the converse
- **THEN** publication and mandate derivation refuse it with the missing parameter named

#### Scenario: Calendar units cannot define a billing period
- **WHEN** an option declares a calendar month or year period
- **THEN** the kit refuses it rather than approximating it in seconds

#### Scenario: A rate Agreement has a fractional start
- **WHEN** rate materialization receives a fractional-second start_utc under an integer-second payment contract
- **THEN** it refuses rather than round upward past the accepted capacity window or rewrite signed Agreement bytes
- **AND** once-only fractional timestamp handling is unchanged

#### Scenario: Rate end treatment is explicit
- **WHEN** a rate option is published or accepted
- **THEN** only early_termination.settles_through supplies term-end treatment through the deal-lifecycle codec and is checked against the servicing declaration
- **AND** an unknown value or undeclared treatment refuses instead of defaulting from current configuration

#### Scenario: A rate option is projected for billing
- **WHEN** the installed billing projection reads a payments option with paired period and reserve_ahead_seconds, with or without setup_amount
- **THEN** it projects `per_period` with the period and its seconds
- **AND** a lone period, a lone reserve_ahead_seconds or a setup_amount without a rate refuses, naming the pairing rule, and nothing projects `total`

#### Scenario: A seller opts out of setup
- **WHEN** a complete rate option omits setup_amount
- **THEN** derivation emits no setup part
- **AND** neither compute domain requires a minimum spend

### Requirement: Rate materialization requires a servicing declaration
SCM MUST refuse to materialize a rate mandate whose treatments or setup charge the composition's rate-servicing declaration does not list, checking the same declaration the publication and acceptance doors check. The refusal MUST be `RateServicingUnavailable` with the `settlement_option_withdrawn_refetch` code the acceptance door uses. This gate MUST also apply to accepted-but-unmaterialized work. Removing publication enablement MUST NOT abandon already materialized deals.

#### Scenario: An accepted option outlives its declaration
- **GIVEN** a previously accepted rate option and no current servicing declaration
- **WHEN** settlement attempts to materialize its mandate
- **THEN** materialization refuses with `settlement_option_withdrawn_refetch` before approval or delivery

#### Scenario: The declaration lacks a treatment or the setup charge
- **GIVEN** a declaration listing some treatments but not one the option's entitlements or term end name, or not declaring a setup charge the option carries
- **WHEN** the materialization door is called
- **THEN** it refuses before deriving or approving a rate mandate
- **AND** a declaration listing every treatment and the setup charge the option uses admits it

#### Scenario: The seller stage reads the composition's declaration
- **WHEN** a compute composition constructs its payments seller stage
- **THEN** it passes the declaration its publication and acceptance doors read, so materialization admits exactly what they admit

#### Scenario: Publication is disabled after materialization
- **WHEN** a previously materialized rate deal is recovered with new publication disabled
- **THEN** its existing servicing continues under accepted terms

### Requirement: Approval expiry is one term under two names
Approval expiry in `arkhai.payments.v1` option parameters MUST be read under either name, `window` or `approval_window`, as one term, and a document giving both a value MUST be refused rather than reconciled; a null names neither. Rate options MUST be written with `approval_window`; once options MUST be written with `window`, whichever name the seller's clause used, so buyers reading only `window` read them. The `arkhai_payments.approval_window` discovery field MUST project approval expiry for every option; `arkhai_payments.window` MUST project it only for once options.

#### Scenario: A buyer reads either name
- **WHEN** a buyer reads an option naming approval expiry `window` or `approval_window`
- **THEN** both give the same expiry
- **AND** an option naming both is refused, even when they agree

#### Scenario: A seller's clause names approval_window for a once option
- **WHEN** a once option is published from a clause that names `approval_window`
- **THEN** the option carries the expiry as `window` and not `approval_window`

#### Scenario: A rate option is discovered
- **WHEN** a buyer filters on approval expiry
- **THEN** `arkhai_payments.approval_window` matches rate and once options alike
- **AND** `arkhai_payments.window` is absent for a rate option

#### Scenario: The registry holds a rate option
- **WHEN** a storefront publishes a rate option naming `approval_window`
- **THEN** the registry accepts and returns it unchanged, holding mechanism parameters opaquely

### Requirement: Compute buyers select what the payments buyer helper can approve
Both compute buyers MUST take the lifecycle capabilities of their payments term context — a stoppable rate part and the partial-period treatments the vendored contract encodes — from the payments kit's buyer helper, the same set mandate derivation and seller presets use, rather than declare their own. Other mechanisms keep their own contexts. A buyer whose term validation or dispute-authority acceptance refused every advertised option MUST be told each distinct reason at normal verbosity, and a `buy` that finds nothing for that reason MUST NOT exit as a successful empty search.

#### Scenario: A buyer selects a seller's spot or on-demand option
- **GIVEN** spot and on-demand options a storefront's preset helper derived, and a buyer accepting their dispute authority
- **WHEN** the buyer selects either one
- **THEN** term validation admits it and the buyer discloses its class, per-period price, notices, penalty and partial-period treatments before negotiating

#### Scenario: Every advertised option is refused
- **WHEN** term validation refuses every option a `buy` discovered
- **THEN** the command prints why each was refused after "No listings matched" and exits 2
