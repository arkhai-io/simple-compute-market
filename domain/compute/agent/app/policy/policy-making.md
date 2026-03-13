# Compute Domain Policy Notes

Core-generic policy authoring and evaluation guidance:
- `core/agent/app/policy/policy-making.md`

## Compute-specific modules

| File | Role |
|------|------|
| `domain/compute/agent/app/policy/store.py` | All active compute callables (`ri.*`, `mo.*`, `negotiation.*`, fulfillment/arbitration transitions) |
| `domain/compute/agent/app/policy/arkhai_common.py` | Shared RL utils: obs builder, model loader, action extraction |
| `domain/compute/agent/app/policy/torch_arkhai_negotiator.py` | Active negotiation callable — puffer bilateral model inference |
| `core/agent/app/policy/seeding.py` | Compute default policy seeding by trigger type |
| `core/agent/app/schema/pydantic_models.py` | Compute event/resource enums and models |
| `core/agent/app/utils/action_executor.py` | Compute-domain action execution |

## Active policy chains

### Negotiation (`EventType.NEGOTIATION`)
Seeded by `ensure_negotiation_policy()`. Mode toggled via `NEGOTIATION_POLICY_MODE` env var.

**bisection** (default):
```
negotiation.guard.always_negotiate_on_price_diff
negotiation.guard.bounded_rounds_and_timeout
negotiation.action.price_interval_concession
negotiation.action.safe_default_reject
```

**rl** (`NEGOTIATION_POLICY_MODE=rl`):
```
negotiation.guard.always_negotiate_on_price_diff
negotiation.guard.bounded_rounds_and_timeout
negotiation.action.torch_arkhai_negotiator   ← puffer bilateral model
negotiation.action.safe_default_reject
```

Model paths (configurable via env vars):
- `ARKHAI_NEGOTIATOR_SELLER_MODEL_PATH` → `domain/compute/agent/app/policy/models/arkhai_negotiator_seller.pt`
- `ARKHAI_NEGOTIATOR_BUYER_MODEL_PATH` → `domain/compute/agent/app/policy/models/arkhai_negotiator_buyer.pt`

Train new models: `market policy train --total-timesteps 10000000 --wandb`
Eval models: `market policy eval --episodes 20`

### Other active chains
- `resource_imbalance.default.v1` → `ri.guard.*` + `ri.action.make_offer_from_resource`
- `order_create.default.v1` → `oc.action.make_offer_from_order_create`
- `order_close.default.v1` → `oc.action.close_order`
- `make_offer.default.v1` → `mo.guard.trigger_is_make_offer` + `negotiation.respond_to_make_offer`
- `ao.action.fulfill_after_accept` (accept offer)
- `rcf.action.trust_fulfillment` (receive fulfillment)
- `arb.action.collect_escrow_after_arbitration` (arbitration)

## Compute policy checklist
1. Register callable with `@policy_callable("<name>")` in `store.py` or a dedicated module.
2. Guard by trigger/event type early — return `None` when not applicable.
3. Return `None` to pass through to the next callable in the chain.
4. Keep action payloads serializable (`model_dump(mode="json")`).
5. Seed in `seeding.py` via `save_policy_composite(components=[...])`.
6. Add/update tests in `domain/compute/tests/`.
