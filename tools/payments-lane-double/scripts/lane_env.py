"""The values a lane needs to run against the double, read from its committed fixtures.

The root Makefile's lane environment targets run this file with the host's
``python3 -I``, outside any project environment, so it imports only the standard
library; ``tomllib`` needs Python 3.11 or newer. It is not part of the double's
package, which the image runs. Each mode prints ``VAR=value`` lines:

- ``compose``: the variables a lane's Compose files read, for its ``--env-file``;
- ``runner``: the test runner's ``PAYMENTS`` settings and the buyer's bearer token,
  for ``docker run --env-file``;
- ``seller-account``: the seller's payee account alone, the account a lane's
  storefront payments check reads.

Every value printed is a public development value, never to be used on a public
network.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
ACCOUNTS_FILE = PROJECT / "fixtures" / "accounts.toml"
DISPUTE_AUTHORITY_FILE = PROJECT / "fixtures" / "dispute-authority.toml"
CA_FILE = PROJECT / "tls" / "lane-ca.pem"

#: The double's service name in a lane and its port; its certificate is issued
#: for that name.
SERVICE_URL = "https://payments-double:8443"
#: Where a lane mounts the lane CA in the test runner and names it as SSL_CERT_FILE.
CA_MOUNT = "/run/payments-lane-double/lane-ca.pem"
#: The variable the test runner's buyer reads its bearer token from. It carries no
#: ARKHAI_ prefix, so the runner's settings loader never reads the token itself.
BUYER_API_KEY_ENV = "PAYMENTS_BUYER_API_KEY"


def _load(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _setting(value: str) -> str:
    # The runner's settings loader parses each environment value as TOML, so a
    # hex identifier or an all-digit token would arrive as a number; `@str` keeps
    # it the string it is.
    return f"@str {value}"


def compose_lines(
    accounts: Mapping[str, Any], authority: Mapping[str, Any], *, ca_file: Path = CA_FILE
) -> list[str]:
    """The lane's Compose variables: the CA file, the seller's token, and the
    registries' recommended dispute authorities as a one-item JSON array."""
    recommended = json.dumps([dict(authority)], separators=(",", ":"), sort_keys=True)
    return [
        f"PAYMENTS_LANE_CA_FILE={ca_file}",
        f"PAYMENTS_LANE_SELLER_API_KEY={accounts['accounts']['seller']['token']}",
        # Single-quoted, so Compose reads the JSON literally.
        f"PAYMENTS_LANE_DISPUTE_AUTHORITIES='{recommended}'",
    ]


def runner_lines(accounts: Mapping[str, Any]) -> list[str]:
    """The test runner's ``PAYMENTS`` settings for a lane-owned target."""
    parties = accounts["accounts"]
    return [
        f"ARKHAI_PAYMENTS__SERVICE_URL={_setting(SERVICE_URL)}",
        f"ARKHAI_PAYMENTS__SERVICE_IDENTITY={_setting(accounts['receipt_identity']['identifier'])}",
        f"ARKHAI_PAYMENTS__FEE_BPS={int(accounts['fee_bps'])}",
        "ARKHAI_PAYMENTS__LIVEMODE=false",
        "ARKHAI_PAYMENTS__LANE_OWNED=true",
        f"ARKHAI_PAYMENTS__API_KEY_ENV={_setting(BUYER_API_KEY_ENV)}",
        f"ARKHAI_PAYMENTS__BUYER_ACCOUNT={_setting(parties['buyer']['account'])}",
        f"ARKHAI_PAYMENTS__SELLER_ACCOUNT={_setting(parties['seller']['account'])}",
        f"{BUYER_API_KEY_ENV}={parties['buyer']['token']}",
        f"SSL_CERT_FILE={CA_MOUNT}",
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("compose", "runner", "seller-account"))
    mode = parser.parse_args(argv).mode
    accounts = _load(ACCOUNTS_FILE)
    if mode == "compose":
        lines = compose_lines(accounts, _load(DISPUTE_AUTHORITY_FILE))
    elif mode == "runner":
        lines = runner_lines(accounts)
    else:
        lines = [accounts["accounts"]["seller"]["account"]]
    sys.stdout.write("".join(f"{line}\n" for line in lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
