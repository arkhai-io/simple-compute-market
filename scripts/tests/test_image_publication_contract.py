"""Every declared image's build writes the revision tag the push targets read, and
records the wheelhouse's digest where it installs from the wheelhouse.

A declared image or development image is pushed from `arkhai:<local>-<rev9>`
(`scripts/publish_artifacts.py`), so a build with no image suffix must write that
tag beside the bare one. The builds are found by following `make build-dev`,
which builds every image, through `make -n`: the recipes it prints, and those of
each subproject Makefile it enters with `cd <dir> && make <target>`, which `make
-n` prints rather than runs. The images are read from the declaration, so an
image joining it is held to a build with no edit here.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from functools import cache
from pathlib import Path
from unittest.mock import Mock

import pytest

from publish_artifacts import main
from release_components import REPO_ROOT, load
from wheelhouse_digest import LABEL

_ENTERS = re.compile(r"^cd (\S+) && make (\S+)((?: [A-Z_]+=\S*)*)\s*$")
_BUILD_TAG = re.compile(r"\bdocker build\b.*?\s-t (\S+)")
_TAG = re.compile(r"\bdocker tag (\S+) (\S+)")


def _environment() -> dict[str, str]:
    # A make running these tests passes its variables down through MAKEFLAGS.
    return {key: value for key, value in os.environ.items()
            if key not in ("MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "MAKELEVEL", "IMAGE_SUFFIX")}


def _make_n(directory: Path, *arguments: str) -> list[str]:
    printed = subprocess.run(["make", "-n", "--no-print-directory", *arguments],
                             cwd=directory, capture_output=True, text=True, check=True,
                             env=_environment()).stdout
    return re.sub(r"\\\n\s*", " ", printed).splitlines()


@cache
def build_commands() -> tuple[tuple[Path, str], ...]:
    """Each command `make build-dev` runs, with the directory it runs in,
    following every subproject Makefile it enters.

    `make -n` runs a `$(MAKE)` line rather than printing it, so the wheelhouse
    build's recursive makes print their own commands, `cd <dir> && make` among
    them, relative to directories this walk cannot see. Only a `cd` naming a
    Makefile's directory relative to the one being read is followed; those
    lines build wheels, not images."""
    commands: list[tuple[Path, str]] = []
    pending: list[tuple[Path, tuple[str, ...]]] = [(REPO_ROOT, ("build-dev",))]
    while pending:
        directory, arguments = pending.pop(0)
        for line in _make_n(directory, *arguments):
            entered = _ENTERS.match(line.strip())
            if entered and (directory / entered.group(1) / "Makefile").is_file():
                pending.append((directory / entered.group(1),
                                (entered.group(2), *entered.group(3).split())))
            else:
                commands.append((directory, line))
    return tuple(commands)


def _built_tags() -> set[str]:
    """The tags a `docker build` writes."""
    return {tag for _, line in build_commands() for tag in _BUILD_TAG.findall(line)}


def _retags() -> set[tuple[str, str]]:
    """Each `docker tag <source> <tag>` a build runs."""
    return {pair for _, line in build_commands() for pair in _TAG.findall(line)}


def _written_tags() -> set[str]:
    return _built_tags() | {tag for _, tag in _retags()}


def _revision() -> str:
    return subprocess.run(["git", "rev-parse", "--short=9", "HEAD"], cwd=REPO_ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()


def _every_image() -> list:
    components = load()
    return [*components.images, *components.development_images]


@pytest.mark.parametrize("image", _every_image(), ids=lambda image: image.name)
def test_a_declared_images_build_writes_its_bare_and_revision_tags(image) -> None:
    bare = f"arkhai:{image.local}"

    assert bare in _built_tags(), f"no build writes {bare}"
    assert (bare, f"{bare}-{_revision()}") in _retags(), (
        f"no build tags {bare} with its revision")


@cache
def image_builds() -> dict[str, tuple[Path, list[str], list[str]]]:
    """Each image a build writes, by its tag: the Dockerfile it builds from, the
    `docker build` command's words, and the commands before it on its line."""
    builds: dict[str, tuple[Path, list[str], list[str]]] = {}
    for directory, line in build_commands():
        if "docker build" not in line:
            continue
        segments: list[list[str]] = [[]]
        for word in shlex.split(line):
            if word == "&&":
                segments.append([])
            else:
                segments[-1].append(word)
        cwd, before = directory, []
        for segment in segments:
            if segment[:1] == ["cd"]:
                cwd = cwd / segment[1]
            elif segment[:2] == ["docker", "build"] and "-t" in segment:
                dockerfile = segment[segment.index("-f") + 1] if "-f" in segment else "Dockerfile"
                builds[segment[segment.index("-t") + 1]] = ((cwd / dockerfile).resolve(),
                                                            segment, list(before))
            else:
                before.append(" ".join(segment))
    return builds


_COPIES_WHEELHOUSE = re.compile(r"^COPY\b[^\n]*\s\.dist/", re.MULTILINE)


@pytest.mark.parametrize("image", _every_image(), ids=lambda image: image.name)
def test_an_image_built_from_the_wheelhouse_records_its_digest(image) -> None:
    """Loading a release candidate uploads nothing unless each image built from
    the wheelhouse carries the wheelhouse's digest, and treats an image with no
    such label as one built from no wheelhouse; every declared image whose
    Dockerfile copies the wheelhouse therefore records it, and no other image
    claims to."""
    dockerfile, build, before = image_builds()[f"arkhai:{image.local}"]
    text = dockerfile.read_text(encoding="utf-8")
    stages = re.split(r"^FROM\b", text, flags=re.MULTILINE)[1:]
    final_stage = stages[-1]

    if not _COPIES_WHEELHOUSE.search(text):
        assert LABEL not in text
        return
    assert any(command.startswith("digest=") and "wheelhouse_digest.py" in command
               for command in before), f"arkhai:{image.local}'s build computes no digest"
    assert "WHEELHOUSE_DIGEST=$digest" in build
    # The argument keys the install's cache only where it is declared before the
    # wheelhouse is copied, and the label keys the cross-stage copies only where
    # it comes before them.
    for stage in stages:
        copied = _COPIES_WHEELHOUSE.search(stage)
        if copied:
            argument = re.search(r"^ARG WHEELHOUSE_DIGEST\s*$", stage, re.MULTILINE)
            assert argument and argument.start() < copied.start()
    label = final_stage.find(f'LABEL {LABEL}="${{WHEELHOUSE_DIGEST}}"')
    argument = re.search(r"^ARG WHEELHOUSE_DIGEST\s*$", final_stage, re.MULTILINE)
    cross_stage = re.search(r"^COPY\b[^\n]*--from=", final_stage, re.MULTILINE)
    assert argument and argument.start() < label
    assert label != -1 and (cross_stage is None or label < cross_stage.start())


def test_the_declared_images_built_from_the_wheelhouse_are_the_five_installing_its_wheels(
) -> None:
    """The registry, both storefronts, provisioning and the test image install the
    repository's wheels; the frps plugin's image builds from its own directory and
    the dev chain's installs none. A change to that set changes which images a
    load holds to the wheelhouse it stores, so it is held here."""
    from_wheelhouse = {tag for tag, (dockerfile, _, _) in image_builds().items()
                       if _COPIES_WHEELHOUSE.search(dockerfile.read_text(encoding="utf-8"))}
    declared = {f"arkhai:{image.local}" for image in _every_image()}

    assert from_wheelhouse & declared == {"arkhai:registry", "arkhai:storefront",
                                          "arkhai:compute-provisioning",
                                          "arkhai:bare-metal-storefront", "arkhai:e2e-tests"}


def _push_sources(target: str) -> set[str]:
    """The images `target` pushes from, as publish_artifacts.py runs it with the
    arguments its recipe passes."""
    printed = _make_n(REPO_ROOT, target, "AR_PROJECT=test-project", "AR_LOCATION=test-region")
    for line in printed:
        words = shlex.split(line)
        if "scripts/publish_artifacts.py" in words and "check" not in words:
            run = Mock()
            assert main(words[words.index("scripts/publish_artifacts.py") + 1:], run=run) == 0
            return {call.args[0][2] for call in run.call_args_list
                    if call.args[0][:2] == ["docker", "tag"]}
    raise AssertionError(f"{target} runs no publish_artifacts.py command")


@pytest.mark.parametrize("target", ["push-images", "push-dev-images"])
def test_every_image_a_push_target_reads_is_one_a_build_writes(target: str) -> None:
    """What each push pushes is `test_publish_artifacts.py`'s; this holds what it
    pushes from to what the builds write."""
    sources = _push_sources(target)

    assert sources
    assert sources <= _written_tags(), f"pushed from tags no build writes: {sources - _written_tags()}"
