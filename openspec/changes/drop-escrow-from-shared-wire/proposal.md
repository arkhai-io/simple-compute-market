## Why

Listing and registry wire formats still describe escrow. Listings publish `accepted_escrows` beside `settlement_options`. Registry models, filter evaluation and database columns, storefront-client models and fixtures, and storefront SQLite publication state all carry escrow fields that only Alkahest reads.

## What Changes

- Listings publish only `settlement_options`. Alkahest's escrow terms live in its option params.
- Registry filtering uses namespaced settlement clause fields (`alkahest.*`, `arkhai_payments.*`, `contact.*`) and has no escrow columns.
- Storefront-client models and fixtures drop escrow types. The `/api/v1/settle/{escrow_uid}` routes become Alkahest-owned routes contributed by its stage, or are keyed by negotiation ID.
- Arkhai's hosted registries are rebuilt from fresh schemas.

## Capabilities

### Modified Capabilities

- `registry-discovery`, `storefront-publication`: settlement is described only by options and clause fields. Storefront-client models follow.

## Non-Goals

- New registry filtering features.

## Dependencies

- `move-escrow-into-alkahest`: Alkahest must own its escrow terms before the shared fields can go.

## Compatibility

This breaks the wire format for listings and the registry API. There is no backwards-compatibility promise, and hosted registries are reset.
