# Contact source representation delta

## Decisions

This delta does not replace the frozen two-sided delivery design. It supplies its missing source representation and acceptance integrity boundary.

### Whole text

Use the existing private contact map with exactly one `text` key for new text clients. `ContactText` is a strict validator for that profile; its serialized object is the existing `contact_payload`, not a wrapper or a new meaning for commercial `terms`. One whole blurb is 1–512 Unicode scalar values, containing a non-whitespace scalar. No trimming, normalization, chunking, or truncation. Larger blurbs are refused. This is deliberately the existing limit, rather than a new version with an arbitrary expanded limit. Old opaque maps retain their old meanings and limits (1–16 keys, key 1–64, value 1–512); they are not automatically interpreted as text.

Review/finalize bodies and signed envelopes remain v2. The existing review binding already hashes exact payload, own route, both parties, introduction package and seller snapshot. Tests must exercise that production binding and refusal, not merely compare hash functions.

### New eligibility and acceptance capture

An explicitly configured public contact profile adds `context_contract: "accepted-listing.v1"`; omission preserves all old serialized profiles, option hashes and obligations. Null, unknown values, and a context contract without the two-sided delivery policy are invalid. This string is a mechanism-owned capability selector, not domain vocabulary in the kit.

Bare metal supplies a strict domain projection, retaining `vms.compute` discovery and `bare_metal.v1` negotiation. A new declaration identifies seller-authored machine facts without a physical machine/host registration. Its listing carries `declaration_id` and no `machine_id` or `physical_host_id`; non-access and absent site/pool/resource authority are mandatory. Old listings still require both existing IDs. No ID is inferred or synthesized.

The immutable publication intent owns the declaration and exact option list. Acceptance validates the listing binding, source envelope, immutable intent, local listing projection and selected option before committing. The accepted package gains `accepted_context`; its JCS SHA-256 digest enters only the new obligation's `accepted_context_digest`. The selected option ID already commits to the eligibility selector. This binds the context into obligation identity without a self-referential plan hash. Party identities, expiry, mechanism and ordinary option params remain in the same obligation/plan. Protected accepted reads check context integrity against that obligation; historical packages are neither extended nor reconstructed.

Absent or inconsistent provenance for an explicitly eligible option is an error, never a registry/browser fallback. Historical policy-only/no-policy options stay on their original paths.

### General file carrier bounds

The additive operator document is `ContactDeclarationOffers`: `{schema_version:3, offers:[{declaration:ContactDeclaration, profile:string}]}`. Profile selects existing configured contact eligibility/policy; the file cannot override it or carry contacts. The array contains 1–256 entries with unique listing and declaration IDs; general listing IDs use `declared-contact-` plus a nonempty identifier suffix, separating them from synthetic fixture IDs. Raw UTF-8 JSON is bounded to 1048576 bytes, including whitespace; duplicate keys, invalid UTF-8, nonfinite numbers and unsupported versions fail. A bytes-only parser supplies the bounded contract without file I/O or publication. One MiB and 256 entries bound parser/preflight work while permitting batches above five; these are safety limits, not capacity or eligibility. The existing v1/v2 128-KiB, 1–5 fixture parsers remain untouched. `contact_contract.py` owns these pure domain carriers; S_INVENTORY owns bounded file reads, configuration/privacy/conflict preflight, registry validation, persistence and CLI wiring.

## Field ownership and serialized shapes

The exact field, provenance, version, canonicalization, diagnostics and compatibility tables are in [contract.md](contract.md), part of this design. Packaged JSON vectors are executable evidence for those tables. All new carriers forbid unknown fields and coercion; diagnostic boundaries return fixed codes rather than raw validation values. Public declarations cannot carry contacts, routes, credentials, site endpoints or access material. Private text/routes/review metadata never enter publication intent.

## Downstream file ownership

- This change owns contact-kit `delivery_contract.py` (text profile), `source_contract.py` (exact eligible option), `settlement_config.py` (explicit eligibility); bare-metal `schema.py` and new `contact_contract.py` (declaration/context/general-file types and bounded no-I/O parsing); storefront new `contact_context.py` (acceptance capture/integrity), `negotiation_service.py`, `introduction_routes.py`, and `sqlite_client.py` (minimal authoritative wiring), plus source-named tests/vectors.
- S_INVENTORY owns `contact_offers.py`, its operator/file entry points and examples/tests. It consumes the frozen general-file/declaration/intent carriers and ordinary admission seam; it must not copy acceptance logic or alter historical file versions/IDs. Exact files and gates are listed in contract.md.
- S_EXCHANGE owns seller text/config resolution, any further private route parsing, exchange persistence/protected-read/rendering/delivery integration in contact-kit and bare-metal delivery modules. It consumes `ContactText` and frozen `accepted_context`; it must not recapture machine facts from current listings or reinterpret old payloads. Existing review binding remains authoritative.

## Validation plan

Build installed internal wheels; execute carrier vectors, source acceptance through the real negotiation service and disposable SQLite, restart/provenance negatives, production review/finalization drift refusal, and legacy contact/domain suites. No real SMTP, registry publication, cloud targets, or actual operator files. Static typing, wheel contents, comment hygiene and OpenSpec validation are separate gates. HTTP delivery/renderer end-to-end qualification is not implied by contract/capture evidence.

## Design promotion record

| Decision | Permanent destination | State |
|---|---|---|
| Text profile, eligibility, digest/protected-read contract | `openspec/specs/contact-exchange-settlement/spec.md` and `architecture.md` | Promoted after independent review |
| Unbacked declaration and immutable intent | `openspec/specs/storefront-publication/spec.md` and `architecture.md`; `openspec/specs/market-composition/spec.md` | Promoted after independent review |
| Source authority boundary | `docs/development/ARCHITECTURE.md` | Promoted |
| Goal and change/capability index currency | `docs/development/ROADMAP.md`, `openspec/changes/README.md`, `openspec/specs/README.md` | Current state and downstream ownership updated; existing capability links retained |
