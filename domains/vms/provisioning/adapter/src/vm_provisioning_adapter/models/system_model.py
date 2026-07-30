"""Server-only models for the system diagnostics and test controllers.

File naming: ``_model`` suffix marks this as a model definition file.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class EvaluateJobRequest(BaseModel):
    """Body for POST /test/evaluate-job."""
    host: str
    vm_target: str = "eval-target"
    ssh_pubkey: Optional[str] = None
    vm_action: str = "create"


class EvaluateJobResponse(BaseModel):
    """Response from POST /test/evaluate-job."""
    params_valid: bool
    host_exists: bool
    rule_matched: Optional[str] = None
    would_pause: bool = False
    errors: list[str] = []
