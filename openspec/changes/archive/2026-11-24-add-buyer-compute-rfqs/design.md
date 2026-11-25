## Context

Any signed-in account holder is eligible to respond. Authorized delegates may respond on the account's behalf. A response expresses interest in discussing a buyer's request. It conveys no right to capacity and binds neither party to a deal.

The registry already authenticates signed requests, enforces separately configured deployment access keys, and verifies ownership of supply listings through publisher bindings. A deployment access key admits traffic to the service. Listing ownership and account identity are distinct concerns. Current registry replay records retain completed response bodies. The existing contact-exchange mechanism discloses contact for an accepted listing-based negotiation and has its own configurable retention policy.

## Decisions

### D1 — Independent introductions

A buyer can select several respondents to one RFQ. Each introduction is private to the buyer and that respondent. Selecting a response leaves the RFQ open for other responses and selections until the buyer closes it or it expires. This allows the buyer to compare providers or discuss a request that several providers could jointly fill.

### D2 — Two explicit consents

When responding, the respondent chooses their contact details and explicitly agrees to share them with this buyer if selected. When selecting that response, the buyer chooses their own contact details and agrees to share them with that respondent. Until selection, neither sees the other’s contact. Selection completes the introduction with no further action from the respondent.

### D3 — Withdrawal before selection

A respondent can withdraw their own response while it is pending. Withdrawal ends consent for that response. If withdrawal and selection race, the registry applies only the first successful transition. A buyer working from an older inbox view cannot select a withdrawn response. Withdrawal affects only that response.

### D4 — Edits and reconfirmation

Consent applies to the terms the respondent saw. Changing the requested quantity, location, start window or rental duration supersedes all pending responses. Each respondent must explicitly confirm the updated terms before the buyer can select their response. Changes to commercial terms in descriptions or metadata also require fresh consent. Preserve consent only for edits the registry can establish are cosmetic. An ambiguous wording change requires reconfirmation. The registry must evaluate the terms at selection so a stale inbox or a retry cannot disclose contact using superseded consent.

### D5 — Closing and expiry

Closing a request or reaching its response deadline ends every pending response. The registry accepts selection only while the request is open and its deadline is still in the future. A selection completed first establishes the introduction. A later close or deadline preserves that introduction under its own retention policy. An old inbox view or retry cannot turn an expired response into an introduction.

### D6 — Registry custody

The running registry service and its operator are trusted to handle contact details. The service encrypts each chosen contact before persistence and keeps the decryption key outside the database. An operator who controls the running service can read contacts. Through the participant API, only the consenting pair can retrieve them after selection.

### D7 — Deletion of pending contact

Withdrawal, dismissal, explicit closure, supersession and early termination delete the affected contact payloads in the transaction that ends eligibility. A time-based deadline ends access immediately. It takes effect on every request, even when no cleanup has run yet. The registry deletes expired ciphertext from live storage within one hour during healthy operation and clears overdue data before admitting RFQ traffic after downtime. It can retain a contact-free record of the outcome. A retry must not restore deleted data. Cleanup preserves the independent retention policy of each completed introduction. Access checks tied to current time make expiry independent of schedule precision.

### D8 — Open RFQ discovery follows supply visibility

Any ordinary authenticated account can discover open RFQs. When `REGISTRY_REQUIRE_READ_API_KEY` is false, the registry advertises public supply discovery and also accepts unsigned open RFQ search and direct lookup by registry-scoped ID. The supply endpoint continues to verify its signed marketplace-principal proof. A service can use that proof to serve supply to a visitor without a user account. Anonymous results contain published requirements and commercial terms, the registry identity and the RFQ ID. They omit party references, private responses and contact details. The buyer sees the full response inbox, and each respondent sees only their own exchange. Private history and mutations require the appropriate verified account authority.

### D9 — Partial coverage

A response may state how much of the requested compute the respondent could supply, using the quantity unit of the RFQ. For a 100-node request, the buyer may see 40 nodes in one private response and an unspecified quantity in another. Omitting the field leaves the quantity open for discussion. Stating a quantity leaves the original request open and creates no reservation or obligation.

### D10 — Optional commercial details

A buyer can describe any proposed price, deposit or payment schedule in the optional description or flat metadata. For example, “Target USD 20 per node-hour, 30% upfront, remaining balance monthly” states a negotiating position. Visitors who can browse a public RFQ can see those terms. The registry preserves the buyer’s wording or scalar value without assigning billing or settlement semantics. Structured compute requirements remain authoritative for quantity and term.

### D11 — Response uniqueness and dismissal

Each respondent account can have one pending response per RFQ revision. Concurrent submissions and retries respect the same limit. The buyer can dismiss a pending response individually. Dismissal ends consent and deletes its contact under the ended-response rule. Other responses remain eligible.

### D12 — Bounded retrieval

The registry operator configures the contact retrieval window in positive whole seconds through the registry profile or its Helm value. It defaults to 30 days. The registry sets each introduction's cutoff at completion using the current setting. A configuration change applies only to new introductions. Either participant can end retrieval early for that pair. At the cutoff, all subsequent reads, including retries, refuse contact disclosure to both participants. Each can keep details already received. Ending one introduction’s retrieval leaves the others on their own schedules.

### D13 — One RFQ API for people and authorized delegates

The browser, interactive terminal and noninteractive callers use the same RFQ operations. An interactive client previews the exact contact, registry, counterparty and terms before asking for confirmation. A noninteractive client explicitly supplies those values, affirmative consent and the expected record version in its operation. An authorized delegate may initiate RFQ contact sharing for the acting account without a separate human approval for each mutation. The account entry point derives the account from its verified credential and checks current RFQ contact-sharing permission before signing. An ordinary account holder's verified interactive session is eligible to express consent to share that account's submitted RFQ contact. An agent acting for the account needs current delegated authority for the same operation. General account access and a caller-supplied consent flag confer no sharing permission by themselves. The hosted authorization layer owns issuance, revocation and enforcement of the applicable permission. The shared API accepts the service's verified verdict for RFQs only and applies it equally to browser, terminal and direct programmatic calls.

### D14 — Implementation cadence

Use two review rounds with one implementation session per round. The first covers account admission, registry migration, request creation and discovery, and isolation from supply. The second covers the public discovery correction, responses, consent, contact retention and recovery, interactive and noninteractive clients, and the buyer/two-respondent journey. It includes real hosted account qualification before closeout. Reviewing the identity and storage contracts first gives the consent work a stable foundation. A single combined round would defer that feedback until the contact lifecycle was already built.

### D15 — Compute vocabulary and descriptive metadata

The registry owns the neutral RFQ envelope, state and access policy. The compute family owns the typed compute request and search filters and generates the declarative validation schema from those models and its existing hardware vocabulary. The installed schema gives the neutral registry the same field rules as the typed clients. For a 100-node request, searchable GPU and quantity fields have typed meanings, and a field such as a negotiable budget carries the buyer's wording. Keep optional flat metadata consistent with seller listing metadata and reuse a shared scalar validator when available. Putting those hardware fields in core would give a neutral service compute-family knowledge. Load the generated schema into the existing registry image, using its declarative listing-schema pattern. A compute-scoped executable could also keep one registry authority, but it would require a separate app composition and Python dependency graph.

## Engineering design for review

### Account admission and key changes

Use a configured account authority that authenticates participants and signs RFQ operations for the registry. The participant’s durable owner is the pair (authority namespace, immutable account subject). The signing principal on this hop represents the authority. Configure the namespace, accepted signer pins and registry audience together. Use the verified registry authority name and exact public principal as the audience. The name alone can be shared by different deployments. Check the current principal before opening replay storage and key logical retries to the durable registry name. Users authenticate to their trusted account entry point. The registry receives an operation-specific proof and never asks users to send a general account credential to a discovered registry.

Have the authority use the existing v2 service-signed request and the registry’s pinned v2 response. The authority derives the subject and permitted action from the verified credential on each invocation. Sign the method, operation, resource, request ID, timestamp and canonical body. Every delegated account body includes the subject, namespace, exact target registry and all operation inputs, including the revision and consent details when applicable. The authority constructs these fields server-side and will sign only RFQ operations it admits. The registry compares the audience and pin with its configuration, checks freshness, and enforces record ownership and lifecycle before reading data or dispatching. A listing key, service identity outside the RFQ trust set, self-signed account claim or caller-supplied account ID grants no account RFQ authority. Disable RFQs until RFQ trust and secret configuration is complete. Supply discovery and its existing access keys retain their current policy.

A hosted account client and a CLI using the same account authority therefore own the same RFQs, even after replacing an account API key or marketplace signer. The external authority owns credential issuance, replacement and revocation. There is no participant signing-key enrollment at the registry. The authority signer has its own lifecycle: an operator installs a successor pin for the same namespace, verifies it, permits bounded overlap, and retires the previous pin. Namespaces remain immutable and disjoint. Losing an authority signer never transfers a participant record to another namespace. Market participant rotation rules still apply anywhere an individual market principal actually owns the record.

### RFQ operations and fields

The registry owns RFQs, responses and introductions in its existing service. A distinct RFQ route family keeps demand out of listing searches and publisher registration. Gate compute RFQs on a configured compute-capable registry. The neutral registry contract carries the kind, envelope and lifecycle data. The compute-scoped contract under `domains/compute` owns typed requirements, filters and response quantity. Generate a versioned RFQ JSON Schema and declarative filter and quantity mappings under `domains/compute/registry/`. The registry image includes this data artifact and compute registry configuration selects it. The neutral registry loads it at startup and checks writes and filters with its existing JSON Schema and declarative filter mechanisms. The mappings select only validated field paths and supported comparison operators. The registry applies generic lifecycle invariants such as deadline, start-window order and an offered quantity bounded by the request using the declared quantity paths. A registry without a configured compute RFQ schema refuses the kind. A malformed configured schema refuses RFQ admission at startup. Test that typed models and deployed validation accept and reject the same cases. The registry's Python lock remains market-neutral.

Use POST bodies under `/rfqs` so signed account operations carry the account, audience and input consistently. Apply the registry's public supply posture (`REGISTRY_REQUIRE_READ_API_KEY=false`) to unsigned open search and ID lookup. An anonymous exchange carries the operation's public input and a caller request ID for response correlation. Use the current open-request query, return the summary projection for anonymous detail, and sign the public response in the existing registry context. A client checks the response against its configured registry pin before relying on that identity. Select anonymous admission only when the call supplies no account authorization. Reject malformed or failed account credentials or proofs without falling back. A verified account continues to use RFQ account admission independently of any supply access key. Search takes a bounded page size (default 25, maximum 100), opaque cursor, and optional GPU model, minimum node count and region. Order by creation time and ID and bind the cursor to filters. Verified account detail also serves historical requirements to the owner or a respondent reading their own record. Responses and contacts have separate projections.

An authorized RFQ detail read returns the registry's verified authority and an opaque, stable buyer reference scoped to that RFQ. Authorized response detail and buyer inbox reads return the registry authority and the corresponding respondent reference scoped to that RFQ. Allocate each reference once per account and RFQ, and persist it across credential changes. The account entry point verifies the signed registry response against the configured authority, checks the expected registry audience and passes that provenance to the client. Clients use the registry identity and an optional trusted registry label with the party reference to identify the intended recipient. They omit global account identifiers and contact fields from these projections. Search results need only carry the registry and RFQ routing reference used to get the detail. Contact-sharing writes echo the verified registry and party reference. Resolve the reference in the live RFQ transaction and compare it with the party eligible for that operation.

| Operation | Caller and effect |
|---|---|
| `/create`, `/{id}/edit`, `/{id}/close` | The buyer creates, replaces or closes their request. Mutations carry expected record version after creation. |
| `/search`, `/{id}/read` | Admitted accounts browse open requirements. Anonymous callers use the same open discovery policy as supply. Search and detail exclude responses and contacts. |
| `/{id}/respond`, `/{id}/responses/{rid}/reconfirm` | Another account explicitly consents on the current terms revision and submits its chosen contact. Reconfirmation submits fresh contact for the revised terms. |
| `/{id}/responses/list`, `/{id}/responses/{rid}/read` | The buyer can see all response summaries. A respondent can read only their own. |
| `/{id}/responses/{rid}/withdraw`, `/dismiss`, `/select` (same response prefix) | The respondent withdraws or the buyer dismisses or selects. Selection includes the buyer’s chosen contact, explicit consent, terms revision and expected response version. It returns an introduction reference. |
| `/introductions/{iid}/read`, `/introductions/{iid}/end` | Each participant can retrieve the other party’s submitted contact or end retrieval for both. Read checks the current state on every call. |

Expose account operations as JSON POST routes under `/rfqs` at the trusted account entry point for the browser, terminal and other programmatic clients. The entry point accepts the configured session or account credential, derives the account from it and forwards the operation under the existing v2 service proof. Session-authenticated writes use the entry point's normal CSRF protection. A contact-sharing mutation includes a stable request ID, the target registry, the operation and record references, the expected terms revision and relevant write version, the confirmed counterparty reference, the submitted contact and an affirmative consent field. The authority requires contact-sharing permission before signing and the registry verifies the counterparty against the current records. Success returns the same contact-free result to each client, including the response or introduction reference. Missing consent is an invalid action. Missing or revoked permission is refused. An unknown or unauthorized private record gets an indistinguishable refusal. Stale versions or changed reuse produce a conflict. An older account entry point or registry without RFQ support yields an unsupported-feature result. The terminal can prompt and display a preview, or accept complete explicit JSON input for a noninteractive call. The caller supplies the reviewed registry, counterparty, terms revision and record version on the noninteractive path. The client must not refresh these values automatically when they become stale. Both paths expose machine-readable outcomes and preserve the request ID when retrying a lost acknowledgement.

Example requirements, inside the signed body:

```json
{
  "shape": {"gpu_model": "B300", "gpu_count": 8},
  "node_count": 100,
  "regions": ["example-region"],
  "start_earliest": "2027-01-01",
  "start_latest": "2027-01-31",
  "term": {"value": 6, "unit": "month"},
  "respond_by": "2026-12-15T18:00:00Z",
  "metadata": {"budget": "USD 20 per node-hour, negotiable"}
}
```

The shape describes one node. Node count and GPU count are positive integers when supplied; node count is required. Validate GPU and other supported shape dimensions against the compute vocabulary. Require at least one region and a non-inverted inclusive ISO calendar-date start window. Express a positive integral term in days or calendar months; six months round-trips as six months and need not be converted to a fixed number of seconds. Parties settle the actual start and end privately. The response deadline is an independent, future UTC instant; creation, edits and all transitions use the registry clock. An optional offered node count is a positive integer in the same unit, at most the requested number for this response. An absent count remains unknown. Description is optional plain text up to 4,000 characters. Optional flat metadata has at most 50 entries, keys of 1–40 ASCII letters, digits, underscores, dots or hyphens, and values of at most 500 characters or a finite number or boolean. Use compatible shared validators when available. Contact is a separate bounded, nonempty string map (up to 16 entries, keys up to 64 characters, nonblank values up to 512); it is never copied into browseable data.

Track a record version for concurrent edits and a terms revision for consent. Compare validated, canonical terms server-side: disregard object-key order, equivalent UTC representations, region-set order and leading/trailing whitespace in descriptive prose. Preserve meaning-bearing text, numbers, punctuation, case and metadata types. Unclassified spelling changes require fresh consent; implementers may add demonstrably equivalent spellings to a tested normalization rule. A change to any remaining substantive field, including budget metadata, supersedes pending responses. Extending a deadline cannot revive an expired RFQ. Distinguish invalid input, absent authentication, unauthorized or unknown private records, stale versions and unavailable contact without echoing sensitive data.

### Persistence, privacy and retry

Use additive tables in the registry migration chain for requests and revisions, responses, introductions, contact payloads and RFQ request receipts. Enforce one pending response per account and revision, one introduction per selected response and one receipt per namespace, subject and request ID in the database. Status, revision, ownership and deadline checks and transitions share a transaction. Use compare-and-set predicates and uniqueness on both SQLite and PostgreSQL. An edit that supersedes pending consent also deletes that revision’s pending contact. Cosmetic edits keep the same terms revision. If selection wins the race, the resulting introduction has an independent cutoff.

Use application-layer authenticated encryption for the bounded contact payload (AES-256-GCM, fresh random nonce for each write). Persist version, key ID, nonce and ciphertext/tag. Bind ciphertext to registry namespace, record ID, party and payload purpose as authenticated associated data; when a pending payload changes purpose, re-encrypt it in the same transaction. Load a dedicated versioned keyring from a mounted secret file, with one current writer and retained readers. Missing required keys fail closed. Re-encrypt retained rows and verify coverage before retiring an old key. Run migration and restore rehearsals using synthetic contacts. A database backup contains ciphertext; deletion from the live service doesn't promise erasure from backups. A restore must reconcile expired records and intervening early terminations before read admission opens; if the latter cannot be reconstructed, redact restored contact payloads before opening.

Withdrawal, dismissal, close, supersession, early termination and selection commit their contact changes with the state transition. Compute deadlines and retrieval cutoffs on reads and writes even if housekeeping is delayed. A restartable, idempotent sweep drains expired pending and completed payloads oldest first in bounded batches. During healthy service it removes ciphertext within one hour of expiry. Track the age of overdue payloads and report sweep failures. Drain overdue payloads before admitting RFQ requests at startup and after undoing an outage or restore reconciliation. End-access deletes both payloads for that pair. A contact read linearizes at its authorized snapshot; once the cutoff passes or early termination commits, a new read, including a retry, cannot disclose. Keep contact out of exception details, request logs, public projections, cached bodies and notifications. Send contact responses with `Cache-Control: no-store`.

Durably bind the verified account request ID before dispatch, even when the operation later fails. Anonymous discovery uses fresh reads and creates no account replay binding. For mutations, save the contact-free outcome (identifiers, state and version) with the mutation in one transaction. Bind the receipt to a keyed digest of the canonical operation inputs using a dedicated secret outside the database; plain hashes of candidate emails allow offline guessing. The stable receipt identity and input digest exclude changing transport proofs and signer key IDs so a legitimate retry survives credential rotation. Store the digest key version so a retry still compares against the original key after rotation. Use the RFQ receipt path directly after signature verification; the listing middleware also stores a body hash and must not run on RFQ operations. Verify current admission and correct caller before serving any receipt. Conflict on changed content under the same operation ID. For reads, bind the request ID to the input fingerprint but reauthorize and render the current result each time; never save a private response or contact response body for replay. Existing listing replay remains byte-for-byte compatible.

### Qualification and review

The SCM deliverable includes the authority-side typed invocation builder and a typed client for the shared account entry point. A synthetic account authority exercises the same contract with the shipped signing and verification code. Qualify the terminal journey through contact exchange on the same operations a browser client calls. Prove permission separation, omitted consent, current counterparty and revision checks, authority pins and audience, independent account namespaces, credential replacement and revocation, and retries across signer changes. Exercise cosmetic and ambiguous edits, concurrent selection and withdrawal, the exact access cutoff even when ciphertext is still present, timed cleanup, and restoration before reopening service. In addition to the synthetic adapter checks, require hosted non-production qualification before the PR. A real hosted session and an authorized programmatic credential must traverse the same account routes with synthetic RFQs and contacts. Demonstrate interactive and noninteractive CLI behavior, successful delegated sharing, and refusal for missing or revoked sharing permission. The RFQ authority applies to the submitted RFQ contact and creates no authority over checkout or settlement.

## Design promotion

| Decision | Permanent location | Knowledge |
| --- | --- | --- |
| D1–D5 and D9–D11 | openspec/specs/buyer-compute-rfqs/spec.md | The request and introduction lifecycle, public commercial details, partial quantity, and consent. |
| D6–D7 and D12 | openspec/specs/buyer-compute-rfqs/spec.md and openspec/specs/buyer-compute-rfqs/architecture.md | The encrypted contact trust model, configurable retrieval window, expiry, and recovery. |
| D6–D7 and D12 | openspec/specs/registry-discovery/configuration.md#rfq-registry-settings and docs/operator-handbook.md#operate-and-recover-rfqs | Key management, new-introduction duration, restore and monitoring. |
| D7–D8 | openspec/specs/registry-discovery/spec.md#durable-replay-reservation and openspec/specs/registry-discovery/architecture.md#body-bound-exchanges-and-durable-replay | Current authority and retry rules. |
| D8 and D13 | openspec/specs/marketplace-identity/spec.md#body-bound-authenticated-request-and-response-version and openspec/specs/marketplace-identity/architecture.md#canonical-version-2-proofs | Account proof, scope, exact target and rotation. |
| D8 and D15 | docs/development/ARCHITECTURE.md#buyer-rfq-authority and docs/development/DEPLOYMENT_AND_CONFIG.md#registry-rfq-configuration-and-recovery | Authority, schema, admission and deployment. |
| D13 | openspec/specs/buyer-compute-rfqs/spec.md and docs/buyer-quickstart.md#post-a-compute-request-and-exchange-contact-details | Shared operations and terminal use. |
| D14 | This change's design and task record | Implementation cadence and qualification history. |
| D15 | openspec/specs/buyer-compute-rfqs/spec.md and openspec/specs/buyer-compute-rfqs/architecture.md | Compute models and the registry's declarative validation boundary. |
