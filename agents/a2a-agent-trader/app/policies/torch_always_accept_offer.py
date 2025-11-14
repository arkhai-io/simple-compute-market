from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Optional, Any

try:  # Torch is optional at runtime; fail gracefully if unavailable.
    torch: Any = importlib.import_module("torch")
except Exception:  # pragma: no cover - environment-dependent
    torch = None

from app.policies.registry import policy_callable
from app.schema.pydantic_models import (
    Action as DomainAction,
    ActionType,
    DecisionContext,
    MakeOfferEvent,
    ComputeResource,
    TokenResource,
    ComputeResourcePortfolio,
)
from app.utils.validation import extract_resources_from_make_offer_event

logger = logging.getLogger(__name__)


_MODEL_PATH = Path(__file__).resolve().parent / "models" / "torch_always_accept_offer.ts"
_loaded_model: Optional[Any] = None


def _get_model() -> Optional[Any]:
    """Lazily load the TorchScript ALWAYS ACCEPT POLICY model."""
    if torch is None:
        logger.warning("[ALWAYS ACCEPT POLICY] PyTorch not available; skipping model load")
        return None
    global _loaded_model
    if _loaded_model is not None:
        return _loaded_model

    if not _MODEL_PATH.exists():
        logger.warning("[ALWAYS ACCEPT POLICY] TorchScript model not found at %s", _MODEL_PATH)
        return None

    try:
        _loaded_model = torch.jit.load(str(_MODEL_PATH))
        _loaded_model.eval()
        logger.info("[ALWAYS ACCEPT POLICY] Loaded TorchScript model from %s", _MODEL_PATH)
    except Exception as exc:  # pragma: no cover - torch errors vary
        logger.error("[ALWAYS ACCEPT POLICY] Failed to load TorchScript model: %s", exc)
        _loaded_model = None
    return _loaded_model


def _select_action(logits: Any, order_id: str | None = None, offer_resource: Any = None, demand_resource: Any = None) -> DomainAction:
    """Map model logits to a domain action with resource details.
    
    Args:
        logits: PyTorch Model output logits
        order_id: Optional order ID to include in parameters
        offer_resource: Optional offer resource to include in parameters
        demand_resource: Optional demand resource to include in parameters
    """
    if torch is None:
        params = {}
        if order_id:
            params["order_id"] = order_id
        if offer_resource:
            params["offer_resource"] = offer_resource.model_dump(mode='json') if hasattr(offer_resource, 'model_dump') else offer_resource
        if demand_resource:
            params["demand_resource"] = demand_resource.model_dump(mode='json') if hasattr(demand_resource, 'model_dump') else demand_resource
        return DomainAction(action_type=ActionType.ACCEPT_OFFER, parameters=params)
    
    # Expect logits shape [batch, 3]; take first entry
    probs = torch.softmax(logits[0], dim=0)
    choice = int(torch.argmax(probs).item())

    if choice == 0:
        action_type = ActionType.REJECT_OFFER
    elif choice == 1:
        action_type = ActionType.ACCEPT_OFFER
    else:
        action_type = ActionType.COUNTER_OFFER

    # Include resource details in parameters
    parameters = {}
    if order_id:
        parameters["order_id"] = order_id
    if offer_resource:
        parameters["offer_resource"] = offer_resource.model_dump(mode='json') if hasattr(offer_resource, 'model_dump') else offer_resource
    if demand_resource:
        parameters["demand_resource"] = demand_resource.model_dump(mode='json') if hasattr(demand_resource, 'model_dump') else demand_resource

    return DomainAction(action_type=action_type, parameters=parameters)


@policy_callable("mo.action.torch_always_accept_offer")
def mo_action_torch_always_accept_offer(context: DecisionContext) -> DomainAction | None:
    """TorchScript-driven offer response conforming to make_offer composite standard.

    Extracts resources from MakeOfferEvent, validates resource types, checks agent
    capacity, and includes resource details in action parameters. The model currently
    uses a placeholder feature vector, but in production should derive features from
    the extracted resources and context.
    """
    # Only process MakeOfferEvent
    if not isinstance(context.event, MakeOfferEvent):
        return None

    # Extract order and resources using utility function
    order, offer_compute, demand_compute, offer_token, demand_token = extract_resources_from_make_offer_event(context)
    
    if order is None:
        return None
    
    offer_resource = order.offer_resource
    demand_resource = order.demand_resource
    
    # Check agent capacity for demand resource if it's a ComputeResource
    # If insufficient capacity, reject immediately without running model
    if demand_compute:
        portfolio_dict = context.available_resources
        if portfolio_dict and "resources" in portfolio_dict:
            try:
                portfolio = ComputeResourcePortfolio.model_validate(portfolio_dict)
                if not portfolio.has_capacity(demand_compute):
                    # Agent doesn't have capacity - reject with resource details
                    logger.info("[TORCH POLICY] Insufficient capacity, rejecting offer")
                    return DomainAction(
                        action_type=ActionType.REJECT_OFFER,
                        parameters={
                            "reason": "insufficient_capacity",
                            "order_id": order.order_id,
                            "demand_resource": demand_compute.model_dump(mode='json'),
                            "offer_resource": offer_resource.model_dump(mode='json'),
                        }
                    )
            except Exception as e:
                # If portfolio validation fails, log and continue to model
                logger.warning(f"[TORCH POLICY] Failed to validate portfolio: {e}")

    model = _get_model()
    if model is None or torch is None:
        logger.warning("[TORCH POLICY] PyTorch not available; returning None")
        return None

    # TODO: Replace this with a real feature vector constructed from:
    # - offer_resource and demand_resource details
    # - agent portfolio state
    # - market conditions
    # - historical performance
    # For now, use placeholder tensor
    example_input = torch.zeros((1, 3), dtype=torch.float32)

    try:
        with torch.no_grad():
            logits = model(example_input)
    except Exception as exc:  # pragma: no cover - inference errors vary
        logger.error("[TORCH POLICY] Inference failed: %s", exc)
        return None

    if logits is None or logits.shape[0] == 0:
        logger.warning("[TORCH POLICY] Model returned empty logits")
        return None

    # Return action with resource details included
    return _select_action(
        logits,
        order_id=order.order_id,
        offer_resource=offer_resource,
        demand_resource=demand_resource,
    )
