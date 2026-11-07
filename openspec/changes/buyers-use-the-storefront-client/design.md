# Design

Design phase; not planned.

## Context

`TESTING.md` requires integration and system tests to call a service through its canonical typed client, so route strings, bodies, and response parsing have one owner. Storefront tests follow that rule. Production buyers do not, so the storefront's route contract has two independent implementations.

Buyer storefront calls outside the typed client today:

| Caller | Routes |
|---|---|
| `core_buyer.negotiation_client` | `POST /api/v1/negotiate/new`, `POST /api/v1/negotiate/{id}` |
| `core_buyer.orchestration` (`submit_settlement_request`, `poll_settlement_status`, `wait_for_settlement`, `signed_storefront_json`) | `POST /api/v1/settle/{id}`, `GET /api/v1/settle/{id}/status` |
| `core_buyer.introductions` | `GET /api/v1/introductions`, `GET /api/v1/introductions/{obligation_ref}` |
| `domains/vms/buyer/arkhai_payments.py` (`VmSettlementTransport`) | `POST /api/v1/settle/{negotiation_id}` |
| `domains/vms/buyer/service_cli.py` | `POST /api/v1/deals/{deal_ref}/heartbeat` |
| `domains/bare_metal/buyer/.../arkhai_payments.py` (`BareMetalSettlementTransport`) | `POST /api/v1/settle/{negotiation_id}` |
| `domains/bare_metal/buyer/.../fulfillment.py` | `POST /api/v1/fulfillments/begin`, `GET /api/v1/fulfillments/{id}/{suffix}` |
| `domains/apicredits/buyer/payments.py` (via `submit_settlement_request`) | `POST /api/v1/settle/{negotiation_id}` |

`settle-through-arkhai-payments` added `settle_agreement`, `settle_evm`, and `refund_settlement` to the typed client and left these callers in place.

## Behaviors the typed client lacks

- **Publisher-trust resolution.** Buyers verify signed storefront responses against a resolver (`make_publisher_trust_resolver`) that re-reads publisher principals from the registry on rotation and reports `publisher_trust_refreshed` to the run log. The client pins a fixed `expected_publishers` set at construction.
- **Exact retries.** `submit_settlement_request` signs every attempt with one `request_id` and one `timestamp`, so the storefront's replay reservation treats retries as the same request. The client accepts a caller-supplied `request_id` but always signs a fresh timestamp.
- **Error shape.** Buyer retry predicates and run-log messages are written against `RuntimeError` from the signed-JSON helpers. The client raises `StorefrontClientError` with a status code.

## Questions to settle before planning

- **Trust resolution in the client.** Accept a resolver callable alongside or instead of `expected_publishers`, and decide how a refresh is reported without the client depending on run-log vocabulary.
- **Retry identity.** Whether exact retry is a client feature (a retry handle carrying request ID and timestamp) or stays with the caller.
- **Sync and async.** Buyer CLIs are synchronous, so they would use `SyncStorefrontClient`; parity already requires both.
- **Client placement.** On the development branch, `kit-owned-storefront-shell` decides where each route's typed client lives: introductions beside `kit/contact-exchange`, bare-metal fulfillment in the bare-metal domain package, and mechanism-specific methods as kit extensions over `authenticated_request`. This change follows that decision rather than moving clients first.
- **Error mapping.** Translate client errors into the retry predicates and run-log outcomes buyers report today, or change those predicates to read status codes.
- **Order.** Migrate one route family at a time (settlement first, since it has three transports), each with buyer tests asserting through the typed client.

## Decisions

None yet.
