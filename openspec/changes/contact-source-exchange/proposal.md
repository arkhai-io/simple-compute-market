# Frozen contact text through recipient delivery

Issue: https://github.com/arkhai-io/simple-compute-market/issues/224

## Why

Explicit contact-text clients need the complete reviewed blurb and accepted machine context to reach each recipient without reconstruction from current settings or listings. The existing review/finalization, immutable introduction and two-intent delivery lifecycle already supply the authority boundary.

## What changes

Render nested accepted context as readable plain text while preserving opaque contact entries verbatim. Document the explicit seller `contact_payload: {text: <whole blurb>}` profile and separate route. Qualify the existing source-contract capture through typed signed HTTP, persisted exchange, restart and fake SMTP with both recipient copies. No new config key, storage migration, UI, runtime contact generation, enrollment, redelivery API or notification framework.

## Permanent documentation impact

- [ ] Existing contact-exchange-settlement spec/architecture: exact reviewed/stored/rendered text and context parity, independent routes, unchanged history.
- [ ] Introduction-delivery spec and new companion architecture: readable inert nested context, recipient isolation, explicit-policy scope alongside legacy local sinks.
- [ ] Deployment/configuration documentation: explicit whole-blurb authoring and separate own route.
- [ ] Roadmap and campaign index: bounded source delivery qualification and remaining external activation boundaries.

Promotion is proposed for independent review, not applied by this change. Local synthetic evidence is neither deployment nor inbox/exactly-once evidence.
