## Why

`add-inference-domain-contract` defines what an inference listing, purchase,
and usage record mean, and `compose-api-family-kit` owns the machinery any
API-selling domain needs to sell access against them. Nothing runs inference.
This change composes the smallest set of roles that can complete one inference
deal on the local development stack and proves that deal end to end, so the
vocabulary is exercised by real buyer and seller boundaries.

The roles are thin composition roots over the family kit. Inference contributes
what the kit cannot know — a model-card listing built from the quota authority,
a guard refusing rate cards the stack cannot yet charge, a materialization that
pins the listing's rate card at acceptance, and the gateway's model check — and
wires the kit's issuance, key authority, gate client, and credits ledger around
them. An earlier version of this change copied the API-credits roles instead and
was withdrawn once the copy measured what inference adds: fewer than 300 lines
against about 12,500 copied. Those three modules, the development seed, and the
startup refusal of a foreign settlement mechanism carry over from it.

Consumption in this change is a **flat charge per request**, using the kit's
gate and authority as API credits ships them. That is not the inference
billing model; it is the smallest thing that proves the market plumbing —
discover, negotiate, settle, issue, call the model, exhaust, top up — is
correct. `meter-inference-usage` replaces the charge model on a stack that
already works. So that no listing advertises a price the stack does not charge,
only request-priced rate cards are publishable until then.

## What Changes

- **Storefront.** An `inference-storefront` executable on the `kit/storefront`
  shell, registered under `market.storefront_domains`, composing the family
  kit's issuance fulfillment, reconciler, and settlement composition with
  Alkahest as its only settlement mechanism, and contributing publication of
  model-card listings from the quota authority, the seller round hook over
  per-credit pricing, the request-priced guard, and the rate-card
  materialization, which it delivers in the delivery's public result.
- **Authority.** An `arkhai:inference-service` image composing the kit's key
  authority and credits ledger under the issuance digest label `inference`,
  with its own database and key namespace. Whether this is the kit's service
  deployed with inference configuration or a composition root of its own is
  `compose-api-family-kit`'s decision, and this change follows it.
- **Gateway.** An `arkhai:inference-gateway` image: an OpenAI-compatible reverse
  proxy in front of a model server, gated by the kit's bearer gate signing as
  the `service` role, charging the listing's per-request credits on admission,
  serving one model at one price with `/v1/models` listing only it. A request
  naming an unlisted model is refused before any charge, and the buyer's
  credential is never forwarded. Streaming responses pass through unbuffered
  even though nothing yet reads their usage.
- **Buyer.** An `arkhai-inference-buyer` plugin under `market.buyer_domains`
  composing the kit's purchase flow and contributing `market inference listing
  list|show`, `buy`, `negotiate`, `settle`, and `settlement status`, the
  `inference` schema identity, model-card discovery filters, and model-card
  rendering, with Alkahest settlement only.
- **Stack.** `domains/inference/compose.yml` (inference registry with the
  filter specification mounted, authority, gateway, storefront, and a model
  server) with the per-domain `compose.inference.yml`,
  `compose.inference-local.yml`, and `compose.inference-lane.yml` files;
  development identities under `dev-env/identities/` and the
  `e2e-inference-dev-env` variables. The model server is a deterministic
  OpenAI-compatible stub built from this repository, so the scenario runs
  without a GPU or an external model download and asserts exact responses; a
  Compose profile swaps in the CPU vLLM image with a small instruct model.
- **Scenario.** `e2e_inference_deal`: discover by model, negotiate a new key,
  settle on the development chain, call `/v1/chat/completions`, be refused an
  unlisted model without charge, consume to `402`, top up the existing key,
  call again, and stream a response — through the shared domain-neutral
  helpers, not a copied VM or API-credits scenario.
- **Build.** `dist-inference-{storefront,buyer,service,gateway,model-stub}`,
  `build-inference-*`, and `test-inference-*` targets; the images join
  `make build`. No inference project needs a separately released dependency.

## Capabilities

### Modified Capabilities

- `inference`: the storefront, authority, gateway, and buyer roles exist and
  complete one deal; flat per-request consumption is the version-1 posture
  until metering lands.
- `api-family`: the kit's contribution surface gains its second consumer.
- `market-composition`: the "shipped domains are loaded" scenario gains the
  inference plugin.
- `deployment-state`: a third registry schema is deployable locally; the
  development identity set and Compose wiring gain the inference roles.
- `test-compatibility`: the per-domain end-to-end deal path exists for
  inference.

## Non-Goals

- No domain-local implementation of anything the family kit owns.
- No admission holds, usage capture, or per-token charging.
- No fiat (`arkhai.payments.v1`) option, no Helm alias, no Arkhai-hosted
  registry, no webapp.
- No per-token rate card on a published listing.
- No seller installer or packaging beyond the Compose stack.
- No TypeScript or Rust gate.

## Dependencies and Related Changes

- **Depends on** `add-inference-domain-contract` and `compose-api-family-kit`
  accepted.
- **Consumes** `sign-multi-language-credits-middleware`'s Python signing path
  as it stands; does not wait on its TypeScript and Rust work.
- **Enables** `meter-inference-usage` by supplying the stack it changes.
- `repair-storefront-alkahest-configuration` owns the development stack's
  Alkahest readiness; this change's scenario needs it green.

## Impact

- New: `domains/inference/{storefront,buyer,service,gateway,model-stub}/`,
  `domains/inference/compose.yml`, the per-domain Compose files, development
  identities, the `e2e-inference-dev-env` target, the e2e lane targets, the
  e2e scenario and marker.
- Touched: root `docker-compose.yml`, `domains/Makefile`, root `Makefile`,
  `e2e-tests/Makefile`, `.github/workflows/e2e.yml`,
  `e2e-tests/pyproject.toml` markers.
- Wire: none beyond the new domain. Database: one new service database, not
  shared. Deployment: new images and one more registry instance in the
  development stack.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — runtime service map and local
      deployment topology gain the inference roles and third registry schema.
- [x] Existing subsystem specification — `market-composition`,
      `deployment-state`, `test-compatibility` scenarios; `api-family`'s
      second consumer.
- [x] New subsystem specification — `inference` gains the role-composition and
      end-to-end requirements.

## Status

Returned to design on 2026-10-19. The copy-based `design.md` and `tasks.md`
were withdrawn with the copied implementation; the design is authored against
`compose-api-family-kit`'s kit once its design passes review.
