# Role-separated integration tests

Tests are organized around the **deployment topology** of the marketplace:
four independent layers and a five-stage pipeline, with buyer and seller
as independent roles within each stage.

## The four layers

These correspond to independently deployed authorities, not a VM topology:

1. **External authorities** — the selected settlement network or hosted
   authority and, for physical domains, the selected site/provisioning
   authority. No scenario may replace an unavailable authority with another
   mechanism or infer a default site.
2. **Registry** — the authenticated index service carrying the domain's exact
   filter schema and immutable publisher/domain bindings.
3. **Seller composition** — one storefront process plus only the domain
   authorities it composes. API credits uses the credits authority and gated
   app; compute domains use selected-site capacity and fulfillment.
4. **Buyer role** — the installed core `market` executable, selected persistent
   profile, domain contribution, and role-scoped credentials. It is a
   subprocess fixture, never a co-located buyer server.

Shared fixtures describe URLs, canonical principals, profile state, and public
client boundaries. Domain scenarios own their listing codec, result assertions,
and teardown meaning; shared code never reaches a storefront database,
provisioner, executor, API-key ledger, or hosted provider.

## Structure

```
roles/
├── conftest.py                  # shared role fixtures
├── buyer_cli.py                 # profiled BuyerCli subprocess/config builder
├── helpers/
│   └── domain_deal.py           # opaque five-stage state + event ordering
├── layers/                      # public layer liveness
│   ├── test_external.py
│   ├── test_registry.py
│   └── test_seller.py
└── scenarios/
    ├── vms/                     # VM-specific fixtures and assertions
    ├── apicredits/
    │   └── test_credits_deal_buyer_cli.py
    ├── bare_metal/
    │   └── test_bare_metal_deal.py
    └── core/                    # mechanism checks with no domain service
        └── test_alkahest_escrow_codecs.py
```

Scenarios are grouped by the domain authority they exercise. They share
`DomainDealState`, profiled buyer construction, safe CLI failure reporting, and
ordered lifecycle-event helpers; they do not share domain payloads. VM release
means capacity release, API-credit teardown means the purchased grant reaches
authoritative exhaustion/HTTP 402, and bare-metal teardown means the accepted
lease releases and the authenticated SSH access stops working. Mechanism-only
checks stay in `core/`.

## Design principles

1. **Real infrastructure for release-qualified deals.** A complete-domain
   assertion uses its ordinary registry, seller, settlement, and domain
   authorities. VM-only mock provisioning remains useful for focused VM
   orchestration checks, but it is not bare-metal whole-host evidence and
   cannot satisfy another domain's deal path.

2. **Chinese Room counterparty.** The selected seller contribution and its
   authorities are black boxes. The scenario asserts authenticated
   buyer-observable behavior through public clients and the installed CLI.

3. **User-visible assertions.** Tests assert outcomes the user cares about:
   "my token balance decreased by the agreed price", "I can SSH into the
   machine I paid for". Not internal state transitions.

4. **Thin wrappers around real code paths.** Tests drive the installed
   `market` executable and released public clients. They never reimplement or
   import a storefront, site, provisioning, credits-authority, executor, or
   settlement service.

5. **Stage isolation via domain-neutral state.** `DomainDealState` records the
   five public boundaries and keeps each domain's delivery/teardown result
   opaque. VM's longer staged suite subclasses it with VM-only observations;
   thin API-credit and bare-metal scenarios use it directly.

6. **Exact stage-state dependencies.** A stage that consumes prior
   `DealState` uses `require_state(deal_state, "field")` with the exact
   dataclass attribute name. When adding a field, add at least one
   downstream consumer and verify the producer/consumer transition.
   Misspelled or unconsumed fields otherwise turn the originating failure
   into a misleading downstream skip.

## Running

Bring up the exact domain wrapper and inject every role-scoped prerequisite
before selecting its marker. The API-credit stack requires
`APICREDITS_ADMIN_KEY_FILE`; the bare-metal scenario additionally requires the
installed `market.buyer_domains/bare-metal` wheel, its registry and seller/site
authorities, a canonical Ed25519 credential in the configured environment
reference, exact public `BARE_METAL.BUY_ARGS`, and
`ARKHAI_E2E_BARE_METAL_SSH_PRIVATE_KEY_FILE`.

```bash
docker compose -f compose.vms.yml up -d
uv run pytest -m e2e_deal_buyer_cli -v

docker compose -f compose.apicredits.yml up -d
uv run pytest -m e2e_credits_deal -v

docker compose -f compose.bare-metal.yml up -d
uv run pytest -m e2e_bare_metal_deal -v
```

The bare-metal scenario performs real SSH, requests teardown through
`market bare-metal`, waits for the accepted terminal teardown status, and
requires the same access attempt to fail afterward. If the buyer contribution,
authority endpoint, selected site, credential, or real access target is absent,
the scenario names that prerequisite and remains unavailable; static Compose or
unit results are not substituted.

## Hosted fiat scenarios

Hosted VM system acceptance has one protected provider lane:
`hosted-stripe-test`. It uses the dedicated hosted state carrier rather than
branching or reinterpreting the Alkahest full-deal state. A collection,
reclaim, missed-webhook, API-restart, or worker-restart scenario:

1. binds the exact marketplace commit and ordinary signed hosted production
   manifest, client wheel, service image, signed release repository/workflow
   reference/source commit, and the protected producer workflow run identity
   recorded separately as orchestration evidence;
2. proves a test-mode secret and non-live Stripe objects, API connectivity, the
   exact allowlisted connected account's ownership/capabilities/readiness, the
   fixed loopback webhook path, and Chromium availability;
3. starts the ordinary hosted migration, API, and reconciliation worker roles
   and proves wallet, chain, RPC, balance, and gas inputs are absent;
4. publishes and discovers one `fiat.stripe.v1` option through marketplace
   clients;
5. negotiates, materializes one accepted obligation, and captures its opaque
   durable operation identity;
6. opens the transient Checkout action in Chromium and completes a supported
   Stripe test-mode payment outcome;
7. forwards the real signed event to
   `http://127.0.0.1:18080/webhooks/stripe` and waits on a named observable
   state with a declared bound;
8. completes VM fulfillment and portable condition evidence through ordinary
   marketplace paths;
9. lets the ordinary hosted worker collect or reclaim and retrieves the exact
   related Stripe objects to prove amount, currency, relation, connected
   destination, operation metadata, and one-effect cardinality; and
10. restarts only ordinary processes or webhook forwarding while preserving
    authority state and the original operation/idempotency identity where the
    selected recovery scenario requires it.

Each operation consumes the prior typed snapshot and returns the next typed
snapshot. Provider retrieval follows the relationships and unique metadata
created by this run; an account's latest object cannot satisfy an assertion.
Setup and read-only polling may retry within bounds. Financial mutations
remain inside production code and are never reissued by the harness under a
new identity.

Run from the repository root after installing the Stripe CLI and Chromium:

```console
make hosted-stripe-test \
  HOSTED_RELEASE_TRUST=/path/to/release-trust \
  HOSTED_RELEASE_MANIFEST=/path/to/production-release/release-manifest.json \
  HOSTED_CLIENT_WHEEL=/path/to/production-release/client.whl \
  HOSTED_COMPOSE_ENV=.dist/hosted-settlement-compose.env \
  HOSTED_PRODUCTION_MANIFEST_SHA256=<sha256> \
  HOSTED_PRODUCTION_CLIENT_WHEEL_SHA256=<sha256> \
  HOSTED_PRODUCTION_IMAGE_DIGEST=sha256:<digest> \
  HOSTED_PRODUCTION_SOURCE_COMMIT=<full-hosted-commit> \
  HOSTED_PRODUCTION_WORKFLOW_REF=<signed-producer-workflow-ref> \
  HOSTED_PRODUCTION_WORKFLOW_RUN_ID=<producer-run> \
  HOSTED_MARKETPLACE_COMMIT=<full-marketplace-commit> \
  HOSTED_STRIPE_TEST_RUN_REF=<unique-run-reference> \
  HOSTED_STRIPE_TEST_SCENARIO=<scenario> \
  HOSTED_STRIPE_TEST_ACCOUNT_REF=<allowlisted-account-reference> \
  HOSTED_STRIPE_TEST_AUTHORITY_ENVIRONMENT=<environment-name> \
  HOSTED_STRIPE_TEST_AUTHORITY_ENV_FILE=/path/to/protected-authority.env
```

Provide `STRIPE_SECRET_KEY` (a test-mode `sk_test` or least-privilege
`rk_test`) and `STRIPE_CONNECTED_ACCOUNT_ID` only through the approved
protected Secret/environment boundary. `HOSTED_STRIPE_TEST_EVIDENCE` may
select the sanitized report destination. Connect onboarding is a separate
manual or scheduled account-lifecycle smoke; every transaction run still
retrieves and validates the maintained allowlisted account before publication.
The target generates a release-pinned ephemeral storefront config from signed
authority/manifest coordinates and removes it on every outcome.

An explicit run that lacks a release, credential, network, account, webhook,
Stripe CLI, or browser prerequisite fails before the applicable mutation
boundary. Reports classify terminal outcomes as `product`, `account`,
`environment`, or `timeout` and keep the marketplace repository/commit
separate from the hosted manifest/client/image and signed
repository/workflow-reference/source identity. The protected producer workflow
run identity remains separate orchestration evidence rather than a
signed-manifest field.
Their allowlist contains scenario/stage, unique run reference, opaque operation
identity, normalized state/amount/currency/cardinality, failure class, and
bounded diagnostics. Credentials, Checkout or Account Link URLs,
account/customer/card data, raw webhooks, unrestricted provider payloads, and
unrelated provider objects are excluded from state, process output, and
reports.

For an authorized recovery that must preserve authority state and the
maintained connected-account binding, stop the protected processes without
removing the authority volume:

```console
make hosted-stripe-test-stop
```

Deterministic provider failure placement and event ordering are covered in the
hosted producer's credential-free financial-provider and webhook-inbox
integration suites. Those tests exercise production journal, retry,
reconciliation, inbox, and idempotency behavior under provider-neutral
scripted outcomes and do not establish Stripe behavior.

Alkahest remains an independent mechanism E2E:

```console
make -C e2e-tests test-buyer-machine \
  BUYER_MODULE=e2e_alkahest_escrow_codecs
```

Local EAS/allowlisted-arbiter tests are condition-boundary work only. There is
currently no standalone hosted local-EAS operator target, and focused
condition evidence does not establish hosted finance or Stripe behavior.
