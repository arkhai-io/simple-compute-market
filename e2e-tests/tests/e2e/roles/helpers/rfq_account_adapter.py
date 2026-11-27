"""Synthetic account authority serving browser sessions and CLI credentials."""

from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
from secrets import compare_digest, token_urlsafe
from threading import Lock, Thread

import httpx
from market_core.rfq import (
    RfqAccountClaim, RfqAccountRequest, RfqAudience, RfqOperation, RfqTarget,
)
from market_identity import Signer
from pydantic import ValidationError
from registry_client.rfq_public import SyncRfqPublicRegistryClient
from registry_client.rfq_registry import RfqRegistryReply, SyncRfqRegistryClient

_MAX_BODY = 262144
_REFERENCE = r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}"
_REFERENCES = ("rfq_id", "response_id", "introduction_id")


def _route_pattern(operation: RfqOperation) -> re.Pattern[str]:
    path = re.escape(operation.route)
    for reference in _REFERENCES:
        path = path.replace(re.escape("{" + reference + "}"), f"(?P<{reference}>{_REFERENCE})")
    return re.compile(path)


_ROUTES = {operation: _route_pattern(operation) for operation in RfqOperation}


def _target(path: str) -> RfqTarget | None:
    for operation, pattern in _ROUTES.items():
        match = pattern.fullmatch(path)
        if match:
            return RfqTarget(operation, **match.groupdict())
    return None


def _failure(status: HTTPStatus, code: str) -> RfqRegistryReply:
    return RfqRegistryReply(status.value, {"detail": code}, {})


@dataclass(frozen=True)
class Credential:
    token: str = field(repr=False)
    account: RfqAccountClaim
    csrf: str | None = field(default=None, repr=False)


class BrowserSessionTransport(httpx.HTTPTransport):
    """Exercise the typed client through the adapter's cookie session and CSRF gates."""

    def __init__(self, session: Credential):
        super().__init__()
        if session.csrf is None:
            raise ValueError("a browser session is required")
        self._session = session
        self._csrf = session.csrf

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        request.headers.pop("Authorization", None)
        request.headers["Cookie"] = f"rfq_session={self._session.token}"
        request.headers["X-CSRF-Token"] = self._csrf
        return super().handle_request(request)


def _registry_key(audience: RfqAudience) -> tuple[str, str, str]:
    return audience.name, audience.principal.scheme, audience.principal.identifier


class AccountAuthority:
    def __init__(
        self, *, signer: Signer, namespace: str, registries: Iterable[tuple[RfqAudience, str]],
        registry_transport: httpx.BaseTransport | None = None,
    ):
        self._signer = signer
        self._namespace = namespace
        self._registries: dict[tuple[str, str, str], str] = {}
        for audience, url in registries:
            if self._registries.setdefault(_registry_key(audience), url) != url:
                raise ValueError("one URL per RFQ registry audience is required")
        self._registry_transport = registry_transport
        self._bearer: dict[str, Credential] = {}
        self._sessions: dict[str, Credential] = {}
        self._drop_ack: set[str] = set()
        self._lock = Lock()

    def issue(self, subject: str, *, can_share_contact: bool, browser: bool = False) -> Credential:
        account = RfqAccountClaim(
            namespace=self._namespace, subject=subject, can_share_contact=can_share_contact,
        )
        credential = Credential(token_urlsafe(24), account, token_urlsafe(24) if browser else None)
        with self._lock:
            credentials = self._sessions if browser else self._bearer
            credentials[credential.token] = credential
        return credential

    def revoke(self, credential: Credential) -> None:
        with self._lock:
            credentials = self._sessions if credential.csrf is not None else self._bearer
            credentials.pop(credential.token, None)

    def revoke_sharing(self, credential: Credential) -> None:
        with self._lock:
            current = self._bearer[credential.token]
            account = current.account.model_copy(update={"can_share_contact": False})
            self._bearer[credential.token] = replace(current, account=account)

    def drop_next_acknowledgement(self, path: str) -> None:
        """Simulate a lost reply after the registry accepts the operation."""
        with self._lock:
            self._drop_ack.add(path)

    def should_drop(self, path: str, reply: RfqRegistryReply) -> bool:
        with self._lock:
            if reply.status == HTTPStatus.OK and path in self._drop_ack:
                self._drop_ack.remove(path)
                return True
            return False

    def _credential(self, headers: Mapping[str, str]) -> Credential | None:
        authorization = headers.get("Authorization", "")
        with self._lock:
            if authorization:
                scheme, _, token = authorization.partition(" ")
                return self._bearer.get(token) if scheme.lower() == "bearer" else None
            try:
                session = SimpleCookie(headers.get("Cookie", "")).get("rfq_session")
            except CookieError:
                return None
            return None if session is None else self._sessions.get(session.value)

    def dispatch(self, path: str, headers: Mapping[str, str], body: bytes) -> RfqRegistryReply:
        target = _target(path)
        if target is None:
            return _failure(HTTPStatus.NOT_FOUND, "Not Found")
        credential = self._credential(headers)
        allows_open_read = target.operation in {RfqOperation.SEARCH, RfqOperation.READ}
        if credential is None and (not allows_open_read or "Authorization" in headers or "Cookie" in headers):
            return _failure(HTTPStatus.UNAUTHORIZED, "rfq_auth_required")
        csrf = headers.get("X-CSRF-Token", "")
        if credential is not None and credential.csrf is not None and not target.operation.is_read:
            if not csrf.isascii() or not compare_digest(csrf, credential.csrf):
                return _failure(HTTPStatus.FORBIDDEN, "rfq_csrf_required")
        try:
            request = RfqAccountRequest.model_validate_json(body)
        except ValidationError:
            return _failure(HTTPStatus.UNPROCESSABLE_ENTITY, "rfq_invalid_request")
        url = self._registries.get(_registry_key(request.registry))
        if url is None:
            return _failure(HTTPStatus.FORBIDDEN, "rfq_registry_audience_refused")
        if credential is not None and target.operation.shares_contact and not credential.account.can_share_contact:
            return _failure(HTTPStatus.FORBIDDEN, "rfq_contact_permission_required")
        try:
            if credential is None:
                with SyncRfqPublicRegistryClient(
                    url, audience=request.registry, transport=self._registry_transport,
                ) as registry:
                    return registry.forward(target, request)
            with SyncRfqRegistryClient(
                url, signer=self._signer, audience=request.registry, transport=self._registry_transport,
            ) as registry:
                return registry.forward(target, credential.account, request)
        except ValidationError:
            return _failure(HTTPStatus.UNPROCESSABLE_ENTITY, "rfq_invalid_request")
        except (ValueError, httpx.TransportError):
            return _failure(HTTPStatus.BAD_GATEWAY, "rfq_registry_unavailable")


@contextmanager
def serve_account_authority(authority: AccountAuthority) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            try:
                content_length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                content_length = 0
            if not 0 < content_length <= _MAX_BODY or self.headers.get("Transfer-Encoding"):
                reply = _failure(HTTPStatus.BAD_REQUEST, "rfq_invalid_request")
            else:
                reply = authority.dispatch(self.path, self.headers, self.rfile.read(content_length))
            if authority.should_drop(self.path, reply):
                self.close_connection = True
                return
            response = json.dumps(reply.body, separators=(",", ":"), ensure_ascii=False).encode()
            self.send_response(reply.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.send_header("Cache-Control", "no-store")
            for name, value in reply.proof.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format: str, *args: object) -> None:
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            worker.join()
