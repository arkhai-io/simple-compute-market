"""Where the double finds its fixtures and TLS material, and where it listens.

The image carries the committed fixtures and TLS files at ``IMAGE_ROOT``, so a
lane runs the double with no mounts and no configuration. A deployment that
supplies its own server certificate mounts it over the image's files at the same
paths. The environment variables exist for running the double outside its image.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

IMAGE_ROOT = Path("/opt/payments-lane-double")
PORT = 8443
_PREFIX = "PAYMENTS_LANE_DOUBLE_"


@dataclass(frozen=True)
class Settings:
    fixtures: Path
    tls: Path
    host: str = "0.0.0.0"
    port: int = PORT

    @property
    def accounts_file(self) -> Path:
        return self.fixtures / "accounts.toml"

    @property
    def certificate_file(self) -> Path:
        return self.tls / "double.pem"

    @property
    def key_file(self) -> Path:
        return self.tls / "double.key.pem"

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> Settings:
        port = environment.get(f"{_PREFIX}PORT", str(PORT))
        if not port.isdigit() or not 0 < int(port) < 65_536:
            raise ValueError(f"{_PREFIX}PORT must be a TCP port number")
        return cls(
            fixtures=Path(environment.get(f"{_PREFIX}FIXTURES", IMAGE_ROOT / "fixtures")),
            tls=Path(environment.get(f"{_PREFIX}TLS", IMAGE_ROOT / "tls")),
            host=environment.get(f"{_PREFIX}HOST", "0.0.0.0"),
            port=int(port),
        )
