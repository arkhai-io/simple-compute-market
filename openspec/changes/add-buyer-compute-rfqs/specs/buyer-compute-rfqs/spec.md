## ADDED Requirements

### Requirement: A buyer can publish compute demand independently of supply

The system SHALL allow a buyer to publish a compute request with a requested quantity and term and a separate deadline for responses. Ordinary supply discovery SHALL continue to return only supply listings.

#### Scenario: The requested term outlasts the response deadline

- **WHEN** a buyer requests 100 B300 nodes for six months and sets a response deadline two weeks from publication
- **THEN** the request preserves both time constraints and does not appear in searches for available machines

### Requirement: Buyers may state a budget in descriptive details

An RFQ MAY include an optional plain-text description and optional bounded flat metadata with scalar values. A buyer MAY state a target budget in either. The registry SHALL preserve these details on authenticated RFQ reads. Omission of a budget SHALL leave the request valid.

#### Scenario: A buyer states a target for private negotiation

- **WHEN** the buyer includes “Target USD 20 per node-hour, negotiable” in the description or as a metadata string
- **THEN** an authenticated reader receives that text in the field the buyer supplied, and the request creates no binding price

### Requirement: Open RFQ discovery requires an authenticated account

The registry SHALL require an authenticated account to list, search or retrieve open RFQs by ID. Any ordinary authenticated account SHALL be eligible to read open request requirements. Discovery SHALL omit private responses and contact details.

#### Scenario: Anonymous discovery in a registry with public supply

- **WHEN** an anonymous caller lists RFQs, searches for one, or requests a known open RFQ by ID, even while supply listings are public
- **THEN** the registry refuses each RFQ request without returning request requirements

#### Scenario: An ordinary account discovers demand

- **WHEN** an authenticated account with no seller role or listing searches for an open request and retrieves it by ID
- **THEN** the account can read the requested compute and term while private responses and contact details stay out of both results

### Requirement: An authenticated account may express interest

The system SHALL allow any authenticated account other than the request owner to respond to an open RFQ without a seller role, publisher registration or a supply listing. The system SHALL bind the response to the authenticated respondent and the request it answers.

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

### Requirement: An ended response retains no contact payload

When a pending response ends without an introduction, the registry SHALL delete its stored contact payload, including the encrypted value. The registry MAY retain the response outcome without contact details. Retrying a completed operation SHALL NOT restore the payload.

#### Scenario: The respondent withdraws

- **WHEN** a pending response is withdrawn and its original submission is retried
- **THEN** the registry deletes the stored contact for the withdrawn response and the retry cannot restore it

#### Scenario: An RFQ ends with pending and completed introductions

- **WHEN** an RFQ closes or expires with one response still pending and another already selected
- **THEN** the registry deletes the pending response’s contact and applies the completed introduction’s own retention policy to its contact details

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

### Requirement: A CLI contact-sharing action requires human confirmation

An authenticated CLI user SHALL be able to browse open RFQs in the terminal. The account authority SHALL require explicit confirmation in a browser session belonging to the staging account before submitting a response, reconfirmation or selection that shares contact. Confirmation SHALL bind the action, target registry, counterparty, current terms revision and chosen contact. A personal API key alone SHALL NOT authorize that submission.

#### Scenario: A respondent confirms from a browser

- **WHEN** a respondent stages a response in the CLI and approves the displayed contact and request in their own browser session while the draft is valid
- **THEN** the authority submits that response once and the buyer must still select it before either party can retrieve the other’s contact

#### Scenario: Approval is absent or no longer valid

- **WHEN** a staged action is abandoned, the link is only opened, another account attempts approval, or the action expires or becomes stale
- **THEN** the attempt creates no pending response or introduction and grants no contact access

#### Scenario: The buyer retries an approved selection

- **WHEN** the buyer confirms a staged selection and retries the completed approval after losing the acknowledgement
- **THEN** the authority can return the contact-free outcome of the first submission and creates no second introduction
