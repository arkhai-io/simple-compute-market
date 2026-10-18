"""The storefront's administrator API, as its command line reaches it.

A command that operates the running storefront calls its administrator API
through the canonical storefront client and never reads or writes the
storefront's database. It signs as the storefront's own marketplace signer,
from ``[Identity.principal]`` in the configuration files the server reads and
``ARKHAI_IDENTITY_CREDENTIAL``, so that principal must be one of
``[Identity.administrators]``. It connects to ``--storefront-url``, else the
configured ``base_url``.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

import typer


def storefront_url(explicit: str | None, configured: str) -> str:
    """The flag, else the configured ``base_url``."""
    return (explicit or configured).rstrip("/")


@contextlib.contextmanager
def storefront_admin_client(explicit_url: str | None) -> Iterator[Any]:
    """The storefront client, signing as the storefront's administrator.

    Configuration that cannot be read, and a missing identity or credential,
    are refused as bad parameters before anything is sent.
    """
    # Imported here so the CLI's help and its commands that do not call the
    # storefront load none of the client, identity, or configuration stack.
    from market_identity import TrustedIdentitySet
    from storefront_client import SyncStorefrontClient

    from .config import (
        BareMetalConfigurationError,
        identity_credential,
        load_storefront_settings,
    )

    try:
        settings = load_storefront_settings()
    except BareMetalConfigurationError as exc:
        raise typer.BadParameter(str(exc)) from exc
    try:
        signer = settings.signer(identity_credential())
    except (KeyError, ValueError) as exc:
        raise typer.BadParameter(
            "the storefront identity ([Identity.principal]) and a matching "
            f"ARKHAI_IDENTITY_CREDENTIAL are required: {exc}"
        ) from exc
    with SyncStorefrontClient(
        storefront_url(explicit_url, settings.base_url),
        signer=signer,
        caller_role="admin",
        expected_publishers=TrustedIdentitySet(identities=(signer.identity,)),
    ) as client:
        yield client


def _origin(exc: Any) -> str:
    """The scheme, host, and port a failed request was sent to."""
    try:
        url = exc.request.url
    except RuntimeError:
        return "the storefront URL"
    port = f":{url.port}" if url.port is not None else ""
    return f"{url.scheme}://{url.host}{port}"


@contextlib.contextmanager
def reporting_failures() -> Iterator[None]:
    """Report a storefront's refusal, or its absence, on stderr and exit with status 1.

    A request no storefront answered is reported by the origin it was sent to
    and the transport error's type, never a traceback.
    """
    import httpx
    from storefront_client import StorefrontClientError

    try:
        yield
    except StorefrontClientError as exc:
        typer.secho(f"Storefront error: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    except httpx.TransportError as exc:
        typer.secho(
            f"Storefront error: no storefront answered at {_origin(exc)} "
            f"({type(exc).__name__})",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1) from exc


__all__ = ["reporting_failures", "storefront_admin_client", "storefront_url"]
