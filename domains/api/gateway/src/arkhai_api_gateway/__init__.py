"""The api family's gateway in front of an OpenAI-style model server; it imports no domain."""

from .app import INVALID_REQUEST, MODEL_NOT_FOUND, create_gateway_app
from .offering import GatewayOffering, read_upstream_credential
from .proxy import UPSTREAM_UNAVAILABLE
from .verification import VerificationHook, VerificationRefusal, admit_all

__all__ = [
    "INVALID_REQUEST",
    "MODEL_NOT_FOUND",
    "UPSTREAM_UNAVAILABLE",
    "GatewayOffering",
    "VerificationHook",
    "VerificationRefusal",
    "admit_all",
    "create_gateway_app",
    "read_upstream_credential",
]
