# Compute Domain Policy Notes

Core-generic policy authoring and evaluation guidance:
- `core/agent/app/policy/policy-making.md`

## Compute-specific modules
- `domain/compute/agent/app/policy/store.py`
  - compute callables (`ri.*`, `mo.*`, `negotiation.*`, fulfillment/arbitration transitions)
- `core/agent/app/policy/seeding.py`
  - compute default policy seeding by trigger type
- `core/agent/app/schema/pydantic_models.py`
  - compute event/resource enums and models
- `core/agent/app/utils/action_executor.py`
  - compute-domain action execution

## Compute policy checklist
1. Register callable with `@policy_callable("<name>")`.
2. Guard by trigger/event type early.
3. Return `None` when not applicable.
4. Keep action payloads serializable (`model_dump(mode="json")`).
5. Add/update unit tests in `agent/tests/unit/`.
