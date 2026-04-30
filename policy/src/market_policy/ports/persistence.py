"""Persistence ports used by core orchestration modules."""

from __future__ import annotations

from typing import Any, Protocol


class PolicyPersistencePort(Protocol):
    async def save_policy(
        self,
        *,
        agent_id: str,
        name: str,
        trigger_type: str,
        callable_ref: str | None = None,
    ) -> None: ...

    async def load_policies_by_trigger(
        self,
        *,
        agent_id: str,
        trigger_type: str,
    ) -> list[dict[str, Any]]: ...

    async def save_policy_composite(
        self,
        *,
        agent_id: str,
        policy_name: str,
        components: list[str],
    ) -> None: ...

    async def load_policy_composite(
        self,
        *,
        agent_id: str,
        policy_name: str,
    ) -> list[str]: ...


class NegotiationThreadPersistencePort(Protocol):
    async def create_negotiation_thread(
        self,
        *,
        negotiation_id: str,
        our_listing_id: str,
        their_listing_id: str,
        our_agent_id: str,
        their_agent_id: str,
        owner_id: str,
        our_initial_price: int | None = None,
        our_strategy: str | None = None,
    ) -> None: ...

    async def get_thread_info(
        self,
        *,
        negotiation_id: str,
        owner_id: str,
    ) -> dict[str, Any] | None: ...

    async def load_negotiation_thread(
        self,
        *,
        negotiation_id: str,
    ) -> list[dict[str, Any]]: ...

    async def save_negotiation_message(
        self,
        *,
        negotiation_id: str,
        round: int | None,
        sender: str,
        our_price: int | None,
        their_price: int | None,
        proposed_price: int | None,
        action_taken: str,
        message_type: str,
        timestamp: str,
    ) -> int: ...

    async def update_negotiation_thread_terminal(
        self,
        *,
        negotiation_id: str,
        terminal_state: str,
    ) -> None: ...

    async def delete_negotiation_thread(
        self,
        *,
        negotiation_id: str,
    ) -> None: ...

    async def check_existing_negotiation(
        self,
        *,
        our_listing_id: str,
        their_listing_id: str,
        our_agent_id: str | None = None,
        their_agent_id: str | None = None,
    ) -> dict[str, Any] | None: ...

    async def get_active_negotiations_for_order(
        self,
        *,
        order_id: str,
    ) -> list[dict[str, Any]]: ...

    async def cancel_negotiations_for_order(
        self,
        *,
        order_id: str,
        except_negotiation_id: str | None = None,
    ) -> list[str]: ...
