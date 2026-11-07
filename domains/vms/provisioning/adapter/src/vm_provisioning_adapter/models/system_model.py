"""Server-only model of the VM job the evaluate-job dry run describes.

A job's parameters are VM's, so the request is VM's own; the dry run's report
is the compute family's ``MockJobEvaluation``.

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
