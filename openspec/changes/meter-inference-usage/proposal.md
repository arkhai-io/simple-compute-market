## Why

`compose-inference-domain-stack` charges one credit per admitted request. That
proves the market, not the product: a five-token greeting and a forty-thousand-
token summarization cost the same, which no seller will price and no buyer
should accept. `add-inference-domain-contract` already defines the usage record,
the rate card, and the deterministic charge; this change puts them on the
request path.

The difficulty is that an inference request's cost is unknown until it finishes,
and a single request can cost more than a key's whole balance. Charging before
the request runs is wrong; letting it run unbilled is worse. The answer is
reserve-then-settle, and the place to do it is the authority, not the gate.

## What Changes

- **Admission holds on the authority.** `hold` reserves a worst-case charge
  against a key and returns a hold identity; `settle` takes a usage record,
  prices it against the grant's pinned rate card, charges the derived amount,
  and releases the remainder; `release` abandons a hold. Holds expire; a
  sweeper reclaims expired holds so a disconnected client cannot strand a
  balance. Pricing happens server-side so a compromised or defective gateway
  cannot under-charge.
- **Gate rework.** The inference gate reads `model` and `max_tokens` from the
  request, refuses a model the key is not entitled to, estimates the worst-case
  charge, places the hold (`402` if it cannot fit, before any GPU time is
  spent), proxies, and settles from the response's `usage`. The optimistic
  batching mode is disabled for inference: it was safe when every request cost
  one credit and is unbounded overdraft at variable cost.
- **Streaming.** The gate forces `stream_options.include_usage` onto the
  upstream request, tees the event stream to the client, and settles from the
  final usage chunk. If the client disconnects mid-stream the gate keeps
  draining the upstream to obtain usage, then settles with outcome `cancelled`.
  Upstream failure releases the hold with outcome `failed`.
- **Pre-flight estimation.** Prompt token count comes from the model server's
  tokenize endpoint or a local tokenizer; **decision gate** in `design.md`,
  resolved by measuring the round-trip cost on the development stack. The
  completion bound is `max_tokens` or the card's `max_completion_tokens`.
- **Usage records and evidence.** Every settled or released hold produces a
  usage record; the authority signs usage evidence and retains records with a
  rollup and retention policy, because one row per request in per-seller SQLite
  degrades under sustained load.
- **Conformance.** Extend the middleware conformance fixture with metered cases
  — hold, settle, cancel, fail, disconnect — so the TypeScript and Rust gates
  have a target when `sign-multi-language-credits-middleware` brings them
  forward. Python is the reference.
- **Scenario.** Extend `e2e_inference_deal`: a long generation is refused when
  the balance cannot cover its worst case, a streamed request cancelled midway
  is charged for what it produced, and a retried settle does not double-charge.

## Capabilities

### Modified Capabilities

- `inference`: admission is hold-then-settle; the rate card is enforced on the
  request path; streaming, cancellation, and failure follow the charge
  derivation; usage records are retained and rolled up.
- `test-compatibility`: cross-language conformance covers metered admission.

## Non-Goals

- No change to API-credits consumption; its fixed-amount gate is untouched.
- No hosted fiat, no external rating platform integration — usage records are
  the seam an adapter would consume; none is built here.
- No embeddings, image, or audio metering; rate-card fields for those remain
  unenforced until their endpoints are in scope.
- No TypeScript or Rust implementation of the metered gate.

## Dependencies and Related Changes

- **Depends on** `compose-inference-domain-stack` for a working stack and on
  `extract-access-issuance-kit` being accepted: the authority this change
  mutates is the kit-composed one, and it is mutated once.
- `add-inference-domain-contract` owns the charge derivation this enforces;
  any change to the formula is a delta there, not here.

## Impact

- Touched: the inference authority (new routes, hold table, sweeper, rollup),
  the inference gateway and its gate, the conformance fixture and Python
  runner, the e2e scenario.
- Wire: new authority routes; the grant row gains hold state. Database: the
  inference authority's own schema only. Deployment: gateway configuration
  gains estimation and hold parameters.

## Permanent documentation impact

- [x] Existing subsystem specification — `inference` (admission, streaming,
      cancellation, retention requirements) and `test-compatibility`.
- [x] `docs/development/TESTING.md` — the conformance section's current example
      gains the metered cases.
- [ ] `docs/development/ARCHITECTURE.md` — none owed unless the authority's
      hold table introduces a new authority boundary; decided in `design.md`.

## Status

Design phase. `tasks.md` is authored when `compose-inference-domain-stack` has
a green `e2e_inference_deal`.
