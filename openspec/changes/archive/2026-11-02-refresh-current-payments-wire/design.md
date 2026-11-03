# Design

## Context

The payment kit consumes an external HTTP authority through generated Pydantic wire models. The selected standalone publication and producer vectors cover fields and constraints missing from the older OpenAPI extraction: optional effective part ends, zero gross snapshots, safe-integer limits, valid HTTP URLs and required nullable durations. Existing models reject otherwise valid payment responses. Cash movement remains outside the marketplace.

## Goals / Non-Goals

Accept the selected published wire contract with strict, reproducible models; prove producer canonical framing, current signatures and historical signature preservation. Keep payment derivation, receipt authority and account ownership unchanged.

Do not add a payment mechanism, funding UI, cash client, rate-part marketplace policy, server rollout, database migration or automatic refund behavior. Real-machine qualification is independently tracked.

## Decisions

1. Vendor the standalone schema rather than reconstructing it from the lossy OpenAPI rendering. Record original publication hashes in `kit/arkhai-payments/schema/SOURCE.md`; do not record private source locations or revision identities. Inspect published content for public suitability before copying it. A neutral schema identifier may be retained only with its exact transformation and resulting hash documented.
2. Generate models with the existing pinned generator. Replace the obsolete nullable rewrite with explicit checks for the selected required-nullable form, preserving the distinction between required null and optional omission. The standalone balance schema references its string asset type through propertyNames; if the generator renders unhashable model keys, dereference only that exact definition into identical string/pattern constraints in the generation copy and test valid/invalid asset keys. Document and guard every normalization. Never hand-edit generated models or replace strict validation with permissive extras.
3. Make current producer vectors the primary conformance input. Retain the older vector bytes separately for historical canonical identities, receipt framing and attachment hashes. Historical verification does not imply that obsolete mandates are accepted by current models.
4. Preserve `wire_json` and transaction/signature semantics. Add regression coverage for current producer snapshots, end values, zero gross, required null, omitted end, bounds and unknown fields. Change serialization only if a producer vector demonstrates a discrepancy and the resulting identity is verified.
5. Refresh the kit version and only affected dependent constraints/locks through repository tooling. Validate rebuilt consumers against BOTH the currently deployed server contract and the selected publication before deploying affected buyers/storefronts or changing an endpoint. Bind each check explicitly; if both contracts are identical, one check may satisfy both with that identity proven. If they differ, establish a compatible rollout order before mutation. Historical signed-byte verification remains additional evidence, not a substitute for current response parsing. Do not deploy or downgrade the external authority merely to match the consumer.
6. The owner-approved cadence applies: focused checks and packaging before intermediate commits; one combined full-suite/independent-review/CI/E2E/Helm round for the frozen candidate. Reuse unchanged evidence. No per-edit full suite.

### Settled at the whole-change implementation triage

**02 F1 — explicit null for an optional, non-nullable property.** The generated
models accept `null` for an optional property whose schema forbids it, such as a
part's `end` or a receipt part's `rate`, and `wire_json` omits it before hashing or
framing a signature. The owner kept this normalization, decided earlier for
mandates, and extended it explicitly to receipts and snapshots: an inserted null
changes no value the kit checks or stores, because the kit computes transaction
identity and verifies receipt signatures over the parsed model's canonical JSON, not
received bytes.
Refusing such nulls through generation was rejected: it would reverse the earlier
decision, retype the generated optional fields and refuse counterparty data that
parses today, for schema exactness with no change in meaning. It would be
reconsidered if any path hashes, stores or forwards raw received payment JSON after
verification. Specified in `openspec/specs/market-composition/spec.md` and
documented in `kit/arkhai-payments/schema/SOURCE.md`; pinned by
`kit/arkhai-payments/tests/test_receipt_fixture.py`.

## Risks / Trade-offs

A wider schema can expose assumptions beyond the two reproduced failures; producer vectors, existing kit tests and dependent settlement suites cover these seams. Generator formatting or model names may change, so review the generated diff and imports. A published vector proves the wire contract, not live funding or physical delivery. Historical server reads prove only their observed response shapes.

## Migration / Recovery

No database or account migration. Pin consumers to the selected publication and deploy affected artifacts only after compatibility checks. Preserve prior artifacts and transaction identifiers for diagnosis; no automatic rollback or repeated migration. If compatibility fails, stop that rollout and diagnose the specific response without mutating the payments service.

## Implementation cadence

Section 1 is one coherent consumer implementation session including conformance and affected metadata. Section 2 freezes and validates that candidate. Section 3 performs documentation promotion and closeout after review. New hardware proof is not substituted with component evidence.

## Open Questions

None affecting implementation. Live deployment compatibility remains an evidence gate, not an undecided product behavior.

## Design promotion record

| Accepted decision | Permanent location | Status |
|---|---|---|
| Strict published contract and current/historical conformance | `openspec/specs/market-composition/spec.md#requirement-arkhai-payments-authority-remains-external` | Delta merged at archive |
| Publication selection and compatibility boundary | `openspec/specs/market-composition/architecture.md#agreement-based-payment-composition` | Promoted in this closeout |
| Published source identity, deterministic generation and nullable/optional serialization | `kit/arkhai-payments/schema/SOURCE.md`; `kit/arkhai-payments/README.md` | Existing implementation documentation confirmed current; no duplicate edit |
| Explicit null for optional properties normalized in mandates, receipts and snapshots (02 F1) | `openspec/specs/market-composition/spec.md#requirement-arkhai-payments-authority-remains-external`; `kit/arkhai-payments/schema/SOURCE.md#required-nullable-durations-and-optional-values` | Promoted at the whole-change implementation triage |
| No new repository-wide authority or dependency layer | `docs/development/ARCHITECTURE.md#authority-boundaries` | No-impact disposition confirmed; no edit |
