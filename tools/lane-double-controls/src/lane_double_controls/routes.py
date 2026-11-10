"""Where the lane doubles' control routes sit, and how a caller is admitted to them.

Every control route is under ``/test/`` on its double's own API port, which a
lane never publishes to its host, and every one is authenticated by the double's
control bearer token. The declarations are the one statement of each route: a
double serving them registers its handlers from them and the typed client builds
its requests from them, so the two cannot disagree on a path or a method.
"""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from urllib.parse import quote

from lane_double_controls.models import ControlError, Double

CONTROL_PREFIX = "/test"
#: Each double's unauthenticated liveness route, which an orchestrator probes.
HEALTH_PATH = "/health"

_BOTH: frozenset[Double] = frozenset({"payments", "mediation"})
_PAYMENTS: frozenset[Double] = frozenset({"payments"})
_MEDIATION: frozenset[Double] = frozenset({"mediation"})
_PARAMETER = re.compile(r"\{([a-z_]+)\}")
# The scheme name is case-insensitive (RFC 7235); a token holds no whitespace.
_BEARER = re.compile(r"^bearer (\S+)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ControlRoute:
    """One control route: its method, its path template, and the doubles serving it."""

    method: str
    path: str
    doubles: frozenset[Double]

    def url(self, **parameters: str) -> str:
        """The route's path with each ``{name}`` replaced by its escaped value."""

        names = _PARAMETER.findall(self.path)
        if sorted(names) != sorted(parameters):
            raise ValueError(f"{self.path} takes {names}, not {sorted(parameters)}")
        return _PARAMETER.sub(lambda match: quote(parameters[match.group(1)], safe=""),
                              self.path)


RULES = ControlRoute("POST", "/test/rules", _BOTH)
RULE_LIST = ControlRoute("GET", "/test/rules", _BOTH)
RULE_DELETE = ControlRoute("DELETE", "/test/rules/{rule_id}", _BOTH)
RULE_RESUME = ControlRoute("POST", "/test/rules/{rule_id}/resume", _MEDIATION)
CLOCK_ADVANCE = ControlRoute("POST", "/test/clock/advance", _BOTH)
CLOCK_RESET = ControlRoute("POST", "/test/clock/reset", _BOTH)
STATUS = ControlRoute("GET", "/test/status", _BOTH)
FUNDING = ControlRoute("POST", "/test/funding", _PAYMENTS)
SIGNER_ROTATE = ControlRoute("POST", "/test/signer/rotate", _PAYMENTS)
CASE_LIST = ControlRoute("GET", "/test/cases", _MEDIATION)
CASE_DECIDE = ControlRoute("POST", "/test/cases/{case_ref}/decide", _MEDIATION)
CASE_CLOSE = ControlRoute("POST", "/test/cases/{case_ref}/close", _MEDIATION)

ROUTES: tuple[ControlRoute, ...] = (
    RULES, RULE_LIST, RULE_DELETE, RULE_RESUME, CLOCK_ADVANCE, CLOCK_RESET, STATUS,
    FUNDING, SIGNER_ROTATE, CASE_LIST, CASE_DECIDE, CASE_CLOSE,
)


def routes_for(double: Double) -> tuple[ControlRoute, ...]:
    """The control routes ``double`` serves."""

    return tuple(route for route in ROUTES if double in route.doubles)


def is_control_path(path: str) -> bool:
    """Whether ``path`` is a control route's."""

    return path == CONTROL_PREFIX or path.startswith(f"{CONTROL_PREFIX}/")


def is_contract_path(path: str) -> bool:
    """Whether ``path`` may be a contract API route, the only routes a fault applies to.

    Control routes keep answering so a finaliser can remove a fault. The health
    route keeps answering because an orchestrator probes it: a Helm release's
    liveness probe failing under *unavailable* would restart the double and lose
    every deal's state, which no outage of the real service does.
    """

    return path != HEALTH_PATH and not is_control_path(path)


def authorize(authorization: str | None, token: str) -> None:
    """Admit a control call bearing ``token``, else refuse it ``401 authentication_required``."""

    match = _BEARER.fullmatch(authorization or "")
    if match is None or not hmac.compare_digest(match.group(1).encode(), token.encode()):
        raise ControlError(401, "authentication_required",
                           "a control call needs the double's control bearer token")


__all__ = [
    "CASE_CLOSE",
    "CASE_DECIDE",
    "CASE_LIST",
    "CLOCK_ADVANCE",
    "CLOCK_RESET",
    "CONTROL_PREFIX",
    "ControlRoute",
    "FUNDING",
    "HEALTH_PATH",
    "ROUTES",
    "RULES",
    "RULE_DELETE",
    "RULE_LIST",
    "RULE_RESUME",
    "SIGNER_ROTATE",
    "STATUS",
    "authorize",
    "is_contract_path",
    "is_control_path",
    "routes_for",
]
