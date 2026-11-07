"""Configuration the storefront refuses to start under.

Each kind of problem stops the storefront before it resolves its signer, opens
its database, or starts a loop, reported under its own heading with every
problem of that kind named by its key:

- a renamed or removed setting it still states (`retired_settings`);
- no credits service to sell for: an unset `[credits].service_url`;
- a capacity configuration it cannot read: no site, a site missing its URL or
  trusted authorities, authorities that are not valid principals, or a
  `[capacity].poll_interval` that is not a positive, finite number of seconds.
  Reading it here, rather than when the capacity runtime or the capacity-event
  pollers are first composed, keeps a malformed site or interval from stopping
  startup after some of it has run.

Only the configuration is judged here. Whether the credits service or a site
answers is not: the storefront starts while either is unreachable, and the calls
that need them retry.
"""

from __future__ import annotations

from dynaconf import Dynaconf

from apicredits_storefront.retired_settings import (
    RETIRED_SETTINGS_HEADING,
    retired_setting_problems,
)
from apicredits_storefront.services.capacity_client import (
    capacity_poll_interval,
    configured_site_ids,
)
from apicredits_storefront.utils.config import credits_service_url

CREDITS_HEADING = "the storefront has no credits service to sell for"
CAPACITY_HEADING = "the storefront cannot read its capacity configuration"


def credits_configuration_problems() -> list[str]:
    """Why the storefront has no credits service to sell for, if it has none."""
    if not credits_service_url():
        return ["[credits].service_url is not configured"]
    return []


class StorefrontStartupError(RuntimeError):
    """The storefront's configuration states a setting it no longer reads, or
    one it cannot read."""


def capacity_configuration_problems() -> list[str]:
    """Why the configured capacity sites or poll interval cannot be read, if
    they cannot, each refusal naming its key."""
    problems: list[str] = []
    try:
        configured_site_ids()
    except RuntimeError as exc:
        problems.append(str(exc))
    try:
        capacity_poll_interval()
    except ValueError as exc:
        problems.append(str(exc))
    return problems


def require_startable_storefront(source: Dynaconf | None = None) -> None:
    """Refuse to start, naming each problem under its heading."""
    sections = [
        f"{heading}: " + "; ".join(problems)
        for heading, problems in (
            (RETIRED_SETTINGS_HEADING, retired_setting_problems(source)),
            (CREDITS_HEADING, credits_configuration_problems()),
            (CAPACITY_HEADING, capacity_configuration_problems()),
        )
        if problems
    ]
    if sections:
        raise StorefrontStartupError(". ".join(sections))


__all__ = [
    "CAPACITY_HEADING",
    "CREDITS_HEADING",
    "StorefrontStartupError",
    "capacity_configuration_problems",
    "credits_configuration_problems",
    "require_startable_storefront",
]
