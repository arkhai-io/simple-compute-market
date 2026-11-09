"""Where the double finds its fixtures, TLS material and payments, and where it listens.

The image carries the committed fixture and TLS files at ``IMAGE_ROOT``, so a lane
runs the double with no mounts and no configuration. It reaches the payments
double by that service's lane-private name, trusting the lane CA alone. The
environment variables exist for running the double outside its image.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

IMAGE_ROOT = Path("/opt/mediation-lane-double")
PORT = 8443
PAYMENTS_URL = "https://payments-double:8443"
_PREFIX = "MEDIATION_LANE_DOUBLE_"


@dataclass(frozen=True)
class Settings:
    fixtures: Path
    tls: Path
    payments_url: str = PAYMENTS_URL
    host: str = "0.0.0.0"
    port: int = PORT

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
        return cls(
            fixtures=Path(environment.get(f"{_PREFIX}FIXTURES", IMAGE_ROOT / "fixtures")),
            tls=Path(environment.get(f"{_PREFIX}TLS", IMAGE_ROOT / "tls")),
            payments_url=environment.get(f"{_PREFIX}PAYMENTS_URL", PAYMENTS_URL),
            host=environment.get(f"{_PREFIX}HOST", "0.0.0.0"),
            port=int(port),
        )
