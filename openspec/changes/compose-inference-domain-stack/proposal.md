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
  model-card listings from the quota authority, the kit's seller round hook,
  the request-priced guard, and the delivery's public result, which carries the
  contract's `InferenceMaterialization` built from the accepted listing the kit
  pins at acceptance.
- **Authority.** An `arkhai:inference-service` image composing the kit's key
  authority and credits ledger under the issuance digest label `inference`,
  with its own database and key namespace, as a service root of its own over
  the kit's `authority` library: the family keeps each domain's root separate,
  since two domains never share a process (the `api-family` capability's
  `architecture.md`, "Service roots and the capacity profile").
- **Gateway.** A family library, `arkhai-api-gateway` under `kit/api`: an
  OpenAI-compatible reverse proxy in front of a model server that checks the
  requested model before charging, authorizes and charges through the kit's
  bearer gate inside the route, never forwards the buyer's credential, streams
  upstream responses unbuffered, serves `/v1/models` listing the one configured
  model, and carries a per-request verification seam for a later attestation
  proof. Inference composes it as the `arkhai:inference-gateway` image from a
  `gateway-service` root that reads and validates the listing the gateway
  fronts, projects it to the family's offering, and supplies the upstream and
  the gate's `service`-role signing credential; a request is charged the
  `request_credits` its key was issued under, which issuance pins on the key
  and verification returns.
- **Buyer.** An `arkhai-inference-buyer` plugin under `market.buyer_domains`
  composing the kit's purchase flow and contributing `market inference listing
  list|show`, `buy`, `negotiate`, `settle`, and `settlement status`, the
  `inference` schema identity, model-card discovery filters, and model-card
  rendering, with Alkahest settlement only.
- **Stack.** `domains/inference/compose.yml` (inference registry selecting the
  packaged filter specification by path, authority, gateway, storefront, and a
  model server) with the per-domain `compose.inference.yml`,
  `compose.inference-local.yml`, and `compose.inference-lane.yml` files;
  development identities under `dev-env/identities/` and the
  `e2e-inference-dev-env` variables. The model server is a deterministic
  OpenAI-compatible stub built under `e2e-tests/`, so the scenario runs
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
- `api-family`: the kit's contribution surface gains its second consumer; the
  family gains a gateway library in front of OpenAI-style model servers; the
  issuance subject may carry accepted terms, which the authority pins on the
  key and `verify` returns; the authority scopes a key to its first grant; the
  gate gains a separable verify step.
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

- **Depends on** `add-inference-domain-contract` and
  `repair-storefront-alkahest-configuration` accepted. `compose-api-family-kit`
  is closed out and archived; its index row advances at archive cleanup, and
  its kit is what this change composes.
- **Consumes** `sign-multi-language-credits-middleware`'s Python signing path
  as it stands; does not wait on its TypeScript and Rust work.
- **Enables** `meter-inference-usage` by supplying the stack it changes.
- `repair-storefront-alkahest-configuration` owns the development stack's
  Alkahest readiness; this change's scenario needs it green, so it gates
  implementation.

## Impact

- New: `kit/api/gateway/`,
  `domains/inference/{storefront,buyer,service,gateway-service}/`, the model
  stub under `e2e-tests/`,
  `domains/inference/compose.yml`, the per-domain Compose files, development
  identities, the `e2e-inference-dev-env` target, the e2e lane targets, the
  e2e scenario and marker.
- Touched in the family: `kit/api/src/arkhai_api/{issuance,evidence}.py`
  (the subject's optional accepted terms, digest, and charge, omitted when
  unset), `kit/api/selling/src/arkhai_api_selling/{contributions,issuance}.py`
  (the public-result extension's delivery context), `kit/api/contracts/src/arkhai_api_contracts/models.py` (verify
  and consume scope fields; verify's pinned terms), the authority's
  `keys_service.py`, `models.py`, and `migrations.py` (`grant_terms`, key
  scope, the scope refusal), `kit/api/gate/src/arkhai_api_gate/{gate,client}.py`
  (the separable verify step, the scope and charge in `verify`), the gate's
  conformance fixtures, and `kit/api/tests/fixtures/pins/` (an
  inference case beside the unchanged API-credits pins).
- Touched elsewhere: root `docker-compose.yml`, `domains/Makefile`, root
  `Makefile`, `e2e-tests/Makefile`, `.github/workflows/e2e.yml`,
  `e2e-tests/pyproject.toml` markers, `dev-env/identities/README.md`.
- Wire: the family issuance subject gains optional accepted terms, their
  digest, and a request charge, of which the digest and charge enter the
  request digest and the signed evidence; `verify` returns them and, with
  `consume`, accepts optional scope fields; each is omitted when unset so API
  credits' bytes are unchanged and the pins prove it. Database: one new
  inference service database, and a migration creating a `grant_terms` table
  in every API-family authority's database, with `credit_grants` unchanged.
  Both inference databases and both API-credit databases are built by the
  family libraries' migration chains through packaged commands
  (`inference-service-migrate`, `inference-storefront-migrate`,
  `apicredits-service-migrate`, `apicredits-storefront-migrate`), run before
  each application, which only checks its database; the chains name no floor,
  and each family storefront names its own baseline migration ID.
  Deployment: new images and one more registry instance in the development
  stack; an API-family authority upgrades by running its migrate command
  before the new image's application, and an image whose chain lacks a
  recorded migration refuses that database as ahead, so recovery is the
  pre-upgrade backup or rolling forward, not the previous image. Removed: the
  API-credits upgrade and rollback end-to-end scenario
  (`e2e_credits_service_rollback`), its pre-kit image, and the requirement
  they proved. Every end-to-end lane, the inference lane included, layers the
  payments and mediation lane doubles.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — runtime service map and local
      deployment topology gain the inference roles and third registry schema.
- [x] Existing subsystem specification — `market-composition`,
      `deployment-state`, `test-compatibility` scenarios; `api-family`'s
      second consumer and its gateway library.
- [x] New subsystem specification — `inference` gains the role-composition and
      end-to-end requirements.

### Knowledge to promote

- D1: the issuance projection names the served model and delivers the gateway
  URL — the `inference` capability's `spec.md`; the `api-family` capability's `architecture.md` contribution table, inference
  column.
- D2: the gateway is a family library composed by a domain executable —
  the `api-family` capability's `spec.md` and `architecture.md`; `docs/development/ARCHITECTURE.md`
  runtime service map.
- D3: the public result carries the contract's materialization, built from the
  extension's inputs, which include the delivery's settlement context —
  the `inference` capability's `spec.md` and `architecture.md`; the `api-family` capability's `spec.md`.
- D4: retry charges and the metering seam — the `inference` capability's `architecture.md`, "Current
  limits".
- D5: the stub model server is a test image; the `vllm` profile —
  `docs/development/DEPLOYMENT_AND_CONFIG.md`; the `deployment-state`
  capability's `spec.md`.
- D6: contribution values — the `inference` capability's `spec.md`.
- D7: the publish request carries the model card — the `inference` capability's `spec.md`.
- D8: the request-priced guard — the `inference` capability's `spec.md`.
- D9: the Alkahest-only refusal — the `inference` capability's `spec.md`.
- D10: Compose files and identities — the `deployment-state` capability's
  `spec.md`; `dev-env/identities/README.md`.
- D11: the scenario's own lane — the `test-compatibility` capability's
  `spec.md`.
- D12: the buyer plugin's contributions — the `inference` capability's `spec.md`.
- D13: no permanent destination — it records how the modules were obtained;
  the resulting behaviour promotes under D3, D7, and D8.
- D14: the gateway signs as the service role, and the service has no
  shared-secret gate — the `inference` capability's `spec.md` and `architecture.md`.
- D15: the authority's database is built by the family chain — the `api-family` capability's
  `architecture.md`, "Current limits".
- D16: verification seams and the measurable image — the `inference` capability's `architecture.md`;
  the `api-family` capability's `architecture.md`.
- D17: the three-party constraint on settlement composition — the `inference` capability's
  `architecture.md`.
- D18: no permanent destination — the implementation cadence is the order of
  `tasks.md`'s sections.
- D19: the storefront starts without its dependencies — the `inference` capability's
  `architecture.md`.
- D20: the migration policy for the family's four stateful services — the
  `deployment-state` capability's `spec.md`, "Service-owned migration
  history", its `architecture.md`, "Migration and initialization boundary",
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup", and
  `docs/operator-handbook.md`, "Upgrading a deployment"; the terms table's
  migration and its refusal by an image without it — the `api-family` capability's `spec.md`, "The
  issuance subject may carry accepted terms"; the lane doubles and the
  inference lane's runner profile — `docs/development/TESTING.md`, the
  `test-compatibility` capability's `spec.md`, and
  `dev-env/identities/README.md`, "The inference stack"; the inference lane's
  injected lane time — `docs/development/TESTING.md`, "Lane time", the
  `test-compatibility` capability's `spec.md` and `architecture.md`, "Lane time
  and the doubles' controls", the `injected-time` capability's
  `architecture.md`, and `dev-env/identities/README.md`, "The inference
  stack"; each inference party's time setting, routes and control — the
  `inference` capability's `spec.md`, "Each inference party's time is
  configured and set through its own control", and the inference service and
  gateway among a lane's parties — the `test-compatibility` capability's
  `spec.md`, "Every party in a lane shares one lane time the scenario sets";
  the inference buyer in the `market` binary and the inference lane outside
  release-candidate validation — `docs/guidance/repository/images.md`, "The
  `market` binary", and `docs/release-handbook.md`, "Running the lanes on a
  release candidate's images", the first stating the binary's domains and the
  second listing the lanes a candidate runs, inference not among them; a baseline ID per
  family storefront — the `api-family` capability's `architecture.md`, "Current limits"; the sweep kept
  for inference and its one-identity assumption — the `inference` capability's `architecture.md`,
  "Current limits".

Decisions the design records under a review finding's heading:

| Decision | Permanent destination |
|---|---|
| A key is scoped to its first grant's service, resource, and accepted terms (F4, review 02 F1) | the `api-family` capability's `spec.md` |
| The issuance subject carries the accepted terms digest and request charge; the gateway charges the key's verified charge (F1) | the `inference` capability's `spec.md`; the `api-family` capability's `spec.md` and `architecture.md` contribution table |
| The family gateway consumes a domain-neutral offering the domain executable projects (review 02 F3) | the `api-family` capability's `spec.md` and `architecture.md` |
| The proof hook binds to the accepted attestation through the terms digest (review 02 F2, review 03 F2) | the `inference` capability's `architecture.md` |
| A key is enforced against the gateway's offering scope at verify and consume (review 03 F1) | the `api-family` capability's `spec.md` |
| Accepted terms persist as a payload, digest, and charge in a `grant_terms` table beside the grant, omitted from the wire when unset, created by a migration appended to the authority chain (review 03 F3, review 04 F1–F2, D20) | the `api-family` capability's `spec.md` and `architecture.md` — "Current limits"; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Verification precedes the charge; the gate's separable verify step (F3) | the `api-family` capability's `spec.md` and `architecture.md` |
| The gateway discovers the listing it fronts by resource and served model, retrying until published (plan review 06 F1) | the `inference` capability's `spec.md` and `architecture.md` |
| The request charge is positive and ledger-bounded; the guard refuses zero (plan review 06 F3) | the `inference` capability's `spec.md`; the `api-family` capability's `spec.md` |
| A top-up is admitted after the gate's verification TTL (F2) | the `inference` capability's `spec.md`; `architecture.md` — "Current limits" |

## Status

Returned to design on 2026-10-19; the copy-based `design.md` and `tasks.md`
were withdrawn with the copied implementation. Redesigned on 2026-10-28
against the `api` family kit, archived on 2026-10-26, and the contract as
implemented; design reviews 01–05 were triaged on 2026-10-28 and 2026-10-29,
their gaps are decided in `design.md`, and review 05's triage advanced the
change to planning.
