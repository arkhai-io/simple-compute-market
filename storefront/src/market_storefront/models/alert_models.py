"""HTTP request/response models for the Alerts controller.

ResourceAlertRequest lives in domain_models (it is also used to build
domain events); re-exported here for controller import convenience.
"""
from __future__ import annotations

from pydantic import BaseModel


class ResourceAlertResponse(BaseModel):
    root_agent_response: str
