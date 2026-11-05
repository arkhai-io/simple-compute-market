"""Minimal common query projections owned by the lifecycle term codec."""

from types import MappingProxyType

from .terms import decode_terms

LIFECYCLE_QUERY_FIELDS = MappingProxyType({
    "adjudication.dispute.interface": "string",
    "adjudication.dispute.account": "string",
    "early_termination.payer": "boolean",
    "early_termination.payee": "boolean",
    "early_termination.payee.notice_seconds": "integer",
    "early_termination.premature_stop_penalty": "integer",
    "delivery_deadline_seconds": "integer",
})


def project_terms(value: object) -> dict[str, str | int | bool]:
    """Project valid terms; money is an integer in the same option's asset.

    An absent entitlement projects false, an absent penalty zero, and an unstated notice or
    delivery deadline is missing rather than a guessed duration.
    """
    terms = decode_terms(value)
    early = terms.early_termination if terms is not None else None
    entitlements = early.entitlements if early is not None else {}
    result: dict[str, str | int | bool] = {
        "early_termination.payer": "payer" in entitlements,
        "early_termination.payee": "payee" in entitlements,
        "early_termination.premature_stop_penalty": early.penalty if early else 0,
    }
    if terms is not None:
        result["adjudication.dispute.interface"] = terms.adjudication.dispute.interface
        result["adjudication.dispute.account"] = terms.adjudication.dispute.account
        if terms.delivery_deadline_seconds is not None:
            result["delivery_deadline_seconds"] = terms.delivery_deadline_seconds
    if "payee" in entitlements:
        result["early_termination.payee.notice_seconds"] = entitlements["payee"].notice_seconds
    return result
