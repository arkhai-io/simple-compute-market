"""Policy decorators for reducing boilerplate and improving readability."""

from functools import wraps
from typing import Callable

from app.schema.pydantic_models import DecisionContext, Action as DomainAction


def requires_trigger(trigger_type: str) -> Callable:
    """Decorator to filter policies by event trigger type.

    This decorator eliminates the repetitive pattern of extracting and checking
    the event type at the beginning of every policy. Instead of:

        def my_policy(context: DecisionContext) -> DomainAction | None:
            et = context.event.event_type
            trigger = et.value if hasattr(et, "value") else str(et)
            if trigger != "negotiation":
                return None
            # ... policy logic

    You can now write:

        @requires_trigger("negotiation")
        def my_policy(context: DecisionContext) -> DomainAction | None:
            # ... policy logic

    Args:
        trigger_type: The event type to match (e.g., "negotiation", "resource_imbalance")

    Returns:
        Decorator function that wraps the policy callable
    """
    def decorator(func: Callable[[DecisionContext], DomainAction | None]) -> Callable:
        @wraps(func)
        def wrapper(context: DecisionContext) -> DomainAction | None:
            et = context.event.event_type
            trigger = et.value if hasattr(et, "value") else str(et)
            if trigger != trigger_type:
                return None
            return func(context)
        return wrapper
    return decorator


def requires_event_type(event_class: type) -> Callable:
    """Decorator to filter policies by event class type.

    This decorator checks if the event is an instance of the specified class.
    Instead of:

        def my_policy(context: DecisionContext) -> DomainAction | None:
            if not isinstance(context.event, NegotiationEvent):
                return None
            # ... policy logic

    You can write:

        @requires_event_type(NegotiationEvent)
        def my_policy(context: DecisionContext) -> DomainAction | None:
            # ... policy logic

    Args:
        event_class: The event class to check (e.g., NegotiationEvent)

    Returns:
        Decorator function that wraps the policy callable
    """
    def decorator(func: Callable[[DecisionContext], DomainAction | None]) -> Callable:
        @wraps(func)
        def wrapper(context: DecisionContext) -> DomainAction | None:
            if not isinstance(context.event, event_class):
                return None
            return func(context)
        return wrapper
    return decorator
