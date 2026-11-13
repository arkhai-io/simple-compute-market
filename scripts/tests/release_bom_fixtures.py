"""Build layout-1 bills of materials, and scratch repositories whose releases
carry them, for the release-record tests.

Every digest these builders take is a synthetic placeholder chosen by a test; none
names a real artifact.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from release_bom import PATH, PUBLIC_VCS_URL


def wheel(dist: str, version: str, sha256: str) -> dict[str, Any]:
    file_name = f"{dist.replace('-', '_')}-{version}-py3-none-any.whl"
    return {
        "type": "library",
        "bom-ref": f"wheel/{dist}",
        "name": dist,
        "version": version,
        "hashes": [{"alg": "SHA-256", "content": sha256}],
        "purl": f"pkg:pypi/{dist}@{version}?file_name={file_name}",
    }


def image(name: str, sha256: str, revision: str) -> dict[str, Any]:
    return {
        "type": "container",
        "bom-ref": f"image/{name}",
        "name": name,
        "hashes": [{"alg": "SHA-256", "content": sha256}],
        "purl": f"pkg:oci/arkhai@sha256%3A{sha256}?tag={name}-{revision[:9]}",
    }


def chart(name: str, version: str, content_digest: str) -> dict[str, Any]:
    return {
        "type": "application",
        "bom-ref": f"chart/{name}",
        "name": name,
        "version": version,
        "properties": [{"name": "arkhai:content-digest", "value": content_digest}],
    }


def binary(name: str, sha256: str) -> dict[str, Any]:
    return {
        "type": "application",
        "bom-ref": f"binary/{name}",
        "name": name,
        "hashes": [{"alg": "SHA-256", "content": sha256}],
        "properties": [{"name": "arkhai:platform", "value": "linux/amd64"}],
    }


def npm(name: str, version: str, sha512: str) -> dict[str, Any]:
    return {
        "type": "library",
        "bom-ref": f"npm/{name}",
        "group": "@arkhai",
        "name": name,
        "version": version,
        "hashes": [{"alg": "SHA-512", "content": sha512}],
    }


def document(version: str, revision: str, components: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "lifecycles": [{"phase": "post-build"}],
            "component": {
                "type": "application",
                "bom-ref": "marketplace",
                "name": "marketplace",
                "version": version,
                "externalReferences": [{"type": "vcs", "url": PUBLIC_VCS_URL}],
                "properties": [
                    {"name": "arkhai:bom-layout", "value": "1"},
                    {"name": "arkhai:source-revision", "value": revision},
                ],
            },
        },
        "components": sorted(components, key=lambda component: component["bom-ref"]),
    }


def serialize(value: dict[str, Any]) -> bytes:
    """Layout 1's serialization: two-space indent, LF, a trailing newline."""
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def digest(fill: str) -> str:
    """A placeholder SHA-256 hex digest, `fill` repeated to 64 characters."""
    return (fill * 64)[:64]


DECLARATION = {
    "distributions": [
        {"key": "core", "path": "core", "dist": "arkhai-core"},
        {"key": "core-buyer", "path": "core/buyer", "dist": "arkhai-core-buyer"},
    ],
    "images": [
        {"name": "registry", "local": "registry"},
        {"name": "provisioning", "local": "compute-provisioning"},
    ],
    "chart": {"path": "helm"},
    "binaries": [{"name": "market", "target": "build-market-binary", "path": ".dist/bin/market"}],
    "development_images": [{"name": "dev-env", "local": "dev-env"}],
}


class Repository:
    """A scratch repository on `main` holding a release declaration, two projects
    and a chart, in which releases are cut as the release procedure cuts them.

    The caller isolates git from the user's configuration and gives it an identity.
    """

    def __init__(self, root: Path):
        self.root = root
        root.mkdir()
        self.git("init", "-q", "-b", "main")
        self.write({
            "manifests/release-components.json": json.dumps(DECLARATION, indent=2) + "\n",
            "core/pyproject.toml": '[project]\nname = "arkhai-core"\nversion = "0.1.0"\n',
            "core/buyer/pyproject.toml":
                '[project]\nname = "arkhai-core-buyer"\nversion = "0.1.0"\n',
            "helm/Chart.yaml": "apiVersion: v2\nname: chart\nversion: 0.1.0\n",
        })
        self.commit("the source")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True,
                              text=True).stdout.strip()

    def write(self, files: dict[str, str | bytes]) -> None:
        for path, content in files.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                target.write_bytes(content)
            else:
                target.write_text(content, encoding="utf-8")

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def head(self, ref: str = "HEAD") -> str:
        return self.git("rev-parse", ref)

    def cut(self, semver: str, bom: bytes | None = None, *, at: str = "main",
            branch: str | None = None, extra: dict[str, str | bytes] | None = None,
            components: list[dict[str, Any]] | None = None, revision: str | None = None) -> str:
        """Cut a release at `at`: a branch, one commit adding `bom` (by default a
        well-formed record of the declared components) and an annotated tag."""
        point = self.head(at)
        self.git("checkout", "-q", "-b", branch or f"releases/{semver}", point)
        if bom is None:
            bom = serialize(document(semver, revision or point,
                                     components if components is not None
                                     else declared_components(point)))
        self.write({PATH: bom, **(extra or {})})
        commit = self.commit(f"record marketplace {semver}")
        self.git("tag", "-a", f"marketplace-v{semver}", "-m", f"marketplace {semver}")
        self.git("checkout", "-q", "main")
        return commit


def declared_components(revision: str, *, core: tuple[str, str] = ("0.1.0", digest("1")),
                        buyer: tuple[str, str] = ("0.1.0", digest("2")),
                        chart_identity: tuple[str, str] = ("0.1.0", digest("3"))
                        ) -> list[dict[str, Any]]:
    """A record naming every release component `DECLARATION` declares, once."""
    return [
        wheel("arkhai-core", *core),
        wheel("arkhai-core-buyer", *buyer),
        image("registry", digest("4"), revision),
        image("provisioning", digest("5"), revision),
        chart("chart", *chart_identity),
        binary("market", digest("6")),
    ]
