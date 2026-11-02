"""Authenticated, stateless HTTP operations at an Agreement-pinned authority."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import ipaddress
import os
import re
from typing import Any, TypeVar
from urllib.parse import quote, urlsplit

import httpx
from jsonschema.exceptions import ValidationError as SchemaValidationError
from market_deal_lifecycle.terms import DisputeAuthority
from pydantic import BaseModel, ValidationError

from .contract import validate, wire
from .models import Append, AppendAnswer, CaseAnswer, Filing, FilingAnswer, ReadAfter, RecordPage, RespondentAfter, RespondentPage, SignedRecordEntry
from .records import verify_record

ModelT = TypeVar("ModelT", bound=BaseModel)
KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class MediationError(Exception):
    """A mediation boundary could not be completed safely."""


class MediationTransportError(MediationError):
    pass


class MediationProtocolError(MediationError):
    pass


class MediationAPIError(MediationError):
    def __init__(self, status: int, code: str):
        self.status = status
        self.code = code
        super().__init__(f"mediation returned HTTP {status}: {code}")


@dataclass(frozen=True)
class MediationCredential:
    """A credential reference bound to the authority's entire pinned identity."""

    identity: tuple[str, str, str, str]
    api_key_env: str


class MediationClient:
    def __init__(
        self, authority: DisputeAuthority, credential: MediationCredential, *,
        environ: Mapping[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        capture: Callable[[bytes], None] | None = None,
        timeout: float = 10,
    ):
        validate("DisputeAuthority", authority.model_dump(mode="json"))
        if authority.identity != credential.identity:
            raise ValueError("mediation credential is bound to another authority")
        token = (os.environ if environ is None else environ).get(credential.api_key_env)
        if not token or token != token.strip() or "\r" in token or "\n" in token:
            raise ValueError("mediation credential environment reference is unavailable")
        url = urlsplit(authority.origin)
        if url.scheme != "https" and not _loopback(url.hostname or ""):
            raise ValueError("mediation requires HTTPS outside loopback")
        self.authority = authority.model_copy(deep=True)
        self._capture = capture
        self._http = httpx.AsyncClient(
            base_url=authority.origin, headers={"Authorization": "Bearer " + token},
            timeout=timeout, transport=transport, follow_redirects=False,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()

    async def file(self, filing: Filing, *, idempotency_key: str) -> FilingAnswer:
        return await self._request(
            FilingAnswer, "FilingAnswer", "POST", "/cases",
            json=_validated("Filing", filing), headers=_key_header(idempotency_key),
        )

    async def append(
        self, append: Append, *, idempotency_key: str, agreement: str, transaction: str,
    ) -> AppendAnswer:
        answer = await self._request(
            AppendAnswer, "AppendAnswer", "POST", "/append",
            json=_validated("Append", append), headers=_key_header(idempotency_key),
        )
        raw = wire(answer)
        if raw["status"] == "accepted":
            verify_record(
                SignedRecordEntry.model_validate(raw["record"]), record_key=self.authority.record_key,
                agreement=agreement, transaction=transaction, case_ref=wire(append)["case_ref"],
            )
            entry = raw["record"]["entry"]
            submitted = wire(append)
            if (entry["kind"] != "appended" or entry["items"] != submitted.get("items", [])
                    or entry.get("concurrence") != submitted.get("concurrence")):
                raise MediationProtocolError("append acknowledgement differs from the submitted items")
        return answer

    async def case(self, case_ref: str, *, agreement: str, transaction: str) -> CaseAnswer:
        validate("CaseRef", case_ref)
        # Opaque case references are a path segment, never a path supplied by a caller.
        from_path = httpx.URL("/cases/").copy_with(raw_path=b"/cases/" + _segment(case_ref))
        answer = await self._request(CaseAnswer, "CaseAnswer", "GET", str(from_path))
        raw = wire(answer)
        if (raw["case_ref"], raw["agreement"], raw["transaction"]) != (case_ref, agreement, transaction):
            raise MediationProtocolError("case answer names another deal")
        return answer

    async def read_record(self, request: ReadAfter, *, transaction: str) -> RecordPage:
        query = _validated("ReadAfter", request)
        page = await self._request(RecordPage, "RecordPage", "GET", "/record", params=query)
        expected = request.after
        if page.agreement.root != request.agreement.root:
            raise MediationProtocolError("record page names another Agreement")
        if len(page.entries) > (request.limit or 1000):
            raise MediationProtocolError("record page exceeds the requested bound")
        for signed in page.entries:
            expected += 1
            verify_record(
                signed, record_key=self.authority.record_key, agreement=request.agreement.root,
                transaction=transaction, sequence=expected,
            )
        if page.next_after != expected or page.has_more and not page.entries:
            raise MediationProtocolError("record cursor is not contiguous or makes no progress")
        return page

    async def respondent(self, request: RespondentAfter) -> RespondentPage:
        page = await self._request(
            RespondentPage, "RespondentPage", "GET", "/respondent",
            params=_validated("RespondentAfter", request),
        )
        if len(page.cases) > (request.limit or 100):
            raise MediationProtocolError("respondent page exceeds the requested bound")
        refs = [case.case_ref.root for case in page.cases]
        if len(refs) != len(set(refs)):
            raise MediationProtocolError("respondent page repeats a case")
        if page.has_more and (not page.cases or page.next_after == request.after):
            raise MediationProtocolError("respondent cursor makes no progress")
        return page

    async def _request(
        self, model: type[ModelT], definition: str, method: str, path: str, **kwargs: Any,
    ) -> ModelT:
        try:
            response = await self._http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise MediationTransportError("mediation transport result is unknown") from exc
        if self._capture is not None:
            self._capture(response.content)
        if response.status_code != 200:
            code = "http_error"
            try:
                candidate = response.json().get("code")
                if isinstance(candidate, str) and KEY.fullmatch(candidate):
                    code = candidate
            except (ValueError, AttributeError):
                pass
            raise MediationAPIError(response.status_code, code)
        try:
            value = response.json()
            validate(definition, value)
            return model.model_validate(value)
        except (ValueError, ValidationError, SchemaValidationError) as exc:
            raise MediationProtocolError("mediation response violates its contract") from exc


def _validated(name: str, model: BaseModel) -> dict[str, Any]:
    return validate(name, wire(model))


def _key_header(key: str) -> dict[str, str]:
    if not KEY.fullmatch(key):
        raise ValueError("invalid mediation idempotency key")
    return {"Idempotency-Key": key}


def _segment(value: str) -> bytes:
    return quote(value, safe="").replace(".", "%2E").encode("ascii")


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
