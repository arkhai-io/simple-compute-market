"""The double's values a lane or a local release reads at run time, from its committed fixtures.

The end-to-end lane targets (``e2e-tests/Makefile``), which pass the seller's
account to each storefront's payments check, and the local Helm release's
out-of-band Secret step (``helm/scripts/topology-secrets.sh``) run this file with
the host's ``python3 -I``, outside any project environment, so it imports only the
standard library; ``tomllib`` needs Python 3.11 or newer. It is not part of the
double's package, which the image runs. Each mode prints one bare value:

- ``seller-account``: the seller's payee account, the account a storefront
  payments check reads;
- ``seller-token``: the seller's bearer token, which a local release writes into
  each storefront's runtime secret overlay.

Every value printed is a public development value, never to be used on a public
network.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
ACCOUNTS_FILE = PROJECT / "fixtures" / "accounts.toml"

#: The double's service name in a lane and its port; its certificate is issued
#: for that name.
SERVICE_URL = "https://payments-double:8443"


def _load(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("seller-account", "seller-token"))
    mode = parser.parse_args(argv).mode
    seller = _load(ACCOUNTS_FILE)["accounts"]["seller"]
    value = seller["account"] if mode == "seller-account" else seller["token"]
    sys.stdout.write(f"{value}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
