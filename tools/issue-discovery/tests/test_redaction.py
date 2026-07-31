from __future__ import annotations

from pathlib import Path

from issue_discovery.config import ToolPaths
from issue_discovery.redaction import Redactor


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def tracked_redactor() -> Redactor:
    paths = ToolPaths(repo_root())
    return Redactor.from_file(paths.config_dir / "redactions.yaml")


def test_redacts_private_key_assignments() -> None:
    private_key = "0x" + "a" * 64
    redacted = tracked_redactor().redact(f'{{"private_key": "{private_key}"}}')

    assert private_key not in redacted
    assert redacted == '{"private_key": "<redacted-private-key>"}'


def test_redacts_admin_key_headers() -> None:
    redacted = tracked_redactor().redact("X-Admin-Key: test-api-key")

    assert "test-api-key" not in redacted
    assert redacted == "X-Admin-Key: <redacted-admin-key>"


def test_redacts_bearer_tokens() -> None:
    redacted = tracked_redactor().redact("Authorization: Bearer abc.def_123")

    assert "abc.def_123" not in redacted
    assert redacted == "Authorization: Bearer <redacted-token>"


def test_redacts_generic_secret_assignments_and_private_key_markers() -> None:
    redactor = tracked_redactor()

    assert redactor.redact('{"client_secret":"live-secret"}') == (
        '{"client_secret":"<redacted-secret>"}'
    )
    assert redactor.redact("-----BEGIN OPENSSH PRIVATE KEY-----") == (
        "-----BEGIN <redacted-private-key>-----"
    )
    assert redactor.redact('{"private key":"alpha beta gamma"}') == (
        '{"private key":"<redacted-secret>"}'
    )
    assert redactor.redact('{"ssh_private_key":"alpha beta"}') == (
        '{"ssh_private_key":"<redacted-secret>"}'
    )
    assert redactor.redact('{"seed_phrase":"alpha beta gamma"}') == (
        '{"seed_phrase":"<redacted-secret>"}'
    )


def test_redacts_wallet_and_email_account_identities() -> None:
    redactor = tracked_redactor()
    wallet = "0x" + "a1" * 20

    assert redactor.redact(f"wallet={wallet}") == "wallet=<redacted-account>"
    assert redactor.redact("operator@example.test") == "<redacted-account>"


def test_redacts_cloud_project_and_host_identities() -> None:
    redactor = tracked_redactor()

    assert redactor.redact('{"project_id":"scratch-project-123"}') == (
        '{"project_id":"<redacted-project>"}'
    )
    assert redactor.redact("projects/scratch-project-123") == (
        "projects/<redacted-project>"
    )
    assert redactor.redact('{"hostname":"private-tower"}') == (
        '{"hostname":"<redacted-host>"}'
    )


def test_redacts_gpu_pci_and_private_network_identities() -> None:
    redactor = tracked_redactor()
    gpu_uuid = "GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    assert redactor.redact(gpu_uuid) == "<redacted-gpu>"
    assert redactor.redact("0000:01:00.0") == "<redacted-pci-bdf>"
    assert redactor.redact("https://192.168.50.4:8443/status") == (
        "https://<redacted-private-ip>:8443/status"
    )
    assert redactor.redact("http://127.0.0.1:8080/status") == (
        "http://<redacted-private-ip>:8080/status"
    )
    assert redactor.redact("http://[::1]:8080/status") == (
        "http://[<redacted-private-ip>]:8080/status"
    )
    assert redactor.redact("ssh://[fd12:3456::1]:22") == (
        "ssh://[<redacted-private-ip>]:22"
    )
    assert redactor.redact("https://tower.localhost/status") == (
        "https://<redacted-private-host>/status"
    )


def test_redacts_home_path_usernames() -> None:
    redacted = tracked_redactor().redact("/home/example-user/project/.ssh/id_ed25519")

    assert "example-user" not in redacted
    assert redacted == "/home/<user>/project/.ssh/id_ed25519"


def test_redacts_macos_home_path_usernames() -> None:
    redacted = tracked_redactor().redact(
        "/Users/example-user/project/.ssh/id_ed25519"
    )

    assert "example-user" not in redacted
    assert redacted == "/Users/<user>/project/.ssh/id_ed25519"


def test_redacts_nested_mapping_values() -> None:
    private_key = "b" * 64
    redacted = tracked_redactor().redact_mapping(
        {
            "outer": {
                "secret": f"private-key={private_key}",
                "paths": ["/home/alice/work", "safe"],
            }
        }
    )

    assert private_key not in str(redacted)
    assert redacted["outer"]["secret"] == "private-key=<redacted-private-key>"
    assert redacted["outer"]["paths"] == ["/home/<user>/work", "safe"]
