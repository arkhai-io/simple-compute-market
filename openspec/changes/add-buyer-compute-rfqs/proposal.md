## Why

A buyer seeking a block of compute for a particular term can search advertised supply, but cannot publish the requirement so other participants can respond. For example, a buyer might need 100 B300 nodes for six months and welcome introductions to more than one provider.

## What Changes

- Propose a demand collection in the compute registry. Buyers describe the shape, number of nodes, acceptable region, start window and requested term, and give the request its own response deadline.
- Let any signed-in account holder respond without a seller role, publisher registration or a listing. A delegate may respond for that account with current RFQ contact-sharing permission. Let the buyer select several respondents independently. Respondents consent to sharing their chosen contact with the buyer when responding. Respondents can withdraw their own pending response before selection. Buyers consent when selecting each response. Only then can that pair see each other’s contact details.
- Let buyers state proposed price, upfront deposit and terms for the remaining balance in the RFQ description or flat metadata. Readers with access to the open RFQ see the published terms.
- Allow a respondent to include an optional nonbinding quantity, including partial coverage, for the buyer to review privately.
- Require fresh consent from pending respondents when the buyer changes the requested compute. Apply the same rule to commercial edits in text or metadata. Only clearly cosmetic changes preserve pending consent.
- Allow one pending response per respondent per revision. The buyer can dismiss an individual response, ending its consent and deleting its stored contact.
- End pending eligibility immediately at explicit closure or the response deadline. Delete pending contacts at closure in the same transaction and clear time-expired ciphertext within one hour during healthy operation. Clear overdue data before serving RFQs after downtime. Completed introductions have a 30-day retrieval window by default, and either participant can end retrieval for the pair sooner.
- Encrypt submitted contacts before persistence, with the decryption key held separately from the registry database. The running service is trusted to enforce participant access.
- Allow anonymous open RFQ search and direct lookup by ID on registries where `REGISTRY_REQUIRE_READ_API_KEY` is off, the existing public supply posture. Require account authentication for mutations and private records. A pinned account authority signs the verified account subject, registry audience, operation and inputs. Ownership survives account credential replacement.
- Expose the same RFQ operations to browsers, interactive CLI callers and agents. Allow a delegate with current account permission to submit exact contact-sharing inputs and affirmative consent on the account's behalf.
- Give clients typed operations for discovery, posting, responding and retrieving their own introductions. The existing listing search continues to describe supply.
- End the marketplace flow at contact handoff. The parties negotiate price, availability and any eventual contract themselves.

## Capabilities

### New Capabilities

- `buyer-compute-rfqs` owns compute requests, responses, consent and access to introductions.

### Modified Capabilities

- `registry-discovery` distinguishes account-scoped RFQ mutation receipts and freshly authorized RFQ reads from listing replay.
- `marketplace-identity` defines delegated-account replay beside principal-scoped replay.

## Impact

The proposed owner is the registry service. Use an additive registry migration and a separate account-authorized route family. Enable RFQs only with an admitted account authority and contact-protection secrets. Qualify the shared API on a hosted non-production account service with an interactive user and an authorized programmatic delegate, using synthetic RFQs and contacts. The typed client and CLI exercise the same registry contract in repeatable repository tests. Each consuming application owns its presentation. Payment, settlement, allocated inventory and provisioning have no part in it.

## Permanent documentation impact

- [x] Repository architecture and existing registry specification
- [x] New subsystem specification and capability index

At closeout, record the RFQ contract in the new buyer-compute-rfqs capability and its rationale in the accompanying architecture document. Index it in `openspec/specs/README.md`. Record the registry replay exception and account boundary in the registry-discovery capability and its companion. Document the service boundary in `docs/development/ARCHITECTURE.md`, key provisioning and restore admission in `docs/development/DEPLOYMENT_AND_CONFIG.md`, and CLI confirmation in `docs/buyer-quickstart.md`.

### Knowledge to promote

- D1: promote private pairwise introductions to the buyer RFQ capability.
- D2: document the operations which give consent in the RFQ specification.
- D3: promote withdrawal and its race with selection to the RFQ lifecycle requirements.
- D4: promote revision binding and the cosmetic normalization rule to the RFQ specification and companion.
- D5: promote authoritative close and expiry to the RFQ specification.
- D6: promote the contact trust boundary, encryption, key rotation and restore admission to RFQ architecture and deployment documentation.
- D7: promote deadline cleanup and contact-free receipts to the RFQ specification, and the account-scoped replay exception to registry discovery and marketplace identity.
- D8: promote account admission, authority scope, stable ownership and separation from supply to the registry companion and repository architecture.
- D9: promote optional, nonbinding partial node counts to the RFQ wire contract.
- D10: promote free-form commercial terms and their visibility and validation to the RFQ specification.
- D11: promote uniqueness and individual dismissal to the RFQ specification.
- D12: promote contact retrieval cutoffs and early termination to the RFQ specification and deployment guide.
- D13: promote the shared account API, interactive and noninteractive inputs, verified party projections and delegated consent to the RFQ specification and the buyer guide.
- D14: no permanent destination — this review cadence applies only to delivery of this change.
- D15: promote the neutral registry and compute-family contract boundary to the RFQ architecture and repository architecture, and generated schema selection to deployment configuration.
