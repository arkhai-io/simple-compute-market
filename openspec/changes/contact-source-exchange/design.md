# Design

## Existing authority and decisions

The reviewed contact source carriers and normative vectors are the representation contract. The seller authors one explicit private `contact_payload` with exactly the `text` key for a whole blurb; old maps remain opaque. `ContactText` validates the existing scalar bound. The seller route remains in the independently configured delivery document. There is no automatic generation, template evaluation or enrollment.

Acceptance already captures bare-metal declaration/machine/terms context and binds its digest into the obligation. Bare-metal protected preparation validates that stored context, without a registry lookup. Review binds the entire package, party identities, buyer text/route and seller text/route snapshot. Finalization already persists the exchange and exactly two awaiting-completion intents in one SQLite transaction. Completion only releases intents after journaled success; committed retry and recovery retain the existing fences. Existing storage is sufficient, so a new exchange schema or migration would create needless compatibility risk.

The delivery event consumes only the frozen party projection. Render nested mappings/lists generically, without importing domain carriers into the delivery kit. Preserve scalar strings, including contact text, literally; use no HTML, template interpreter, shell interpolation or dynamic header. Existing scalar context/contact formatting remains unchanged. This replaces Python container representations for nested context with readable indented fields, including accepted listing identity, declaration details, terms and provenance. Domain interpretation remains in bare-metal acceptance/preparation.

## Alternatives

New seller keys, text chunking, automatic map conversion and a new persistence model are rejected: the reviewed source contract already provides a compatible representation. Recapturing from current registry/listing state is rejected because accepted context is immutable. Renderer-only evidence is insufficient; typed HTTP and fake SMTP must exercise the actual role wiring and persistence.

## Validation and evidence ownership

Use deterministic disposable fixtures and the real typed signed negotiation/introduction transports with SQLite and an owned loopback server. Observe both frozen recipient messages through the existing fake SMTP seam. New tests cover text/context parity, seller and buyer drift, corrupt accepted context, listing withdrawal/mutation, private projections and exact retry after restart. Existing contact-state, HTTP lifecycle, compatibility/vector and fake SMTP tests retain completion contention/failure, delayed review/cancel/finalize fences, lost acknowledgements, verified TLS refusal, bounded retry and route cleanup evidence. Rebuild/reinstall affected wheels and compare source, wheel and installed bytes; report typing and broader suite limitations separately.

### Observed story claims

The issue's `.review`, `.receive` and `.preserve` claims are driven through installed typed signed HTTP against disposable SQLite in `domains/bare_metal/storefront/tests/test_http_contact_source_exchange.py` (32 cases), with no real publication or SMTP.

- `.review`: exact independently retained option params, conditions, declaration/machine, terms and provenance correspond to the accepted package. Eight self-consistent substitutions pass internal digest consistency but fail caller expectation checks. Buyer/seller text and route drift refuse capture; missing profile/policy stays unavailable. Current public terms/channel and SMTP rotation do not replace accepted terms or expand fingerprints. Strict version/caller-context negatives preserve no-store and safe refusals.
- `.receive`: both fake-SMTP copies carry the exact counterparty blurb and frozen listing/machine/terms. Pre-MIME rendering preserves Unicode and whitespace exactly; decoded MIME differs only by SMTP line-ending canonicalization and its terminal newline. Route-only addresses and the other contact never enter a recipient body; nested projections and logs are recursively decoded for canaries.
- `.preserve`: listing withdrawal after acceptance, settings mutation after capture and restart leave the record unchanged. An injected transport failure discards the real successful finalize response before the caller sees its body/proof; owner-status recovery and exact retry preserve one record/two intents. Transaction barriers deterministically prove cancellation before delayed review/finalize and committed finalization before cancellation. Historical no-outbound records remain byte-identical with no jobs.

Inherited suites were rerun, not counted as new scenario implementations: `test_http_contact_delivery.py` covers durable settlement leases/non-success/restart before SMTP, `kit/contact-exchange/tests/unit/test_delivery_state.py` covers finite retries, stale attempts and cleanup, and `kit/delivery/tests/unit/test_smtp_attempt.py` covers verified STARTTLS refusal, lost DATA acknowledgement and positive DATA acknowledgement despite failed/blocked QUIT.

Complete installed-wheel candidate suites passed without skips: delivery 54, contact 170, bare-metal domain 126, storefront 295, shared buyer 125 and bare-metal buyer 12. After combining general declaration publication, the storefront suite passes 302 cases, bringing the combined total to 789. Python vectors are included in contact/domain/storefront suites; Bun independently passes 63 text/canonical-vector cases. Changed source/tests pass typing and import checks, including the common prepared-offer listing accessor used by both publication formats. Expanded source typing has seven diagnostics in unchanged files; repository-wide strict OpenSpec retains 12 unrelated failures. Independent review found no issues. Post-promotion scoped specs/change validation, comment hygiene, cross-references and 92-file source/wheel/installed parity pass. No deployment, inbox or exactly-once claim follows from local evidence.

## Design promotion record

| Decision | Permanent destination | State |
|---|---|---|
| Explicit whole seller text, frozen package and review snapshot | `openspec/specs/contact-exchange-settlement/spec.md` and `architecture.md` | Promoted after review; validated |
| Generic readable inert context, recipient-only projection | `openspec/specs/introduction-delivery/spec.md` and `architecture.md` | Promoted after review; validated |
| Authoring and separate route configuration | `docs/development/DEPLOYMENT_AND_CONFIG.md` | Promoted after review; validated |
| Source delivery qualification, remaining activation gaps | `docs/development/ROADMAP.md`, `openspec/changes/README.md` | Current source and remaining combined qualification recorded |
| Capability index | `openspec/specs/README.md` | Existing capabilities retained; companion link added and resolved |

No repository-wide dependency/authority change is needed. Prior completed and frozen change history remains untouched.
