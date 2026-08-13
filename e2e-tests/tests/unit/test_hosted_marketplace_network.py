from __future__ import annotations

from tests.e2e.roles.scenarios.vms.hosted.network import _primary_registry_authority


def test_primary_registry_authority_uses_advertised_url_not_runtime_endpoint() -> None:
    authority = _primary_registry_authority(
        {
            "registry": {
                "urls": ["http://registry:8080"],
                "authorities": {
                    "http://registry:8080": {
                        "authority": "registry-a",
                        "principals": [{"scheme": "ed25519", "identifier": "registry-principal"}],
                    }
                },
            }
        }
    )

    assert authority["authority"] == "registry-a"
