"""Resource-free authority admission and ordered preference before commitment."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from .configuration import DisputeEntry, NO_DISPUTE_AUTHORITIES
from .terms import TermContext, decode_terms, validate_terms


class AuthoritySelection:
    """An injected option preference; no authority is fetched or constructed here.

    Contexts declare the installed payment capabilities and dispute interfaces.
    The owning buyer composition supplies them, along with registry-local policy.
    A rank of None refuses the option; lower ranks prefer accepted authorities.
    """

    def __init__(
        self, authorities_by_registry: Mapping[str, tuple[DisputeEntry, ...]], *,
        contexts: Mapping[str, TermContext], report: Callable[[str], None] = lambda _: None,
    ) -> None:
        self.authorities = {url.rstrip("/"): tuple(entries) for url, entries in authorities_by_registry.items()}
        self.contexts = dict(contexts)
        self.report = report

    def rank(self, mechanism: str, lifecycle: object, *, registry_url: str = "") -> int:
        context = self.contexts.get(mechanism, TermContext(mechanism=mechanism, has_adapter=False))
        if context.mechanism != mechanism:
            raise ValueError("selection context names another mechanism")
        if not context.has_adapter:
            validate_terms(lifecycle, context)
            return 0
        terms = decode_terms(lifecycle)
        if terms is None:
            raise ValueError("a lifecycle adapter requires adjudication")
        entries = self.authorities.get(registry_url.rstrip("/"), self.authorities.get("", ()))
        entries = tuple(entry for entry in entries if not entry.not_accepted)
        if not entries:
            raise ValueError(NO_DISPUTE_AUTHORITIES)
        dispute = terms.adjudication.dispute
        for index, entry in enumerate(entries):
            if entry.identity == dispute.identity and entry.params == dispute.params:
                validate_terms(lifecycle, replace(
                    context, buyer=True, authority=entry.requirements,
                    accepted_authorities=(entry.authority,),
                ))
                return index
        # Name changed fields without repeating an unaccepted endpoint or key.
        nearest = min(entries, key=lambda entry: sum(
            getattr(entry, field) != getattr(dispute, field)
            for field in ("interface", "origin", "account", "record_key", "params")
        ))
        changed = [field for field in ("interface", "origin", "account", "record_key", "params")
                   if getattr(nearest, field) != getattr(dispute, field)]
        raise ValueError("unaccepted dispute authority; mismatched " + ", ".join(changed))

    def __call__(self, option: Any, listing: Mapping[str, Any]) -> int | None:
        try:
            return self.rank(option.settlement_schema, option.lifecycle,
                             registry_url=str(listing.get("source_registry_url") or ""))
        except ValueError as exc:
            self.report(str(exc))
            return None
