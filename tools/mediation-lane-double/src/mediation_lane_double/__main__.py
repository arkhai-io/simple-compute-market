"""Serve the double over HTTPS: ``python -m mediation_lane_double``."""

from __future__ import annotations

import logging
import os

import uvicorn
from market_arkhai_payments import PaymentsClient

from mediation_lane_double.app import create_app
from mediation_lane_double.authority import load_authority
from mediation_lane_double.settings import Settings, install_time_source


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_environment(os.environ)
    source = install_time_source(settings)
    authority = load_authority(settings.authority_file)
    # The authority acts at payments as its own account, under the lane CA.
    payments = PaymentsClient(settings.payments_url, api_key=authority.payments_token,
                              ca_bundle=str(settings.lane_ca_file))
    app = create_app(authority, payments, source=source)
    # The kit's client refuses plain HTTP outside loopback, so the double serves
    # HTTPS only, under the lane CA its callers trust.
    uvicorn.run(app, host=settings.host, port=settings.port,
                ssl_certfile=str(settings.certificate_file),
                ssl_keyfile=str(settings.key_file))


if __name__ == "__main__":
    main()
