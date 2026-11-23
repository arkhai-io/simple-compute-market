## ADDED Requirements

### Requirement: A buyer can publish compute demand independently of supply

The system SHALL allow a buyer to publish a compute request with a requested quantity and term and a separate deadline for responses. Ordinary supply discovery SHALL continue to return only supply listings.

#### Scenario: The requested term outlasts the response deadline

- **WHEN** a buyer requests 100 B300 nodes for six months and sets a response deadline two weeks from publication
- **THEN** the request preserves both time constraints and does not appear in searches for available machines

### Requirement: The registry validates compute requests through a registered contract

The registry SHALL admit the compute RFQ kind only when configured with a valid declarative schema and filter mapping generated from the compute-family contract. The registry SHALL use the schema and mapping to validate structured hardware, node counts, terms and search filters before serving the operation. The core registry SHALL own record lifecycle and account authorization. Descriptive metadata SHALL remain independent of structured matching and validation.

#### Scenario: A registry serves a configured compute RFQ kind

- **WHEN** a buyer publishes a valid typed compute request with an optional descriptive budget
- **THEN** a respondent can search by the hardware and quantity fields and sees the original budget wording

#### Scenario: The compute contract is unavailable

- **WHEN** an authenticated account attempts to publish a compute RFQ at a registry without the configured compute RFQ schema
- **THEN** the registry refuses the unsupported RFQ kind without creating a record

### Requirement: Buyers may state commercial terms in descriptive details

An RFQ MAY include an optional plain-text description and optional bounded flat metadata with scalar values. A buyer MAY state proposed price, deposit and other payment terms in either. The registry SHALL preserve these terms on every eligible open RFQ read, including anonymous reads where discovery is public. The request SHALL remain valid without commercial terms.

#### Scenario: A buyer states a target for private negotiation

- **WHEN** the buyer states “USD 20 per node-hour, 30% upfront, balance monthly” in the description or a metadata string
- **THEN** an eligible reader receives the wording as supplied, and publication creates no binding price or payment obligation

### Requirement: Open RFQ discovery follows supply visibility

The registry SHALL permit anonymous search and direct lookup by registry-scoped ID for open RFQs when `REGISTRY_REQUIRE_READ_API_KEY` is false, the registry's advertised public supply posture. Any ordinary authenticated account SHALL be eligible to read open requests. Anonymous discovery SHALL expose only published RFQ information and routing identity. It SHALL omit party references, private responses and contact details. Anonymous requests SHALL NOT retrieve closed or expired RFQs, and an invalid supplied account proof SHALL NOT fall back to anonymous access.

#### Scenario: Anonymous discovery in a registry with public supply

- **WHEN** an anonymous caller searches open RFQs or looks up a known open RFQ ID on a public registry
- **THEN** the registry returns the published request with its registry identity and ID and omits private fields

#### Scenario: Anonymous discovery in a registry with private supply

- **WHEN** an anonymous caller requests an RFQ on a registry that requires a supply read key
- **THEN** the registry refuses the request without disclosing RFQ information

#### Scenario: Anonymous lookup after closure

- **WHEN** an anonymous caller requests the ID of a closed or expired RFQ on a public registry
- **THEN** the registry refuses disclosure in the same way as for an unknown ID

#### Scenario: An ordinary account discovers demand

- **WHEN** an authenticated account with no seller role or listing searches for an open request and retrieves it by ID
- **THEN** the account can read the requested compute and term while private responses and contact details stay out of both results

### Requirement: An authenticated account may express interest

The system SHALL allow a signed-in account holder other than the request owner to respond to an open RFQ without a seller role, publisher registration or a supply listing. The account authority SHALL admit an ordinary holder's verified interactive session to express consent for its submitted RFQ contact and SHALL require current RFQ contact-sharing permission from a delegate. The system SHALL bind the response to the authenticated respondent and the request it answers.

#### Scenario: A participant with no listed inventory responds

- **WHEN** an authenticated participant responds to another buyer's open compute request
- **THEN** the buyer can review the response without the respondent publishing supply or reserving capacity

### Requirement: A response can indicate partial coverage

The registry SHALL accept a response with or without a quantity. A supplied quantity SHALL use the request’s unit and MAY cover only part of the request. The buyer SHALL be able to read it with the private response. Omission SHALL mean unspecified. The response quantity SHALL create no capacity reservation or commitment by either party.

#### Scenario: A provider can supply part of the request

- **WHEN** a provider indicates 40 nodes in a response to a request for 100 nodes
- **THEN** the buyer can see 40 nodes in that response before selecting anyone, and the RFQ still requests 100 nodes

#### Scenario: A provider leaves quantity open

- **WHEN** a provider submits an otherwise valid response without a quantity
- **THEN** the registry accepts it and the buyer sees the quantity as unspecified

### Requirement: Pending consent follows the requested terms

A change to the requested quantity, location, start window or rental duration SHALL require each pending respondent to explicitly confirm the revised terms before selection. Commercial edits to descriptions or metadata SHALL require fresh consent unless the registry can establish the edit is cosmetic. When the effect is ambiguous the registry SHALL require reconfirmation. A clearly cosmetic correction SHALL preserve pending consent.

#### Scenario: The buyer shortens the rental term

- **WHEN** the buyer changes a six-month request to one month while responses are pending and attempts to select a response to the old terms
- **THEN** the service refuses selection and keeps both parties’ contacts private
- **AND** once one respondent confirms the one-month term, the buyer can select that response while other respondents must still confirm for themselves

#### Scenario: An edited note changes or may change a commercial term

- **WHEN** a buyer changes a stated budget from USD 20 to USD 10 per node-hour, or revises a note whose commercial meaning the registry cannot establish as equivalent
- **THEN** the registry refuses selection under the old consent until that respondent confirms the revised request

#### Scenario: A spelling correction preserves the request

- **WHEN** the buyer corrects a spelling error that the registry can establish is cosmetic
- **THEN** the buyer can select an otherwise eligible pending response using the respondent’s existing consent

### Requirement: The buyer can manage individual pending responses

The registry SHALL allow at most one pending response per respondent account per RFQ revision. The buyer who owns the RFQ SHALL be able to dismiss a pending response, ending consent and triggering deletion of its contact payload while leaving the RFQ and other responses open.

#### Scenario: A respondent submits twice

- **WHEN** one account submits concurrent responses to the same revision or retries a successful submission
- **THEN** at most one response from that account is pending for that revision

#### Scenario: The buyer dismisses one of two responses

- **WHEN** the buyer dismisses the first pending response
- **THEN** its contact payload is deleted, a later selection of it is refused and the second response remains eligible

### Requirement: A respondent can withdraw a pending response

The respondent SHALL be able to withdraw their own pending response. Withdrawal and selection of that response SHALL be mutually exclusive. Once withdrawal succeeds, the system SHALL refuse selection of that response and SHALL keep each party’s contact private from the other for that response.

#### Scenario: A buyer selects from an older inbox view

- **WHEN** the buyer opens a pending response, the respondent withdraws it, and the buyer then selects it
- **THEN** selection is refused, neither party gains access to the other’s contact, and other responses remain eligible on their own terms

#### Scenario: Selection and withdrawal arrive together

- **WHEN** the buyer selects a pending response as its respondent tries to withdraw it
- **THEN** exactly one transition succeeds and both parties see the same outcome on retry
- **AND** if withdrawal succeeds, the system creates no introduction for that response

### Requirement: Closing or expiring a request ends pending responses

When the buyer closes an RFQ or its response deadline is reached, the registry SHALL expire every pending response and refuse any new selection. The registry SHALL preserve introductions completed before that cutoff under their own contact-access policy.

#### Scenario: The buyer closes a request with one completed introduction and one pending response

- **WHEN** the buyer closes the RFQ and then attempts to select the pending response from an earlier inbox view
- **THEN** selection is refused and neither party receives the other’s contact for that response
- **AND** the pair already introduced can continue their discussion using the details they exchanged

#### Scenario: A selection reaches the registry at the deadline

- **WHEN** the registry evaluates a new selection at or after the response deadline, even if the buyer opened the response earlier
- **THEN** it refuses the selection and creates no introduction, even if an expiry cleanup job has yet to run

### Requirement: Contact payload cleanup respects the cutoff

The registry SHALL delete the affected contact payload, including ciphertext, in the same transaction as an explicit withdrawal, dismissal, close, supersession or early termination. A time-based cutoff SHALL immediately end eligibility even while expired ciphertext remains. The registry SHALL delete expired pending and completed contact payloads from live storage within one hour during healthy operation and SHALL clear overdue payloads before admitting RFQ traffic after downtime. The registry MAY retain contact-free outcomes. Retrying a completed operation SHALL NOT restore payloads.

#### Scenario: The respondent withdraws

- **WHEN** a pending response is withdrawn and its original submission is retried
- **THEN** the withdrawal has already deleted its contact payload and the retry cannot restore it

#### Scenario: An RFQ expires while cleanup is pending

- **WHEN** an RFQ expires with one response still pending and another already selected
- **THEN** the pending contact cannot become eligible for disclosure, even before its payload is deleted
- **AND** the registry deletes that payload within one hour during healthy operation, while the completed introduction follows its own retention policy

#### Scenario: Expiry passes while the registry is stopped

- **WHEN** the registry starts after pending response or introduction contact access expired during downtime
- **THEN** it clears the overdue contact payloads before admitting RFQ traffic

### Requirement: One request supports independent introductions

The buyer SHALL be able to select multiple respondents to one open RFQ. Selecting a response SHALL leave the request open. Each respondent SHALL have access only to their own response and introduction on that request.

#### Scenario: A buyer selects two respondents

- **WHEN** the buyer selects one respondent to an open RFQ and a second participant subsequently responds
- **THEN** the buyer can select the second respondent on the same request
- **AND** after each pair consents, the buyer can read both introductions and each respondent can read only their own

### Requirement: Stored contact details are protected against a database-only disclosure

The registry SHALL encrypt submitted contact details before storing them for a pending response or a completed introduction. The decryption key SHALL be held outside the registry database. Logs and replay records SHALL omit plaintext contact details.

#### Scenario: A database copy contains pending and completed introductions

- **WHEN** an operator inspects a standalone database copy after one response was submitted and another was selected
- **THEN** the stored contacts are encrypted, and the copy contains neither their plaintext nor the key needed to recover them

### Requirement: Contact disclosure requires mutual consent

When submitting a response, the respondent SHALL explicitly consent to share their chosen contact with the buyer if selected. When selecting that response, the buyer SHALL explicitly consent to share their chosen contact with that respondent. The system SHALL then make both contacts available only to that pair without further respondent confirmation. Their introduction SHALL create no purchase or settlement obligation.

#### Scenario: A response is pending

- **WHEN** a respondent submits their chosen contact and consent and the buyer has yet to select them
- **THEN** the buyer can review the response and neither participant can retrieve the other’s contact

#### Scenario: The buyer completes the introduction

- **WHEN** the buyer selects that pending response and confirms the contact they wish to share
- **THEN** each participant can retrieve the other’s chosen contact even if the respondent has taken no further action

#### Scenario: An unrelated signed-in account requests contact

- **WHEN** an account outside the consenting pair requests either party's contact from the introduction
- **THEN** the system refuses disclosure

### Requirement: Completed introductions have a bounded contact retrieval window

The default retrieval window SHALL end 30 days after an introduction completes. Either participant SHALL be able to end retrieval early for both participants in that introduction. At or after the cutoff the registry SHALL refuse all further contact reads for that pair, including retries.

#### Scenario: Two introductions complete on different dates

- **WHEN** the default 30-day window ends for the first introduction and the second introduction is still within its window
- **THEN** the registry refuses further contact reads for the first and continues to authorize the second pair

#### Scenario: A participant ends access before expiry

- **WHEN** either participant ends retrieval and the other retries an earlier successful contact read
- **THEN** the registry returns no contact details and future reads by either participant remain closed

### Requirement: RFQ ownership belongs to an authenticated account

The registry SHALL derive the owner from the stable namespace and account subject asserted by a configured RFQ account authority in a fresh v2 signed request. It SHALL verify the signer, registry audience, resource, operation and complete input before admitting the request. A subject supplied by an untrusted client SHALL confer no access. Changing an account credential or rotating the authority signer within that namespace SHALL preserve ownership.

#### Scenario: A CLI credential replaces an older credential

- **WHEN** an account authority verifies the replacement for the account that owns an existing request
- **THEN** the same account can manage the request and see its inbox under its existing identity
- **AND** a revoked credential or matching subject text under another authority cannot exercise that ownership

#### Scenario: The account service authorizes only a read

- **WHEN** the registry receives a signed proof for discovery presented as consent to sharing a contact
- **THEN** it refuses the mismatched operation and discloses no contact details

### Requirement: Compute requests preserve quantity and time units

The registry SHALL keep the requested node count distinct from per-node GPU count. It SHALL preserve positive integral terms with their stated unit of day or calendar month, an inclusive start-date window, and a separate UTC response deadline. A response quantity, when supplied, SHALL be an integral number of nodes between one and the requested node count.

#### Scenario: A six-month request is read back

- **WHEN** the buyer requests 100 nodes with eight GPUs per node for six calendar months
- **THEN** an authenticated reader sees those three values with their original units and a provider can offer 40 nodes

### Requirement: Restore cannot reopen a deleted introduction

The registry SHALL enforce the active contact-access state before admitting reads after a restore, and SHALL redact restored contacts whose current eligibility cannot be established. Cleanup SHALL resume after interruption without restoring any deleted payload.

#### Scenario: A backup predates an early termination

- **WHEN** the registry restores such a backup and has no authoritative later termination history
- **THEN** it withholds and redacts contacts of uncertain eligibility before reopening reads

### Requirement: Consent uses verified registry and party references

The account entry point SHALL provide the verified registry identity and an opaque buyer reference on authorized RFQ detail reads. On authorized private response reads it SHALL provide the verified registry identity and the corresponding opaque respondent reference. Party references SHALL stay stable for an account within an RFQ across credential changes and SHALL be scoped to that RFQ. These projections SHALL omit raw account subjects and contact details. Interactive clients SHALL preview the verified registry and recipient reference before asking for approval. Interactive clients and programmatic callers SHALL echo the values they verified when submitting the operation. The registry SHALL check the reference against the current eligible party.

#### Scenario: A buyer browses two registries with the same RFQ identifier

- **WHEN** the buyer opens a response in the second registry and selects it
- **THEN** the preview and signed mutation identify the second registry and its verified respondent
- **AND** a write that substitutes the first registry or an unrelated party reference is refused

#### Scenario: An authenticated reader retrieves an RFQ before responding

- **WHEN** an eligible reader opens RFQ details to prepare a response
- **THEN** the reader receives the verified registry and the RFQ-specific buyer reference without receiving the buyer's contact or underlying account subject

### Requirement: Interactive clients and authorized delegates use the same RFQ API

The account entry point SHALL expose the same operations, inputs and outcomes to the browser, the terminal and programmatic callers, including contact-sharing actions. The terminal SHALL accept complete operation inputs and return machine-readable outcomes and errors without prompts when invoked noninteractively. A delegate with current sharing permission SHALL be able to initiate an RFQ contact share for the acting account. Each interactive client SHALL preview the exact contact and counterparty and ask for explicit approval before submission. The account authority SHALL verify permission to share contact for the acting account and the submitted affirmative consent before signing the action. The signed input SHALL bind the action, target registry, counterparty, current terms revision, relevant write version and chosen contact. The registry SHALL enforce the current ownership, counterparty, revision and eligibility checks. General read or posting authority on a programmatic credential SHALL NOT authorize contact sharing. Successful mutations SHALL return a contact-free outcome.

#### Scenario: A respondent approves in the terminal

- **WHEN** a respondent with contact-sharing permission approves the displayed contact, counterparty and current request terms in the terminal
- **THEN** the terminal submits through the common API and receives the same contact-free response result that a browser client would receive
- **AND** the buyer must still select the response before either party can retrieve the other’s contact

#### Scenario: An authorized delegate acts without interactive prompts

- **WHEN** an authorized delegate submits explicit consent, the chosen contact, verified registry and recipient, and expected terms and record versions
- **THEN** the service admits the same operation and returns the same contact-free result as for an interactive caller

#### Scenario: Permission or approval is missing

- **WHEN** a requester attempts a contact-sharing action without affirmative consent or with a credential lacking current contact-sharing permission
- **THEN** the service refuses the action and creates no pending response or introduction

#### Scenario: The confirmed request is stale

- **WHEN** the terms, expected response version or counterparty changes before the confirmed mutation is admitted
- **THEN** the service refuses the mutation and the client must obtain fresh approval for the current action

#### Scenario: The buyer retries after losing the acknowledgement

- **WHEN** the buyer repeats a completed selection with the same logical inputs and request ID using a currently authorized credential
- **THEN** the service returns the contact-free outcome and creates no second introduction
