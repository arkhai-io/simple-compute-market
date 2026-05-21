"""Shared infrastructure for Arkhai policy adapters (seller and buyer).

Observation layout, model creation, checkpoint loading, and action extraction
are identical for both sides. Role-specific logic (accept/counter/reject
thresholds, model path, env var) lives in the role-specific modules.
"""
from __future__ import annotations

import importlib
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import gymnasium as gym
from domain.compute.agent.app.policy.store import get_compute_resource_portfolio

from market_storefront.models.domain_models import (
    ComputeResource,
    DecisionContext,
    GPUModel,
)

try:  # Torch is optional at runtime; fail gracefully if unavailable.
    torch: Any = importlib.import_module("torch")
except Exception:  # pragma: no cover - environment-dependent
    torch = None

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Environment stub for puffer model creation
# ---------------------------------------------------------------------------

class PolicyEnvStub:
    """Minimal env shape/action stub for puffer Default policy."""

    def __init__(self, obs_dim: int) -> None:
        self.single_observation_space = gym.spaces.Box(
            low=0.0,
            high=1.0,
            shape=(obs_dim,),
            dtype="float32",
        )
        self.single_action_space = gym.spaces.MultiDiscrete([9, 2])
        # Aliases required by pufferlib.models.Default dict-obs detection fallback
        self.observation_space = self.single_observation_space
        self.action_space = self.single_action_space


# ---------------------------------------------------------------------------
# Config parsing helpers
# ---------------------------------------------------------------------------

def parse_node_types() -> int:
    try:
        return max(1, int(os.getenv("ARKHAI_NODE_TYPES", "5")))
    except ValueError:
        return 5


def parse_job_nodes(node_types: int) -> list[float]:
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
                    "[ARKHAI COMMON] Invalid ARKHAI_JOB_GPU_%s_NODES value '%s'; using default",
                    slot,
                    slot_raw,
                )
                values.append(10.0)
        return values
    values = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            values.append(float(item))
        except ValueError:
            logger.warning(
                "[ARKHAI COMMON] Invalid ARKHAI_JOB_GPU_NODES value '%s'; using defaults",
                raw,
            )
            return [10.0] * node_types
    if not values:
        return [10.0] * node_types
    if len(values) < node_types:
        values.extend([values[-1]] * (node_types - len(values)))
    return values[:node_types]


def parse_gpu_slot_map(node_types: int) -> dict[str, int]:
    mapping: dict[str, int] = {
        GPUModel.H200.value: 0,
        GPUModel.TESLA_V100.value: 1,
        GPUModel.RTX_5080.value: 2,
        GPUModel.RTX_A5000.value: 3,
        GPUModel.RTX_4090.value: 4,
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
        "[ARKHAI COMMON] Invalid ARKHAI_GPU_SLOT_MAP='%s'; using defaults",
        raw,
    )
    return {
        key: slot
        for key, slot in mapping.items()
        if 0 <= slot < node_types
    }


def obs_dim(node_types: int) -> int:
    # Upstream Arkhai layout:
    # 1 (time) + 2*N (cluster nodes) + 5 (tb/energy) + N (request nodes) + 5 (request meta + prev_reward)
    return 12 + 3 * node_types


# ---------------------------------------------------------------------------
# Model creation and checkpoint loading
# ---------------------------------------------------------------------------

def create_model(obs_dim: int) -> Optional[Any]:
    if torch is None:
        return None
    try:
        puffer_models = importlib.import_module("pufferlib.models")
        env_stub = PolicyEnvStub(obs_dim)
        return puffer_models.Default(env_stub, hidden_size=128)
    except Exception as exc:
        logger.error("[ARKHAI COMMON] Failed to create puffer model stub: %s", exc)
        return None


def load_state_dict(model_file: Path, obs_dim_val: int) -> Optional[Any]:
    if torch is None:
        return None

    model = create_model(obs_dim_val)
    if model is None:
        return None

    try:
        raw_state = torch.load(str(model_file), map_location="cpu")
    except Exception as exc:
        logger.error("[ARKHAI COMMON] Failed reading model file %s: %s", model_file, exc)
        return None

    if not isinstance(raw_state, dict):
        logger.error("[ARKHAI COMMON] Unsupported checkpoint format at %s", model_file)
        return None

    state_dict = raw_state.get("policy_state_dict", raw_state)
    if not isinstance(state_dict, dict):
        logger.error("[ARKHAI COMMON] Invalid state_dict in %s", model_file)
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
        logger.error("[ARKHAI COMMON] Failed loading checkpoint into policy: %s", exc)
        return None

    model.eval()
    logger.info("[ARKHAI COMMON] Loaded checkpoint model from %s", model_file)
    return model


def get_model(
    env_var_name: str,
    default_model_path: Path,
    obs_dim_val: int,
    *,
    _cache: dict[str, Any] | None = None,
) -> Optional[Any]:
    """Lazily load an Arkhai model checkpoint.

    Uses a module-level cache keyed by (env_var_name, obs_dim) to avoid
    re-loading the same model.
    """
    if torch is None:
        logger.warning("[ARKHAI COMMON] PyTorch not available; skipping model load")
        return None

    if _cache is None:
        _cache = _MODEL_CACHE

    cache_key = f"{env_var_name}:{obs_dim_val}"
    if cache_key in _cache:
        return _cache[cache_key]

    env_path = os.getenv(env_var_name, "").strip()
    if env_path:
        p = Path(env_path)
        # Resolve relative paths against this module's directory, not CWD
        model_file = p if p.is_absolute() else Path(__file__).resolve().parent / p
    else:
        model_file = default_model_path
    if not model_file.exists():
        logger.warning(
            "[ARKHAI COMMON] Model checkpoint not found at %s. "
            "Set %s to a puffer checkpoint path.",
            model_file,
            env_var_name,
        )
        return None

    loaded = load_state_dict(model_file, obs_dim_val)
    if loaded is None:
        return None

    _cache[cache_key] = loaded
    return loaded


_MODEL_CACHE: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Observation / portfolio helpers
# ---------------------------------------------------------------------------

def gpu_slot(resource: ComputeResource, gpu_slot_map: dict[str, int]) -> Optional[int]:
    return gpu_slot_map.get(resource.gpu_model)


def count_nodes_by_slot(
    portfolio: ComputeResourcePortfolio,
    node_types: int,
    gpu_slot_map: dict[str, int],
) -> tuple[list[float], list[float]]:
    total = [0.0] * node_types
    free = [0.0] * node_types
    for resource in portfolio.resources:
        if not isinstance(resource, ComputeResource):
            continue
        slot = gpu_slot(resource, gpu_slot_map)
        if slot is None:
            continue
        total[slot] += float(resource.gpu_count)
        # Local portfolio has no direct free-capacity metric; use conservative estimate.
        free[slot] += float(resource.gpu_count) * 0.5
    return total, free


# ---------------------------------------------------------------------------
# Negotiation observation builder
# ---------------------------------------------------------------------------

MAX_GPU = 10.0
_EPISODE_LENGTH = 100.0
_REQUEST_TIMEOUT = 10.0  # matches negotiation guard max_rounds


def build_negotiation_observation(
    context: DecisionContext,
    node_types: int = 5,
) -> Optional[Any]:
    """Build Arkhai-aligned observation for bilateral negotiation events.

    Maps DecisionContext → (1, 12 + 3*node_types) float32 tensor.
    Layout mirrors upstream Arkhai compute_observations for the negotiation-
    specific features; unused cluster/energy dims are zeroed consistently.

    Feature mapping (27 features for node_types=5):
      0  time_frac               datetime.now().hour / 24.0
      1  gpu0_total_norm         slot-0 GPU total / MAX_GPU
      2  gpu0_free_norm          slot-0 GPU free / MAX_GPU (50% estimate)
      3  gpu1_total_norm         slot-1 GPU total / MAX_GPU
      4  gpu1_free_norm          slot-1 GPU free / MAX_GPU
      5  gpu2_total_norm         slot-2 GPU total / MAX_GPU
      6  gpu2_free_norm          slot-2 GPU free / MAX_GPU
      7  gpu3_total_norm         slot-3 GPU total / MAX_GPU
      8  gpu3_free_norm          slot-3 GPU free / MAX_GPU
      9  gpu4_total_norm         slot-4 GPU total / MAX_GPU
     10  gpu4_free_norm          slot-4 GPU free / MAX_GPU
     11  tb_usage_norm           0.0 (not tracked)
     12  tb_capacity_norm        0.0
     13  kwh_storage_norm        0.0
     14  kwh_capacity_norm       0.0
     15  kw_generation_norm      0.0
     16  request_gpu0_nodes_norm demand GPU qty / MAX_GPU (slot 0 only)
     17  request_gpu1_nodes_norm 0.0
     18  request_gpu2_nodes_norm 0.0
     19  request_gpu3_nodes_norm 0.0
     20  request_gpu4_nodes_norm 0.0
     21  request_tb_norm         0.0
     22  request_start_norm      round_num / episode_length
     23  request_duration_norm   order.duration_hours / 168.0 (1 week)
     24  negotiation_count_norm  round_num / request_timeout (10)
     25  price_ratio             their_price / our_initial_price, clipped [0, 2]
     26  prev_reward             0.0
    """
    if torch is None:
        return None

    dim = obs_dim(node_types)
    observation = torch.zeros((1, dim), dtype=torch.float32)
    gpu_slot_map = parse_gpu_slot_map(node_types)

    try:
        # 0: time of day
        observation[0, 0] = (time.localtime().tm_hour % 24) / 24.0

        # 1-6: cluster GPU totals and free counts per slot
        totals = [0.0] * node_types
        frees = [0.0] * node_types
        from domain.compute.agent.app.policy.store import get_compute_resource_portfolio
        portfolio = get_compute_resource_portfolio(context)
        if portfolio is not None:
            totals, frees = count_nodes_by_slot(portfolio, node_types, gpu_slot_map)
        for slot in range(node_types):
            observation[0, 1 + slot * 2] = min(1.0, totals[slot] / MAX_GPU)
            observation[0, 2 + slot * 2] = min(1.0, frees[slot] / MAX_GPU)

        # 7-11: TB / energy — zeroed (not tracked in negotiation context)

        base = 12  # start of request features

        # 12-14: request GPU nodes by slot (slot 0 from demand resource in thread_info order)
        thread_info = context.market_state.get("thread_info", {}) if context.market_state else {}
        order_dict = thread_info.get("order") if thread_info else None
        request_gpu_qty = 0.0
        request_gpu_slot = 0
        if isinstance(order_dict, dict):
            for res_key in ("offer_resource", "demand_resource"):
                res = order_dict.get(res_key) or {}
                if isinstance(res, dict) and "gpu_model" in res:
                    gpu_name = res.get("gpu_model", "")
                    slot = gpu_slot_map.get(gpu_name)
                    if slot is not None:
                        request_gpu_qty = float(res.get("gpu_count", 0))
                        request_gpu_slot = slot
                    break
        observation[0, base + request_gpu_slot] = min(1.0, request_gpu_qty / MAX_GPU)

        # 15: request_tb — zeroed

        # 16: request_start_norm — round_num / episode_length
        negotiation_history = context.negotiation_history or []
        agent_id = context.agent_id or ""
        round_num = float(sum(1 for m in negotiation_history if m.get("sender") == agent_id))
        observation[0, base + node_types + 1] = min(1.0, round_num / _EPISODE_LENGTH)

        # 17: request_duration_norm
        duration_hours = 0.0
        if isinstance(order_dict, dict):
            duration_hours = float(order_dict.get("duration_hours") or 0)
        observation[0, base + node_types + 2] = min(1.0, duration_hours / 168.0)

        # 18: negotiation_count_norm
        observation[0, base + node_types + 3] = min(1.0, round_num / _REQUEST_TIMEOUT)

        # 19: price_ratio
        event_data = context.event.data or {} if context.event else {}
        their_price = event_data.get("proposed_price")
        our_initial_price = thread_info.get("our_initial_price") if thread_info else None
        if their_price is not None and our_initial_price and float(our_initial_price) > 0:
            price_ratio = float(their_price) / float(our_initial_price)
            observation[0, base + node_types + 4] = min(2.0, max(0.0, price_ratio))

        # 20: prev_reward — zeroed

        return observation

    except Exception as exc:
        logger.error("[ARKHAI COMMON] Failed to build negotiation observation: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Action extraction from model output
# ---------------------------------------------------------------------------

def extract_actions_from_logits(output: Any) -> tuple[int, int]:
    """Extract (price_idx, sell_flag) from puffer policy outputs."""
    if torch is None:
        return 4, 0

    try:
        if not isinstance(output, tuple) or len(output) != 2:
            logger.warning("[ARKHAI COMMON] Unexpected model output type: %s", type(output))
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

        logger.warning("[ARKHAI COMMON] Could not parse action logits; using defaults")
        return 4, 0
    except Exception as exc:
        logger.error("[ARKHAI COMMON] Failed parsing actions: %s", exc)
        return 4, 0


