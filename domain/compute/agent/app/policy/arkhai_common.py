"""Shared infrastructure for Arkhai policy adapters (seller and buyer).

Observation layout, model creation, checkpoint loading, and action extraction
are identical for both sides. Role-specific logic (accept/counter/reject
thresholds, model path, env var) lives in the role-specific modules.

Inference here does **not** depend on pufferlib. The trained checkpoints
were produced by ``pufferlib.models.Default(env_stub, hidden_size=128)``
in the non-Dict, MultiDiscrete branch — that architecture is a few
``nn.Linear`` layers with a GELU, reproducible inline (see
``ArkhaiInferencePolicy`` below). Outputs are bit-identical to the
pufferlib version on the existing ``.pt`` files.

Training still uses pufferlib's C env + trainer (``domain/compute/training/``);
runtime callers (storefront, buyer) only need torch.
"""
from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path
from typing import Any, Optional

from market_storefront.models.domain_models import GPUModel

try:  # Torch is optional at runtime; fail gracefully if unavailable.
    torch: Any = importlib.import_module("torch")
except Exception:  # pragma: no cover - environment-dependent
    torch = None


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inline inference-only port of pufferlib.models.Default
# ---------------------------------------------------------------------------
#
# State-dict compatible with checkpoints trained against
# ``pufferlib.models.Default(env_stub, hidden_size=128)`` for the
# (Box obs, MultiDiscrete([9, 2]) action) shape used by arkhai_negotiator_*.pt.
# Three nn.Linear layers + GELU; sum of action_nvec = 11 output logits split
# into two heads (price_idx ∈ {0..8}, sell_flag ∈ {0, 1}) plus a value head.

def _build_inference_policy(obs_dim_val: int) -> Optional[Any]:
    """Construct the inference model class lazily so this module imports
    cleanly when torch is absent (``policy_mode = bisection`` deployments).
    """
    if torch is None:
        return None

    import torch.nn as nn

    action_nvec = (9, 2)
    hidden_size = 128

    class ArkhaiInferencePolicy(nn.Module):
        action_nvec = (9, 2)

        def __init__(self) -> None:
            super().__init__()
            self.encoder = nn.Sequential(
                nn.Linear(obs_dim_val, hidden_size),
                nn.GELU(),
            )
            self.decoder = nn.Linear(hidden_size, sum(action_nvec))
            self.value = nn.Linear(hidden_size, 1)

        def forward(self, observations: Any) -> tuple[Any, Any]:
            batch = observations.shape[0]
            hidden = self.encoder(observations.float().view(batch, -1))
            logits = self.decoder(hidden).split(action_nvec, dim=1)
            values = self.value(hidden)
            return logits, values

    return ArkhaiInferencePolicy()


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
    """Build a fresh inference policy with random weights.

    The caller (``load_state_dict`` below) overwrites those weights from
    a checkpoint. Returns ``None`` if torch isn't installed — callers
    must handle that path (storefront falls back to bisection middleware).
    """
    return _build_inference_policy(obs_dim)


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


MAX_GPU = 10.0


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


