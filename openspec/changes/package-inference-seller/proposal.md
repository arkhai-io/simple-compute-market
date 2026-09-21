## Why

Becoming an inference seller after `compose-inference-domain-stack` means
cloning the repository, building images, writing a storefront TOML by hand,
generating signing material, and wiring four containers to a public URL. The
`arkhai-vllm-apitokens-demo` repository is that done by hand, and it drifted
from the main repository within weeks because nothing kept it honest.

Supply is the side of a marketplace that has to be solved first, and the
people with spare GPUs are comparing this against running a model server and
keeping it. This change makes the seller path "answer a few questions, run two
commands." It is deliberately the **thin** version: a configuration generator
and a Compose template, not a wizard. GPU detection, TLS automation, and
market-rate price suggestion are recorded as deferred with a trigger — three
third-party sellers reporting where they got stuck — because those features are
guesses until then.

## What Changes

- **`arkhai-inference-seller`** distribution with an `arkhai-inference` CLI:
  `init` asks for the models to serve, the rate card per model, the registry
  URL and any write token, the public storefront URL, and the settlement
  asset; generates signing material into `0600` files on the repository's
  `*_CREDENTIAL_FILE` convention; renders `storefront.inference.toml`,
  `compose.inference.yml`, and `.env` from templates that are the stack
  change's own files parameterized. `up` runs the stack. `status` shows
  listings, balances, and open holds. `models add` pulls a model and publishes
  a listing.
- **Reachability check.** `init` verifies the storefront `base_url` answers
  from outside the host and says plainly when it does not, because an
  unreachable storefront is the failure that otherwise costs an afternoon.
- **Documentation.** An inference seller quickstart alongside the existing
  seller quickstarts under `docs/`; the vLLM API-credits cookbook gains a pointer;
  the demo repository is archived with a pointer once this lands.
- **Distribution.** Installable with `uv tool install` from the published
  wheels; the templates ship inside the wheel, not in a cloned repository.

## Capabilities

### Modified Capabilities

- `inference`: a seller can compose the inference roles from published
  artifacts and a generated configuration without a repository checkout.
- `deployment-state`: the generated Compose stack is a supported deployment
  shape with its own configuration contract.

## Non-Goals

- No GPU, driver, or VRAM detection; no automatic `--max-model-len` sizing.
- No TLS or reverse-proxy automation.
- No price suggestion from registry data.
- No Helm chart for inference sellers; Kubernetes sellers use the stack
  change's images directly.
- No Arkhai-hosted registry deployment; the default registry URL in the
  template is a placeholder until one exists.

## Dependencies and Related Changes

- **Depends on** `compose-inference-domain-stack` (the files it templates) and
  `meter-inference-usage` (a seller must not be packaged on the flat-charge
  posture).
- `configure-pypi-trusted-publishing` governs whether the new distribution can
  be installed from the index alone; until it completes, the installer's
  `--find-links` path is documented.

## Impact

- New: `domains/inference/seller/` distribution, templates, quickstart.
- Touched: `docs/cookbooks/vllm-apicredits-seller.md` (pointer),
  `domains/Makefile`, release inventory.
- Wire: none. Database: none. Deployment: one new supported shape.

## Permanent documentation impact

- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md` — the generated-stack
      configuration contract.
- [x] Existing subsystem specification — `inference` and `deployment-state`.
- [ ] `docs/development/ARCHITECTURE.md` — none owed.

## Status

Design phase. `tasks.md` is authored when `meter-inference-usage` is accepted.
