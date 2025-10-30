# Policies: authoring, registering, and evaluating

This document explains how the policy system works, how to write new policies (rules and callables), and how they are evaluated by the agent.

## What is a policy?
A policy maps context (event + resources + market state) to an Action, e.g., "accept_offer" or "reject_offer". Policies can be declared as:
- Rule-based policies (JSON-like via Pydantic models)
- Python callable policies (for custom logic)
- Hybrid evaluation (rules first, then callables)

## Key modules
- `app/policies/schema.py`
  - ComparisonOperator, Condition, ConditionGroup(ALL/ANY), ActionSelection, Action, PolicyRule, DecisionContext
  - Helpers to resolve field paths like `event.data.tag` and apply operators
- `app/policies/evaluator.py`
  - RuleBasedEvaluator, CallableEvaluator, HybridEvaluator
- `app/policies/sqlite_client.py`
  - Minimal SQLite persistence for policies
- `app/policies/store.py`
  - PolicyStore that loads/saves rules, registers callables, caches per agent+trigger, and evaluates

## Domain models used in policies
- `Event`, `EventType`, `ComputeResource`, `MarketOrder` live in `app/schema/pydantic_models.py`.
- Policies inspect `DecisionContext`, which includes:
  - `agent_id`
  - `event` (Event)
  - `available_resources` (dict)
  - `market_state` (dict)
  - `negotiation_history` (list)
  - `past_experiences` (list)

## Evaluation order (hybrid)
1. Rules (highest priority first); first matching rule produces an Action
2. Callables (in registration order); first returning Action wins
3. If nothing matches, result is None (agent should fallback safely)

## Writing rule policies
Rules are expressed with `PolicyRule` using `Condition` or a `ConditionGroup`.

Field paths resolve against the decision context:
- `event.event_type`, `event.data.<key>`
- `resources.<key>` (i.e., `available_resources`)
- `market.<key>` (i.e., `market_state`)
- `agent_id`

Supported operators:
- `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `contains`

Example: accept an offer when we have capacity
```python
from app.policies.schema import PolicyRule, Condition, ActionSelection, ComparisonOperator

accept_offer_rule = PolicyRule(
    name="accept_if_capacity",
    description="Accept negotiation offers when we have capacity",
    trigger_type="negotiation",
    conditions=[
        Condition(field="event.data.message_type", operator=ComparisonOperator.EQ, value="offer"),
        # Your own preprocessing can expose a boolean like resources.has_capacity
        Condition(field="resources.has_capacity", operator=ComparisonOperator.EQ, value=True),
    ],
    action=ActionSelection(action_type="accept_offer", parameters={}, confidence=1.0),
    priority=100,
)
```

Reject if no capacity (lower priority):
```python
reject_rule = PolicyRule(
    name="reject_if_no_capacity",
    description="Reject negotiation offers when we lack capacity",
    trigger_type="negotiation",
    conditions=[
        Condition(field="event.data.message_type", operator=ComparisonOperator.EQ, value="offer"),
        Condition(field="resources.has_capacity", operator=ComparisonOperator.EQ, value=False),
    ],
    action=ActionSelection(action_type="reject_offer", parameters={}, confidence=1.0),
    priority=90,
)
```

## Writing callable policies
Callable policies accept a `DecisionContext` and return `Action | None`.

Deterministic threshold-based example:
```python
from app.policies.schema import Action, ActionType

def simple_negotiation_callable(context):
    if context.event.event_type != "negotiation":
        return None
    if context.event.data.get("message_type") != "offer":
        return None
    total_gpus = int(context.available_resources.get("total_gpus", 0))
    threshold = int(context.market_state.get("gpu_threshold", 1))
    return Action(action_type=ActionType.ACCEPT_OFFER if total_gpus >= threshold else ActionType.REJECT_OFFER)
```

Randomized sample (for parity/testing):
```python
import random
from app.policies.schema import Action, ActionType

def simple_negotiation_random(context):
    if context.event.event_type != "negotiation":
        return None
    if context.event.data.get("message_type") != "offer":
        return None
    choice = random.choice([ActionType.ACCEPT_OFFER, ActionType.REJECT_OFFER])
    return Action(action_type=choice)
```

## Registering and saving policies
Use `PolicyStore` to register callables and save rules to SQLite.

```python
from app.policies.store import PolicyStore, simple_negotiation_callable, simple_negotiation_random
from app.policies.sqlite_client import SQLiteClient

sqlite = SQLiteClient(db_path="/tmp/policies.db")
store = PolicyStore(sqlite)

# Register callables
store.register_callable("simple_negotiation_callable", simple_negotiation_callable())
store.register_callable("simple_negotiation_random", simple_negotiation_random())

# Save rules
await store.save_policy(
    agent_id="agent_001",
    policy_name="accept_if_capacity",
    trigger_type="negotiation",
    rule=accept_offer_rule,
)
await store.save_policy(
    agent_id="agent_001",
    policy_name="reject_if_no_capacity",
    trigger_type="negotiation",
    rule=reject_rule,
)

# Optionally: register callable fallback if rules don't match
await store.save_policy(
    agent_id="agent_001",
    policy_name="callable_fallback",
    trigger_type="negotiation",
    callable_ref="simple_negotiation_callable",
)
```

## Evaluating policies
```python
from app.policies.schema import DecisionContext

context = DecisionContext(
    agent_id="agent_001",
    event=event,  # app.schema.pydantic_models.Event
    available_resources={"total_gpus": 3, "has_capacity": True},
    market_state={"gpu_threshold": 2},
)

action = await store.evaluate_policy(agent_id="agent_001", context=context)
if action:
    # Execute action
    ...
```

## Persistence & caching
- All policies persist in SQLite (`policies` table)
- The store caches by `(agent_id, trigger_type)` and invalidates on `save_policy`
- Rules are prioritized by `priority` (higher first)

## Tips & best practices
- Prefer simple rules for clarity; use callables for complex logic
- Keep priorities disjoint and document them
- Validate conditions carefully; prefer explicit `resources.*` flags that your agent/adapter prepares
- Return `None` from callables when not applicable (lets other policies run)

## Troubleshooting
- No action returned: confirm rules matched the exact `trigger_type` and field paths
- Callables not running: ensure they’re registered and saved with `callable_ref`
- Enum/string mismatches: `EventType` is serialized as strings (e.g., `"negotiation"`)
