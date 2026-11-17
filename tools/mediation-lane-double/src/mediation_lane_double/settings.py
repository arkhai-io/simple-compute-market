"""Where the double finds its fixtures, TLS material and payments, where it listens, and its time.

The image carries the committed fixture and TLS files at ``IMAGE_ROOT``, so a lane
runs the double with no mounts and no configuration. It reaches the payments
double by that service's lane-private name, trusting the lane CA alone. The
environment variables exist for running the double outside its image, except
``MEDIATION_LANE_DOUBLE_TIME_SOURCE``: ``"wall"`` by default, ``"injected"`` in a
lane whose every party shares one time the scenario sets.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import injected_time
from injected_time import WALL, SourceName, TimeSource, source_for

IMAGE_ROOT = Path("/opt/mediation-lane-double")
PORT = 8443
PAYMENTS_URL = "https://payments-double:8443"
_PREFIX = "MEDIATION_LANE_DOUBLE_"
TIME_SOURCE_SETTING = f"{_PREFIX}TIME_SOURCE"


@dataclass(frozen=True)
class Settings:
    fixtures: Path
    tls: Path
    payments_url: str = PAYMENTS_URL
    host: str = "0.0.0.0"
    port: int = PORT
    time_source: SourceName = WALL

    @property
    def authority_file(self) -> Path:
        return self.fixtures / "authority.toml"

    @property
    def certificate_file(self) -> Path:
        return self.tls / "double.pem"

    @property
    def key_file(self) -> Path:
        return self.tls / "double.key.pem"

    @property
    def lane_ca_file(self) -> Path:
        return self.tls / "lane-ca.pem"

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> Settings:
        port = environment.get(f"{_PREFIX}PORT", str(PORT))
        if not port.isdigit() or not 0 < int(port) < 65_536:
            raise ValueError(f"{_PREFIX}PORT must be a TCP port number")
        # Any value but "wall" or "injected" refuses startup, naming the setting.
        time_source = source_for(environment.get(TIME_SOURCE_SETTING, WALL),
                                 setting=TIME_SOURCE_SETTING).name
        return cls(
            fixtures=Path(environment.get(f"{_PREFIX}FIXTURES", IMAGE_ROOT / "fixtures")),
            tls=Path(environment.get(f"{_PREFIX}TLS", IMAGE_ROOT / "tls")),
            payments_url=environment.get(f"{_PREFIX}PAYMENTS_URL", PAYMENTS_URL),
            host=environment.get(f"{_PREFIX}HOST", "0.0.0.0"),
            port=int(port),
            time_source=time_source,
        )


def install_time_source(settings: Settings, *,
                        logger: logging.Logger | None = None) -> TimeSource:
    """Install the process's time source from ``settings``, announcing injected time.

    Installed before anything reads the time, so the double's records and the
    kits it calls through read the one source.
    """
    source = injected_time.install(source_for(settings.time_source, setting=TIME_SOURCE_SETTING))
    if source.name != WALL:
        (logger or logging.getLogger(__name__)).info(
            "%s is %s: the double holds %s until its time control sets it",
            TIME_SOURCE_SETTING, source.name, source.now())
    return source
