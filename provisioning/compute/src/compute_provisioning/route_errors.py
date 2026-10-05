"""The one error a framework-free route service reports a refusal with.

A route service validates and performs a route without depending on a web
framework, so it cannot raise an HTTP exception. It raises this, carrying the
status a binding answers with and the detail it returns; each binding turns it
into its framework's response.
"""

from __future__ import annotations

from typing import Any


class ProvisioningRouteError(RuntimeError):
    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


__all__ = ["ProvisioningRouteError"]
