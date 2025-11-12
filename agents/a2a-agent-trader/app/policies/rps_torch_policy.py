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
from app.schema.pydantic_models import Action as DomainAction, ActionType, DecisionContext

logger = logging.getLogger(__name__)


_MODEL_PATH = Path(__file__).resolve().parent / "models" / "rps_policy.ts"
_loaded_model: Optional[Any] = None


def _get_model() -> Optional[Any]:
    """Lazily load the TorchScript RPS policy model."""
    if torch is None:
        logger.warning("[RPS POLICY] PyTorch not available; skipping model load")
        return None
    global _loaded_model
    if _loaded_model is not None:
        return _loaded_model

    if not _MODEL_PATH.exists():
        logger.warning("[RPS POLICY] TorchScript model not found at %s", _MODEL_PATH)
        return None

    try:
        _loaded_model = torch.jit.load(str(_MODEL_PATH))
        _loaded_model.eval()
        logger.info("[RPS POLICY] Loaded TorchScript model from %s", _MODEL_PATH)
    except Exception as exc:  # pragma: no cover - torch errors vary
        logger.error("[RPS POLICY] Failed to load TorchScript model: %s", exc)
        _loaded_model = None
    return _loaded_model


def _select_action(logits: Any) -> DomainAction:
    """Map model logits to a domain action."""
    if torch is None:
        return DomainAction(action_type=ActionType.ACCEPT_OFFER, parameters={})
    # Expect logits shape [batch, 3]; take first entry
    probs = torch.softmax(logits[0], dim=0)
    choice = int(torch.argmax(probs).item())

    if choice == 0:
        action_type = ActionType.REJECT_OFFER
    elif choice == 1:
        action_type = ActionType.ACCEPT_OFFER
    else:
        action_type = ActionType.COUNTER_OFFER

    return DomainAction(action_type=action_type)


@policy_callable("mo.action.rps_torch_offer")
def mo_action_rps_torch_offer(context: DecisionContext) -> DomainAction | None:
    """TorchScript-driven offer response conforming to make_offer composite standard.

    The proof-of-concept feeds a zero tensor into the TorchScript model and
    maps logits to ACCEPT/REJECT/COUNTER outcomes. In production, derive feature
    vectors from `context` instead of using the placeholder tensor.
    """
    event_type = getattr(context.event, "event_type", None)
    trigger = event_type.value if hasattr(event_type, "value") else str(event_type)
    if trigger != "make_offer":
        return None

    model = _get_model()
    if model is None or torch is None:
        logger.warning("[RPS POLICY] PyTorch not available; returning None")
        return None

    # TODO: Replace this with a real feature vector constructed from the context
    example_input = torch.zeros((1, 3), dtype=torch.float32)

    try:
        with torch.no_grad():
            logits = model(example_input)
    except Exception as exc:  # pragma: no cover - inference errors vary
        logger.error("[RPS POLICY] Inference failed: %s", exc)
        return None

    if logits is None or logits.shape[0] == 0:
        logger.warning("[RPS POLICY] Model returned empty logits")
        return None

    return _select_action(logits)
