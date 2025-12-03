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


# Default model path - can be overridden via environment variable
_DEFAULT_MODEL_PATH = Path(__file__).resolve().parent.parent / "policies" / "models" / "torch_market_seller.ts"
_loaded_model: Optional[Any] = None


def _get_model(model_path: Optional[Path] = None) -> Optional[Any]:
    """Lazily load the TorchScript Market seller model.
    
    Args:
        model_path: Optional path to model file. If None, uses default path.
    """
    if torch is None:
        logger.warning("[MARKET SELLER POLICY] PyTorch not available; skipping model load")
        return None
    
    global _loaded_model
    if _loaded_model is not None:
        return _loaded_model

    # Use provided path or default
    model_file = model_path or _DEFAULT_MODEL_PATH
    
    # Also check environment variable
    import os
    env_model_path = os.environ.get("MARKET_SELLER_MODEL_PATH")
    if env_model_path:
        model_file = Path(env_model_path)

    if not model_file.exists():
        logger.warning(
            "[MARKET SELLER POLICY] TorchScript model not found at %s. "
            "Set MARKET_SELLER_MODEL_PATH environment variable to specify model path.",
            model_file
        )
        return None

    try:
        _loaded_model = torch.jit.load(str(model_file))
        _loaded_model.eval()
        logger.info("[MARKET SELLER POLICY] Loaded TorchScript model from %s", model_file)
    except Exception as exc:  # pragma: no cover - torch errors vary
        logger.error("[MARKET SELLER POLICY] Failed to load TorchScript model: %s", exc)
        _loaded_model = None
    return _loaded_model


def _build_market_observation(
    context: DecisionContext,
    offer_resource: Optional[Any] = None,
    demand_resource: Optional[Any] = None,
) -> Optional[torch.Tensor]:
    """Build Market environment observation vector from DecisionContext.
    
    Market environment has 14 observation features:
    [0] nodes[0].total / max_nodes
    [1] nodes[0].free / max_nodes
    [2] nodes[1].total / max_nodes
    [3] nodes[1].free / max_nodes
    [4] space_tb / max_space_tb
    [5] free_space_tb / max_space_tb
    [6] energy / energy_storage
    [7] energy_gen / energy_gen
    [8] energy_storage / energy_storage
    [9] request.nodes[0] / max_nodes
    [10] request.nodes[1] / max_nodes
    [11] request.space_tb / max_space_tb
    [12] request.duration / max_job_duration
    [13] prev_reward
    
    Args:
        context: DecisionContext with agent state and event
        offer_resource: Optional offer resource
        demand_resource: Optional demand resource
    
    Returns:
        Observation tensor of shape (1, 14) or None if cannot construct
    """
    if torch is None:
        return None
    
    try:
        # Get agent portfolio
        portfolio_dict = context.available_resources
        portfolio = None
        if portfolio_dict and "resources" in portfolio_dict:
            try:
                portfolio = ComputeResourcePortfolio.model_validate(portfolio_dict)
            except Exception as e:
                logger.warning(f"[MARKET SELLER POLICY] Failed to validate portfolio: {e}")
        
        # Initialize observation vector (all zeros as fallback)
        obs = torch.zeros((1, 14), dtype=torch.float32)
        
        # TODO: Map actual portfolio state to observation features
        # For now, use placeholder values normalized to [0, 1]
        # In production, this should extract:
        # - Node counts (A100/H100) from portfolio
        # - Storage capacity from portfolio
        # - Energy state (if available)
        # - Request details from demand_resource
        # - Previous reward from context
        
        # Placeholder: set some basic values
        if portfolio and portfolio.resources:
            # Estimate node counts (simplified)
            total_nodes = sum(r.quantity for r in portfolio.resources if isinstance(r, ComputeResource))
            obs[0, 0] = min(1.0, total_nodes / 100.0)  # nodes[0].total / max_nodes
            obs[0, 1] = obs[0, 0] * 0.5  # nodes[0].free / max_nodes (estimate)
        
        # Request features from demand_resource
        if demand_resource and isinstance(demand_resource, ComputeResource):
            # Map demand resource to request features
            obs[0, 9] = min(1.0, demand_resource.quantity / 100.0)  # request.nodes[0]
            obs[0, 10] = 0.0  # request.nodes[1] (H100)
        
        # Previous reward (if available in context)
        # This would need to be tracked separately or extracted from context
        obs[0, 13] = 0.0  # prev_reward placeholder
        
        return obs
        
    except Exception as e:
        logger.error(f"[MARKET SELLER POLICY] Failed to build observation: {e}")
        return None


def _extract_actions_from_logits(output: Any) -> tuple[int, int]:
    """Extract price_idx and sell_flag from model output.
    
    Market environment uses MultiDiscrete([9, 2]):
    - price_idx: 0-8 (price multiplier index for job offers)
      * Higher index → higher offer price → more rejections but higher margin
      * Lower index → lower offer price → easier acceptance but lower margin
    - sell_flag: 0 or 1 (energy marketplace sell flag)
      * If 1: sell 50% of current stored energy at current kw_price(t)
      * Energy sale proceeds are added to reward
      * Overflow sells may occur automatically if storage exceeds capacity
    
    The model outputs: ((price_logits, sell_logits), values)
    where:
    - price_logits: shape [1, 9] - logits for price_idx
    - sell_logits: shape [1, 2] - logits for sell_flag (energy sell decision)
    - values: shape [1, 1] - value estimate
    
    Args:
        output: Model output (tuple of ((price_logits, sell_logits), values))
    
    Returns:
        Tuple of (price_idx, sell_flag) where sell_flag controls energy sales
    """
    if torch is None:
        return 4, 0  # Default: middle price, no sell
    
    # Handle output format: ((price_logits, sell_logits), values)
    if isinstance(output, tuple) and len(output) == 2:
        action_logits, _ = output[0], output[1]
        
        # action_logits is itself a tuple: (price_logits, sell_logits)
        if isinstance(action_logits, tuple) and len(action_logits) == 2:
            price_logits, sell_logits = action_logits[0], action_logits[1]
            
            # Extract price_idx from price_logits [1, 9]
            price_idx = int(torch.argmax(price_logits[0] if len(price_logits.shape) > 1 else price_logits).item())
            
            # Extract sell_flag from sell_logits [1, 2]
            sell_flag = int(torch.argmax(sell_logits[0] if len(sell_logits.shape) > 1 else sell_logits).item())
            
            return price_idx, sell_flag
    
    # Fallback: try to extract from single tensor (old format)
    if isinstance(output, tuple):
        logits = output[0]
    else:
        logits = output
    
    # Try to extract from single logits tensor
    if isinstance(logits, torch.Tensor):
        if logits.shape[-1] >= 9:
            price_logits = logits[0, :9] if len(logits.shape) > 1 else logits[:9]
            price_idx = int(torch.argmax(price_logits).item())
        else:
            price_idx = 4  # Default middle price
        
        if logits.shape[-1] >= 11:
            sell_logits = logits[0, 9:11] if len(logits.shape) > 1 else logits[9:11]
            sell_flag = int(torch.argmax(sell_logits).item())
        else:
            sell_flag = 0  # Default: no sell
        
        return price_idx, sell_flag
    
    # Last resort: return defaults
    return 4, 0


def _build_action_parameters(
    order_id: str | None = None,
    offer_resource: Any = None,
    demand_resource: Any = None,
    price_idx: int | None = None,
    sell_flag: int | None = None,
) -> dict[str, Any]:
    """Build parameter payload with resource/order info and market actions."""
    parameters: dict[str, Any] = {}
    
    if order_id:
        parameters["order_id"] = order_id
    if offer_resource:
        parameters["offer_resource"] = (
            offer_resource.model_dump(mode="json")
            if hasattr(offer_resource, "model_dump")
            else offer_resource
        )
    if demand_resource:
        parameters["demand_resource"] = (
            demand_resource.model_dump(mode="json")
            if hasattr(demand_resource, "model_dump")
            else demand_resource
        )
    
    # Add market-specific action parameters
    if price_idx is not None:
        parameters["price_idx"] = price_idx
    if sell_flag is not None:
        parameters["sell_flag"] = sell_flag
    
    return parameters


@policy_callable("mo.action.torch_market_seller")
def mo_action_torch_market_seller(context: DecisionContext) -> DomainAction | None:
    """TorchScript-driven market seller policy using trained RL model.
    
    Uses a trained Market environment model to make pricing and energy selling decisions.
    The model takes Market environment observations (14 features) and outputs:
    - price_idx (0-8): Price multiplier index for job offers
      * Higher index → higher offer price → more rejections but higher margin
      * Lower index → lower offer price → easier acceptance but lower margin
    - sell_flag (0-1): Energy marketplace sell flag
      * If 1: sell 50% of current stored energy at current kw_price(t)
      * Energy sale proceeds are added to reward
    
    The Market environment models a seller-side controller for:
    - Cloud compute marketplace (nodes per type, storage TB, duration)
    - Energy marketplace (buy/sell energy based on time-varying prices)
    
    Args:
        context: DecisionContext with event and agent state
    
    Returns:
        DomainAction or None if cannot process
    """
    # Only process MakeOfferEvent
    if not isinstance(context.event, MakeOfferEvent):
        return None

    # Extract order and resources
    order, offer_resource, demand_resource = extract_resources_from_make_offer_event(context)
    
    if order is None:
        return None
    
    # Check agent capacity for demand resource if it's a ComputeResource
    if isinstance(demand_resource, ComputeResource):
        portfolio_dict = context.available_resources
        if portfolio_dict and "resources" in portfolio_dict:
            try:
                portfolio = ComputeResourcePortfolio.model_validate(portfolio_dict)
                if not portfolio.has_capacity(demand_resource):
                    logger.info("[MARKET SELLER POLICY] Insufficient capacity, rejecting offer")
                    return DomainAction(
                        action_type=ActionType.REJECT_OFFER,
                        parameters={
                            "reason": "insufficient_capacity",
                            "order_id": order.order_id,
                            "demand_resource": demand_resource.model_dump(mode="json"),
                            "offer_resource": offer_resource.model_dump(mode="json"),
                        }
                    )
            except Exception as e:
                logger.warning(f"[MARKET SELLER POLICY] Failed to validate portfolio: {e}")
    
    # Load model
    model = _get_model()
    if model is None or torch is None:
        logger.warning("[MARKET SELLER POLICY] Model not available; returning None")
        return None

    # Build Market environment observation from context
    # The Market environment expects 14 normalized features:
    # [0-3]: Node capacity (total/free for types 0 and 1)
    # [4-5]: Storage capacity (total/free)
    # [6-8]: Energy state (charge, gen, storage)
    # [9-12]: Request details (nodes, storage, duration)
    # [13]: Previous reward
    observation = _build_market_observation(context, offer_resource, demand_resource)
    if observation is None:
        logger.warning("[MARKET SELLER POLICY] Failed to build observation; returning None")
        return None

    # Run inference
    try:
        with torch.no_grad():
            output = model(observation)
    except Exception as exc:
        logger.error("[MARKET SELLER POLICY] Inference failed: %s", exc)
        return None

    if output is None:
        logger.warning("[MARKET SELLER POLICY] Model returned None")
        return None

    # Extract actions from model output
    price_idx, sell_flag = _extract_actions_from_logits(output)
    
    logger.debug(
        f"[MARKET SELLER POLICY] Model inference: price_idx={price_idx}, sell_flag={sell_flag} "
        f"(sell_flag controls energy sales, not compute resource sales)"
    )
    
    # Map market actions to domain actions
    # Note: sell_flag is for energy marketplace, not for compute resource sales
    # price_idx determines the offer price multiplier for job offers
    # For compute resource offers, we map price_idx to action type:
    # - Lower price_idx (0-3): More competitive pricing → ACCEPT or COUNTER
    # - Higher price_idx (4-8): Higher pricing → REJECT or COUNTER
    # The actual mapping should be refined based on your domain requirements
    
    # Map price_idx to action type (this is a simplified mapping)
    # In production, you might want to use price_idx to set actual offer prices
    if price_idx <= 3:
        # Lower price index → more competitive → accept or counter
        action_type = ActionType.ACCEPT_OFFER
    elif price_idx <= 6:
        # Medium price index → counter offer
        action_type = ActionType.COUNTER_OFFER
    else:
        # Higher price index → reject
        action_type = ActionType.REJECT_OFFER
    
    parameters = _build_action_parameters(
        order_id=order.order_id,
        offer_resource=offer_resource,
        demand_resource=demand_resource,
        price_idx=price_idx,
        sell_flag=sell_flag,  # Energy marketplace sell flag
    )
    
    return DomainAction(action_type=action_type, parameters=parameters)

