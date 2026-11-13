"""Read a marketplace release's bill of materials, in layout 1, and compute the
content digests it records.

A marketplace release is recorded by one commit on its release branch that adds
`manifests/release-bom.cdx.json`. The deployment that validated the release
builds that document and owns its format; this repository reads it in
`make check-release-versions` and `make check-release-record`, and only in the
layout it knows. Layout 1 is CycloneDX 1.6:

- the subject, `metadata.component`, is the release: bom-ref and name
  `marketplace`, the release semver, the repository's public vcs link, and the
  properties `arkhai:bom-layout` = `1` and `arkhai:source-revision`, the full
  commit every component was built from;
- each component has bom-ref `<kind>/<name>` and one content identity: a wheel
  its SHA-256 and a `pkg:pypi` purl naming its file, an image its manifest
  digest and a `pkg:oci` purl tagged `<name>-<rev9>`, the chart its version and
  `arkhai:content-digest`, the binary its SHA-256 and `arkhai:platform`, and an
  npm package its version and SHA-512.

The document's identity is the SHA-256 of its bytes as committed, so the reader
digests those bytes and never re-serializes them. It refuses a layout it does
not know, and in layout 1 any field, purl qualifier or URL the layout does not
admit: the document is committed to a public repository, so it may carry
content identities and nothing else, in particular no registry host, project or
path (`AGENTS.md`, "Public repository discipline").

The chart's content digest is a dirhash of a `helm package` archive's regular
files, computed from the archive rather than the chart's directory because Helm
rewrites every `Chart.yaml` it packages. That rewrite may differ between Helm
versions, so the chart is packaged only by the Helm `.helm-version` pins.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tarfile
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from release_components import REPO_ROOT, chart_field

PATH = "manifests/release-bom.cdx.json"
LAYOUT = "1"
PUBLIC_VCS_URL = "https://github.com/arkhai-io/simple-compute-market"
HELM_VERSION_FILE = ".helm-version"

KINDS = ("wheel", "image", "chart", "binary", "npm")

_HEX = {"SHA-256": re.compile(r"^[0-9a-f]{64}$"), "SHA-512": re.compile(r"^[0-9a-f]{128}$")}
_SHA256 = _HEX["SHA-256"]
_REVISION = re.compile(r"^[0-9a-f]{40}$")
SEMVER = r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?"
_SEMVER = re.compile(rf"^{SEMVER}$")
# Every version layout 1 records — a wheel's, the chart's, an npm package's —
# begins with a digit.
_VERSION = re.compile(r"^[0-9][0-9A-Za-z.+!-]*$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")

_HEADER_KEYS = ("bomFormat", "specVersion", "version", "metadata", "components")
_METADATA_KEYS = ("lifecycles", "component")
_SUBJECT_KEYS = ("type", "bom-ref", "name", "version", "externalReferences", "properties")

# Each kind's component type and the keys layout 1 gives it.
_COMPONENT_KEYS: dict[str, tuple[str, tuple[str, ...]]] = {
    "wheel": ("library", ("type", "bom-ref", "name", "version", "hashes", "purl")),
    "image": ("container", ("type", "bom-ref", "name", "hashes", "purl")),
    "chart": ("application", ("type", "bom-ref", "name", "version", "properties")),
    "binary": ("application", ("type", "bom-ref", "name", "hashes", "properties")),
    "npm": ("library", ("type", "bom-ref", "group", "name", "version", "hashes")),
}
_HASH_ALGORITHM = {"wheel": "SHA-256", "image": "SHA-256", "binary": "SHA-256", "npm": "SHA-512"}
_NPM_GROUP = "@arkhai"
_PLATFORM = "linux/amd64"


class BomError(ValueError):
    """A bill of materials this reader refuses, or a digest it cannot compute."""


@dataclass(frozen=True)
class Component:
    """One component by its bom-ref, its version where its kind has one, and its
    content identity: the hex digest layout 1 records for its kind."""

    bom_ref: str
    kind: str
    name: str
    version: str | None
    identity: str


@dataclass(frozen=True)
class Bom:
    digest: str
    version: str
    source_revision: str
    components: tuple[Component, ...]

    def by_ref(self) -> dict[str, list[Component]]:
        """Each bom-ref with every component carrying it, in document order."""
        found: dict[str, list[Component]] = {}
        for component in self.components:
            found.setdefault(component.bom_ref, []).append(component)
        return found


def _keys(value: Any, allowed: tuple[str, ...], where: str, problems: list[str]) -> bool:
    if not isinstance(value, dict):
        problems.append(f"{where} is not an object")
        return False
    for key in value:
        if key not in allowed:
            problems.append(f"{where} has field {key!r}, which layout 1 does not admit")
    for key in allowed:
        if key not in value:
            problems.append(f"{where} has no {key!r}")
    return True


def _string(value: Any, pattern: re.Pattern[str], where: str, problems: list[str]) -> str | None:
    if isinstance(value, str) and pattern.match(value):
        return value
    problems.append(f"{where} is {json.dumps(value)}, which layout 1 does not admit")
    return None


def _properties(value: Any, names: tuple[str, ...], where: str,
                problems: list[str]) -> dict[str, Any]:
    """The named properties, refusing any other or a repeated one."""
    if not isinstance(value, list):
        problems.append(f"{where}.properties is not a list")
        return {}
    found: dict[str, Any] = {}
    for index, item in enumerate(value):
        at = f"{where}.properties[{index}]"
        if not _keys(item, ("name", "value"), at, problems):
            continue
        name = item.get("name")
        if name not in names:
            problems.append(f"{at} is property {json.dumps(name)}, which layout 1 does not admit")
        elif name in found:
            problems.append(f"{where} has property {name!r} twice")
        else:
            found[name] = item.get("value")
    for name in names:
        if name not in found:
            problems.append(f"{where} has no property {name!r}")
    return found


def _hash(value: Any, algorithm: str, where: str, problems: list[str]) -> str | None:
    if not isinstance(value, list) or len(value) != 1:
        problems.append(f"{where}.hashes is not one {algorithm} hash")
        return None
    entry = value[0]
    if not _keys(entry, ("alg", "content"), f"{where}.hashes[0]", problems):
        return None
    if entry.get("alg") != algorithm:
        problems.append(f"{where}.hashes[0].alg is {json.dumps(entry.get('alg'))}, not {algorithm!r}")
        return None
    return _string(entry.get("content"), _HEX[algorithm], f"{where}.hashes[0].content", problems)


def _purl(component: dict[str, Any], kind: str, name: str, version: str | None,
          identity: str | None, revision: str | None, where: str,
          problems: list[str]) -> None:
    purl = component.get("purl")
    if not isinstance(purl, str):
        problems.append(f"{where}.purl is not a string")
        return
    if "repository_url=" in purl:
        problems.append(f"{where}.purl carries a repository_url, which names a registry")
        return
    if kind == "wheel":
        file_name = re.escape(re.sub(r"[-_.]+", "_", name))
        pattern = (rf"^pkg:pypi/{re.escape(name)}@{re.escape(version or '')}"
                   rf"\?file_name=(?i:{file_name})-{re.escape(version or '')}-[A-Za-z0-9_.-]+\.whl$")
        expected = f"pkg:pypi/{name}@{version}?file_name=<its wheel file>"
    else:
        tag = f"{name}-{revision[:9]}" if revision else f"{name}-<rev9>"
        pattern = rf"^pkg:oci/arkhai@sha256%3A{re.escape(identity or '')}\?tag={re.escape(tag)}$"
        expected = f"pkg:oci/arkhai@sha256%3A<its digest>?tag={tag}"
    if not re.match(pattern, purl):
        problems.append(f"{where}.purl is {json.dumps(purl)}, not {expected}")


def _component(value: Any, index: int, revision: str | None,
               problems: list[str]) -> Component | None:
    where = f"components[{index}]"
    bom_ref = value.get("bom-ref") if isinstance(value, dict) else None
    kind, _, name = bom_ref.partition("/") if isinstance(bom_ref, str) else ("", "", "")
    if kind not in _COMPONENT_KEYS:
        problems.append(f"{where} has bom-ref {json.dumps(bom_ref)}, not <kind>/<name> "
                        f"with a kind of {', '.join(KINDS)}")
        return None
    where = bom_ref
    component_type, keys = _COMPONENT_KEYS[kind]
    before = len(problems)
    if not _keys(value, keys, where, problems) or len(problems) > before:
        return None
    if value.get("type") != component_type:
        problems.append(f"{where}.type is {json.dumps(value.get('type'))}, not {component_type!r}")
    if _string(name, _NAME, f"{where} name", problems) and value.get("name") != name:
        problems.append(f"{where}.name is {json.dumps(value.get('name'))}, not {name!r}")
    version = None
    if "version" in keys:
        version = _string(value.get("version"), _VERSION, f"{where}.version", problems)
    identity = None
    if kind in _HASH_ALGORITHM:
        identity = _hash(value.get("hashes"), _HASH_ALGORITHM[kind], where, problems)
    if kind in ("wheel", "image"):
        _purl(value, kind, name, version, identity, revision, where, problems)
    if kind == "chart":
        digest = _properties(value.get("properties"), ("arkhai:content-digest",), where, problems)
        if "arkhai:content-digest" in digest:
            identity = _string(digest["arkhai:content-digest"], _SHA256,
                               f"{where} arkhai:content-digest", problems)
    if kind == "binary":
        platform = _properties(value.get("properties"), ("arkhai:platform",), where, problems)
        if "arkhai:platform" in platform and platform["arkhai:platform"] != _PLATFORM:
            problems.append(f"{where} arkhai:platform is {json.dumps(platform['arkhai:platform'])}, "
                            f"not {_PLATFORM!r}")
    if kind == "npm" and value.get("group") != _NPM_GROUP:
        problems.append(f"{where}.group is {json.dumps(value.get('group'))}, not {_NPM_GROUP!r}")
    if len(problems) > before or identity is None:
        return None
    return Component(bom_ref=bom_ref, kind=kind, name=name, version=version, identity=identity)


class _RepeatedKey(ValueError):
    pass


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """An object's members, refusing a key stated twice: JSON parsers keep one copy
    or the other, so a repeated key could hide a field from this reader."""
    found: dict[str, Any] = {}
    for key, value in pairs:
        if key in found:
            raise _RepeatedKey(key)
        found[key] = value
    return found


def _urls(value: Any, where: str, found: list[str]) -> None:
    """Every location holding a string that is a URL, a component's named by its
    bom-ref."""
    if isinstance(value, dict):
        for key, item in value.items():
            _urls(item, f"{where}.{key}" if where else key, found)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            label = f"{where}[{index}]"
            if where == "components" and isinstance(item, dict) and isinstance(
                    item.get("bom-ref"), str):
                label = item["bom-ref"]
            _urls(item, label, found)
    elif isinstance(value, str) and _URL.search(value):
        found.append(where)


def layout(document: Any) -> Any:
    """The `arkhai:bom-layout` the document's subject states, or None."""
    try:
        properties = document["metadata"]["component"]["properties"]
    except (KeyError, TypeError):
        return None
    if not isinstance(properties, list):
        return None
    for item in properties:
        if isinstance(item, dict) and item.get("name") == "arkhai:bom-layout":
            return item.get("value")
    return None


def parse(data: bytes, source: str = PATH) -> Bom:
    """The bill of materials in `data`, or `BomError` naming every problem.

    `Bom.digest` is the SHA-256 of `data` exactly as given.
    """
    try:
        document = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BomError(f"{source}: not UTF-8 JSON: {error}") from error
    except _RepeatedKey as error:
        raise BomError(f"{source}: an object states {str(error)!r} twice; a reader taking "
                       "either copy would read another document") from error
    stated = layout(document)
    if stated != LAYOUT:
        raise BomError(f"{source}: arkhai:bom-layout is {json.dumps(stated)}; "
                       f"this reader knows only layout {LAYOUT}")

    problems: list[str] = []
    _keys(document, _HEADER_KEYS, "the document", problems)
    for key, expected in (("bomFormat", "CycloneDX"), ("specVersion", "1.6"), ("version", 1)):
        # Compared with its type, since Python takes `true` and `1.0` to equal 1.
        if key in document and (type(document[key]), document[key]) != (type(expected), expected):
            problems.append(f"{key} is {json.dumps(document[key])}, not {json.dumps(expected)}")

    metadata = document.get("metadata")
    subject: dict[str, Any] = {}
    if _keys(metadata, _METADATA_KEYS, "metadata", problems):
        if metadata.get("lifecycles") != [{"phase": "post-build"}]:
            problems.append("metadata.lifecycles is not [{\"phase\": \"post-build\"}]")
        if _keys(metadata.get("component"), _SUBJECT_KEYS, "the subject", problems):
            subject = metadata["component"]
    version = revision = None
    if subject:
        for key, expected in (("type", "application"), ("bom-ref", "marketplace"),
                              ("name", "marketplace")):
            if subject.get(key) != expected:
                problems.append(f"the subject's {key} is {json.dumps(subject.get(key))}, "
                                f"not {expected!r}")
        version = _string(subject.get("version"), _SEMVER, "the subject's version", problems)
        if subject.get("externalReferences") != [{"type": "vcs", "url": PUBLIC_VCS_URL}]:
            problems.append("the subject's externalReferences are not the one vcs link "
                            f"{PUBLIC_VCS_URL}")
        properties = _properties(subject.get("properties"),
                                 ("arkhai:bom-layout", "arkhai:source-revision"),
                                 "the subject", problems)
        if "arkhai:source-revision" in properties:
            revision = _string(properties["arkhai:source-revision"], _REVISION,
                               "the subject's arkhai:source-revision", problems)

    components: list[Component] = []
    raw_components = document.get("components")
    if isinstance(raw_components, list):
        for index, value in enumerate(raw_components):
            component = _component(value, index, revision, problems)
            if component is not None:
                components.append(component)
    elif "components" in document:
        problems.append("components is not a list")

    urls: list[str] = []
    _urls(document, "", urls)
    for where in urls:
        if where != "metadata.component.externalReferences[0].url":
            problems.append(f"{where} holds a URL; the only URL layout 1 admits is the vcs link")

    if problems:
        raise BomError(f"{source}:\n" + "\n".join(f"  {line}" for line in problems))
    assert version is not None and revision is not None
    return Bom(digest=hashlib.sha256(data).hexdigest(), version=version,
               source_revision=revision, components=tuple(components))


def dirhash(files: Iterable[tuple[str, bytes]]) -> str:
    """The content digest of a set of files, each given by its path and contents.

    Its lines, one per file in bytewise order of path, are the file's lowercase
    SHA-256 hex, two spaces, its path and a newline; the digest is the lowercase
    SHA-256 hex of those lines. Only the paths and contents enter it, so two
    archives holding the same files under different metadata share a digest.
    """
    entries = sorted(files, key=lambda entry: entry[0].encode("utf-8"))
    paths = [path for path, _ in entries]
    for path in paths:
        if "\n" in path or not path:
            raise BomError(f"cannot digest a file named {path!r}")
    repeated = sorted({path for path in paths if paths.count(path) > 1})
    if repeated:
        raise BomError("cannot digest two files at one path: " + ", ".join(repeated))
    lines = "".join(f"{hashlib.sha256(data).hexdigest()}  {path}\n" for path, data in entries)
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def files_digest(paths: Iterable[Path]) -> str:
    """The dirhash of files named by their base names, as the wheelhouse digest is."""
    return dirhash((path.name, path.read_bytes()) for path in paths)


def archive_digest(archive: Path) -> str:
    """The dirhash of a gzipped tar archive's regular files, by archive path.

    A file is its path and contents, so a path the archive stores more than once
    with the same contents is one file: `helm package` stores each subchart of a
    chart whose dependencies live under its `charts/` directory twice. A path
    stored twice with different contents is refused, since which copy a reader
    takes is then the reader's choice.
    """
    files: dict[str, bytes] = {}
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isreg():
                continue
            handle = tar.extractfile(member)
            assert handle is not None
            data = handle.read()
            if files.setdefault(member.name, data) != data:
                raise BomError(f"{archive.name} stores {member.name} twice with different "
                               "contents")
    return dirhash(files.items())


def run_helm(args: list[str]) -> str:
    """Run Helm and return its standard output."""
    result = subprocess.run(["helm", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise BomError(f"helm {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def pinned_helm(root: Path = REPO_ROOT) -> str:
    """The Helm release `.helm-version` pins, such as `v4.3.0`."""
    pin = root / HELM_VERSION_FILE
    try:
        version = pin.read_text(encoding="utf-8").strip()
    except FileNotFoundError as error:
        raise BomError(f"{pin} is missing") from error
    if not re.match(r"^v\d+\.\d+\.\d+$", version):
        raise BomError(f"{pin} holds {version!r}, not a Helm release such as v4.3.0")
    return version


@dataclass(frozen=True)
class ChartPackage:
    name: str
    version: str
    content_digest: str


def package_chart(chart_dir: Path, root: Path = REPO_ROOT,
                  helm: Callable[[list[str]], str] = run_helm) -> ChartPackage:
    """Package the chart at `chart_dir` with the pinned Helm, as `make dist-helm`
    does, and return its name, version and content digest.

    Refuses under any other Helm, whose `Chart.yaml` rewrite may differ.
    """
    pinned = pinned_helm(root)
    reported = helm(["version", "--short"]).strip()
    if reported.split("+", 1)[0] != pinned:
        raise BomError(f"the chart's content digest needs Helm {pinned} ({HELM_VERSION_FILE}); "
                       f"`helm version --short` reports {reported or 'nothing'}")
    chart_yaml = (chart_dir / "Chart.yaml").read_text(encoding="utf-8")
    name, version = chart_field(chart_yaml, "name"), chart_field(chart_yaml, "version")
    if not name or not version:
        raise BomError(f"{chart_dir / 'Chart.yaml'} states no name or no version")
    with tempfile.TemporaryDirectory() as destination:
        helm(["package", str(chart_dir), "--destination", destination])
        archive = Path(destination) / f"{name}-{version}.tgz"
        if not archive.is_file():
            raise BomError(f"helm package wrote no {archive.name}")
        return ChartPackage(name=name, version=version, content_digest=archive_digest(archive))
