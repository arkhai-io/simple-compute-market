# Core Policy Authoring

This document covers domain-agnostic policy mechanics in core.

## Core modules
- `core/agent/app/policy/registry.py`
  - `CALLABLE_REGISTRY`, `@policy_callable(name)`
- `core/agent/app/policy/discovery.py`
  - module discovery so decorators execute
- `core/agent/app/policy/store.py`
  - policy registry/cache/evaluation orchestration
- `core/agent/app/policy/composite.py`
  - callable chaining helpers
- `core/agent/app/policy/manager.py`
  - discovery + registration + delegated seeding hook

## Callable contract
A policy callable receives a context and returns either:
- an action (policy matched), or
- `None` (not applicable; next policy may run).

## Registration flow
1. Decorate callables with `@policy_callable("<stable_name>")`.
2. Run discovery for your package.
3. Register discovered callables into `PolicyStore`.

## Composite flow
- Save a policy row with `callable_ref=<composite_name>`.
- Save ordered components in `policy_composites`.
- Evaluation runs components in order until one returns an action.

## Seeding boundary
Core does not define domain event triggers.
- `PolicyManager` accepts an injected seeding callback.
- Domain modules seed default policies for their own triggers.
