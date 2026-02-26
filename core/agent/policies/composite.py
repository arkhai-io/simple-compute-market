from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Dict, List

from app.schema.pydantic_models import Action as DomainAction, DecisionContext

if TYPE_CHECKING:
    from app.policies.store import PolicyStore


def chain_callables(
    names: list[str],
    *,
    registry: Dict[str, Callable[[DecisionContext], DomainAction | None]],
) -> Callable[[DecisionContext], DomainAction | None]:
    """Chain multiple callables together, returning the first non-None action.

    Args:
        names: Ordered list of callable names to chain
        registry: Dictionary mapping callable names to their functions

    Returns:
        A callable that executes each component in order until one returns an action
    """
    def _impl(context: DecisionContext) -> DomainAction | None:
        for name in names:
            func = registry.get(name)
            if not func:
                continue
            act = func(context)
            if act is not None:
                return act
        return None
    return _impl


def build_composite_callable(
    store: "PolicyStore",
    name: str,
    component_names: List[str],
) -> Callable[[DecisionContext], DomainAction | None]:
    """Create a composite callable from registered sub-callables and record its components.

    This function:
    1. Records the composite name and its components in the store
    2. Returns a callable that chains the components together

    Args:
        store: PolicyStore instance to register the composite in
        name: Name for the composite callable
        component_names: Ordered list of component callable names

    Returns:
        A callable that executes each component in order until one returns an action
    """
    store.register_composite(name, component_names)
    return chain_callables(component_names, registry=store._registry)

