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


def test_redacts_home_path_usernames() -> None:
    redacted = tracked_redactor().redact("/home/levi/project/.ssh/id_ed25519")

    assert "levi" not in redacted
    assert redacted == "/home/<user>/project/.ssh/id_ed25519"


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
