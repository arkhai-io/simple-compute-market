"""The typed client of a lane double's control routes.

A caller drives a double's controls through this client. It authenticates with
the double's control token, trusts the CA bundle it is given alone when it is
given one, and raises every refusal as ``ControlError`` with the double's control
code, so a caller branches on the code and never on a status or a body. A transport failure is httpx's own error: a control call that cannot reach
its double is a broken lane, not an answer.
"""

from __future__ import annotations

import ssl
from types import TracebackType
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from lane_double_controls import routes
from lane_double_controls.models import (
    CaseList,
    CaseView,
    ClockAdvance,
    ClockView,
    ControlError,
    ControlErrorBody,
    Funded,
    Funding,
    Rule,
    RuleList,
    RuleView,
    Ruling,
    SignerIdentity,
    Status,
)

_Answer = TypeVar("_Answer", bound=BaseModel)


class ControlClient:
    """Calls one double's control routes.

    ``base_url`` is the double's API origin, such as
    ``https://payments-double:8443``. ``transport`` replaces the network, for a
    test driving an in-process app.
    """

    def __init__(self, base_url: str, *, token: str, ca_bundle_path: str | None = None,
                 transport: httpx.BaseTransport | None = None, timeout: float = 10.0) -> None:
        verify: ssl.SSLContext | bool = (
            ssl.create_default_context(cafile=ca_bundle_path) if ca_bundle_path else True)
        self._http = httpx.Client(
            base_url=base_url, transport=transport, verify=verify, timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
            # A lane-private service name must never be sent through a proxy the
            # runner's environment names.
            trust_env=False,
        )

    def __enter__(self) -> ControlClient:
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def install_rule(self, rule: Rule) -> RuleView:
        return self._call(routes.RULES, RuleView, body=rule)

    def rules(self) -> RuleList:
        return self._call(routes.RULE_LIST, RuleList)

    def delete_rule(self, rule_id: str) -> None:
        self._send(routes.RULE_DELETE, rule_id=rule_id)

    def resume_rule(self, rule_id: str) -> RuleView:
        return self._call(routes.RULE_RESUME, RuleView, rule_id=rule_id)

    def advance_clock(self, seconds: int) -> ClockView:
        return self._call(routes.CLOCK_ADVANCE, ClockView, body=ClockAdvance(seconds=seconds))

    def reset_clock(self) -> ClockView:
        return self._call(routes.CLOCK_RESET, ClockView)

    def status(self) -> Status:
        return self._call(routes.STATUS, Status)

    def fund(self, account: str, amount: int) -> Funded:
        return self._call(routes.FUNDING, Funded,
                          body=Funding(account=account, amount=str(amount)))

    def rotate_signer(self) -> SignerIdentity:
        return self._call(routes.SIGNER_ROTATE, SignerIdentity)

    def cases(self, transaction: str) -> CaseList:
        return self._call(routes.CASE_LIST, CaseList, params={"transaction": transaction})

    def decide(self, case_ref: str, ruling: Ruling) -> CaseView:
        return self._call(routes.CASE_DECIDE, CaseView, body=ruling, case_ref=case_ref)

    def close_case(self, case_ref: str) -> CaseView:
        return self._call(routes.CASE_CLOSE, CaseView, case_ref=case_ref)

    def _call(self, route: routes.ControlRoute, answer: type[_Answer], *,
              body: BaseModel | None = None, params: dict[str, str] | None = None,
              **path: str) -> _Answer:
        return answer.model_validate(self._send(route, body=body, params=params, **path).json())

    def _send(self, route: routes.ControlRoute, *, body: BaseModel | None = None,
              params: dict[str, str] | None = None, **path: str) -> httpx.Response:
        response = self._http.request(
            route.method, route.url(**path), params=params,
            json=None if body is None else body.model_dump(mode="json", exclude_none=True))
        if response.is_error:
            raise _refusal(response)
        return response


def _refusal(response: httpx.Response) -> ControlError:
    try:
        body = ControlErrorBody.model_validate(response.json())
    except (ValueError, ValidationError):
        # Not a control refusal at all, such as a proxy's page: keep the status,
        # and say the body was not the controls' own.
        return ControlError(response.status_code, "unexpected_response",
                            f"the double answered {response.status_code} without a control error")
    return ControlError(response.status_code, body.code, body.message)


__all__ = ["ControlClient"]
