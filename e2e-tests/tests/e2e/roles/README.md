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

## Alkahest deal scenario

```console
make -C e2e-tests test-buyer-machine \
  BUYER_MODULE=e2e_alkahest_escrow_codecs
```
