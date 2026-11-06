"""Serve the double over HTTPS: ``python -m payments_lane_double``."""

from __future__ import annotations

import os

import uvicorn

from payments_lane_double.accounts import load_accounts
from payments_lane_double.app import create_app
from payments_lane_double.settings import Settings


def main() -> None:
    settings = Settings.from_environment(os.environ)
    app = create_app(load_accounts(settings.accounts_file))
    # The kit's client refuses plain HTTP outside loopback, so the double serves
    # HTTPS only, under the lane CA its callers trust.
    uvicorn.run(app, host=settings.host, port=settings.port,
                ssl_certfile=str(settings.certificate_file),
                ssl_keyfile=str(settings.key_file))


if __name__ == "__main__":
    main()
