"""The channel a run takes is derived from the tree, not configured beside it."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import importlib.util  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "select_hosted_client_channel",
    Path(__file__).resolve().parents[1] / "select-hosted-client-channel.py",
)
assert _SPEC and _SPEC.loader
selector = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(selector)

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")


def _tree(root: Path, *, pin: str, trusted: str | None) -> Path:
    (root / "kit" / "hosted-settlement").mkdir(parents=True)
    (root / "kit" / "hosted-settlement" / "pyproject.toml").write_text(
        f'dependencies = ["arkhai-hosted-settlement-client=={pin}"]\n', encoding="utf-8"
    )
    (root / "manifests").mkdir()
    if trusted is not None:
        (root / "manifests" / f"hosted-settlement-v{trusted}-trust.json").write_text(
            json.dumps(
                {
                    "repository": "arkhai-io/stripe-settlement-service",
                    "release_version": trusted,
                    "schema_version": 5,
                    "manifest_filename": "release-manifest.json",
                    "client_wheel": {
                        "filename": (
                            f"arkhai_hosted_settlement_client-{trusted}"
                            "-py3-none-any.whl"
                        )
                    },
                }
            ),
            encoding="utf-8",
        )
    return root


def test_a_pinned_version_with_a_signed_release_is_verified(tmp_path: Path) -> None:
    selected = selector.channel(_tree(tmp_path, pin="0.2.1", trusted="0.2.1"))

    assert selected["channel"] == "release"
    assert selected["version"] == "0.2.1"
    assert selected["schema_version"] == "5"
    assert selected["trust"] == "manifests/hosted-settlement-v0.2.1-trust.json"


def test_a_pin_ahead_of_the_last_signature_takes_the_internal_channel(
    tmp_path: Path,
) -> None:
    """There is no release to verify, and the run does not pretend otherwise."""

    selected = selector.channel(_tree(tmp_path, pin="0.3.0", trusted="0.2.1"))

    assert selected["channel"] == "internal"
    assert selected["version"] == "0.3.0"
    assert selected["wheel"] == "arkhai_hosted_settlement_client-0.3.0-py3-none-any.whl"
    assert "trust" not in selected
    assert "manifest" not in selected


def test_releasing_the_pinned_version_moves_it_back_without_an_edit(
    tmp_path: Path,
) -> None:
    """The channel follows the tree; publishing a release is the whole change."""

    assert selector.channel(_tree(tmp_path / "before", pin="0.3.0", trusted="0.2.1"))[
        "channel"
    ] == "internal"
    assert selector.channel(_tree(tmp_path / "after", pin="0.3.0", trusted="0.3.0"))[
        "channel"
    ] == "release"


def test_a_trust_config_that_contradicts_its_own_filename_is_refused(
    tmp_path: Path,
) -> None:
    root = _tree(tmp_path, pin="0.2.1", trusted="0.2.1")
    path = root / "manifests" / "hosted-settlement-v0.2.1-trust.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["release_version"] = "0.9.9"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(selector.ChannelUndecidable, match="pins"):
        selector.channel(root)


@pytest.mark.parametrize(
    "dependencies",
    [
        "",
        'a = ["arkhai-hosted-settlement-client==0.2.1"]\n'
        'b = ["arkhai-hosted-settlement-client==0.3.0"]\n',
    ],
)
def test_a_tree_that_states_no_single_pin_is_refused(
    dependencies: str, tmp_path: Path
) -> None:
    """Two answers to which version to obtain is no answer."""

    (tmp_path / "kit" / "hosted-settlement").mkdir(parents=True)
    (tmp_path / "kit" / "hosted-settlement" / "pyproject.toml").write_text(
        dependencies, encoding="utf-8"
    )
    (tmp_path / "manifests").mkdir()

    with pytest.raises(selector.ChannelUndecidable):
        selector.channel(tmp_path)


def test_this_repository_selects_the_channel_its_own_files_imply() -> None:
    """The selector's answer, checked against the state it reads.

    Which version that is comes from the pin, because naming it here would be
    the third place stating it -- the one this selector exists to remove -- and
    would make every routine bump look like a broken test. The channel is
    checked the same way. It was asserted as `internal` while the pin was an
    unreleased client, which made binding a signed release look like a
    regression; what the assertion was always for is that the two agree.
    """

    pinned = selector.pinned_version(REPO_ROOT)
    selected = selector.channel(REPO_ROOT)
    signed = REPO_ROOT / "manifests" / f"hosted-settlement-v{pinned}-trust.json"

    assert selected["version"] == pinned
    assert selected["channel"] == ("release" if signed.exists() else "internal")
    if signed.exists():
        assert selected["trust"] == str(signed.relative_to(REPO_ROOT))
        assert selected["wheel"].endswith(f"-{pinned}-py3-none-any.whl")


def test_the_workflow_names_no_hosted_version_of_its_own() -> None:
    """Every asset the dev-pace workflow asks for follows from the pin."""

    hosted = WORKFLOW[WORKFLOW.index("Select the hosted client channel") :]
    hosted = hosted[: hosted.index("Build sibling wheels")]

    assert "0.2.1" not in hosted
    assert "migrations-v5" not in hosted
    assert "steps.hosted.outputs.version" in hosted
    assert "steps.hosted.outputs.schema_version" in hosted


def test_the_release_path_still_verifies_and_the_internal_path_does_not() -> None:
    assert (
        "run: make verify-hosted-release HOSTED_RELEASE_TRUST=" in WORKFLOW
    ), "the released path verifies what signed it"
    staging = WORKFLOW[WORKFLOW.index("Stage the development hosted client") :]
    staging = staging[: staging.index("      - name:", 1)] if "      - name:" in staging[1:] else staging
    assert "verify-hosted-release" not in staging, "nothing signed the internal wheel"


def test_an_unreachable_index_reports_the_version_and_the_channel() -> None:
    assert "::error::hosted client" in WORKFLOW
    assert "AR_WORKLOAD_IDENTITY_PROVIDER" in WORKFLOW
    assert "or release that version" in WORKFLOW


#: Names a producer release asset carries, spelled with the version in them.
#: Each is derivable from the pin, so a literal one in a workflow is a second
#: statement of which release is bound -- and the one that goes stale, because
#: nothing reads it back.
_STALE_HOSTED_LITERALS = (
    re.compile(r"hosted-settlement-v\d+\.\d+\.\d+-trust\.json"),
    re.compile(r"(?:openapi|conformance)-v\d+\.\d+\.\d+\.json"),
    re.compile(r"migrations-v\d+\.json"),
    re.compile(r"HOSTED_RELEASE_TAG"),
)


@pytest.mark.parametrize(
    "workflow",
    sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")),
    ids=lambda path: path.name,
)
def test_no_workflow_names_a_hosted_release_of_its_own(workflow: Path) -> None:
    """Every workflow asks the selector which release is bound, or asks nobody.

    Three workflows consume the producer and only one derived the version.
    `release.yml` carried `HOSTED_RELEASE_TAG: v0.2.1` and `publish-pypi.yml`
    opened `hosted-settlement-v0.2.1-trust.json` by name; both survived the
    move to v0.4.2 unchanged, and both then reached for a release that does
    not exist. The failure was a publish job reporting `release not found`,
    which names neither the version it wanted nor where it got it.
    """

    text = workflow.read_text(encoding="utf-8")
    found = sorted(
        {match.group(0) for pattern in _STALE_HOSTED_LITERALS for match in pattern.finditer(text)}
    )

    assert not found, (
        f"{workflow.name} names {found}; derive it from "
        "scripts/select-hosted-client-channel.py instead"
    )
