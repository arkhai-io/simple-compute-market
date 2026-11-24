"""Where the lane doubles' control routes sit, and how a caller is admitted to them.

Every control route is under ``/test/`` on its party's own API port, and every
one is authenticated by the party's control bearer token; a lane publishes no
double's port to its host, while the sample app's is its published API port.
The declarations are the one statement of each route: a party serving them
registers its handlers from them and the typed client builds its requests from
them, so the two cannot disagree on a path or a method. The time route is
served only by a party whose time is injected, as a wall-time instance offers no
way to change its time.
"""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from urllib.parse import quote

from lane_double_controls.models import ControlError, ControlParty

CONTROL_PREFIX = "/test"
#: Each double's unauthenticated liveness route, which an orchestrator probes.
HEALTH_PATH = "/health"

_EVERY: frozenset[ControlParty] = frozenset({"payments", "mediation", "sample-app"})
_BOTH: frozenset[ControlParty] = frozenset({"payments", "mediation"})
_PAYMENTS: frozenset[ControlParty] = frozenset({"payments"})
_MEDIATION: frozenset[ControlParty] = frozenset({"mediation"})
_PARAMETER = re.compile(r"\{([a-z_]+)\}")
# The scheme name is case-insensitive (RFC 7235); a token holds no whitespace.
_BEARER = re.compile(r"^bearer (\S+)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ControlRoute:
    """One control route: its method, its path template, and the parties serving it."""

    method: str
    path: str
    parties: frozenset[ControlParty]

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
TIME = ControlRoute("POST", "/test/time", _EVERY)
STATUS = ControlRoute("GET", "/test/status", _EVERY)
FUNDING = ControlRoute("POST", "/test/funding", _PAYMENTS)
SIGNER_ROTATE = ControlRoute("POST", "/test/signer/rotate", _PAYMENTS)
RESERVE = ControlRoute("POST", "/test/transactions/{transaction}/reserve", _PAYMENTS)
CASE_LIST = ControlRoute("GET", "/test/cases", _MEDIATION)
CASE_DECIDE = ControlRoute("POST", "/test/cases/{case_ref}/decide", _MEDIATION)
CASE_CLOSE = ControlRoute("POST", "/test/cases/{case_ref}/close", _MEDIATION)

ROUTES: tuple[ControlRoute, ...] = (
    RULES, RULE_LIST, RULE_DELETE, RULE_RESUME, TIME, STATUS,
    FUNDING, SIGNER_ROTATE, RESERVE, CASE_LIST, CASE_DECIDE, CASE_CLOSE,
)


def routes_for(party: ControlParty, *, time_settable: bool) -> tuple[ControlRoute, ...]:
    """The control routes ``party`` serves: the time route only if its time is settable."""

    return tuple(route for route in ROUTES
                 if party in route.parties and (time_settable or route is not TIME))


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
    "CONTROL_PREFIX",
    "ControlRoute",
    "FUNDING",
    "HEALTH_PATH",
    "RESERVE",
    "ROUTES",
    "RULES",
    "RULE_DELETE",
    "RULE_LIST",
    "RULE_RESUME",
    "SIGNER_ROTATE",
    "STATUS",
    "TIME",
    "authorize",
    "is_contract_path",
    "is_control_path",
    "routes_for",
]
