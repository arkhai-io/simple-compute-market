"""The single-enumeration, workflow-credential and market-binary check, over
synthetic files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from check_release_components import (
    check,
    check_market_binary,
    component_patterns,
    main,
    makefile_problems,
    revision_problems,
    workflow_credential_problems,
    workflow_enumeration_problems,
)
from release_components import parse

DECLARATION = {
    "distributions": [
        {"key": "core", "path": "core", "dist": "arkhai-core"},
        {"key": "core-buyer", "path": "core/buyer", "dist": "arkhai-core-buyer"},
        {"key": "boats-buyer", "path": "domains/boats/buyer", "dist": "arkhai-boats-buyer"},
    ],
    "images": [
        {"name": "registry", "local": "registry"},
        {"name": "provisioning", "local": "compute-provisioning"},
    ],
    "chart": {"path": "helm"},
    "binaries": [{"name": "market", "target": "build-market-binary",
                  "path": ".dist/bin/market"}],
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
    """Both rules' refusals of one workflow, the credential rule's first."""
    return (workflow_credential_problems("wf.yml", text)
            + workflow_enumeration_problems("wf.yml", text, PATTERNS))


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


@pytest.mark.parametrize("reference", ["secrets.PYPI_TOKEN", "secrets['PYPI_TOKEN']",
                                       "Secrets.pypi_token",
                                       "format('}}', secrets.PYPI_TOKEN)"])
def test_a_secret_other_than_the_github_token_is_refused(reference: str) -> None:
    text = CLEAN_WORKFLOW.replace("make test", f"make test TOKEN=${{{{ {reference} }}}}")

    assert _workflow(text) == [
        "wf.yml: references secret PYPI_TOKEN; only GITHUB_TOKEN is allowed"]


@pytest.mark.parametrize("expression", ["${{ toJSON(secrets) }}",
                                        "${{ secrets[matrix.name] }}"])
def test_reading_the_secrets_context_without_naming_a_secret_is_refused(
        expression: str) -> None:
    text = CLEAN_WORKFLOW.replace("make test", f"make test ALL={expression}")

    assert _workflow(text) == [
        "wf.yml: reads the secrets context without naming a secret; "
        "only GITHUB_TOKEN is allowed"]


def test_a_secret_on_a_block_scalar_line_beginning_with_a_hash_is_refused() -> None:
    """Inside a block scalar such a line is text, not a comment, and Actions
    substitutes the expression in it."""
    text = CLEAN_WORKFLOW.replace(
        "        run: make test\n",
        "        env:\n          T: |\n            #${{ secrets.PYPI_TOKEN }}\n"
        "        run: make test\n")

    assert _workflow(text) == [
        "wf.yml: references secret PYPI_TOKEN; only GITHUB_TOKEN is allowed"]


@pytest.mark.parametrize("reference", ["secrets['GITHUB_TOKEN']", "secrets.github_token"])
def test_the_github_token_however_spelled_and_the_word_secrets_in_a_command_pass(
        reference: str) -> None:
    text = CLEAN_WORKFLOW.replace(
        "make test", f"make check-secrets TOKEN=${{{{ {reference} }}}}")

    assert _workflow(text) == []


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


@pytest.mark.parametrize("push", ["true", "${{ github.event_name != 'pull_request' }}"])
def test_a_build_push_action_that_may_push_is_refused(push: str) -> None:
    text = CLEAN_WORKFLOW + (
        "      - name: Image\n"
        "        uses: docker/build-push-action@v6\n"
        "        with:\n"
        f"          push: {push}\n")

    assert _workflow(text) == [
        f"wf.yml: step 'Image' publishes with docker/build-push-action and push: {push}"]


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
    ("run: helm pull arkhai-node-operator", "chart helm"),
    ("run: sha256sum .dist/bin/market", "binary market"),
])
def test_a_workflow_naming_a_declared_component_is_refused(line: str, component: str) -> None:
    text = CLEAN_WORKFLOW + f"      - name: List\n        {line}\n"

    assert _workflow(text) == [
        f"wf.yml: names {component}; read it from the declaration instead"]


def test_a_workflow_naming_a_declared_npm_package_is_refused() -> None:
    declaration = {**DECLARATION, "npm": [{"path": "middleware/typescript"}]}
    patterns = component_patterns(parse(declaration), None)
    text = CLEAN_WORKFLOW + "      - name: Pack\n        run: cd middleware/typescript\n"

    assert workflow_enumeration_problems("wf.yml", text, patterns) == [
        "wf.yml: names npm package middleware/typescript; read it from the declaration instead"]


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


@pytest.mark.parametrize("target", ["publish-images", "load-candidate"])
def test_every_publish_target_name_is_a_publish_target(target: str) -> None:
    text = f"{target}:\n\tsave arkhai:registry\n"

    assert _makefile(text) == [
        f"Makefile: publish target {target} names image registry; "
        "read it from the declaration instead"]


@pytest.mark.parametrize("target", ["build-e2e-vm", "pull-release-images"])
def test_every_lane_target_name_is_a_lane_target(target: str) -> None:
    text = f"{target}:\n\tdocker pull example.invalid/arkhai:provisioning-abc\n"

    assert _makefile(text) == [
        f"Makefile: lane target {target} names image provisioning; "
        "read it from the declaration instead"]


def test_an_image_named_by_its_published_name_is_found() -> None:
    """`provisioning` is built as `compute-provisioning`; either name is found."""
    text = "push-images:\n\tsave arkhai:provisioning\n"

    assert _makefile(text) == [
        "Makefile: publish target push-images names image provisioning; "
        "read it from the declaration instead"]


def test_a_declared_npm_package_named_by_a_publish_target_is_refused() -> None:
    declaration = {**DECLARATION, "npm": [{"path": "middleware/typescript"}]}
    patterns = component_patterns(parse(declaration), None)
    text = "push-npm:\n\tcd middleware/typescript && pack\n"

    assert makefile_problems("Makefile", text, patterns) == [
        "Makefile: publish target push-npm names npm package middleware/typescript; "
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
        "\tpython3 scripts/publish_artifacts.py images --registry $(DOCKER_REGISTRY)\n"
        "push-cli:\n"
        "\tpython3 scripts/publish_artifacts.py binaries --suffix abc\n"
        "load-candidate:\n"
        "\tpython3 scripts/load_candidate.py --revision abc\n")

    assert _makefile(text) == []


BINARY_PROJECT = "core/buyer/market-binary"
EXACT = ("arkhai-core-buyer", "arkhai-boats-buyer")


def _pyproject(root: Path, path: str, text: str) -> None:
    (root / path).mkdir(parents=True, exist_ok=True)
    (root / path / "pyproject.toml").write_text(text, encoding="utf-8")


def _binary_tree(root: Path, dependencies: tuple[str, ...] = EXACT,
                 freeze: tuple[str, ...] = ("pyinstaller==6.22.3",)) -> None:
    """The declaration, its projects, and the binary's project depending on
    `dependencies`: `core/buyer` defines the `market` console script and
    `domains/boats/buyer` registers a buyer domain."""
    (root / "manifests").mkdir(exist_ok=True)
    (root / "manifests" / "release-components.json").write_text(
        json.dumps(DECLARATION), encoding="utf-8")
    _pyproject(root, "core", '[project]\nname = "arkhai-core"\nversion = "1.0.0"\n')
    _pyproject(root, "core/buyer",
               '[project]\nname = "arkhai-core-buyer"\nversion = "1.0.0"\n'
               '[project.scripts]\nmarket = "core_buyer.cli:main"\n')
    _pyproject(root, "domains/boats/buyer",
               '[project]\nname = "arkhai-boats-buyer"\nversion = "1.0.0"\n'
               '[project.entry-points."market.buyer_domains"]\nboats = "boats.plugin:domain"\n')
    _pyproject(root, BINARY_PROJECT,
               '[project]\nname = "arkhai-market-binary"\nversion = "0.1.0"\n'
               f"dependencies = {json.dumps(list(dependencies))}\n"
               f"[dependency-groups]\nfreeze = {json.dumps(list(freeze))}\n"
               "[tool.uv]\npackage = false\n")


def test_the_market_binary_rule_passes_an_exact_project(tmp_path: Path) -> None:
    _binary_tree(tmp_path)

    assert check_market_binary(tmp_path) == []


def test_the_market_binary_rule_compares_normalised_names_and_ignores_specifiers(
        tmp_path: Path) -> None:
    _binary_tree(tmp_path, ("Arkhai_Core_Buyer>=1.0", "arkhai.boats-buyer ; sys_platform == 'linux'"))

    assert check_market_binary(tmp_path) == []


def test_the_market_binary_rule_names_a_missing_domain_and_its_project(tmp_path: Path) -> None:
    _binary_tree(tmp_path, ("arkhai-core-buyer",))

    assert check_market_binary(tmp_path) == [
        f"{BINARY_PROJECT}/pyproject.toml: does not depend on arkhai-boats-buyer, which "
        "domains/boats/buyer registers a market.buyer_domains entry point"]


def test_the_market_binary_rule_names_a_missing_cli(tmp_path: Path) -> None:
    _binary_tree(tmp_path, ("arkhai-boats-buyer",))

    assert check_market_binary(tmp_path) == [
        f"{BINARY_PROJECT}/pyproject.toml: does not depend on arkhai-core-buyer, which "
        "core/buyer defines the `market` console script"]


def test_the_market_binary_rule_names_an_extra_distribution(tmp_path: Path) -> None:
    _binary_tree(tmp_path, (*EXACT, "arkhai-core"))

    assert check_market_binary(tmp_path) == [
        f"{BINARY_PROJECT}/pyproject.toml: depends on arkhai-core, which is neither the "
        "buyer CLI nor a declared buyer domain"]


def test_the_market_binary_rule_ignores_the_freeze_group(tmp_path: Path) -> None:
    _binary_tree(tmp_path, freeze=("pyinstaller==6.22.3", "arkhai-core"))

    assert check_market_binary(tmp_path) == []


def test_the_market_binary_rule_refuses_a_missing_project(tmp_path: Path) -> None:
    _binary_tree(tmp_path)
    (tmp_path / BINARY_PROJECT / "pyproject.toml").unlink()

    assert check_market_binary(tmp_path) == [
        f"{BINARY_PROJECT}/pyproject.toml does not exist; the market binary is built from it"]


def test_the_check_reads_workflows_and_makefiles_under_a_root(tmp_path: Path) -> None:
    _binary_tree(tmp_path)
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
    _binary_tree(tmp_path)
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "tests.yml").write_text(CLEAN_WORKFLOW,
                                                                  encoding="utf-8")
    (tmp_path / "Makefile").write_text(
        "build-registry:\n\tdocker build -t arkhai:registry .\n", encoding="utf-8")

    assert check(tmp_path) == []


def _tree_breaking_every_rule(root: Path) -> None:
    """A tree whose workflow holds a publishing credential and names a declared
    distribution, whose publish target names a declared image, and whose binary
    project lacks the buyer domain."""
    _binary_tree(root, ("arkhai-core-buyer",))
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "tests.yml").write_text(
        CLEAN_WORKFLOW.replace("contents: read", "contents: write")
        + "      - name: List\n        run: pip install arkhai-core-buyer\n",
        encoding="utf-8")
    (root / "Makefile").write_text("GIT_SUFFIX := $(shell git rev-parse --short HEAD)\n"
                                   "push-images:\n\tdocker push arkhai:registry\n",
                                   encoding="utf-8")


def test_the_credential_rule_runs_alone(tmp_path: Path) -> None:
    _tree_breaking_every_rule(tmp_path)

    assert check(tmp_path, rules=("credentials",)) == [
        ".github/workflows/tests.yml: grants contents: write"]


def test_the_credential_rule_reads_no_declaration(tmp_path: Path) -> None:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "tests.yml").write_text(CLEAN_WORKFLOW,
                                                                  encoding="utf-8")

    assert check(tmp_path, rules=("credentials",)) == []


def test_the_enumeration_rule_runs_alone(tmp_path: Path) -> None:
    _tree_breaking_every_rule(tmp_path)

    assert check(tmp_path, rules=("enumeration",)) == [
        ".github/workflows/tests.yml: names distribution arkhai-core-buyer; "
        "read it from the declaration instead",
        "Makefile: publish target push-images names image registry; "
        "read it from the declaration instead",
    ]


def test_the_market_binary_rule_runs_alone(tmp_path: Path) -> None:
    _tree_breaking_every_rule(tmp_path)

    assert check(tmp_path, rules=("market-binary",)) == [
        f"{BINARY_PROJECT}/pyproject.toml: does not depend on arkhai-boats-buyer, which "
        "domains/boats/buyer registers a market.buyer_domains entry point"]


def test_with_no_rule_named_every_rule_runs(tmp_path: Path) -> None:
    _tree_breaking_every_rule(tmp_path)

    assert check(tmp_path) == (check(tmp_path, rules=("enumeration",))
                               + check(tmp_path, rules=("credentials",))
                               + check(tmp_path, rules=("market-binary",))
                               + check(tmp_path, rules=("revision",)))


def test_the_revision_rule_runs_alone(tmp_path: Path) -> None:
    _tree_breaking_every_rule(tmp_path)

    assert check(tmp_path, rules=("revision",)) == [
        "Makefile: abbreviates a revision with --short; use git rev-parse --short=9"]


@pytest.mark.parametrize("abbreviation", ["--short", "--short=7", "--short=12"])
def test_a_revision_abbreviated_otherwise_than_to_nine_characters_is_refused(
        abbreviation: str) -> None:
    text = f"GIT_SUFFIX := $(shell git rev-parse {abbreviation} HEAD)\n"

    assert revision_problems("dev-env/Makefile", text) == [
        f"dev-env/Makefile: abbreviates a revision with {abbreviation}; "
        "use git rev-parse --short=9"]


def test_a_revision_abbreviated_in_a_recipe_across_a_continuation_is_refused() -> None:
    text = "tag:\n\tdocker tag arkhai:x arkhai:x-$$(git rev-parse \\\n\t\t--short HEAD)\n"

    assert revision_problems("Makefile", text) == [
        "Makefile: abbreviates a revision with --short; use git rev-parse --short=9"]


def test_nine_characters_a_full_revision_and_a_comment_pass() -> None:
    text = ("GIT_SUFFIX := $(shell git rev-parse --short=9 HEAD)\n"
            "FULL := $(shell git rev-parse HEAD)\n"
            "# git rev-parse --short HEAD in a comment is not a revision\n")

    assert revision_problems("Makefile", text) == []


def test_the_command_runs_the_rules_it_names(capsys: pytest.CaptureFixture[str]) -> None:
    """On this tree the workflow-credential rule passes alone; its message names
    only what it establishes."""
    assert main(["--rule", "credentials"]) == 0
    assert capsys.readouterr().out == "OK: no workflow can publish.\n"


def test_every_makefile_in_this_tree_abbreviates_a_revision_to_nine_characters(
        capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--rule", "revision"]) == 0
    assert capsys.readouterr().out == (
        "OK: every Makefile abbreviates a revision to nine characters.\n")
