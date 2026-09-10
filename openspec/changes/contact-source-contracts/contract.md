# Contact source carrier contract

Design record for the implemented source contract, promoted to the [permanent carrier tables](../../specs/contact-exchange-settlement/spec.md#primitive-rules). It does not authorize deployment or publication. The signed request/response envelope, review/finalize body, and mechanism remain v2, v2, and `contact-exchange.v1` respectively. The existing frozen delivery contract is not rewritten.

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

The inventory publisher must project the declaration's name and machine fields into the existing flat `vms.compute` discovery fields, validate against the signed active registry schema, and preserve the typed local projection. No registry schema or discovery identity is changed here. This candidate implements local admission/capture, not the new operator file/publisher workflow.

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

One MiB and 256 declarations are parser/preflight safety bounds, not physical capacity or market policy. Six valid entries and both count/byte endpoints are conformance cases. The typed intent is produced later from each declaration and its resolved eligible option(s); files never provide source digests or accepted context. Existing `ContactOffers`/`ContactDeliveryOffers` v1/v2 remain 1–5 synthetic entries with the unchanged 128-KiB loader. General file parsing does not opt a runtime into publication, validate configured profile existence, certify public content, or check existing database IDs. S_INVENTORY owns those whole-file gates, bounded reading, signed registry-schema validation, intent persistence and publication sequencing.

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

Old clients can refuse new eligible options. They are not silently granted disclosure authority. This contract does not qualify a new seller configuration UI, inventory file parser, buyer adapter, renderer, email delivery, release or activation.

## Machine-readable evidence

`kit/contact-exchange/src/market_contact_exchange/fixtures/contact_source_v1.json` is packaged in the contact wheel. It contains `schema_version`, fixture notice, signed-envelope version, `cases`, generated carrier `schemas`, an exact `acceptance_trace`, and `compatibility_options`. Each case names its carrier, full input, acceptance decision and (for success) exact serialized value, JCS UTF-8 hex and SHA-256. Negative case error names are normalized conformance categories, not raw Pydantic messages. JSON Schema describes structure; scalar, no-coercion, cross-field, canonical identity and provenance rules in the vectors/validators remain required.

Python replays every vector; bare-metal replay reconstructs the exact capture and accepted plan. `file_contract` specifies byte/count constants, one fixture document, raw cases (literal `utf8_hex` or the UTF-8 fixture JSON padded with ASCII spaces to `pad_to_bytes`), and count cases (clone its entry, assigning `declared-contact-example-{index}` / `declaration-example-{index}`). These instructions avoid megabyte fixtures while specifying exact boundary decisions. The dependency-free Bun runner independently checks text scalar/blank/unknown-key decisions and canonical bytes/digests for all accepted vectors. It does not claim an independent TypeScript implementation of every domain validator.

## Downstream handoff

S_INVENTORY consumes `ContactDeclarationOffers`/`parse_contact_declaration_offers`, `ContactDeclaration`, `declaration_listing`, `ContactPublicationIntent` and `SQLiteClient.upsert_bare_metal_listing`. It owns bounded file reads, profile/policy/privacy/duplicate/existing-ID preflight and registry projection in `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/contact_offers.py`; explicit opt-in wiring in that package's `cli.py` and `runtime.py`; general public fixtures under `domains/bare_metal/storefront/examples/`; and invalid-tail, restart, partial-upsert, signed-schema and legacy/physical regressions in `domains/bare_metal/storefront/tests/test_contact_publication.py`. It must keep old file versions/IDs frozen and validate the active signed `vms.compute` schema before publication. It must not duplicate acceptance capture. General carrier validation alone is not evidence for publication preflight sequencing.

S_EXCHANGE consumes `ContactText`/`parse_contact_text` and `accepted_context` from the accepted package. It owns seller text/config resolution, buyer transport/adaptation as needed, explicit exchange persistence/protected projections and recipient rendering/delivery tests. It must not chunk text, alter private-map/route authority, expand bounds, recapture machine facts, or change eligibility/digest semantics without another reviewed contract delta. The existing `delivery_state` review binding includes the complete package already; this candidate proves its drift refusal without rewriting it.

Concrete S_EXCHANGE seams are `kit/contact-exchange/src/market_contact_exchange/delivery_contract.py`, `delivery_state.py`, `delivery_routes.py`, `delivery_runtime.py` and `settlement_config.py`; role wiring is in `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/introduction_routes.py` and `delivery.py`, with source-named tests under their package test directories. Seller configuration remains role-owned; full rendering/persistence/HTTP delivery qualification is downstream. Any shared buyer transport change belongs to `core/buyer/src/core_buyer/introductions.py`, remains mechanism-opaque, and requires its own tests. Permanent destinations are contact-exchange-settlement spec/architecture for text, eligibility and accepted context, storefront-publication spec/architecture for declaration/file admission, and market-composition spec for unchanged unbacked authority ownership. Configuration/CLI documentation follows actual S_INVENTORY implementation, not this parser-only boundary.
