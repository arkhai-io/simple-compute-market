"""Artifact publication ordering, refusal, and credential handling."""

import argparse
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publish_artifacts import publish_wheel, push_image


@pytest.fixture
def args():
    return argparse.Namespace(project="example-project", location="example-region",
                              prefix="example", package="example-package", version="1.0",
                              wheel="example.whl", registry="https://example.invalid",
                              clobber=False, source="local", target="remote", suffix="abc")


def result(code=0, stderr="", stdout=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


def test_existing_wheel_is_skipped(args):
    run = Mock(return_value=result())
    publish_wheel(args, run)
    assert run.call_count == 1


@pytest.mark.parametrize("clobber", [False, True])
def test_absent_wheel_publishes_without_deletion(args, clobber, monkeypatch):
    args.clobber = clobber
    monkeypatch.setenv("UV_PUBLISH_TOKEN", "unrelated")
    run = Mock(side_effect=[result(1, "NOT_FOUND"), result(stdout="credential\n"), result()])
    publish_wheel(args, run)
    call = run.call_args
    assert call.args[0] == ["uv", "publish", "--publish-url", args.registry, args.wheel]
    assert call.kwargs["env"]["UV_PUBLISH_PASSWORD"] == "credential"
    assert "UV_PUBLISH_TOKEN" not in call.kwargs["env"]
    assert "credential" not in str(call.args)


def test_clobber_deletes_before_publishing(args):
    args.clobber = True
    run = Mock(side_effect=[result(), result(), result(stdout="credential"), result()])
    publish_wheel(args, run)
    assert run.call_args_list[1].args[0][:5] == ["gcloud", "artifacts", "versions", "delete", "1.0"]
    assert run.call_args_list[-1].args[0][0] == "uv"


def test_failed_delete_stops_publication(args):
    args.clobber = True
    run = Mock(side_effect=[result(), subprocess.CalledProcessError(1, ["gcloud"])])
    with pytest.raises(subprocess.CalledProcessError):
        publish_wheel(args, run)
    assert run.call_count == 2


def test_lookup_permission_failure_stops_publication(args):
    run = Mock(return_value=result(1, "PERMISSION_DENIED"))
    with pytest.raises(RuntimeError, match="Cannot check"):
        publish_wheel(args, run)
    assert run.call_count == 1


def test_image_tags_and_pushes_both_names(args):
    run = Mock()
    push_image(args, run)
    assert [call.args[0] for call in run.call_args_list] == [
        ["docker", "tag", "arkhai:local-abc", "https://example.invalid/arkhai:remote-abc"],
        ["docker", "tag", "arkhai:local-abc", "https://example.invalid/arkhai:remote"],
        ["docker", "push", "https://example.invalid/arkhai:remote-abc"],
        ["docker", "push", "https://example.invalid/arkhai:remote"],
    ]


def test_failed_tag_stops_pushes(args):
    run = Mock(side_effect=subprocess.CalledProcessError(1, ["docker"]))
    with pytest.raises(subprocess.CalledProcessError):
        push_image(args, run)
    assert run.call_count == 1


@pytest.mark.parametrize("missing", ["project", "location"])
def test_cli_requires_explicit_destination(missing):
    values = dict(project="example-project", location="example-region", prefix="example")
    values[missing] = ""
    command = [sys.executable, "scripts/publish_artifacts.py"]
    for key, value in values.items():
        command.extend([f"--{key}", value])
    completed = subprocess.run([*command, "check"], capture_output=True, text=True)
    assert completed.returncode == 2
    assert f"AR_{missing.upper()} is required" in completed.stderr
