"""The layout-1 bill-of-materials reader, the dirhash, and the pinned Helm.

The fixture is an example document in layout 1, written one key per line at
two-space indent. Its digests and revision are placeholders.

The unit cases stub Helm at the reader's own wrapper. The real-Helm cases package
the deployment chart with the pinned release; they skip where it is not on PATH,
except under `HELM_REQUIRED=1`, which CI's packaging job sets, where a skip is a
failure.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
from collections import Counter
from pathlib import Path

import pytest

from release_bom import (
    PUBLIC_VCS_URL,
    BomError,
    archive_digest,
    dirhash,
    files_digest,
    package_chart,
    parse,
    pinned_helm,
    run_helm,
)
from release_components import REPO_ROOT

FIXTURE = Path(__file__).parent / "fixtures" / "release-bom-layout1.cdx.json"
REVISION = "0123456789abcdef0123456789abcdef01234567"

# SHA-256 of the empty string and of "abc", the standard's own test vectors.
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
ABC_SHA256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_bytes())


def _bytes(document: dict) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode("utf-8")


def _refusal(document: dict) -> str:
    with pytest.raises(BomError) as refused:
        parse(_bytes(document))
    return str(refused.value)


def _component(document: dict, bom_ref: str) -> dict:
    return next(item for item in document["components"] if item["bom-ref"] == bom_ref)


# The reader


def test_the_fixture_parses_into_its_subject_and_components() -> None:
    data = FIXTURE.read_bytes()

    bom = parse(data)

    assert bom.version == "0.4.0"
    assert bom.source_revision == REVISION
    assert bom.digest == hashlib.sha256(data).hexdigest()
    by_ref = bom.by_ref()
    assert sorted(by_ref) == ["binary/market", "chart/arkhai-node-operator",
                              "image/provisioning", "image/registry", "wheel/arkhai-core",
                              "wheel/arkhai-core-buyer"]
    core = by_ref["wheel/arkhai-core"][0]
    assert (core.kind, core.name, core.version, core.identity) == (
        "wheel", "arkhai-core", "0.9.0", "1" * 64)
    chart = by_ref["chart/arkhai-node-operator"][0]
    assert (chart.version, chart.identity) == ("0.5.0", "4" * 64)
    assert by_ref["image/registry"][0].identity == "2" * 64
    assert by_ref["binary/market"][0].version is None


def test_the_digest_is_of_the_bytes_as_committed() -> None:
    document = _fixture()
    compact = json.dumps(document).encode("utf-8")

    assert parse(compact).digest == hashlib.sha256(compact).hexdigest()
    assert parse(compact).digest != parse(_bytes(document)).digest


def test_a_component_named_twice_is_kept_for_the_record_check_to_name() -> None:
    document = _fixture()
    document["components"].append(copy.deepcopy(_component(document, "image/registry")))

    assert len(parse(_bytes(document)).by_ref()["image/registry"]) == 2


@pytest.mark.parametrize("value", ["2", 1, None])
def test_an_unknown_layout_is_refused_and_named(value) -> None:
    document = _fixture()
    properties = document["metadata"]["component"]["properties"]
    if value is None:
        properties.pop(0)
    else:
        properties[0]["value"] = value

    message = _refusal(document)

    assert "arkhai:bom-layout is " + json.dumps(None if value is None else value) in message
    assert "only layout 1" in message


def test_an_unknown_field_is_refused_and_named() -> None:
    document = _fixture()
    document["serialNumber"] = "urn:uuid:00000000-0000-0000-0000-000000000000"
    _component(document, "wheel/arkhai-core")["supplier"] = {"name": "anyone"}
    document["metadata"]["component"]["properties"].append({"name": "arkhai:built-by",
                                                            "value": "someone"})

    message = _refusal(document)

    assert "the document has field 'serialNumber'" in message
    assert "wheel/arkhai-core has field 'supplier'" in message
    assert "property \"arkhai:built-by\"" in message


def test_a_repository_url_in_a_purl_is_refused_and_names_the_component() -> None:
    document = _fixture()
    component = _component(document, "image/registry")
    component["purl"] += "&repository_url=registry.example.invalid/project/docker"

    message = _refusal(document)

    assert "image/registry.purl carries a repository_url" in message


@pytest.mark.parametrize("change", ["vcs link", "extra link", "url in a value"])
def test_a_foreign_url_is_refused_and_named(change: str) -> None:
    document = _fixture()
    subject = document["metadata"]["component"]
    if change == "vcs link":
        subject["externalReferences"][0]["url"] = "https://example.invalid/fork"
    elif change == "extra link":
        subject["externalReferences"].append({"type": "distribution",
                                              "url": "https://example.invalid/dist"})
    else:
        _component(document, "binary/market")["properties"][0]["value"] = "https://example.invalid"

    message = _refusal(document)

    if change == "url in a value":
        assert "binary/market.properties[0].value holds a URL" in message
    else:
        assert f"not the one vcs link {PUBLIC_VCS_URL}" in message
    if change == "extra link":
        assert "externalReferences[1].url holds a URL" in message


def test_a_key_stated_twice_is_refused_so_no_copy_can_hide_a_field() -> None:
    clean = '"purl": "pkg:pypi/arkhai-core@0.9.0?file_name=arkhai_core-0.9.0-py3-none-any.whl"'
    hidden = clean[:-1] + '&repository_url=registry.example.invalid/project"'
    data = FIXTURE.read_text(encoding="utf-8").replace(clean, f"{hidden},\n      {clean}")

    with pytest.raises(BomError, match="an object states 'purl' twice"):
        parse(data.encode("utf-8"))


def test_the_header_values_are_compared_with_their_json_type() -> None:
    document = _fixture()
    document["version"] = True

    assert "version is true, not 1" in _refusal(document)


def test_a_wheels_purl_names_its_own_file() -> None:
    document = _fixture()
    _component(document, "wheel/arkhai-core")["purl"] = (
        "pkg:pypi/arkhai-core@0.9.0?file_name=arkhai_kit_other-0.9.0-py3-none-any.whl")

    assert "wheel/arkhai-core.purl is " in _refusal(document)


def test_metadata_lifecycles_and_properties_are_layout_1s() -> None:
    document = _fixture()
    document["metadata"]["lifecycles"] = [{"phase": "build"}]
    _component(document, "binary/market")["properties"].append(
        {"name": "arkhai:platform", "value": "linux/amd64"})

    message = _refusal(document)

    assert "metadata.lifecycles is not" in message
    assert "binary/market has property 'arkhai:platform' twice" in message


def test_each_kind_holds_its_own_identity() -> None:
    document = _fixture()
    _component(document, "wheel/arkhai-core")["hashes"][0]["alg"] = "SHA-512"
    _component(document, "image/registry")["purl"] = (
        "pkg:oci/arkhai@sha256%3A" + "2" * 64 + "?tag=registry-latest")
    _component(document, "binary/market")["properties"][0]["value"] = "darwin/arm64"
    chart = _component(document, "chart/arkhai-node-operator")
    chart["properties"][0]["value"] = "sha256:" + "4" * 64

    message = _refusal(document)

    assert "wheel/arkhai-core.hashes[0].alg is \"SHA-512\", not 'SHA-256'" in message
    assert "image/registry.purl" in message and "tag=registry-012345678" in message
    assert "binary/market arkhai:platform is \"darwin/arm64\"" in message
    assert "chart/arkhai-node-operator arkhai:content-digest" in message


def test_a_bom_ref_must_be_a_known_kind_and_match_its_name() -> None:
    document = _fixture()
    _component(document, "binary/market")["bom-ref"] = "tarball/market"
    _component(document, "wheel/arkhai-core")["name"] = "arkhai-kit-core"

    message = _refusal(document)

    assert "bom-ref \"tarball/market\", not <kind>/<name>" in message
    assert "wheel/arkhai-core.name is \"arkhai-kit-core\", not 'arkhai-core'" in message


def test_an_npm_package_carries_its_group_and_sha512() -> None:
    document = _fixture()
    document["components"].append({
        "type": "library", "bom-ref": "npm/credits-middleware", "group": "@arkhai",
        "name": "credits-middleware", "version": "0.2.0",
        "hashes": [{"alg": "SHA-512", "content": "6" * 128}]})

    npm = parse(_bytes(document)).by_ref()["npm/credits-middleware"][0]

    assert (npm.version, npm.identity) == ("0.2.0", "6" * 128)

    document["components"][-1]["group"] = "@someone"
    document["components"][-1]["hashes"] = [{"alg": "SHA-256", "content": "6" * 64}]
    message = _refusal(document)
    assert "npm/credits-middleware.group is \"@someone\", not '@arkhai'" in message
    assert "npm/credits-middleware.hashes[0].alg is \"SHA-256\", not 'SHA-512'" in message


def test_a_version_begins_with_a_digit_so_it_cannot_carry_a_host() -> None:
    document = _fixture()
    _component(document, "chart/arkhai-node-operator")["version"] = "europe-docker.pkg.dev"

    assert "chart/arkhai-node-operator.version is \"europe-docker.pkg.dev\"" in _refusal(document)


def test_the_header_and_subject_are_layout_1s() -> None:
    document = _fixture()
    document["specVersion"] = "1.5"
    document["metadata"]["component"]["version"] = "next"
    document["metadata"]["component"]["properties"][1]["value"] = REVISION[:9]

    message = _refusal(document)

    assert "specVersion is \"1.5\", not \"1.6\"" in message
    assert "the subject's version is \"next\"" in message
    assert "arkhai:source-revision is \"012345678\"" in message


# The dirhash


def test_the_dirhash_of_a_known_file_set_equals_its_hand_computed_value() -> None:
    # Lines in bytewise path order: "Chart.yaml" sorts before "templates/…"
    # and "values.yaml" because upper case precedes lower case.
    manifest = (f"{ABC_SHA256}  Chart.yaml\n"
                f"{EMPTY_SHA256}  templates/empty.yaml\n"
                f"{ABC_SHA256}  values.yaml\n")

    digest = dirhash([("values.yaml", b"abc"), ("templates/empty.yaml", b""),
                      ("Chart.yaml", b"abc")])

    assert digest == hashlib.sha256(manifest.encode("ascii")).hexdigest()
    assert re.fullmatch(r"[0-9a-f]{64}", digest)


def test_two_files_at_one_path_cannot_be_digested() -> None:
    with pytest.raises(BomError, match="two files at one path: a"):
        dirhash([("a", b"1"), ("a", b"2")])


def _archive(path: Path, files: list[tuple[str, bytes]], mtime: int, uid: int,
             mode: int) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        directory = tarfile.TarInfo("chart")
        directory.type, directory.mtime = tarfile.DIRTYPE, mtime
        tar.addfile(directory)
        for name, data in files:
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.uid, info.mode = len(data), mtime, uid, mode
            tar.addfile(info, io.BytesIO(data))
    return path


def test_two_archives_of_one_file_set_with_different_metadata_give_one_digest(tmp_path) -> None:
    files = [("chart/Chart.yaml", b"name: chart\nversion: 0.1.0\n"),
             ("chart/values.yaml", b"image: {}\n")]

    first = _archive(tmp_path / "first.tgz", files, mtime=0, uid=0, mode=0o644)
    second = _archive(tmp_path / "second.tgz", list(reversed(files)), mtime=1_700_000_000,
                      uid=1000, mode=0o600)

    assert first.read_bytes() != second.read_bytes()
    assert archive_digest(first) == archive_digest(second) == dirhash(files)


def test_a_path_an_archive_stores_twice_with_one_content_is_one_file(tmp_path) -> None:
    files = [("chart/Chart.yaml", b"name: chart\n"), ("chart/charts/sub/values.yaml", b"a: 1\n")]

    archive = _archive(tmp_path / "chart.tgz", files + files[1:], mtime=0, uid=0, mode=0o644)

    assert archive_digest(archive) == dirhash(files)


def test_a_path_an_archive_stores_twice_with_different_contents_is_refused(tmp_path) -> None:
    files = [("chart/charts/sub/Chart.yaml", b"name: sub\n"),
             ("chart/charts/sub/Chart.yaml", b"name: sub\nversion: 0.1.0\n")]

    archive = _archive(tmp_path / "chart.tgz", files, mtime=0, uid=0, mode=0o644)

    with pytest.raises(BomError, match="stores chart/charts/sub/Chart.yaml twice with "
                                       "different contents"):
        archive_digest(archive)


def test_the_wheelhouse_digest_is_the_dirhash_over_file_names(tmp_path) -> None:
    (tmp_path / "a-1.0-py3-none-any.whl").write_bytes(b"abc")
    (tmp_path / "b-1.0-py3-none-any.whl").write_bytes(b"")

    digest = files_digest(sorted(tmp_path.iterdir()))

    assert digest == dirhash([("a-1.0-py3-none-any.whl", b"abc"),
                              ("b-1.0-py3-none-any.whl", b"")])


# The pinned Helm


def test_helm_version_equals_the_release_tests_yml_installs() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    step = re.search(r"uses:\s*azure/setup-helm@\S+\s*\n\s*with:\s*\n\s*version:\s*['\"]?([^'\"\s]+)",
                     workflow)

    assert step, "tests.yml installs no Helm through azure/setup-helm"
    assert step.group(1) == pinned_helm(), (
        "tests.yml's setup-helm version and .helm-version must name the same Helm")


class _StubHelm:
    """Helm at the reader's own wrapper: answers `version` and writes a package."""

    def __init__(self, version: str, files: list[tuple[str, bytes]]):
        self.version, self.files, self.calls = version, files, []

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        if args[0] == "version":
            return self.version + "\n"
        destination = Path(args[args.index("--destination") + 1])
        _archive(destination / "chart-0.1.0.tgz", self.files, mtime=0, uid=0, mode=0o644)
        return ""


def _chart(tmp_path: Path) -> Path:
    chart = tmp_path / "chart"
    chart.mkdir()
    (chart / "Chart.yaml").write_text("apiVersion: v2\nname: chart\nversion: 0.1.0\n", "utf-8")
    (tmp_path / ".helm-version").write_text("v4.3.0\n", "utf-8")
    return chart


def test_no_pin_means_no_chart_digest(tmp_path) -> None:
    chart = _chart(tmp_path)
    (tmp_path / ".helm-version").unlink()

    with pytest.raises(BomError, match=r"\.helm-version is missing"):
        package_chart(chart, root=tmp_path, helm=_StubHelm("v4.3.0", []))


def test_another_helm_is_refused_before_anything_is_packaged(tmp_path) -> None:
    helm = _StubHelm("v4.2.1+g0000000", [])

    with pytest.raises(BomError, match=r"needs Helm v4\.3\.0 .*reports v4\.2\.1\+g0000000"):
        package_chart(_chart(tmp_path), root=tmp_path, helm=helm)

    assert helm.calls == [["version", "--short"]]


def test_the_pinned_helm_packages_and_the_archive_is_digested(tmp_path) -> None:
    files = [("chart/Chart.yaml", b"name: chart\nversion: 0.1.0\n")]
    helm = _StubHelm("v4.3.0+gbec5b06", files)

    package = package_chart(_chart(tmp_path), root=tmp_path, helm=helm)

    assert (package.name, package.version, package.content_digest) == (
        "chart", "0.1.0", dirhash(files))
    assert helm.calls[1][:2] == ["package", str(tmp_path / "chart")]


@pytest.fixture
def pinned_helm_on_path() -> None:
    """Skip without the pinned Helm on PATH, except under `HELM_REQUIRED=1`, which
    CI's packaging job sets, where a skip is a failure."""
    reason = None
    if shutil.which("helm") is None:
        reason = "no helm on PATH"
    elif run_helm(["version", "--short"]).strip().split("+", 1)[0] != pinned_helm():
        reason = f"the helm on PATH is not the {pinned_helm()} .helm-version pins"
    if reason is not None:
        if os.environ.get("HELM_REQUIRED") == "1":
            pytest.fail(reason)
        pytest.skip(reason)


@pytest.mark.usefixtures("pinned_helm_on_path")
def test_the_deployment_chart_packaged_twice_gives_one_content_digest() -> None:
    first = package_chart(REPO_ROOT / "helm")
    second = package_chart(REPO_ROOT / "helm")

    assert first == second
    assert first.name == "arkhai-node-operator"


@pytest.mark.usefixtures("pinned_helm_on_path")
def test_the_pinned_helm_stores_the_subcharts_files_twice(tmp_path) -> None:
    # The premise of counting a repeated path once: the deployment chart keeps its
    # subcharts under charts/, and the pinned Helm archives each of their files twice.
    run_helm(["package", str(REPO_ROOT / "helm"), "--destination", str(tmp_path)])
    archive = next(tmp_path.glob("*.tgz"))
    with tarfile.open(archive, "r:gz") as tar:
        names = Counter(member.name for member in tar.getmembers() if member.isreg())

    repeated = {name for name, count in names.items() if count > 1}
    under_charts = {name for name in names if "/charts/" in name}
    assert repeated == under_charts != set()
    assert set(names.values()) == {1, 2}
