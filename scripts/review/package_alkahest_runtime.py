from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import inspect
import shutil
import tarfile
from pathlib import Path

DIST_NAME = "alkahest-py"
PACKAGE_NAME = "alkahest_py"
OUTPUT_ROOT = Path(".snapshot/alkahest-runtime")
ARCHIVE_PATH = Path(".snapshot/alkahest-runtime.tar.gz")


def package_root() -> Path:
    spec = importlib.util.find_spec(PACKAGE_NAME)
    if spec is None or not spec.submodule_search_locations:
        raise SystemExit(f"{PACKAGE_NAME!r} is not installed")
    return Path(next(iter(spec.submodule_search_locations))).resolve()


def copy_package(root: Path) -> None:
    destination = OUTPUT_ROOT / "package" / PACKAGE_NAME
    shutil.copytree(
        root,
        destination,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
        ),
    )


def copy_distribution_metadata() -> None:
    distribution = importlib.metadata.distribution(DIST_NAME)
    destination = OUTPUT_ROOT / "metadata"
    destination.mkdir(parents=True, exist_ok=True)

    for relative_path in distribution.files or ():
        path = Path(distribution.locate_file(relative_path)).resolve()
        if not path.is_file():
            continue
        if ".dist-info" not in path.parts and ".egg-info" not in path.parts:
            continue

        target = destination / path.name
        shutil.copy2(path, target)


def describe_object(output, label: str, obj: object) -> None:
    output.write(f"\n## {label}\n")
    output.write(f"repr: {obj!r}\n")
    output.write(f"type: {type(obj)!r}\n")

    try:
        output.write(f"signature: {inspect.signature(obj)}\n")
    except (TypeError, ValueError):
        pass

    output.write("members:\n")
    for name in sorted(dir(obj)):
        if name.startswith("__"):
            continue

        try:
            member = getattr(obj, name)
        except Exception as exc:
            output.write(f"  {name}: <error {exc!r}>\n")
            continue

        try:
            signature = str(inspect.signature(member))
        except (TypeError, ValueError):
            signature = ""

        output.write(
            f"  {name}{signature}: {type(member).__module__}."
            f"{type(member).__qualname__}\n"
        )


def write_introspection() -> None:
    package = importlib.import_module(PACKAGE_NAME)

    with (OUTPUT_ROOT / "introspection.txt").open(
        "w",
        encoding="utf-8",
    ) as output:
        describe_object(output, PACKAGE_NAME, package)

        relevant_names = (
            "AlkahestClient",
            "StringObligationClient",
            "Attestation",
            "Attested",
            "AttestationRequest",
            "AttestationRequestData",
            "EnvTestManager",
        )

        for name in relevant_names:
            if hasattr(package, name):
                describe_object(output, name, getattr(package, name))


def write_binary_symbols(root: Path) -> None:
    shared_objects = sorted(root.rglob("*.so"))

    with (OUTPUT_ROOT / "shared-objects.txt").open(
        "w",
        encoding="utf-8",
    ) as output:
        for path in shared_objects:
            output.write(f"{path}\n")


def create_archive() -> None:
    if ARCHIVE_PATH.exists():
        ARCHIVE_PATH.unlink()

    with tarfile.open(ARCHIVE_PATH, "w:gz") as archive:
        archive.add(OUTPUT_ROOT, arcname=OUTPUT_ROOT.name)


def main() -> None:
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    OUTPUT_ROOT.mkdir(parents=True)

    root = package_root()
    copy_package(root)
    copy_distribution_metadata()
    write_introspection()
    write_binary_symbols(root)
    create_archive()

    print(ARCHIVE_PATH)


if __name__ == "__main__":
    main()