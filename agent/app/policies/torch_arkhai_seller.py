"""Arkhai seller policy adapter backed by upstream puffer checkpoints.

This policy intentionally keeps local logic thin:
- Observation layout follows upstream Arkhai ordering.
- Model loading expects puffer `state_dict` checkpoints.
- Action mapping remains local (domain-level accept/counter/reject).
"""
from __future__ import annotations

import importlib
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import gymnasium as gym

from app.policies.registry import policy_callable
from app.schema.pydantic_models import (
    Action as DomainAction,
    ActionType,
    ComputeResource,
    ComputeResourcePortfolio,
    DecisionContext,
    GPUModel,
    MakeOfferEvent,
    TokenResource,
)
from app.utils.config import CONFIG
from app.utils.validation import extract_resources_from_make_offer_event

try:  # Torch is optional at runtime; fail gracefully if unavailable.
    torch: Any = importlib.import_module("torch")
except Exception:  # pragma: no cover - environment-dependent
    torch = None

logger = logging.getLogger(__name__)

_DEFAULT_MODEL_PATH = Path(__file__).resolve().parent.parent / "policies" / "models" / "arkhai_seller.pt"
_loaded_model: Optional[Any] = None
_loaded_model_obs_dim: Optional[int] = None


class _PolicyEnvStub:
    """Minimal env shape/action stub for puffer Default policy."""

    def __init__(self, obs_dim: int) -> None:
        self.single_observation_space = gym.spaces.Box(
            low=0.0,
            high=1.0,
            shape=(obs_dim,),
            dtype="float32",
        )
        self.single_action_space = gym.spaces.MultiDiscrete([9, 2])


def _parse_node_types() -> int:
    try:
        return max(1, int(os.getenv("ARKHAI_NODE_TYPES", "3")))
    except ValueError:
        return 3


def _parse_job_nodes(node_types: int) -> list[float]:
    raw = os.getenv("ARKHAI_JOB_GPU_NODES", "")
    if not raw.strip():
        values: list[float] = []
        for slot in range(node_types):
            slot_raw = os.getenv(f"ARKHAI_JOB_GPU_{slot}_NODES", "").strip()
            if not slot_raw:
                values.append(10.0)
                continue
            try:
                values.append(float(slot_raw))
            except ValueError:
                logger.warning(
                    "[ARKHAI SELLER POLICY] Invalid ARKHAI_JOB_GPU_%s_NODES value '%s'; using default",
                    slot,
                    slot_raw,
                )
                values.append(10.0)
        return values
    values: list[float] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            values.append(float(item))
        except ValueError:
            logger.warning(
                "[ARKHAI SELLER POLICY] Invalid ARKHAI_JOB_GPU_NODES value '%s'; using defaults",
                raw,
            )
            return [10.0] * node_types
    if not values:
        return [10.0] * node_types
    if len(values) < node_types:
        values.extend([values[-1]] * (node_types - len(values)))
    return values[:node_types]


def _parse_gpu_slot_map(node_types: int) -> dict[str, int]:
    mapping: dict[str, int] = {
        GPUModel.H200.value: 0,
        GPUModel.TESLA_V100.value: 1,
        GPUModel.RTX_5080.value: 2,
    }
    raw = os.getenv("ARKHAI_GPU_SLOT_MAP", "").strip()
    if not raw:
        return {
            key: slot
            for key, slot in mapping.items()
            if 0 <= slot < node_types
        }

    parsed: dict[str, int] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        gpu_name, slot_str = pair.split(":", 1)
        try:
            slot = int(slot_str.strip())
        except ValueError:
            continue
        if 0 <= slot < node_types:
            parsed[gpu_name.strip()] = slot

    if parsed:
        return parsed
    logger.warning(
        "[ARKHAI SELLER POLICY] Invalid ARKHAI_GPU_SLOT_MAP='%s'; using defaults",
        raw,
    )
    return {
        key: slot
        for key, slot in mapping.items()
        if 0 <= slot < node_types
    }


def _obs_dim(node_types: int) -> int:
    # Upstream Arkhai layout:
    # 1 (time) + 2*N (cluster nodes) + 5 (tb/energy) + N (request nodes) + 5 (request meta + prev_reward)
    return 12 + 3 * node_types


def _create_model(obs_dim: int) -> Optional[Any]:
    if torch is None:
        return None
    try:
        puffer_models = importlib.import_module("pufferlib.models")
        env_stub = _PolicyEnvStub(obs_dim)
        return puffer_models.Default(env_stub, hidden_size=128)
    except Exception as exc:
        logger.error("[ARKHAI SELLER POLICY] Failed to create puffer model stub: %s", exc)
        return None


def _load_state_dict(model_file: Path, obs_dim: int) -> Optional[Any]:
    if torch is None:
        return None

    model = _create_model(obs_dim)
    if model is None:
        return None

    try:
        raw_state = torch.load(str(model_file), map_location="cpu")
    except Exception as exc:
        logger.error("[ARKHAI SELLER POLICY] Failed reading model file %s: %s", model_file, exc)
        return None

    if not isinstance(raw_state, dict):
        logger.error("[ARKHAI SELLER POLICY] Unsupported checkpoint format at %s", model_file)
        return None

    state_dict = raw_state.get("policy_state_dict", raw_state)
    if not isinstance(state_dict, dict):
        logger.error("[ARKHAI SELLER POLICY] Invalid state_dict in %s", model_file)
        return None

    # If checkpoint came from wrapped recurrent policy, extract base policy weights.
    if any(k.startswith("policy.") for k in state_dict):
        state_dict = {
            k.removeprefix("policy."): v
            for k, v in state_dict.items()
            if k.startswith("policy.")
        }

    try:
        model.load_state_dict(state_dict, strict=False)
    except Exception as exc:
        logger.error("[ARKHAI SELLER POLICY] Failed loading checkpoint into policy: %s", exc)
        return None

    model.eval()
    logger.info("[ARKHAI SELLER POLICY] Loaded checkpoint model from %s", model_file)
    return model


def _get_model(obs_dim: int) -> Optional[Any]:
    """Lazily load the Arkhai model checkpoint."""
    if torch is None:
        logger.warning("[ARKHAI SELLER POLICY] PyTorch not available; skipping model load")
        return None

    global _loaded_model, _loaded_model_obs_dim
    if _loaded_model is not None and _loaded_model_obs_dim == obs_dim:
        return _loaded_model

    env_path = os.getenv("ARKHAI_SELLER_MODEL_PATH", "").strip()
    model_file = Path(env_path) if env_path else _DEFAULT_MODEL_PATH
    if not model_file.exists():
        logger.warning(
            "[ARKHAI SELLER POLICY] Model checkpoint not found at %s. "
            "Set ARKHAI_SELLER_MODEL_PATH to a puffer checkpoint path.",
            model_file,
        )
        return None

    loaded = _load_state_dict(model_file, obs_dim)
    if loaded is None:
        return None

    _loaded_model = loaded
    _loaded_model_obs_dim = obs_dim
    return _loaded_model


def _gpu_slot(resource: ComputeResource, gpu_slot_map: dict[str, int]) -> Optional[int]:
    return gpu_slot_map.get(resource.gpu_model.value)


def _count_nodes_by_slot(
    portfolio: ComputeResourcePortfolio,
    node_types: int,
    gpu_slot_map: dict[str, int],
) -> tuple[list[float], list[float]]:
    total = [0.0] * node_types
    free = [0.0] * node_types
    for resource in portfolio.resources:
        if not isinstance(resource, ComputeResource):
            continue
        slot = _gpu_slot(resource, gpu_slot_map)
        if slot is None:
            continue
        total[slot] += float(resource.quantity)
        # Local portfolio has no direct free-capacity metric; use conservative estimate.
        free[slot] += float(resource.quantity) * 0.5
    return total, free


def _extract_token_amount(offer_resource: Any, demand_resource: Any) -> float:
    if isinstance(offer_resource, TokenResource):
        return float(offer_resource.amount)
    if isinstance(demand_resource, TokenResource):
        return float(demand_resource.amount)
    return 0.0


def _build_arkhai_observation(
    context: DecisionContext,
    offer_resource: Optional[Any] = None,
    demand_resource: Optional[Any] = None,
    order: Optional[Any] = None,
) -> Optional[Any]:
    """Build upstream-aligned Arkhai observation vector.

    Layout follows upstream compute_observations:
    [time] + [cluster nodes total/free * N] + [tb_usage, tb_capacity, kwh_storage, kwh_capacity, kw_generation]
    + [request nodes * N] + [request tb, start, duration, negotiations, price, prev_reward]
    """
    if torch is None:
        return None

    node_types = _parse_node_types()
    obs = torch.zeros((1, _obs_dim(node_types)), dtype=torch.float32)
    job_nodes = _parse_job_nodes(node_types)
    gpu_slot_map = _parse_gpu_slot_map(node_types)
    idx = 0

    try:
        # Time of day
        obs[0, idx] = (time.localtime().tm_hour % 24) / 24.0
        idx += 1

        # Portfolio extraction
        totals = [0.0] * node_types
        frees = [0.0] * node_types
        portfolio_dict = context.available_resources
        if portfolio_dict and "resources" in portfolio_dict:
            try:
                portfolio = ComputeResourcePortfolio.model_validate(portfolio_dict)
                totals, frees = _count_nodes_by_slot(portfolio, node_types, gpu_slot_map)
            except Exception as exc:
                logger.warning("[ARKHAI SELLER POLICY] Failed to validate portfolio: %s", exc)

        # Cluster node totals and free amounts
        for slot in range(node_types):
            denom = job_nodes[slot] + 1.0
            obs[0, idx] = min(1.0, totals[slot] / denom)
            idx += 1
            obs[0, idx] = min(1.0, frees[slot] / denom)
            idx += 1

        # TB and energy states (placeholders until local state tracking is added)
        obs[0, idx] = 0.0  # tb_usage
        idx += 1
        obs[0, idx] = 0.5  # tb_capacity normalized
        idx += 1
        obs[0, idx] = 0.0  # kwh_storage normalized
        idx += 1
        obs[0, idx] = 0.5  # kwh_capacity normalized
        idx += 1
        obs[0, idx] = 0.1  # kw_generation normalized
        idx += 1

        # Request node quantities by slot
        request_nodes = [0.0] * node_types
        if isinstance(demand_resource, ComputeResource):
            slot = _gpu_slot(demand_resource, gpu_slot_map)
            if slot is not None:
                request_nodes[slot] = float(demand_resource.quantity)
        for slot in range(node_types):
            denom = job_nodes[slot] + 1.0
            obs[0, idx] = min(1.0, request_nodes[slot] / denom)
            idx += 1

        # Request metadata
        obs[0, idx] = 0.0  # request tb usage
        idx += 1
        obs[0, idx] = 0.0  # request start
        idx += 1

        duration_hours = float(getattr(order, "duration_hours", 0) or 0)
        job_duration = float(os.getenv("ARKHAI_JOB_DURATION", "10") or 10)
        obs[0, idx] = min(1.0, duration_hours / (job_duration + 1.0))
        idx += 1

        obs[0, idx] = 0.0  # negotiations/request timeout ratio
        idx += 1

        token_amount = _extract_token_amount(offer_resource, demand_resource)
        obs[0, idx] = token_amount / (token_amount + 1.0) if token_amount > 0 else 0.0
        idx += 1

        obs[0, idx] = 0.0  # previous reward
        return obs
    except Exception as exc:
        logger.error("[ARKHAI SELLER POLICY] Failed to build observation: %s", exc)
        return None


def _extract_actions_from_logits(output: Any) -> tuple[int, int]:
    """Extract (price_idx, sell_flag) from puffer policy outputs."""
    if torch is None:
        return 4, 0

    try:
        if not isinstance(output, tuple) or len(output) != 2:
            logger.warning("[ARKHAI SELLER POLICY] Unexpected model output type: %s", type(output))
            return 4, 0

        logits = output[0]

        # Native puffer MultiDiscrete output: tuple/list of tensors [(B,9), (B,2)]
        if isinstance(logits, (tuple, list)) and len(logits) >= 2:
            price_logits = logits[0][0] if len(logits[0].shape) > 1 else logits[0]
            sell_logits = logits[1][0] if len(logits[1].shape) > 1 else logits[1]
            return int(torch.argmax(price_logits).item()), int(torch.argmax(sell_logits).item())

        # Optional concatenated fallback: tensor (B,11)
        if isinstance(logits, torch.Tensor):
            flat = logits[0] if len(logits.shape) > 1 else logits
            if flat.shape[-1] >= 11:
                return (
                    int(torch.argmax(flat[:9]).item()),
                    int(torch.argmax(flat[9:11]).item()),
                )

        logger.warning("[ARKHAI SELLER POLICY] Could not parse action logits; using defaults")
        return 4, 0
    except Exception as exc:
        logger.error("[ARKHAI SELLER POLICY] Failed parsing actions: %s", exc)
        return 4, 0


def _build_action_parameters(
    order_id: str | None = None,
    offer_resource: Any = None,
    demand_resource: Any = None,
    price_idx: int | None = None,
    sell_flag: int | None = None,
    order: Any = None,
) -> dict[str, Any]:
    parameters: dict[str, Any] = {}

    if order is not None:
        if hasattr(order, "model_dump"):
            parameters["order"] = order.model_dump(mode="json")
        elif isinstance(order, dict):
            parameters["order"] = order

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

    if price_idx is not None:
        parameters["price_idx"] = price_idx
        multipliers = [0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2]
        if 0 <= price_idx < len(multipliers):
            parameters["price_multiplier"] = multipliers[price_idx]
    if sell_flag is not None:
        parameters["sell_flag"] = sell_flag
        parameters["energy_sell_action"] = "sell_50_percent" if sell_flag == 1 else "hold"

    return parameters


@policy_callable("mo.action.torch_arkhai_seller")
async def mo_action_torch_arkhai_seller(context: DecisionContext) -> DomainAction | None:
    """Model-based Arkhai seller policy for MakeOffer events."""
    if not isinstance(context.event, MakeOfferEvent):
        return None

    order, offer_resource, demand_resource = extract_resources_from_make_offer_event(context)
    if order is None:
        return None

    if isinstance(demand_resource, ComputeResource):
        portfolio_dict = context.available_resources
        if portfolio_dict and "resources" in portfolio_dict:
            try:
                portfolio = ComputeResourcePortfolio.model_validate(portfolio_dict)
                if not portfolio.has_capacity(demand_resource):
                    return DomainAction(
                        action_type=ActionType.REJECT_OFFER,
                        parameters={
                            "reason": "insufficient_capacity",
                            "order_id": order.order_id,
                            "demand_resource": demand_resource.model_dump(mode="json"),
                            "offer_resource": offer_resource.model_dump(mode="json"),
                        },
                    )
            except Exception as exc:
                logger.warning("[ARKHAI SELLER POLICY] Failed to validate portfolio: %s", exc)

    node_types = _parse_node_types()
    model = _get_model(_obs_dim(node_types))
    if model is None or torch is None:
        logger.warning("[ARKHAI SELLER POLICY] Model unavailable; returning None")
        return None

    observation = _build_arkhai_observation(context, offer_resource, demand_resource, order)
    if observation is None:
        logger.warning("[ARKHAI SELLER POLICY] Failed to build observation; returning None")
        return None

    try:
        with torch.no_grad():
            output = model(observation)
    except Exception as exc:
        logger.error("[ARKHAI SELLER POLICY] Inference failed: %s", exc)
        return None

    price_idx, sell_flag = _extract_actions_from_logits(output)

    maker_offers_compute = isinstance(offer_resource, ComputeResource) and isinstance(
        demand_resource, TokenResource
    )
    maker_offers_tokens = isinstance(offer_resource, TokenResource) and isinstance(
        demand_resource, ComputeResource
    )
    current_url = CONFIG.base_url_override.rstrip("/")
    maker_url = order.order_maker.rstrip("/")
    is_maker = maker_url == current_url or maker_url.endswith(current_url) or current_url.endswith(
        maker_url
    )
    if is_maker:
        agent_role = "seller" if maker_offers_compute else "buyer"
    else:
        agent_role = "buyer" if maker_offers_compute else "seller"
    if not maker_offers_compute and not maker_offers_tokens:
        agent_role = "seller"

    if agent_role == "seller":
        action_type = (
            ActionType.ACCEPT_OFFER
            if price_idx <= 7
            else ActionType.COUNTER_OFFER
            if price_idx == 8
            else ActionType.REJECT_OFFER
        )
    else:
        action_type = (
            ActionType.ACCEPT_OFFER
            if price_idx <= 6
            else ActionType.COUNTER_OFFER
            if price_idx == 7
            else ActionType.REJECT_OFFER
        )

    parameters = _build_action_parameters(
        order_id=order.order_id,
        offer_resource=offer_resource,
        demand_resource=demand_resource,
        price_idx=price_idx,
        sell_flag=sell_flag,
        order=order if action_type == ActionType.ACCEPT_OFFER else None,
    )
    return DomainAction(action_type=action_type, parameters=parameters)
