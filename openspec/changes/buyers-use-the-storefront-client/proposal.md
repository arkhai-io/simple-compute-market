## Why

The storefront has a canonical typed client, `StorefrontClient` and `SyncStorefrontClient` in `core/storefront-client`, but no production buyer uses it. Every buyer builds storefront route strings and request bodies itself:

- `core_buyer`'s signed-JSON helpers cover negotiation (`/api/v1/negotiate/new`, `/api/v1/negotiate/{id}`), Alkahest settlement and status (`/api/v1/settle/{id}`, `/status`), and introductions;
- VM and bare metal each carry a private payment settlement transport;
- bare metal carries a private fulfillment transport;
- the VM service CLI posts deal heartbeats directly.

Integration and system tests are required to use the typed client, so the route contract is pinned on the test side only. When the server changes a request shape, the typed client and the production buyers can disagree, and no test notices. `settle-through-arkhai-payments` found exactly this: the typed client could not express the payment settle request that every production buyer was already sending by hand.

## What Changes

- Production buyers call storefront routes through typed clients rather than hand-built requests: negotiation open and continue, settlement and status, payment agreement settlement and status, introductions, heartbeats, and bare-metal fulfillment.
- The VM and bare-metal payment settlement transports and `core_buyer.submit_settlement_request` collapse into typed client calls.
- The typed client gains what buyers need and it lacks today. The main gap is publisher-trust resolution that refreshes on rotation: buyers verify signed responses through a resolver, while the client pins a fixed `expected_publishers` set at construction.
- `core_buyer` and buyer domain packages depend on the client package that owns each route.

## Capabilities

### Modified Capabilities

- `buyer-orchestration`: buyers call storefront routes only through the typed client that owns each route.

## Non-Goals

- Changing any route path, request body, signed operation, or response.
- Moving routes between storefront packages, or deciding where each route's typed client lives; the storefront shell extraction decides that.
- Registry discovery calls, which already use the registry client.

## Status

Design phase; not planned. Recorded from `settle-through-arkhai-payments`, which added `settle_agreement`, `settle_evm`, and `refund_settlement` to the typed client but left the buyer helpers and transports in place.

## Impact

- Code: `core/buyer/src/core_buyer/{orchestration,negotiation_client,introductions}.py`; `domains/vms/buyer/{arkhai_payments,service_cli}.py`; `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/{arkhai_payments,fulfillment}.py`; `domains/apicredits/buyer/payments.py`; `core/storefront-client`.
- Dependencies: `core/buyer` and the buyer domain packages gain a storefront client dependency.
- Tests: buyer unit tests that assert hand-built bodies move to the typed client's contract.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification — `openspec/specs/buyer-orchestration/spec.md`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Buyers call storefront routes only through the owning typed client — `openspec/specs/buyer-orchestration/spec.md`.
- Goal 4 current state notes that buyers share the storefront's typed client — `docs/development/ROADMAP.md`.

## Dependencies and Related Changes

- Builds on `settle-through-arkhai-payments`, which supplies the agreement settlement and refund client methods.
- On the development branch, `kit-owned-storefront-shell` decides where each route's typed client lives, and its five-piece route rule places mechanism-specific methods in kit client extensions over the core client's `authenticated_request`. Planning starts from that decision so no client moves twice.
