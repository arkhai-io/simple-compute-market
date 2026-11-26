"""The admission core's settings, composed into each authority's own as
``authenticated_requests``."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_RETENTION_SECONDS = 86_400
DEFAULT_PRUNE_INTERVAL_SECONDS = 86_400

_PositiveSeconds = Annotated[int, Field(strict=True, gt=0)]


class AuthenticatedRequestsSettings(BaseModel):
    """How long recorded outcomes answer exact retries, and how often expired
    replay rows are swept.

    ``recorded_outcome_retention_seconds`` counts from a request's origin, its
    first signing instant; past it, an exact retry of a recorded route is answered
    expired. ``replay_prune_interval_seconds`` is the time between sweeps after
    the one at startup. Each is a positive integer, 24 hours when absent.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    recorded_outcome_retention_seconds: _PositiveSeconds = DEFAULT_RETENTION_SECONDS
    replay_prune_interval_seconds: _PositiveSeconds = DEFAULT_PRUNE_INTERVAL_SECONDS
