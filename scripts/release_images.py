#!/usr/bin/env python3
"""Run a release candidate's images in the local end-to-end lanes, and record them.

Images do not rebuild to the same digest, so a lane validating a release
candidate runs the images the candidate stored rather than building its own.
With `RELEASE_IMAGES=1` and the candidate's `IMAGE_SUFFIX`, a lane's Compose
files run each release image as `arkhai:<local><IMAGE_SUFFIX>`, and the lane
builds none of them. The declared release images come from
`manifests/release-components.json`, read through `release_components`; the
mapping from an image's published name to its local name is applied here alone.

- `pull` pulls each declared release image as `<registry>/arkhai:<name><suffix>`
  and tags it `arkhai:<local><suffix>`. Docker keeps the repo digest it pulled
  across the retag, which is what `record` reads. The registry is passed in, as
  the push targets take it.
- `check`, before a lane builds or starts anything, fails naming each declared
  release image the lane's Compose files run that is missing locally, and each
  they name without the suffix, which would run whatever image holds the bare tag.
- `record`, once the lane's stack is up, writes
  `.snapshot/e2e-release-images-<lane>.json`, and prints it: each release image the
  lane's running containers run, by its published name, with the manifest digest
  of its one repo digest from a registry. It fails when a release image the
  Compose files run has no running container, when an image has no repo digest
  from a registry, and when it has two different ones: choosing between two would
  need the registry's name, which the record never carries. A repo digest in the
  local `arkhai` repository names no registry, and is not counted: an image store
  that keeps images in containerd gives a locally built image one, which a pull
  never would.

Each command refuses an empty suffix: a candidate's images are named by their
revision, and the bare tags name whatever was built or pulled last.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from release_components import DECLARATION_PATH, REPO_ROOT, DeclarationError, Image, load

Run = Callable[..., subprocess.CompletedProcess]

SNAPSHOT_DIR = ".snapshot"
# The repository every image a lane runs is named in locally.
LOCAL_REPOSITORY = "arkhai"


class Refused(RuntimeError):
    """The command found the candidate's images unusable, and names why."""


def local_tag(image: Image, suffix: str) -> str:
    return f"{LOCAL_REPOSITORY}:{image.local}{suffix}"


def registry_digests(repo_digests: list[str]) -> set[str]:
    """The manifest digests of `repo_digests` that a registry served, each
    `<registry>/<repository>@<digest>`; one in the local repository names none."""
    return {digest for repository, _, digest in
            (reference.partition("@") for reference in repo_digests)
            if repository != LOCAL_REPOSITORY}


def pull(registry: str, images: tuple[Image, ...], suffix: str,
         run: Run = subprocess.run) -> None:
    for image in images:
        remote = f"{registry}/arkhai:{image.name}{suffix}"
        run(["docker", "pull", remote], check=True)
        run(["docker", "tag", remote, local_tag(image, suffix)], check=True)


def _compose(compose: str, suffix: str, arguments: list[str], root: Path,
             run: Run) -> str:
    """Run `docker compose` over the lane's files with the candidate's suffix, as
    the lane's own Compose commands see it, and return its output."""
    environment = {**os.environ, "IMAGE_SUFFIX": suffix}
    return run(["docker", "compose", *shlex.split(compose), *arguments], cwd=root,
               env=environment, capture_output=True, text=True, check=True).stdout


def check_problems(images: tuple[Image, ...], compose: str, suffix: str, root: Path,
                   run: Run = subprocess.run) -> list[str]:
    """Every declared release image the lane's Compose files run that is missing
    locally, and every one they name without the suffix."""
    referenced = set(_compose(compose, suffix, ["config", "--images"], root, run).split())
    problems: list[str] = []
    for image in images:
        tag = local_tag(image, suffix)
        if local_tag(image, "") in referenced:
            problems.append(f"the lane's Compose files run arkhai:{image.local} rather than "
                            f"{tag}: name it arkhai:{image.local}${{IMAGE_SUFFIX:-}}")
        if tag in referenced:
            inspected = run(["docker", "image", "inspect", tag], capture_output=True, text=True)
            if inspected.returncode != 0 and "No such image" in inspected.stderr:
                problems.append(f"{tag} is not present locally: pull the candidate's images "
                                "with make -C e2e-tests pull-release-images")
            elif inspected.returncode != 0:
                problems.append(f"cannot inspect {tag}: {inspected.stderr.strip()}")
    return problems


def _inspect(kind: str, ids: list[str], run: Run) -> list[dict]:
    return json.loads(run(["docker", kind, "inspect", *ids], capture_output=True,
                          text=True, check=True).stdout)


def record(lane: str, images: tuple[Image, ...], compose: str, suffix: str, root: Path,
           run: Run = subprocess.run) -> dict:
    """The record of the release images the lane's running containers run."""
    referenced = set(_compose(compose, suffix, ["config", "--images"], root, run).split())
    containers = _compose(compose, suffix, ["ps", "--quiet"], root, run).split()
    by_tag = {local_tag(image, suffix): image for image in images}
    image_ids: dict[str, set[str]] = {}
    for container in _inspect("container", containers, run) if containers else []:
        image = by_tag.get(container["Config"]["Image"])
        if image:
            image_ids.setdefault(image.name, set()).add(container["Image"])
    problems = [f"the lane's Compose files run {local_tag(image, suffix)}, and no running "
                "container runs it" for image in images
                if local_tag(image, suffix) in referenced and image.name not in image_ids]
    if not image_ids:
        problems.append(f"no running container of the lane runs a release image named with "
                        f"the suffix {suffix}")
        raise Refused("\n".join(problems))
    every_id = sorted(set().union(*image_ids.values()))
    repo_digests = {entry["Id"]: entry.get("RepoDigests") or []
                    for entry in _inspect("image", every_id, run)}
    recorded: dict[str, str] = {}
    for image in images:
        if image.name not in image_ids:
            continue
        digests = sorted(set().union(*(registry_digests(repo_digests.get(image_id, []))
                                       for image_id in image_ids[image.name])))
        if not digests:
            problems.append(f"{local_tag(image, suffix)} has no repo digest from a registry, "
                            "so it was not pulled: its manifest digest is unknown")
        elif len(digests) > 1:
            problems.append(f"{local_tag(image, suffix)} has repo digests "
                            f"{', '.join(digests)}; the record names one manifest")
        else:
            recorded[image.name] = digests[0]
    if problems:
        raise Refused("\n".join(problems))
    return {"lane": lane, "image_suffix": suffix, "images": recorded}


def record_path(root: Path, lane: str) -> Path:
    return root / SNAPSHOT_DIR / f"e2e-release-images-{lane}.json"


def main(argv: list[str] | None = None, run: Run = subprocess.run,
         root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    pulled = commands.add_parser("pull", help="pull the declared release images")
    pulled.add_argument("--registry", required=True)
    checked = commands.add_parser("check", help="refuse a release image the lane cannot run")
    recorded = commands.add_parser("record", help="record the release images the lane runs")
    recorded.add_argument("--lane", required=True)
    for command in (checked, recorded):
        command.add_argument("--compose", required=True,
                             help="the lane's Compose arguments, as one string")
    for command in (pulled, checked, recorded):
        command.add_argument("--suffix", required=True)
    args = parser.parse_args(argv)
    if not args.suffix.strip():
        parser.error("IMAGE_SUFFIX is required: a candidate's images are named by its "
                     "revision, as -<rev9>")
    if args.command == "pull" and not args.registry.strip():
        parser.error("DOCKER_REGISTRY is required")
    try:
        images = load(root / DECLARATION_PATH).images
        if args.command == "pull":
            pull(args.registry, images, args.suffix, run)
        elif args.command == "check":
            problems = check_problems(images, args.compose, args.suffix, root, run)
            if problems:
                raise Refused("\n".join(problems))
            print(f"OK: every release image the lane runs is present with the suffix "
                  f"{args.suffix}.")
        else:
            document = record(args.lane, images, args.compose, args.suffix, root, run)
            text = json.dumps(document, indent=2) + "\n"
            path = record_path(root, args.lane)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(text, end="")
    except (DeclarationError, Refused) as error:
        for line in str(error).splitlines():
            print(f"release_images: {line}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip() if isinstance(error.stderr, str) else ""
        print(f"release_images: {shlex.join(map(str, error.cmd))} failed"
              + (f": {detail}" if detail else ""), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
