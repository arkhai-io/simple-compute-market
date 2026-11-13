"""The single-enumeration and workflow-credential check, over synthetic files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from check_release_components import (
    check,
    component_patterns,
    makefile_problems,
    workflow_problems,
)
from release_components import parse

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
    "binaries": [{"name": "market", "target": "build-market", "path": ".dist/bin/market"}],
    "development_images": [{"name": "dev-env", "local": "dev-env"}],
}
PATTERNS = component_patterns(parse(DECLARATION), "arkhai-node-operator")

CLEAN_WORKFLOW = """\
name: Tests
on:
  push:
    branches: [dev]
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # A comment naming npm publish or arkhai-core is not a step.
      - name: Download
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: gh release download model-v1 --pattern '*.pt'
      - name: Test
        run: make test
"""


def _workflow(text: str) -> list[str]:
    return workflow_problems("wf.yml", text, PATTERNS)


def _makefile(text: str) -> list[str]:
    return makefile_problems("Makefile", text, PATTERNS)


def test_a_clean_workflow_passes() -> None:
    assert _workflow(CLEAN_WORKFLOW) == []


def test_a_workflow_with_no_top_level_permissions_is_refused() -> None:
    text = CLEAN_WORKFLOW.replace("permissions:\n  contents: read\n", "")

    assert _workflow(text) == [
        "wf.yml: declares no top-level permissions:, so it gets the repository's default "
        "token, which may write"]


@pytest.mark.parametrize("grant", ["id-token", "packages", "attestations", "contents"])
def test_a_write_grant_anywhere_is_refused(grant: str) -> None:
    text = CLEAN_WORKFLOW.replace(
        "    runs-on: ubuntu-latest\n",
        f"    runs-on: ubuntu-latest\n    permissions:\n      {grant}: write\n")

    assert _workflow(text) == [f"wf.yml: grants {grant}: write"]


def test_write_all_is_refused() -> None:
    text = CLEAN_WORKFLOW.replace("permissions:\n  contents: read\n",
                                  "permissions: write-all\n")

    assert _workflow(text) == ["wf.yml: grants permissions: write-all"]


def test_a_secret_other_than_the_github_token_is_refused() -> None:
    text = CLEAN_WORKFLOW.replace("make test", "make test TOKEN=${{ secrets.PYPI_TOKEN }}")

    assert _workflow(text) == [
        "wf.yml: references secret PYPI_TOKEN; only GITHUB_TOKEN is allowed"]


def test_inherited_secrets_are_refused() -> None:
    text = CLEAN_WORKFLOW + "  reuse:\n    uses: ./.github/workflows/x.yml\n    secrets: inherit\n"

    assert _workflow(text) == ["wf.yml: passes on every secret with secrets: inherit"]


@pytest.mark.parametrize(("step", "named"), [
    ("uses: pypa/gh-action-pypi-publish@release/v1", "pypa/gh-action-pypi-publish"),
    ("uses: softprops/action-gh-release@v2", "softprops/action-gh-release"),
    ("run: npm publish --provenance", "npm publish"),
    ("run: docker push example.invalid/image", "docker push"),
    ("run: gh release create v1 out.tgz", "gh release create"),
])
def test_a_named_publishing_step_is_refused_naming_the_step(step: str, named: str) -> None:
    text = CLEAN_WORKFLOW + f"      - name: Ship it\n        {step}\n"

    assert _workflow(text) == [f"wf.yml: step 'Ship it' publishes with {named}"]


def test_a_build_push_action_pushing_is_refused() -> None:
    text = CLEAN_WORKFLOW + (
        "      - name: Image\n"
        "        uses: docker/build-push-action@v6\n"
        "        with:\n"
        "          push: true\n")

    assert _workflow(text) == [
        "wf.yml: step 'Image' publishes with docker/build-push-action and push: true"]


def test_a_build_push_action_that_only_builds_passes() -> None:
    text = CLEAN_WORKFLOW + (
        "      - name: Image\n"
        "        uses: docker/build-push-action@v6\n"
        "        with:\n"
        "          push: false\n")

    assert _workflow(text) == []


@pytest.mark.parametrize(("line", "component"), [
    ("run: pip install arkhai-core-buyer", "distribution arkhai-core-buyer"),
    ("run: docker save arkhai:compute-provisioning", "image provisioning"),
    ("run: docker save arkhai:dev-env-abc", "development image dev-env"),
    ("run: helm lint helm/", "chart helm"),
    ("run: sha256sum .dist/bin/market", "binary market"),
])
def test_a_workflow_naming_a_declared_component_is_refused(line: str, component: str) -> None:
    text = CLEAN_WORKFLOW + f"      - name: List\n        {line}\n"

    assert _workflow(text) == [
        f"wf.yml: names {component}; read it from the declaration instead"]


def test_a_longer_name_is_not_taken_for_a_declared_one() -> None:
    text = CLEAN_WORKFLOW + "      - name: Other\n        run: pip install arkhai-core-extras\n"

    assert _workflow(text) == []


def test_a_publish_target_listing_wheels_is_refused() -> None:
    text = (
        "clobber-wheels:\n"
        "\tpublish --wheel .dist/arkhai_core-$(VERSION)-py3-none-any.whl\n"
        "\tpublish --wheel .dist/arkhai_core_buyer-$(VERSION)-py3-none-any.whl\n")

    assert _makefile(text) == [
        "Makefile: publish target clobber-wheels names distribution arkhai-core; "
        "read it from the declaration instead",
        "Makefile: publish target clobber-wheels names distribution arkhai-core-buyer; "
        "read it from the declaration instead",
    ]


def test_a_target_running_an_uploader_is_a_publish_target() -> None:
    text = (
        "ARTIFACT_COMMAND = python3 scripts/publish_artifacts.py\n"
        "ship:\n"
        "\t$(ARTIFACT_COMMAND) image --target registry --source registry\n")

    assert _makefile(text) == [
        "Makefile: publish target ship names image registry; "
        "read it from the declaration instead"]


def test_a_list_held_in_a_variable_is_found() -> None:
    text = (
        "IMAGES := arkhai:registry \\\n"
        "\tarkhai:compute-provisioning\n"
        "push-images:\n"
        "\tfor image in $(IMAGES); do docker push $$image; done\n")

    assert _makefile(text) == [
        "Makefile: publish target push-images names image registry; "
        "read it from the declaration instead",
        "Makefile: publish target push-images names image provisioning; "
        "read it from the declaration instead",
    ]


def test_a_publish_target_naming_the_chart_or_the_binary_is_refused() -> None:
    text = (
        "push-charts:\n"
        "\thelm push .dist/arkhai-node-operator-*.tgz oci://example.invalid\n"
        "push-cli:\n"
        "\tupload --source=.dist/bin/market\n")

    assert _makefile(text) == [
        "Makefile: publish target push-charts names chart helm; "
        "read it from the declaration instead",
        "Makefile: publish target push-cli names binary market; "
        "read it from the declaration instead",
    ]


def test_a_lane_target_naming_a_release_image_is_refused() -> None:
    text = "test-e2e-vm:\n\tdocker image inspect arkhai:registry$(IMAGE_SUFFIX)\n"

    assert _makefile(text) == [
        "Makefile: lane target test-e2e-vm names image registry; "
        "read it from the declaration instead"]


def test_a_build_target_naming_its_own_image_passes() -> None:
    text = (
        "build-registry:\n"
        "\tdocker build -t arkhai:registry$(IMAGE_SUFFIX) .\n"
        "# push-images: a comment naming arkhai:registry is not a target\n")

    assert _makefile(text) == []


def test_a_publish_target_reading_the_declaration_passes() -> None:
    text = (
        "push-images:\n"
        "\tpython3 scripts/publish_artifacts.py images --set images\n"
        "push-wheels:\n"
        "\tpython3 scripts/push-distributions.py --dist-dir .dist\n")

    assert _makefile(text) == []


def test_the_check_reads_workflows_and_makefiles_under_a_root(tmp_path: Path) -> None:
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests" / "release-components.json").write_text(
        json.dumps(DECLARATION), encoding="utf-8")
    (tmp_path / "helm").mkdir()
    (tmp_path / "helm" / "Chart.yaml").write_text("name: arkhai-node-operator\n",
                                                  encoding="utf-8")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "tests.yml").write_text(CLEAN_WORKFLOW,
                                                                  encoding="utf-8")
    (tmp_path / "e2e-tests").mkdir()
    (tmp_path / "e2e-tests" / "Makefile").write_text(
        "test-e2e:\n\tdocker run arkhai:dev-env\n", encoding="utf-8")
    (tmp_path / "Makefile").write_text("push-charts:\n\thelm push arkhai-node-operator-0.1.0.tgz\n",
                                       encoding="utf-8")

    assert sorted(check(tmp_path)) == [
        "Makefile: publish target push-charts names chart helm; "
        "read it from the declaration instead",
        "e2e-tests/Makefile: lane target test-e2e names development image dev-env; "
        "read it from the declaration instead",
    ]


def test_a_clean_tree_passes(tmp_path: Path) -> None:
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests" / "release-components.json").write_text(
        json.dumps(DECLARATION), encoding="utf-8")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "tests.yml").write_text(CLEAN_WORKFLOW,
                                                                  encoding="utf-8")
    (tmp_path / "Makefile").write_text(
        "build-registry:\n\tdocker build -t arkhai:registry .\n", encoding="utf-8")

    assert check(tmp_path) == []
