"""Shared helpers used by cli.py and groups/*.py."""
from __future__ import annotations

import json
import os
import textwrap
import urllib.error
import urllib.request
from pathlib import Path

import typer

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Network / HTTP helpers
# ---------------------------------------------------------------------------

def _resolve_agent_url(agent_url: str | None) -> str:
    url = agent_url or os.getenv("AGENT_URL") or os.getenv("BASE_URL_OVERRIDE") or "http://localhost:8000"
    return url.rstrip("/")


def _normalize_registry_url(raw_url: str) -> str:
    return raw_url.rstrip("/")


def _fetch_json(url: str) -> dict:
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if exc.fp else str(exc)
        typer.secho(f"Registry error ({exc.code}): {detail}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)
    except Exception as exc:
        typer.secho(f"Request failed: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)


def _post_json(url: str, payload: dict, timeout: int = 120) -> dict:
    try:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if exc.fp else str(exc)
        typer.secho(f"Agent error ({exc.code}): {detail}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)
    except Exception as exc:
        typer.secho(f"Failed to call agent endpoint: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Display / formatting helpers
# ---------------------------------------------------------------------------

def _short_ts(value: str | None) -> str:
    if not value:
        return "-"
    return value.replace("T", " ")[:19]


def _shorten(text: str, width: int = 36) -> str:
    if not text:
        return "-"
    return textwrap.shorten(text, width=width, placeholder="…")


def _short_contract_address(value: str) -> str:
    if not value:
        return "-"
    if len(value) <= 12:
        return value
    return f"{value[:6]}…{value[-4:]}"


def _format_resource(resource: dict) -> str:
    if not resource:
        return "-"
    if not isinstance(resource, dict):
        return str(resource)
    is_compute = resource.get("type") == "compute" or "gpu_model" in resource
    if is_compute:
        ordered_keys = ("type", "gpu_model", "quantity", "sla", "region")
        lines = [f"{key}={resource[key]}" for key in ordered_keys if key in resource]
        extra_keys = sorted(k for k in resource.keys() if k not in ordered_keys)
        lines.extend(f"{key}={resource[key]}" for key in extra_keys)
        return "\n".join(lines) if lines else json.dumps(resource, separators=(",", ":"), sort_keys=True)

    token_payload = resource.get("token")
    is_token = resource.get("type") == "token" or isinstance(token_payload, dict) or "symbol" in resource
    if is_token:
        token_data = token_payload if isinstance(token_payload, dict) else resource
        symbol = token_data.get("symbol")
        decimals = token_data.get("decimals")
        amount = resource.get("amount", token_data.get("amount"))
        contract = token_data.get("contract_address")
        lines = []
        if symbol is not None:
            lines.append(f"symbol={symbol}")
        if decimals is not None:
            lines.append(f"decimals={decimals}")
        if amount is not None:
            lines.append(f"amount={amount}")
        if contract is not None:
            lines.append(f"contract_address={_short_contract_address(str(contract))}")
        return "\n".join(lines) if lines else json.dumps(resource, separators=(",", ":"), sort_keys=True)

    parts: list[str] = []
    for key in ("type", "region", "gpu_model", "sla", "symbol"):
        if key in resource:
            parts.append(f"{key}={resource[key]}")
    if parts:
        return ", ".join(parts)
    return json.dumps(resource, separators=(",", ":"), sort_keys=True)


def _format_resource_full(resource: dict | str | None) -> str:
    if resource is None or resource == "":
        return "-"
    if isinstance(resource, str):
        return resource
    try:
        return json.dumps(resource, separators=(",", ":"), sort_keys=True)
    except Exception:
        return str(resource)


def _normalize_registry_resource(resource: dict) -> dict:
    """Convert registry token resource amounts to friendly units for create endpoint."""
    if not isinstance(resource, dict):
        return resource
    token = resource.get("token")
    amount = resource.get("amount")
    if isinstance(token, dict) and "decimals" in token and amount is not None:
        try:
            decimals = int(token["decimals"])
        except (TypeError, ValueError):
            return resource
        from decimal import Decimal, InvalidOperation
        try:
            amount_value = Decimal(str(amount))
        except (InvalidOperation, ValueError, TypeError):
            return resource
        human_amount = amount_value / (Decimal(10) ** decimals)
        normalized = dict(resource)
        normalized["amount"] = str(human_amount.normalize())
        return normalized
    return resource


