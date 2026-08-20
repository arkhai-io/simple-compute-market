## MODIFIED Requirements

### Requirement: Hosted consumer configuration pins the expanded release

Enabling any expanded hosted profile MUST pin one exact verified hosted manifest, client wheel, API/schema version, payer-profile contract, funding-authorization contract, funding-profile set, identity capability, and service image identity. Buyer and storefront roles MUST agree on those public pins before publication or authorization. Marketplace schemas MUST reject hosted provider, Customer, PaymentMethod, mandate, webhook, database, migration, and administrator fields.

Those pins MUST be taken from the hosted release the run bound. A consumer MUST NOT carry an API version, schema version, or capability set of its own that a bound release is then measured against, because a consumer that names one release in its own configuration cannot admit the next one, and reports a genuine contract disagreement as a configuration edit that was not made. Where a run binds a release, the rendered consumer configuration MUST state that release's coordinates; where no release is bound, no consumer configuration MUST be rendered at all.

Enforcement MUST NOT weaken. A disagreement between the bound release and the composed authority MUST fail closed before publication or authorization exactly as it does when the pins are written down.

#### Scenario: Buyer and storefront pins differ

- **WHEN** the buyer expects a different payer/profile capability or client identity from the publishing storefront's verified authority release
- **THEN** compatibility fails before terms acceptance or payer authorization

#### Scenario: A run binds a hosted release the consumer has never seen

- **WHEN** a run binds a hosted release whose API version, schema version, or capability set differs from every release bound before it
- **THEN** the rendered consumer configuration pins that release's own coordinates and the run proceeds, without a change to consumer source

#### Scenario: The composed authority contradicts the bound release

- **WHEN** the authority a run composed serves an API version, schema version, or capability set other than the one the run bound
- **THEN** the run fails closed before publication or payer authorization and names the disagreement

### Requirement: Buyer hosted compatibility includes local payer readiness

Buyer compatibility for a hosted option MUST require the exact installed profile capability, supported USD/country policy, required interaction ability under the current action policy, and a selected local buyer profile with an active opaque payer binding ready for that authority/environment. Discovery-time checks MUST use only local profile metadata and advertised option data; they MUST perform no hosted mutation. Compatibility MUST be revalidated immediately before negotiation start and exact authorization.

A setup that the authority reports as awaiting payer-held verification MUST be treated as not yet ready. It MUST NOT be reported as revoked, unavailable, or failed, and it MUST NOT satisfy a saved or off-session mode until the authority reports the instrument ready.

#### Scenario: Buyer selects an ACH interaction mode

- **WHEN** an advertised ACH option survives resource filtering and the selected local profile has an active authority/environment binding plus interaction capability
- **THEN** explicit interactive mode remains compatible without a saved mandate, while saved/off-session mode requires the exact ready instrument and mandate

#### Scenario: Local readiness changes after discovery

- **WHEN** the selected payer binding or instrument readiness becomes revoked before negotiation starts
- **THEN** revalidation fails without accepting terms or switching to another profile

#### Scenario: A setup is awaiting payer-held verification

- **WHEN** the authority reports a bank-funded setup as pending the payer's own verification evidence
- **THEN** saved and off-session modes remain incompatible for that instrument, the profile is not reported as revoked or unavailable, and no other funding option is substituted

## ADDED Requirements

### Requirement: A payer submits its own instrument setup verification

Where the bound hosted release declares the direct payer instrument setup capability, a buyer MUST be able to complete a bank-funded instrument setup by submitting the verification evidence the payer's own bank made available to them, without a browser session and without an operator acting on the payer's behalf.

One submission MUST name exactly one pending setup under exactly one opaque payer binding, and MUST carry exactly one form of evidence: either the deposited minor-unit amounts, or the descriptor code. Carrying both, or neither, MUST fail before any hosted mutation.

The submission and its result MUST carry no provider identifier, Customer, PaymentMethod, mandate, bank or card detail, client secret, action URL, or raw provider payload, and marketplace persistence MUST NOT retain the submitted evidence. The result MUST expose only the opaque setup reference, public readiness, and any transient action the authority returns.

Starting a setup that the payer will answer directly MAY carry one opaque provider token naming the instrument the payer already holds, because an authority given no instrument issues a hosted page instead and the setup is no longer one the payer can answer. That token MUST be transient on the same terms as an action URL: passed to the authority, never persisted in a marketplace row, never projected, and never reported. Marketplace configuration MUST continue to reject provider and payment-method fields outright.

Where the bound release does not declare the capability, the operation MUST be reported as an unavailable prerequisite naming that capability, before any hosted mutation, rather than attempted and failed.

#### Scenario: A payer submits microdeposit amounts

- **WHEN** a payer submits the two deposited minor-unit amounts against a setup the authority reports as awaiting verification
- **THEN** the authority's readiness for that setup is returned, the instrument becomes usable for saved and off-session modes once it is ready, and no provider material is persisted or reported

#### Scenario: A submission carries both forms of evidence

- **WHEN** a submission names both deposited amounts and a descriptor code, or names neither
- **THEN** it is refused before any hosted call, and the pending setup is left untouched

#### Scenario: The bound release lacks the capability

- **WHEN** a verification submission is attempted against a bound release that does not declare direct payer instrument setup
- **THEN** the capability is reported as the unavailable prerequisite before any hosted mutation, and no alternate path is substituted

#### Scenario: A setup is started from an instrument the payer holds

- **WHEN** a setup is started with an opaque provider token for the payer's own instrument
- **THEN** the authority reports the setup as awaiting verification with no hosted action, and the token appears in no marketplace row, projection, or report

#### Scenario: Verification evidence is not retained

- **WHEN** a submission has been made and its result recorded
- **THEN** marketplace persistence and any report contain the opaque setup reference and public readiness only, and contain no amounts, descriptor code, or provider payload
