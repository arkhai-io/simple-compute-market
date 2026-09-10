# General declaration publisher

## Decisions

Consume the existing domain `ContactDeclarationOffers` bytes parser (one MiB, 1–256 entries), `ContactPublicationIntent`, declaration projection and ordinary SQLite admission. Do not change carrier schemas, historical loaders or acceptance capture.

The additive command is `bare-metal-storefront publish-declarations --offers PATH`. `BARE_METAL_STOREFRONT_CONTACT_DECLARATIONS_PATH` opts into the same reconciliation on every startup. Simultaneous synthetic and declaration startup paths fail before publication. An absent path does nothing. Startup wiring belongs in `server.py`, where the existing publication lifecycle lives; runtime authority construction does not need modification.

The fixed public notice is `CONTACT-ONLY: machine facts are operator declarations; ownership and availability are unverified; no payment or physical commitment.` Require that literal in the selected configured profile terms and emit it in the registry description. Missing notice fails instead of rewriting authored terms. Require explicit `accepted-listing.v1` eligibility, the exact two-sided delivery policy, private seller contact and valid role-owned delivery configuration. No contact or route is invented from declarations. Configured private contact/route/SMTP literals are checked across both public requests and intent before schema reads or writes; this is not general DLP.

Prepare all entries, validate the signed active `vms.compute/1` schema, and check all existing listing IDs before persistence. All new intents become durable through per-listing transactions before any registry POST. Share the existing bounded signed upsert loop without changing old intent shapes. A database failure can leave partial local intent; remote failure can leave partial or uncertain effects. Retrying the same file preserves identities; changed public content needs a new listing ID. Omission never withdraws inventory. Third-party declarations confer no site, pool, resource, ownership or availability authority.

## Alternatives

Version-dispatch through the old file command was rejected in favor of an additive explicit opt-in that leaves the historical 128-KiB parser and fixture surface unchanged. No schema amendment, generalized inventory subsystem or physical registration is needed.

## Validation

Drive the installed command and startup lifecycle against disposable real signed registry and SQLite services. Prove greater-than-five TEST declarations, invalid tails, duplicate and old-ID refusal, exact eligible options, private-literal refusal, changed immutable intent, signed schema/trust failure, lost acknowledgements, restart, omission and inactive IDs. Run unchanged synthetic, domain admission, physical binding/publication and storefront suites from installed wheels. Static typing, packaging/parity, comment hygiene and strict scoped OpenSpec validation are separate checks. Live activation, real mail and physical machine behavior are outside this work.

## Design promotion record

| Decision | Destination | State |
|---|---|---|
| Whole-file declaration publication and immutable retries | `openspec/specs/storefront-publication/spec.md` | Promoted after independent review |
| Operator assertions without physical authority, bounded partial effects | `openspec/specs/storefront-publication/architecture.md` | Promoted after independent review; repository-wide authority map unchanged |
| Explicit opt-in and exact notice/profile prerequisites | `docs/development/DEPLOYMENT_AND_CONFIG.md` | Promoted; both-path startup guidance reconciled |
| Campaign dependency and current state | `openspec/changes/README.md` | Source-reviewed/promoted state recorded |
| Roadmap and capability index | `docs/development/ROADMAP.md`; existing `openspec/specs/README.md` ownership | Current state updated and remaining work assigned; existing capability links retained |
