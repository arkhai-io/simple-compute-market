#!/usr/bin/env python3
"""Load a release candidate: store every declared component of HEAD under its revision.

A release candidate is a default-branch commit loaded under its nine-character
revision; the deployment validates it from there. One invocation binds the
stored wheels to the images validated, in this order:

1. build the wheelhouse once (`make dist`) and check its versions against every
   earlier marketplace release (`make check-release-versions`), then take its
   digest (`scripts/wheelhouse_digest.py`);
2. remove each declared image's and development image's local revision tag, so
   that a tag an earlier build of this revision left cannot pass for this load's;
   build the market binary, the chart's package and every declared image and
   development image from that wheelhouse (`make build-candidate`, with no
   image suffix, so each image's revision tag is written); and confirm each
   declared component exists;
3. refuse, naming what differs, unless the wheelhouse's digest is still the one
   step 1 took and every image labelled with a wheelhouse digest carries it.
   An image whose build installs from the wheelhouse records the label
   (a test holds every such Dockerfile to it), so an image without one was
   built from no wheelhouse;
4. delete the revision's `wheelhouse`, `chart` and binary versions, all of
   them, before uploading any;
5. upload the declared wheels as the generic package `wheelhouse` and the chart's
   package as `chart`, version `<revision>`, in `<prefix>-candidates`, each
   declared binary as the package of its name in `<prefix>-cli`, and push every
   declared image and development image as `make push-images` does.

A generic upload cannot replace a file its version holds, so without the deletes
a reload would fail part-way after replacing some files. With them, the store
holds exactly one load's declared set for the revision, and a load failing after
the deletes leaves it incomplete, never mixed. No upload keeps an earlier file.

The load does not refuse an edited tree: every identity a release's bill of
materials records is a content identity, and the source revision is the
operator's word. Nothing installs from the development Python index, so the
load does not push to it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from publish_artifacts import (
    Destination,
    Run,
    chart_package,
    push_images,
    upload_binaries,
    upload_generic,
)
from release_components import (
    DECLARATION_PATH,
    REPO_ROOT,
    DeclarationError,
    ReleaseComponents,
    declared_wheels,
    load,
)
from wheelhouse_digest import LABEL, MissingWheels, wheelhouse_digest

CANDIDATES = "candidates"
WHEELHOUSE_PACKAGE = "wheelhouse"
CHART_PACKAGE = "chart"


class LoadRefused(RuntimeError):
    """The load found its components inconsistent and uploaded nothing."""


def _make(root: Path, target: str, run: Run) -> None:
    # IMAGE_SUFFIX is set empty: a suffixed build writes no revision tag.
    run(["make", "--no-print-directory", target, "IMAGE_SUFFIX="], cwd=root, check=True)


def untag(tag: str, run: Run) -> None:
    """Remove the local tag `tag`; the image keeps its other tags, and the build
    cache keeps its layers. A tag that does not exist is already removed."""
    removed = run(["docker", "image", "rm", tag], capture_output=True, text=True)
    if removed.returncode != 0 and "No such image" not in removed.stderr:
        raise LoadRefused(f"cannot remove the earlier {tag}, so this load could not tell "
                          f"its own build from it: {removed.stderr.strip()}")


def image_labels(tag: str, run: Run) -> dict[str, str] | None:
    """The labels of the local image `tag`, or None when there is no such image."""
    inspected = run(["docker", "image", "inspect", "--format", "{{json .Config.Labels}}", tag],
                    capture_output=True, text=True)
    if inspected.returncode != 0:
        return None
    return json.loads(inspected.stdout or "null") or {}


def built_problems(components: ReleaseComponents, root: Path, dist_dir: Path,
                   revision: str, digest: str, run: Run) -> list[str]:
    """What steps 2 and 3 refuse: a declared component the build did not write,
    a wheelhouse whose digest moved, and an image labelled with another digest.
    Step 2 removed every declared image's revision tag first, so a tag found here
    was written by this load's build."""
    problems: list[str] = []
    now = wheelhouse_digest(root, dist_dir)
    if now != digest:
        problems.append(f"the wheelhouse {dist_dir} changed while the load built from it: "
                        f"its digest was {digest} and is now {now}")
    for image in (*components.images, *components.development_images):
        tag = f"arkhai:{image.local}-{revision}"
        labels = image_labels(tag, run)
        if labels is None:
            problems.append(f"{tag} was not built")
        elif LABEL in labels and labels[LABEL] != digest:
            problems.append(f"{tag} was built from another wheelhouse: its {LABEL} is "
                            f"{labels[LABEL] or '(empty)'}, the wheelhouse's is {digest}")
    package = chart_package(components, dist_dir, root)
    if not package.is_file():
        problems.append(f"the chart's package {package} was not built")
    for binary in components.binaries:
        if not (root / binary.path).is_file():
            problems.append(f"the binary {binary.name} was not built at {binary.path}")
    return problems


def delete_version(destination: Destination, repository: str, package: str, version: str,
                   run: Run) -> None:
    """Delete a generic package version with every file it holds; one that does
    not exist is already deleted."""
    deleted = run(["gcloud", "artifacts", "versions", "delete", version,
                   *destination.flags(repository), f"--package={package}", "--quiet"],
                  capture_output=True, text=True)
    if deleted.returncode != 0 and "NOT_FOUND" not in deleted.stderr:
        raise LoadRefused(f"cannot delete {package} {version} from {repository}: "
                          f"{deleted.stderr.strip()}")


def load_candidate(destination: Destination, docker_registry: str, revision: str,
                   root: Path = REPO_ROOT, run: Run = subprocess.run) -> None:
    """Steps 1 to 5, raising before any delete or upload when a check refuses."""
    dist_dir = root / ".dist"
    _make(root, "dist", run)
    _make(root, "check-release-versions", run)
    components = load(root / DECLARATION_PATH)
    digest = wheelhouse_digest(root, dist_dir)

    for image in (*components.images, *components.development_images):
        untag(f"arkhai:{image.local}-{revision}", run)
    _make(root, "build-candidate", run)
    problems = built_problems(components, root, dist_dir, revision, digest, run)
    if problems:
        raise LoadRefused("uploaded nothing:\n" + "\n".join(f"  {line}" for line in problems))

    candidates = destination.repository(CANDIDATES)
    delete_version(destination, candidates, WHEELHOUSE_PACKAGE, revision, run)
    delete_version(destination, candidates, CHART_PACKAGE, revision, run)
    for binary in components.binaries:
        delete_version(destination, destination.repository("cli"), binary.name, revision, run)

    for wheel in declared_wheels(components, root, dist_dir):
        upload_generic(destination, candidates, WHEELHOUSE_PACKAGE, revision, wheel, run)
    upload_generic(destination, candidates, CHART_PACKAGE, revision,
                   chart_package(components, dist_dir, root), run)
    upload_binaries(destination, components.binaries, revision, root, run)
    push_images(docker_registry, components.images, revision, run)
    push_images(docker_registry, components.development_images, revision, run)


def main(argv: list[str] | None = None, run: Run = subprocess.run,
         root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name in ("project", "location", "prefix", "docker-registry", "revision"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args(argv)
    try:
        load_candidate(Destination(args.project, args.location, args.prefix),
                       args.docker_registry, args.revision, root, run)
    except subprocess.CalledProcessError as error:
        command = " ".join(map(str, error.cmd))
        print(f"load-candidate: {command} failed with exit status {error.returncode}",
              file=sys.stderr)
        return 1
    except (LoadRefused, DeclarationError, MissingWheels) as error:
        print(f"load-candidate: {error}", file=sys.stderr)
        return 1
    print(f"OK: release candidate {args.revision} is loaded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
