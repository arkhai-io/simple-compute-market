# contact-exchange-settlement Specification

## Purpose

Define settlement by introduction: `contact-exchange.v1` puts buyer and seller
durably in authenticated contact, with no payment, escrow, or provisioning.
Acceptance, explicit contact capture, and party reads are separate operations.

## Requirements

### Requirement: An introduction completes a deal

Under `contact-exchange.v1`, the accepted plan MUST carry one non-financial
obligation. Explicit introduction start MUST persist the reveal before driving
materialization, check, and collection through the shared settlement runtime.
Completion MUST require neither payment nor provisioning and MUST NOT depend on
whether either party has read the reveal. Acceptance alone MUST NOT complete it.

#### Scenario: A contact-exchange deal settles

- **WHEN** the accepted buyer explicitly starts the introduction with its contact
- **THEN** both contacts and accepted context are persisted and the obligation
  completes without escrow, funding authorization, a chain client, or provisioning

### Requirement: Contact is revealed only after acceptance, only to the counterparty

Contact payloads MUST NOT appear in listings, options, or discovery responses.
Only the accepted buyer SHALL authorize introduction start. After start persists
the reveal, either authenticated party MUST be able to read the counterparty's
contact payload and agreed context through the introductions surface. Reads MUST
be idempotent and MUST NOT capture contacts or advance settlement. No other
principal may read either payload.

#### Scenario: Counterparty reads the introduction

- **WHEN** an authenticated party to a started contact-exchange deal requests its
  introduction
- **THEN** it receives the persisted counterparty payload and agreed context,
  and a repeat request returns the same result

#### Scenario: A non-party requests the introduction

- **WHEN** a principal that is not a party requests the reveal
- **THEN** the request is refused and no contact data is returned

### Requirement: The agreed context is durable

Start MUST capture the buyer-supplied contact, configured seller contact, and
introduction package from the immutable accepted plan. Reads MUST serve these
persisted artifacts, not reconstruct them from current configuration or mutable
negotiation state. Identical repeated starts MUST reuse the record; changed
contact payloads MUST be refused rather than overwrite it. If completion fails
after capture, the reveal MUST remain durable and the same start may retry
completion through the existing obligation.

#### Scenario: Reveal after restart

- **WHEN** the storefront restarts after contact capture, including after seller
  contact configuration changes
- **THEN** a party read serves the identical persisted introduction package

#### Scenario: Completion fails after capture

- **WHEN** lifecycle completion fails after the introduction is persisted
- **THEN** start returns temporary unavailability, the reveal remains readable,
  and an identical start can converge without replacing either contact

### Requirement: Contact payloads are bounded, deliberate PII persistence

Contact payloads MUST be size-bounded at configuration and introduction start,
MUST be persisted only for deals whose introduction has started, and MUST be
deletable without disturbing the settled obligation. A deal that never starts
MUST persist zero contact payloads. The deletion primitive does not imply an
automated retention scheduler or deletion of recipient-owned delivered copies.

#### Scenario: Unstarted deals hold no contact data

- **WHEN** a contact-exchange deal is accepted but the buyer does not start it
- **THEN** no contact payload is persisted for that deal

#### Scenario: Introduction teardown removes the payloads

- **WHEN** an operator invokes introduction deletion at the end of its retention
  window
- **THEN** both payloads are deleted while the settled obligation record remains

### Requirement: Bare-metal contact-only environment composition

The bare-metal environment factory SHALL derive introduction-only operation from
an enabled mechanism set containing only `contact-exchange.v1`. It SHALL construct
no site, capacity, provisioning, chain, or hosted financial runtime. Health SHALL
mark physical checks `not_applicable` and incomplete contact configuration
unavailable. Physical composition SHALL continue to require trusted sites.
Recipient-side delivery remains optional; the synthetic file-publication path
SHALL require no delivery callback, without disabling delivery in other contact
compositions.

#### Scenario: Wallet-free contact-only startup

- **WHEN** a seller supplies an Ed25519 identity, admin identities, public URL,
  database path, and ready contact-only settlement configuration with no delivery
- **THEN** the ordinary server starts with no physical, financial, or delivery
  runtime and no fabricated trusted site

#### Scenario: Contact readiness is incomplete

- **WHEN** the contact-only configuration has no seller contact payload or profile
- **THEN** health is degraded rather than claiming introduction readiness

### Requirement: Unbacked bare-metal contact admission

An unbacked bare-metal listing SHALL contain only validated rateless
`contact-exchange.v1` options with asset `introduction`, no `bare_metal` physical
option facts, no accepted escrows, and exactly `access_methods: [none]`.
Negotiation in introduction-only composition or against an unbacked listing
SHALL refuse financial mechanisms, physical option facts, SSH keys, access
references, or an access method other than `none`. Descriptive machine/host
labels SHALL NOT confer site or provisioning authority.

Shared provenance belongs to [market composition](../market-composition/spec.md#requirement-unbacked-storefront-provenance);
file publication belongs to [storefront publication](../storefront-publication/spec.md#requirement-synthetic-contact-publication-validates-the-whole-file).

#### Scenario: An unbacked offer is accepted

- **WHEN** the buyer selects the exact advertised contact option with non-access
  `bare_metal.v1` terms
- **THEN** acceptance records no resource reservation or contact payload

#### Scenario: A financial or physical offer is unbacked

- **WHEN** an operator submits a financial option, physical access, or a pool or
  Physical Resource without a site
- **THEN** admission fails before writing the listing

### Requirement: Accepted introductions are resolvable before consent

New bare-metal contact acceptances SHALL commit their immutable accepted plan
and pending obligation bookkeeping atomically under the
[shared persistence contract](../market-composition/spec.md#requirement-accepted-plan-bookkeeping-shares-the-commit-transaction).
Registration SHALL create no contact record, mechanism invocation, settlement
operation, fulfillment binding, reservation, or completion. Re-registration
SHALL preserve existing lifecycle state.

#### Scenario: Authorized read before start and after restart

- **WHEN** the accepted buyer or seller signs a read for a registered obligation
  before explicit contact sharing, including after restart
- **THEN** the storefront returns request-bound signed HTTP 409 with detail
  `introduction has not been started`
- **AND** no contact payload or settlement operation is persisted by acceptance
  or the pending read

#### Scenario: A pending response is altered

- **WHEN** the response proof, body, status, principal, method, operation,
  resource, or request identity is altered
- **THEN** authenticated response verification refuses it
- **AND** unknown, nonparty, or unauthenticated requests do not receive authorized
  pending semantics; unsigned refusals retain their response bodies

#### Scenario: An older accepted plan lacks bookkeeping

- **WHEN** a read supplies only the opaque reference of an older unregistered
  acceptance
- **THEN** it remains unresolved with HTTP 404, without a scan or backfill
- **AND** authorized explicit start with the known negotiation ID can still
  capture contacts and register the obligation through the ordinary lifecycle

### Requirement: Literal configured contacts stay out of public artifacts

The contact kit SHALL recursively check decoded public string keys and values
for nonempty configured contact values at profile validation, option construction,
and accepted-obligation construction. Synthetic file publication SHALL use the
same check before local listing intent or registry calls. The check SHALL be
case-sensitive literal substring matching, not general data-loss prevention.

#### Scenario: A contact value requires JSON escaping

- **WHEN** a configured value appears literally in a decoded public string,
  including nested terms/context, arrays, Unicode, quotes, slashes, backslashes,
  or newlines
- **THEN** the owning boundary refuses the artifact
- **AND** a contaminated last offer blocks the whole file before listing/binding
  writes or registry calls

Synthetic publication diagnostics can include the supplied listing ID verbatim.
If that ID contains a configured contact value, the diagnostic echoes it even
though publication is refused. Artifact validation is not a universal diagnostic
redaction boundary.

#### Scenario: Private data is transformed or unconfigured

- **WHEN** public input contains a transformed value or other unconfigured
  private data
- **THEN** the literal guard makes no detection guarantee; it does not normalize
  case, Unicode, URLs, or arbitrary encodings

### Requirement: Whole contact text is a strict profile of the private map

A text client SHALL submit exactly `{"text": <whole blurb>}` as its private contact payload. The blurb SHALL preserve 1–512 Unicode scalar values including whitespace and escaping, contain at least one non-whitespace scalar, and reject oversize or lone-surrogate input without truncation. Older opaque maps SHALL retain their meanings. Review/finalization and signed identity envelopes SHALL remain version 2.

#### Scenario: A reviewed Unicode blurb is changed

- **WHEN** a buyer changes any scalar or its own route after review
- **THEN** finalization refuses the prior binding without capturing contacts

### Requirement: Explicit context eligibility freezes authoritative declaration facts

Only new options with `context_contract: "accepted-listing.v1"` SHALL require typed accepted listing context. The storefront SHALL capture that context from immutable publication intent and listing binding at acceptance, validate the exact selected option, and bind its canonical digest into the obligation. Protected reads SHALL validate the persisted package against the accepted obligation, never reconstruct from a registry or current seller configuration.

#### Scenario: Provenance is absent or inconsistent

- **WHEN** an eligible option lacks matching immutable declaration/option provenance
- **THEN** acceptance fails before committing a plan or capturing contact data

#### Scenario: The authoritative listing projection cannot be decoded or validated

- **WHEN** an eligible option's stored listing projection contains malformed JSON or invalid domain structure
- **THEN** acceptance raises `NegotiationRequestError` with exactly `invalid_contact_provenance`, without input values or negotiation/obligation persistence

#### Scenario: The projection database is unavailable

- **WHEN** projection loading fails with a database operational error
- **THEN** the database failure remains distinct from invalid provenance and no negotiation or obligation is persisted

#### Scenario: Historical acceptance is read

- **WHEN** an older option or accepted plan has no context eligibility
- **THEN** its terms, IDs, digests, legacy read behavior and no-outbound semantics remain unchanged

### Requirement: Declaration identifiers are not physical authority

A bare-metal contact declaration SHALL use a declaration identifier with no machine or physical-host identifier and no site, pool or Physical Resource authority. It SHALL retain `vms.compute` discovery, `bare_metal.v1` negotiation and non-access terms. Site-backed listings SHALL retain required machine and physical-host identifiers.

#### Scenario: A declaration claims a physical backing

- **WHEN** a declaration supplies a machine, physical-host, site, pool or Physical Resource identity
- **THEN** admission refuses it rather than treating a placeholder as authority

The source carriers SHALL conform to the field, canonicalization and compatibility tables below; their fixtures are packaged in the contact-exchange wheel.

### Requirement: Reviewed text and context survive finalization unchanged

For an explicitly delivery-enabled agreement, finalization SHALL atomically store
one immutable introduction and exactly two recipient intents awaiting successful
settlement completion. The record SHALL retain the exact reviewed buyer text,
seller contact snapshot and accepted package. A committed retry SHALL observe
that capture without replacing it or racing the completion owner. Recovery SHALL
release intents only after journaled materialization, condition and collection
success, never on busy, pending or manual-required results.

#### Scenario: Reviewed inputs change before capture

- **WHEN** buyer text or own route, seller text or own route, parties or the
  accepted package changes after review
- **THEN** existing review/provenance fences refuse finalization without an
  introduction or recipient intents
- **AND** missing required profile or delivery configuration remains unavailable,
  not implicit consent to another configuration

#### Scenario: Current public settings change without changing accepted inputs

- **WHEN** current public profile terms/channel or SMTP credentials rotate but the
  accepted package, contact snapshots and recipient routes remain unchanged
- **THEN** finalization retains the accepted package rather than substituting
  current public settings or requiring an expanded review fingerprint

#### Scenario: A finalize response is lost

- **WHEN** the server commits finalization but the caller loses its HTTP response
- **THEN** authenticated owner status and an exact retry after restart recover the
  same committed introduction and exactly two intents, without a replacement send

#### Scenario: Cancellation races a delayed request

- **WHEN** cancellation commits before a delayed review or finalization transaction
- **THEN** the delayed request cannot create an introduction or intents
- **AND** cancellation after committed finalization reports committed, not cancelled

#### Scenario: Accepted and captured facts outlive mutable sources

- **WHEN** a listing is withdrawn after acceptance or settings change after capture
- **THEN** both recipient projections and subsequent rendering use the frozen
  accepted package and contact record, not a current registry or configuration lookup
- **AND** historical no-outbound records acquire neither jobs nor fabricated provenance

## Evidence

- Whole-text review/store/render parity, independent retained acceptance checks,
  recursive privacy canaries, lost finalization response, deterministic cancellation
  fences and historical no-job restart:
  `domains/bare_metal/storefront/tests/test_http_contact_source_exchange.py`.
- Journaled completion, contention and recovery before send:
  `domains/bare_metal/storefront/tests/test_http_contact_delivery.py`.

- Environment composition, health, admission, signed pending reads, explicit
  capture, party refusal, restart, rollback, and old unregistered references:
  `domains/bare_metal/storefront/tests/test_contact_only_runtime.py`.
- Shared start/read and persistence semantics:
  `kit/contact-exchange/src/market_contact_exchange/introduction_routes.py` and
  `kit/contact-exchange/src/market_contact_exchange/migrations.py`.
- Decoded-string guard across profiles, options, and accepted terms/context:
  `kit/contact-exchange/tests/unit/test_contact_value_protection.py`.
- Whole-file escaped-value refusal before local intent or registry calls:
  `domains/bare_metal/storefront/tests/test_contact_publication.py::test_full_file_refuses_escaped_contact_before_intent_or_publication`.
- Optional recipient delivery composition:
  `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/delivery.py` and
  `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py`.

## Primitive rules

All new objects forbid unknown keys, reject coercion, and require the listed fields unless explicitly optional. Integer versions reject booleans, floats and numeric strings. Positive machine/term integers are 1–9007199254740991 inclusive, the interoperable JSON integer range. Digests are exactly 64 lowercase hexadecimal characters. Declaration/listing identifiers match `[A-Za-z0-9_-]{1,128}`; they are opaque seller declarations, not physical registrations.

String bounds count Unicode scalar values after JSON decoding; lone surrogates fail. No trimming, normalization, case folding, chunking, or truncation. Nonblank means at least one scalar outside this frozen set: U+0009–000D, U+001C–0020, U+0085, U+00A0, U+1680, U+2000–200A, U+2028–2029, U+202F, U+205F, U+3000. U+200B is not blank. Channel additionally must equal its whitespace-trimmed value. These are existing contact semantics, not a claim about grapheme counts or rendering controls.

## Private text and review

| Carrier/field | Type and bounds | Owner and source | Visibility |
|---|---|---|---|
| `ContactText.text` | Nonblank scalar string, 1–512 | Human author of that party's blurb | Private |
| Serialized `contact_payload` | Exactly `{"text": <whole blurb>}` for text clients | `ContactText.model_dump(mode="json")`; no wrapper or additional field | Private signed review/finalize and persisted exchange |
| Historical `contact_payload` | Nonempty map; 1–16 entries; scalar keys 1–64; nonblank scalar values 1–512 | Existing party-authored contact map | Private; no automatic conversion to text |
| `schema_version` | Integer `2` | Existing review/finalize contract | Authenticated wire |
| `negotiation_id` | `[A-Za-z0-9_-]{1,128}` | Accepted storefront negotiation | Authenticated wire |
| `obligation_ref` | Digest | Existing `derive_obligation_ref` of exact accepted obligation | Authenticated wire |
| `finalization_id` | Canonical lowercase UUIDv4 | Buyer intent owner | Authenticated wire |
| `delivery_route` | Exact `{kind:"email", address:string}` | Each party's own existing route authority | Private; never inferred from contact text |
| `review_token`, `consent` | Existing canonical 43-character token; literal `exchange-contacts-and-deliver.v1` | Server review; explicit buyer authorization | Private finalize only |

Mailbox syntax remains ASCII dot-atom local part 1–64, dot-separated DNS labels 1–63, total at most 254; no display names, lists, whitespace, literals, trailing dot, SMTPUTF8 or implicit IDNA. Case is preserved. No new route or consent alternative is introduced.

`parse_contact_text` returns `ContactText` or `ValueError("invalid_contact_text")` without raw validation values. Pydantic model diagnostics are internal: never expose `.errors()`/`.json()` or field locations as public diagnostics. Existing HTTP carrier rejection remains a safe 422 boundary. No contact text belongs in public `terms` or machine context.

## Public eligibility and exact option

Optional `ContactProfile.context_contract` is exactly `"accepted-listing.v1"`. Absent is omitted, explicit null is invalid, and the exact existing delivery policy is required. It is explicit eligibility for newly captured context, not global enrollment.

`ContextContactOption` has exactly these keys:

| Field | Type | Owner/source |
|---|---|---|
| `option_id` | Digest | Existing `derive_settlement_option_id` over the whole option content below |
| `mechanism` | `"contact-exchange.v1"` | Contact kit |
| `asset` | `"introduction"` | Contact kit |
| `rates` | Empty array | Contact kit; no price |
| `params.profile` | `[a-z0-9][a-z0-9_.-]*`, 1–128 | Selected configured profile key |
| `params.channel` | Trimmed nonblank scalar string, 1–128 | Configured public profile; descriptive, not route selection |
| `params.terms` | Nonblank scalar string, 1–4000 | Configured public commercial terms, never machine JSON |
| `params.claimant_principal` | Existing canonical `Identity` object | Listing seller |
| `params.delivery_policy` | Exact existing `contact-delivery.v1` object | Explicit configured profile |
| `params.context_contract` | `"accepted-listing.v1"` | Explicit configured profile |

No other option or params keys are admitted for this eligibility. The kit's accepted-obligation builder requires a domain-supplied context; an unsupported domain fails closed rather than inventing one.

The mechanism-owned `delivery_policy` object has exactly five required literal strings: `kind:"contact-delivery.v1"`, `mode:"two-sided-contact"`, `channel:"email"`, `trigger:"explicit-finalization"`, `recipient_authority:"each-party-own-route"`. The policy is public; SMTP and each own route remain private and are not option fields. `claimant_principal` uses the identity kit's exact `{scheme, identifier}` carrier (canonical Ed25519 or EIP-191), not an address alias; scheme normalization and signature envelopes remain identity-kit owned.

## Declaration, listing and immutable intent

`ContactDeclaration` is public seller-authored data, not site-certified inventory:

| Field | Type | Owner/source |
|---|---|---|
| `schema_version` | Integer `1` | Bare-metal source contract |
| `listing_id` | Identifier | Seller's stable market listing identity |
| `declaration_id` | Identifier | Seller's declaration identity; no physical authority |
| `name` | Nonblank scalar string, 1–160 | Seller's public machine label |
| `machine_details.gpu_model` | Nonblank scalar string, 1–128 | Seller declaration; registry vocabulary is separately validated at publication |
| `machine_details.gpu_count` | Positive integer | Seller declaration |
| `machine_details.vcpu_count` | Positive integer | Seller declaration |
| `machine_details.ram_gb` | Positive integer | Seller declaration; existing GB vocabulary |
| `machine_details.disk_gb` | Positive integer | Seller declaration; existing GB vocabulary |
| `machine_details.region` | Nonblank scalar string, 1–128 | Seller declaration; discovery label, not a site endpoint |

The bare-metal local listing projection is exactly `kind:"bare_metal.v1"`, `virtualization_type:"bare_metal"`, `declaration_id`, `access_methods:["none"]`, `site:{region:<declared region>}`, and `capabilities:{gpu_model,gpu_count,vcpu_count,ram_gb,disk_gb}`. It omits `machine_id`, `physical_host_id`, and duration bounds. `site.region` is a descriptive label; the authoritative binding's `site_id` is null. New declaration listings forbid extra input fields. Historical listings retain their old full serialization and require both machine/physical-host IDs; a declaration cannot be site-backed.

Python declaration validation checks every supported `Mapping`, including `UserDict`, before field discard or coercion. Nested site/capability mappings obey the same exact shape. Declaration identifiers must already be strings; bytes and other scalar types are rejected. Historical listing coercion and extra-field handling remain unchanged.

The inventory publisher must project the declaration's name and machine fields into the existing flat `vms.compute` discovery fields, validate against the signed active registry schema, and preserve the typed local projection. No registry schema or discovery identity is changed here. Local admission and acceptance capture are distinct from the operator file/publisher workflow.

`ContactPublicationIntent` has exactly `{schema_version:3, declaration:ContactDeclaration, settlement_options:ContextContactOption[]}`. The option list has 1–32 unique option IDs. Schema 3 is a new **local immutable intent**, not a claim that the operator offer-file parser accepts a version-3 file. Each option claimant must equal the listing seller. The intent's declaration/listing/options must exactly match the admitted local listing and option list. Private data is forbidden in these public inputs; the mechanism's configured-literal guard also checks the captured context before accepting an obligation. This guard is not general DLP; inventory publication retains its whole-file privacy obligation.

Its source envelope is exactly `{kind:"bare_metal.introduction-declaration.v1", schema_version:1, site_id:null, pool_id:null, physical_resource_id:null, declaration_id, publication_intent}`. Shared binding fields remain `listing_id`, null authority fields, `offering_mode`, `domain_identity`, `contract_major`, `contract_minor`, `derivation_key`, `source_envelope_json`, `last_reconciled_at`. Core owns binding identity/immutability. No physical placeholder is persisted.

## General declaration file boundary

`ContactDeclarationOffers` and `parse_contact_declaration_offers` live in `domains/bare_metal/src/arkhai_bare_metal/contact_contract.py`. The parser accepts bytes, not a filesystem path, and performs no I/O.

| Field/bound | Exact contract | Owner/source |
|---|---|---|
| `schema_version` | Integer `3` | Domain input version, independent of intent version and signed envelope |
| `offers` | Array of 1–256 `ContactDeclarationOffer` objects | Operator's whole intended batch |
| `offers[].declaration` | Exact `ContactDeclaration` above | Public operator assertion, including third-party machine facts; no ownership/availability certification |
| `offers[].profile` | `[a-z0-9][a-z0-9_.-]*`, 1–128 | Operator selection of configured public contact profile; no inline policy override |
| General listing namespace | `declared-contact-` followed by at least one identifier character, total at most 128 | Separates new file IDs from old synthetic fixtures; existing-ID conflicts still require database preflight |
| Uniqueness | Both listing IDs and declaration IDs unique throughout the array | Domain file validator |
| Raw file | At most 1048576 bytes inclusive, UTF-8 JSON without BOM; whitespace counts | Domain parser; publisher must read at most limit + 1 bytes |
| JSON errors | Duplicate object keys at every depth, nonfinite numbers, malformed JSON, invalid UTF-8, excessive nesting, unknown keys/version and scalar coercion refused | `ValueError("invalid_contact_declaration_file")` with no supplied values |

One MiB and 256 declarations are parser/preflight safety bounds, not physical capacity or market policy. Six valid entries and both count/byte endpoints are conformance cases. The typed intent is produced later from each declaration and its resolved eligible option(s); files never provide source digests or accepted context. Existing `ContactOffers`/`ContactDeliveryOffers` v1/v2 remain 1–5 synthetic entries with the unchanged 128-KiB loader. General file parsing does not opt a runtime into publication, validate configured profile existence, certify public content, or check existing database IDs. The inventory publisher owns whole-file gates, bounded reading, signed registry-schema validation, intent persistence and publication sequencing.

## Accepted context and integrity

`AcceptedContactContext` is public context within a party-protected accepted package:

| Field | Type | Owner and demonstrated source |
|---|---|---|
| `schema_version` | Integer `1` | Bare-metal source contract |
| `discovery_schema` | `"vms.compute"` | Domain discovery family; active filter version remains registry-owned |
| `negotiation_schema` | `"bare_metal.v1"` | Exact domain negotiation codec |
| `declaration` | `ContactDeclaration` | Immutable source-envelope publication intent, checked against local listing |
| `accepted_terms.duration_seconds` | Positive integer | Accepted `BareMetalMessage.duration_seconds` |
| `accepted_terms.access_method` | `"none"` | Accepted message; SSH key and access reference must both be absent |
| `option_id` | Digest | Exact selected option, verified as a member of immutable intent |
| `publication_intent_digest` | Digest | SHA-256 JCS of the full typed intent |
| `source_envelope_digest` | Digest | SHA-256 JCS of decoded source envelope |
| `listing_binding_digest` | Digest | SHA-256 JCS of binding identity fields, excluding `source_envelope_json` and mutable `last_reconciled_at` |

The accepted package at `SettlementPlan.service_terms["contact-exchange.v1"]` has exactly `option_id`, `profile`, `channel`, `terms`, `delivery_policy`, `context_contract`, `listing_id`, `accepted_context`. Profile/channel/terms/policy/selector are the selected option values. No `negotiated_context` or replacement buyer-supplied machine JSON is admitted for the new shape.

The new accepted obligation params contain the selected option params plus `payer_principal` (accepted buyer) and `accepted_context_digest` (SHA-256 JCS of the entire accepted context). The top-level obligation/plan retain their existing payer/claimant principals, asset, expiry, conditions and mechanism. Context is not added to historical params. An obligation digest now commits to context for this eligibility, avoiding a recursive plan hash.

Capture path:

1. Local admission validates the strict intent, declaration projection and seller-owned exact options; core persists immutable source/binding with SQL null physical authority.
2. `BareMetalNegotiationService._open_exact_selection` resolves the selected trusted listing option and immutable binding. `capture_contact_context` verifies that source and the accepted non-access message before any opening/plan is persisted.
3. The existing kit obligation builder includes the opaque domain capture and checks configured contact literals over the full public artifact. Bare metal validates the resulting package/digest/option/party relation.
4. The existing accepted-plan commit transaction registers the digest-bearing obligation with pending bookkeeping only. No contacts, recipient jobs, reservation or mechanism operation are created.
5. `_accepted_introduction` derives the requested obligation reference from that persisted plan and runs `validate_accepted_contact_context` before serving it to review/finalization/protected reads. It never rereads a mutable listing, registry or browser for machine facts. Missing or inconsistent required provenance fails closed.
6. Review uses the existing private salted HMAC binding over exact own contact/route, both parties, full accepted package, policy, intent and expiry; seller contact/route have their own keyed snapshot. Mutating text, route, party, option, context, terms, or seller snapshot cannot pass the prior review. Existing finalization fencing/persistence remain unchanged.

Option IDs deliberately retain the repository's existing SHA-256 of UTF-8 `json.dumps({mechanism,asset,rates,params}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`. Do not silently replace that algorithm with JCS for historical IDs. Source binding's canonical stored JSON and derivation-key algorithm are also unchanged. New context digests and existing review HMAC inputs use `market_identity.canonical_json` (RFC 8785); the vectors include exact UTF-8 hex and SHA-256. Hashes of public machine facts are public; contact/route fingerprints remain salted/keyed private metadata.

## Errors and compatibility

| Input/record | Behavior |
|---|---|
| Old no-policy profile/option/accepted plan | Same serialized terms, option/obligation IDs, pull-only or explicitly local legacy behavior; no backfill/jobs |
| Existing delivery-policy-only v2 option/plan | Existing review/finalize lifecycle and map payloads; no new context fabricated |
| New context selector + strict unbacked declaration/intent | New option identity and new acceptance capture/digest; existing v2 review/finalize input |
| Old ID reused for a new declaration/intent | Immutable binding rejects changed provenance; no retrofit |
| Null/unknown selector, unknown keys/version or coercion | Strict validation refusal, never downgrade |
| Eligible option without matching source/declaration/exact option, or malformed JSON/invalid domain structure in its authoritative listing projection | `NegotiationRequestError("invalid_contact_provenance")` (409), with no supplied values and no negotiation or obligation persistence; capture helpers use the same fixed code in `ValueError` |
| Database operational failure while loading the authoritative projection | Propagates as a database failure, not a validation rejection; no negotiation or obligation persistence |
| Corrupt accepted package/digest/party/option | `ValueError("invalid_contact_provenance")`; existing prepare boundary maps to privacy-preserving 404 |
| Changed review input/package/parties | Existing `finalization_conflict` (409), no capture |
| Changed seller snapshot | Existing `review_changed` (409), no capture |
| Existing malformed carrier / unavailable config | Existing safe 422 / 503 behavior |

Old clients can refuse new eligible options. They are not silently granted disclosure authority. Carrier validation alone does not qualify a seller configuration UI, file-publication workflow, buyer adapter, renderer, email delivery, release or activation.

## Machine-readable evidence

`kit/contact-exchange/src/market_contact_exchange/fixtures/contact_source_v1.json` is packaged in the contact wheel. It contains `schema_version`, fixture notice, signed-envelope version, `cases`, generated carrier `schemas`, an exact `acceptance_trace`, and `compatibility_options`. Each case names its carrier, full input, acceptance decision and (for success) exact serialized value, JCS UTF-8 hex and SHA-256. Negative case error names are normalized conformance categories, not raw Pydantic messages. JSON Schema describes structure; scalar, no-coercion, cross-field, canonical identity and provenance rules in the vectors/validators remain required.

Python replays every vector; bare-metal replay reconstructs the exact capture and accepted plan. `file_contract` specifies byte/count constants, one fixture document, raw cases (literal `utf8_hex` or the UTF-8 fixture JSON padded with ASCII spaces to `pad_to_bytes`), and count cases (clone its entry, assigning `declared-contact-example-{index}` / `declaration-example-{index}`). These instructions avoid megabyte fixtures while specifying exact boundary decisions. The dependency-free Bun runner independently checks text scalar/blank/unknown-key decisions and canonical bytes/digests for all accepted vectors. It does not claim an independent TypeScript implementation of every domain validator.
