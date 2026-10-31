"""A registry's bearer token reaches that registry, beside the signature.

A registry that gates writes needs the storefront's bearer token on every
request, in addition to the storefront's signature. These tests read what
actually reaches each registry: publication's writes through the composed
fan-out, and status's signed health read. Publication's fan-out opens its own
HTTP clients, so its registries here are local HTTP servers that record the
headers each request carries, on loopback; status's reads go through an
injected transport. Every registry answers unsigned, so each client refuses
the reply; what is asserted is the request it sent.

The level is integration of the registry clients the storefront composes
against stand-in registries at their HTTP boundary. Every URL, key, and token
here is a development fixture, never to be used on a public network.
"""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from core_storefront.multi_registry_client import RegistryAuthorityTrust
from market_identity import TrustedIdentitySet

from arkhai_bare_metal_storefront.publication_service import BareMetalRegistryConfiguration
from storefront_configuration import REGISTRY, SELLER

#: Development-only token; it authorizes nothing anywhere.
TOKEN = "dev-only-registry-token-not-a-secret"
SIGNATURE = "X-Market-Signature"

TRUST = RegistryAuthorityTrust(
    authority="registry",
    principals=TrustedIdentitySet(identities=(REGISTRY.identity,)),
)


class _Registry:
    """A loopback registry that records each request's headers and answers 503."""

    def __init__(self) -> None:
        seen: list[dict[str, str]] = []

        class Handler(BaseHTTPRequestHandler):
            def _answer(self) -> None:
                seen.append({k.lower(): v for k, v in self.headers.items()})
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _answer

            def log_message(self, *args) -> None:
                pass

        self.seen = seen
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "_Registry":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()


def _delete_everywhere(configuration: BareMetalRegistryConfiguration) -> list:
    async def run():
        async with configuration.client_factory(SELLER)() as client:
            return await client.delete_listing_per_registry(
                listing_id="00000000-0000-0000-0000-000000000000",
                registry_urls=list(configuration.urls),
            )

    return asyncio.run(run())


def test_publication_sends_each_registry_its_own_token_beside_the_signature(caplog) -> None:
    caplog.set_level("DEBUG")
    with _Registry() as gated, _Registry() as open_registry:
        configuration = BareMetalRegistryConfiguration(
            authorities={gated.url: TRUST, open_registry.url: TRUST},
            auth={gated.url: TOKEN},
        )

        results = _delete_everywhere(configuration)

    assert [result["registry_url"] for result in results] == [gated.url, open_registry.url]
    assert gated.seen and open_registry.seen
    assert {request.get("authorization") for request in gated.seen} == {f"Bearer {TOKEN}"}
    assert all("authorization" not in request for request in open_registry.seen)
    # The token is sent beside the signature, never in its place.
    assert all(SIGNATURE.lower() in request for request in gated.seen + open_registry.seen)
    # A refused reply's reported error, and every log line, never carries it.
    assert all(TOKEN not in (result["error"] or "") for result in results)
    assert TOKEN not in caplog.text


def test_publication_sends_no_authorization_without_a_token() -> None:
    with _Registry() as registry:
        _delete_everywhere(BareMetalRegistryConfiguration(authorities={registry.url: TRUST}))

    assert registry.seen
    assert all("authorization" not in request for request in registry.seen)
    assert all(SIGNATURE.lower() in request for request in registry.seen)


def test_status_reads_each_registry_with_its_own_token() -> None:
    sent: dict[str, httpx.Request] = {}

    def answer(request: httpx.Request) -> httpx.Response:
        sent[request.url.host] = request
        return httpx.Response(503, text="down")

    transport = httpx.MockTransport(answer)
    for host, auth in (("registry-gated", {"http://registry-gated": TOKEN}), ("registry-open", {})):
        configuration = BareMetalRegistryConfiguration(
            authorities={f"http://{host}": TRUST}, auth=auth
        )
        result = asyncio.run(configuration.reachability(SELLER, transport=transport))
        assert TOKEN not in result

    assert sent["registry-gated"].headers.get("authorization") == f"Bearer {TOKEN}"
    assert "authorization" not in sent["registry-open"].headers
    assert all(SIGNATURE in request.headers for request in sent.values())


def test_status_finds_a_token_however_its_url_is_spelled() -> None:
    """Status looks a token up by normalized URL, as publication's fan-out does,
    so a key spelled with another case or a trailing slash still reaches its
    registry."""
    sent: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(503, text="down")

    configuration = BareMetalRegistryConfiguration(
        authorities={"http://registry-gated": TRUST},
        auth={"HTTP://Registry-Gated/": TOKEN},
    )

    result = asyncio.run(
        configuration.reachability(SELLER, transport=httpx.MockTransport(answer))
    )

    assert result == "http_502"
    assert [request.headers.get("authorization") for request in sent] == [f"Bearer {TOKEN}"]
    assert SIGNATURE in sent[0].headers


def test_the_configuration_never_shows_its_tokens() -> None:
    configuration = BareMetalRegistryConfiguration(
        authorities={"http://registry-gated": TRUST}, auth={"http://registry-gated": TOKEN}
    )

    assert TOKEN not in repr(configuration)
    assert TOKEN not in str(configuration)
