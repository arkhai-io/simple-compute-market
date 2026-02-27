# Policies: authoring, registering, and evaluating (callable-only)

This document explains how to write callable policies with decorators, how discovery works, and how composite policies are evaluated in order.

## What is a policy?
A policy maps context (event + resources + market state) to an Action, e.g., "accept_offer" or "reject_offer". Policies are Python callables (for custom logic). Composites are ordered chains of callable names stored in the DB.

## Key modules
- `app/schema/pydantic_models.py`
  - Domain Action, DecisionContext
- `app/policies/registry.py`
  - `CALLABLE_REGISTRY`, `@policy_callable(name)` decorator
- `app/policies/discovery.py`
  - `discover_and_register(package)` to import policy modules so decorators run
- `app/policies/sqlite_client.py`
  - SQLite tables: `policies` and `policy_composites`
- `app/policies/store.py`
  - `PolicyStore` that bulk-registers discovered callables and evaluates by callable name or composite components
- `app/policies/composite.py`
  - Utilities for programmatically building composite callables: `chain_callables()`, `build_composite_callable()`

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
1. Load policies for `(agent_id, trigger_type)`.
2. For each policy:
   - If `callable_ref` is a registered callable name, execute it. If it returns an Action, stop.
   - Otherwise treat it as a composite name: load `policy_composites` rows by `(agent_id, policy_name = callable_ref)` and execute each sub-callable in order until one returns an Action.
3. If nothing matches, result is `None` (agent should fallback safely).

## Writing callable policies
Callable policies accept a `DecisionContext` and return `Action | None`. Use the decorator to register the stable name.

```python
from core.agent.policy.registry import policy_callable
from app.schema.pydantic_models import Action as Action, ActionType, DecisionContext

@policy_callable("mo.action.accept_offer")
def mo_action_accept_offer(ctx: DecisionContext) -> Action | None:
    return Action(action_type=ActionType.ACCEPT_OFFER, parameters={})
```

## Discovery & bulk registration
At startup, import policy modules so decorators run and then bulk-register the discovered callables.

```python
from core.agent.policy.discovery import discover_and_register
from core.agent.policy.registry import CALLABLE_REGISTRY

discover_and_register("app.policies")
store.register_callables(CALLABLE_REGISTRY)
```

## Composites (ordered chains)
Composites are stored as data in the DB. A policy row points to a composite name via `callable_ref`. Its ordered sub-callables live in `policy_composites`.

Evaluation executes sub-callables in order and returns the first non-None action.

Recommended naming: `domain.variant.vN` (e.g., `resource_imbalance.default.v1`).

### Programmatically building composites
For programmatic composite creation, use utilities from `core.agent.policy.composite`:

```python
from core.agent.policy.composite import build_composite_callable

# Build a composite callable and register it in the store
composite_func = build_composite_callable(
    store=policy_store,
    name="my_composite.v1",
    component_names=["guard.check_condition", "action.perform_action"]
)
# The composite is now registered and can be used as a callable_ref
```

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
SELECT name, trigger_type, callable_ref
FROM policies
WHERE agent_id = ?
ORDER BY trigger_type;
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

## Code snippets (current implementation)

### Decorated guard/action callables
```python
from core.agent.policy.registry import policy_callable
from app.schema.pydantic_models import Action as Action, DecisionContext

@policy_callable("ri.guard.trigger_is_resource_imbalance")
def ri_guard_trigger_is_resource_imbalance(context: DecisionContext) -> Action | None:
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "resource_imbalance":
        return None
    return None

@policy_callable("ri.guard.resource_present")
def ri_guard_resource_present(context: DecisionContext) -> Action | None:
    res = getattr(context.event, "resource", None)
    if not res:
        return None
    return None

@policy_callable("ri.action.make_offer_from_resource")
def ri_action_make_offer_from_resource(context: DecisionContext) -> Action | None:
    from app.schema.pydantic_models import ActionType
    res = getattr(context.event, "resource", None)
    if not res:
        return None
    return Action(
        action_type=ActionType.MAKE_OFFER,
        parameters={"gpu_model": res.gpu_model,"sla": res.sla,"region": res.region},
    )

@policy_callable("mo.guard.trigger_is_make_offer")
def mo_guard_trigger_is_make_offer(context: DecisionContext) -> Action | None:
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "make_offer":
        return None
    return None

@policy_callable("mo.action.accept_offer")
def mo_action_accept_offer(context: DecisionContext) -> Action | None:
    from app.schema.pydantic_models import ActionType
    return Action(action_type=ActionType.ACCEPT_OFFER, parameters={})

@policy_callable("mo.action.torch_always_accept_offer")
def mo_action_torch_always_accept_offer(context: DecisionContext) -> Action | None:
    """Example TorchScript-backed offer policy.

    This mirrors the proof-of-concept in `app/policies/torch_always_accept_offer_policy.py.py`:
    it loads `models/torch_always_accept_offer.ts`, runs inference on a placeholder tensor,
    and maps logits to ACCEPT/REJECT/COUNTER.
    """
    import torch

    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "make_offer":
        return None

    model = torch.jit.load("app/policies/models/torch_always_accept_offer.ts")
    model.eval()

    with torch.no_grad():
        logits = model(torch.zeros((1, 3), dtype=torch.float32))

    probs = torch.softmax(logits[0], dim=0)
    choice = int(torch.argmax(probs).item())
    if choice == 0:
        action_type = ActionType.REJECT_OFFER
    elif choice == 1:
        action_type = ActionType.ACCEPT_OFFER
    else:
        action_type = ActionType.COUNTER_OFFER

    return Action(
        action_type=action_type
    )
```

### Negotiation policies
```python
from core.agent.policy.registry import policy_callable
from app.schema.pydantic_models import Action as Action, ActionType, DecisionContext
import random

@policy_callable("simple_negotiation_random")
def simple_negotiation_random(context: DecisionContext) -> Action | None:
    """50/50 accept/reject for negotiation offers."""
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "negotiation":
        return None
    
    # Check message_type - could be on event attribute or in data
    msg_type = getattr(context.event, "message_type", None) or context.event.data.get("message_type")
    if msg_type != "offer":
        return None
    
    choice = random.choice([ActionType.ACCEPT_OFFER, ActionType.REJECT_OFFER])
    return Action(action_type=choice, parameters={})

@policy_callable("simple_negotiation_callable")
def simple_negotiation_callable(context: DecisionContext) -> Action | None:
    """Accept offer if GPU threshold is met, otherwise reject."""
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "negotiation":
        return None
    
    msg_type = getattr(context.event, "message_type", None) or context.event.data.get("message_type")
    if msg_type != "offer":
        return None
    
    total_gpus = int(context.available_resources.get("total_gpus", 0))
    gpu_threshold = 1  # Default threshold
    if total_gpus < gpu_threshold:
        return Action(action_type=ActionType.REJECT_OFFER, parameters={})
    return Action(action_type=ActionType.ACCEPT_OFFER, parameters={})
```

### Discovery and bulk registration at startup
```python
# app/agent.py
from core.agent.policy.discovery import discover_and_register
from core.agent.policy.registry import CALLABLE_REGISTRY

discover_and_register("app.policies")
self._policy_store.register_callables(CALLABLE_REGISTRY)
```

### Saving composite policies and ordered components
```python
# app/agent.py
await self._policy_store.save_policy(
    agent_id=self.name,
    policy_name="resource_imbalance_default_v1",
    trigger_type=EventType.RESOURCE_IMBALANCE.value,
    callable_ref="resource_imbalance.default.v1",
)
await self._sqlite_client.save_policy_composite(
    agent_id=self.name,
    policy_name="resource_imbalance.default.v1",
    components=[
        "ri.guard.trigger_is_resource_imbalance",
        "ri.guard.resource_present",
        "ri.action.make_offer_from_resource",
    ],
)

await self._policy_store.save_policy(
    agent_id=self.name,
    policy_name="make_offer_default_v1",
    trigger_type=EventType.MAKE_OFFER.value,
    callable_ref="make_offer.default.v1",
)
await self._sqlite_client.save_policy_composite(
    agent_id=self.name,
    policy_name="make_offer.default.v1",
    components=[
        "mo.guard.trigger_is_make_offer",
        "mo.action.accept_offer",
    ],
)
```

### Evaluation expands composites and runs sub-callables in order
```python
# app/policies/store.py
policy_action = None
for ref in data["callables"]:
    if ref in self._registry:
        ce = CallableEvaluator(self._registry[ref])
        policy_action = await ce.evaluate(context)
        if policy_action is not None:
            break
    components = await self._sqlite.load_policy_composite(agent_id=agent_id, policy_name=ref)
    if components:
        for comp in components:
            func = self._registry.get(comp)
            if not func:
                continue
            ce = CallableEvaluator(func)
            policy_action = await ce.evaluate(context)
            if policy_action is not None:
                break
        if policy_action is not None:
            break
```

## Built-in policies (as shipped)

Default policies are provisioned at startup; they are callable-only and expressed as composites in the DB. Their leaf callables are registered via decorators in `app/policies/store.py`.

- Resource Imbalance
  - Policy name: `resource_imbalance_default_v1`
  - Trigger: `resource_imbalance`
  - callable_ref (composite): `resource_imbalance.default.v1`
  - Ordered sub-callables:
    1. `ri.guard.trigger_is_resource_imbalance`: checks the incoming event is `resource_imbalance`
    2. `ri.guard.resource_present`: ensures `event.resource` exists
    3. `ri.action.make_offer_from_resource`: returns `ActionType.MAKE_OFFER` with parameters from the resource

- Make Offer
  - Policy name: `make_offer_default_v1`
  - Trigger: `make_offer`
  - callable_ref (composite): `make_offer.default.v1`
  - Ordered sub-callables:
    1. `mo.guard.trigger_is_make_offer`: checks the incoming event is `make_offer`
    2. `mo.action.torch_always_accept_offer`: TorchScript-driven decision (accept/reject/counter)
       - `mo.action.accept_offer` remains available as a simpler deterministic fallback

- Negotiation (single callable)
  - Policy name: `simple_negotiation_random`
  - Trigger: `negotiation`
  - callable_ref: `simple_negotiation_random`
  - Behavior: 50/50 random accept/reject for negotiation offers
  - Alternative: `simple_negotiation_callable` - accepts if GPU threshold is met, otherwise rejects

SQL to inspect these after startup (use your `AGENT_ID`):

```sql
SELECT name, trigger_type, callable_ref, priority
FROM policies
WHERE agent_id = ?
ORDER BY trigger_type, priority DESC;
```

```sql
-- Resource imbalance components
SELECT position, component_name
FROM policy_composites
WHERE agent_id = ? AND policy_name = 'resource_imbalance.default.v1'
ORDER BY position;

-- Make offer components
SELECT position, component_name
FROM policy_composites
WHERE agent_id = ? AND policy_name = 'make_offer.default.v1'
ORDER BY position;
```
