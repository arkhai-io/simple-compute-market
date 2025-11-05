# Policies: authoring, registering, and evaluating (callable-only)

This document explains how to write callable policies with decorators, how discovery works, and how composite policies are evaluated in order.

## What is a policy?
A policy maps context (event + resources + market state) to an Action, e.g., "accept_offer" or "reject_offer". Policies are Python callables (for custom logic). Composites are ordered chains of callable names stored in the DB.

## Key modules
- `app/policies/schema.py`
  - Action (PolicyAction), DecisionContext
- `app/policies/registry.py`
  - `CALLABLE_REGISTRY`, `@policy_callable(name)` decorator
- `app/policies/discovery.py`
  - `discover_and_register(package)` to import policy modules so decorators run
- `app/policies/sqlite_client.py`
  - SQLite tables: `policies` and `policy_composites`
- `app/policies/store.py`
  - `PolicyStore` that bulk-registers discovered callables and evaluates by callable name or composite components

## Domain models used in policies
- `Event`, `EventType`, `ComputeResource`, `MarketOrder` live in `app/schema/pydantic_models.py`.
- Policies inspect `DecisionContext`, which includes:
  - `agent_id`
  - `event` (Event)
  - `available_resources` (dict)
  - `market_state` (dict)
  - `negotiation_history` (list)
  - `past_experiences` (list)

## Evaluation flow (callable-only)
1. Load policies for `(agent_id, trigger_type)` ordered by `priority` (desc).
2. For each policy:
   - If `callable_ref` is a registered callable name, execute it. If it returns an Action, stop.
   - Otherwise treat it as a composite name: load `policy_composites` rows by `(agent_id, policy_name = callable_ref)` and execute each sub-callable in order until one returns an Action.
3. If nothing matches, result is `None` (agent should fallback safely).

## Writing callable policies
Callable policies accept a `DecisionContext` and return `Action | None`. Use the decorator to register the stable name.

```python
from app.policies.registry import policy_callable
from app.policies.schema import Action as PolicyAction, DecisionContext
from app.schema.pydantic_models import ActionType

@policy_callable("mo.action.accept_offer")
def mo_action_accept_offer(ctx: DecisionContext) -> PolicyAction | None:
    return PolicyAction(action_type=ActionType.ACCEPT_OFFER, parameters={})
```

## Discovery & bulk registration
At startup, import policy modules so decorators run and then bulk-register the discovered callables.

```python
from app.policies.discovery import discover_and_register
from app.policies.registry import CALLABLE_REGISTRY

discover_and_register("app.policies")
store.register_callables(CALLABLE_REGISTRY)
```

## Composites (ordered chains)
Composites are stored as data in the DB. A policy row points to a composite name via `callable_ref`. Its ordered sub-callables live in `policy_composites`.

Evaluation executes sub-callables in order and returns the first non-None action.

Recommended naming: `domain.variant.vN` (e.g., `resource_imbalance.default.v1`).

## Saving policies (single or composite)
Use `PolicyStore.save_policy(...)` to save a policy row. `callable_ref` can be either a callable name or a composite name.

```python
# Save single-callable policy
await store.save_policy(
    agent_id="agent_001",
    policy_name="make_offer_default_v1",
    trigger_type="make_offer",
    callable_ref="mo.action.accept_offer",
)

# Save composite policy (components must exist in policy_composites)
await store.save_policy(
    agent_id="agent_001",
    policy_name="resource_imbalance_default_v1",
    trigger_type="resource_imbalance",
    callable_ref="resource_imbalance.default.v1",
)
```

## Evaluating policies
```python
from app.policies.schema import DecisionContext

context = DecisionContext(
    agent_id="agent_001",
    event=event,  # app.schema.pydantic_models.Event
    available_resources={"total_gpus": 3},
    market_state={},
)

action = await store.evaluate_policy(agent_id="agent_001", context=context)
if action:
    # Execute action
    ...
```

## SQL inspection
List policies and composite components:

```sql
SELECT name, trigger_type, callable_ref, priority
FROM policies
WHERE agent_id = ?
ORDER BY trigger_type, priority DESC;
```

```sql
SELECT position, component_name
FROM policy_composites
WHERE agent_id = ? AND policy_name = ?
ORDER BY position;
```

## Tips & best practices
- Use stable, namespaced callable names (e.g., `ri.guard.*`, `ri.action.*`, `mo.action.*`)
- Keep priorities disjoint and document them
- Return `None` from callables when not applicable (lets other policies run)

## Troubleshooting
- No action returned: confirm trigger matches and composite components exist and are named correctly
- Callables not running: ensure discovery imported the module and the decorator name matches `callable_ref`
- Enum/string mismatches: `EventType` is serialized as strings (e.g., `"negotiation"`)
