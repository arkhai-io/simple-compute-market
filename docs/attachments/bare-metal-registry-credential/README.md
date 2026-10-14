# Bare-metal registry credential verification

## Prepared target

Local bare-metal storefront package and dedicated Helm render, not a deployed service. No cloud target, Secret, container, or server is created by this setup. The registry hostname and principals in the production-values example are public placeholders. Unit fixtures use deterministic development signers and a development-only bearer; they must never be used on a public network.

Prerequisites: Python 3.13 on PATH, uv, and Helm 3.15.3 (available through mise below).

From the repository root:

```sh
export PATH="$(mise where python@3.13)/bin:$PATH"
make dist
make -C domains/bare_metal/storefront reinit
```

## Runnable first-use surfaces

Exercise environment parsing and the actual publication clients' HTTP headers, with and without a bearer:

```sh
env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy \
  uv run --project domains/bare_metal/storefront --frozen --no-sync pytest \
  domains/bare_metal/storefront/tests/test_publication_cli.py \
  domains/bare_metal/storefront/tests/test_http_system.py -q
```

Render the dedicated deployment with complete public registry trust and an existing Secret reference, without the Secret value:

```sh
mise exec helm@3.15.3 -- helm template bare-metal-review \
  helm/charts/bare-metal-storefront \
  --values helm/charts/bare-metal-storefront/examples/production-values.yaml
```

The rendered pod has registry URL/authority/principals as public values and `BARE_METAL_STOREFRONT_REGISTRY_API_KEY` only through `secretKeyRef`. An empty `registry.apiKeySecret.name` omits the bearer environment variable. The chart defaults leave the registry wholly unconfigured.

## Observed results

- Bare-metal storefront suite: **311 passed**.
- Dedicated chart tests and umbrella `make -C helm test-render` with Helm 3.15.3: **passed**, including the storefront's own parser check.
- Generated values-schema tests: **34 passed** after `make helm-values-schema`.
- `make check-locks`, `make check-architecture`, `make check-packaging`, and `make check-comment-hygiene`: **passed**.
- Scoped documentation citations and strict OpenSpec validation: **passed**.

Bearer absence remains header absence. A bearer-present reachability read still rejects an unsigned registry reply, and configuration repr omits the credential.

These are execution/static-render results, not a visual report or live-registry qualification. The full end-to-end pipeline and deployed HTTP-401-to-success reproduction were not run; no live target or credentials were supplied to this worker. A deployed verifier needs its own configured registry authority/principals and existing API-key Secret; do not substitute the example identities or development bearer.
