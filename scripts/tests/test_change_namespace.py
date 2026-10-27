"""Tests for the names that keep one change's Helm validation apart from another's."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import change_namespace


# --- the namespace --------------------------------------------------------------

def test_a_change_validates_in_its_own_namespace() -> None:
    assert change_namespace.namespace("add-a-pool-default") == "validate-add-a-pool-default"


def test_a_name_of_exactly_sixty_three_characters_is_kept_whole() -> None:
    change = "a" * (63 - len("validate-"))

    assert change_namespace.namespace(change) == "validate-" + change


def test_a_longer_name_is_cut_and_ends_in_a_stable_hash_of_the_whole() -> None:
    change = "a-very-long-change-name-that-runs-well-past-what-a-namespace-holds"
    full = "validate-" + change
    digest = hashlib.sha256(full.encode()).hexdigest()[:8]

    name = change_namespace.namespace(change)

    assert len(name) == 63
    assert name == full[:54] + "-" + digest
    assert change_namespace.namespace(change) == name


def test_two_long_names_sharing_a_prefix_get_different_namespaces() -> None:
    shared = "x" * 60

    assert (change_namespace.namespace(shared + "-one")
            != change_namespace.namespace(shared + "-two"))


def test_a_cut_ending_in_a_hyphen_does_not_double_it() -> None:
    change = "a" * 44 + "-" + "b" * 20

    name = change_namespace.namespace(change)

    assert "--" not in name and len(name) < 63


@pytest.mark.parametrize("change", ["", "Upper-case", "under_score", "-leading", "trailing-",
                                    "double--hyphen", "dot.ted"])
def test_a_name_that_is_not_a_change_name_is_refused(change: str) -> None:
    with pytest.raises(ValueError, match="not a change name"):
        change_namespace.namespace(change)


def test_the_image_suffix_is_the_change_name() -> None:
    assert change_namespace.image_suffix("pilot") == "-pilot"


# --- the image overlay ----------------------------------------------------------

VALUES = """\
# A comment.
global:
  imageRepository: ""
  integrationTests:
    name: arkhai
    tag: e2e-tests   # the test image
registry:
  enabled: true
  image:
    name: arkhai
    tag: "registry"
  agents:
    bob:
      principals:
        - scheme: eip191
          identifier: "0x01"
provisioning:
  server:
    image:
      name: arkhai
      tag: compute-provisioning
  notes: |
    image:
      name: arkhai
      tag: inside-a-block-scalar
  cache:
    image:
      name: redis
      tag: 7-alpine
"""


def test_every_tag_of_an_image_built_here_is_read_by_its_path_of_keys() -> None:
    assert change_namespace.image_tags(VALUES) == {
        ("global", "integrationTests", "tag"): "e2e-tests",
        ("registry", "image", "tag"): "registry",
        ("provisioning", "server", "image", "tag"): "compute-provisioning",
    }


def test_a_tag_inside_a_list_is_refused_rather_than_skipped() -> None:
    values = "images:\n  - name: arkhai\n    tag: storefront\n"

    with pytest.raises(ValueError, match="line 3: an image tag inside a list"):
        change_namespace.image_tags(values)


def test_a_tag_opening_a_list_item_is_refused() -> None:
    with pytest.raises(ValueError, match="line 2"):
        change_namespace.image_tags("images:\n  - tag: storefront\n")


def test_the_overlay_suffixes_every_tag_and_states_nothing_else() -> None:
    assert change_namespace.image_overlay("pilot", VALUES) == {
        "global": {"integrationTests": {"tag": "e2e-tests-pilot"}},
        "registry": {"image": {"tag": "registry-pilot"}},
        "provisioning": {"server": {"image": {"tag": "compute-provisioning-pilot"}}},
    }


def test_the_overlay_is_written_as_json(tmp_path: Path) -> None:
    values = tmp_path / "values.yaml"
    values.write_text(VALUES, "utf-8")

    written = change_namespace.write_image_overlay("pilot", tmp_path / "out" / "images.json",
                                                   values)

    assert json.loads(written.read_text("utf-8"))["registry"] == {
        "image": {"tag": "registry-pilot"}}


# --- the command line -----------------------------------------------------------

def test_the_command_prints_the_namespace(capsys: pytest.CaptureFixture[str]) -> None:
    assert change_namespace.main(["pilot"]) == 0

    assert capsys.readouterr().out == "validate-pilot\n"


def test_the_command_also_writes_the_overlay(tmp_path: Path,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "images.json"

    assert change_namespace.main(["pilot", "--image-overlay", str(target)]) == 0

    assert json.loads(target.read_text("utf-8"))["storefront"]["image"]["tag"] == (
        "storefront-pilot")
    assert capsys.readouterr().out == "validate-pilot\n"


def test_a_changes_images_are_its_own_tags_of_each_image_built_here() -> None:
    images = change_namespace.change_images("foo")

    assert "arkhai:storefront-foo" in images and "arkhai:compute-provisioning-foo" in images
    assert len(images) == len(change_namespace.BUILT_IMAGES)
    # A change whose name ends in this one's keeps its images.
    assert "arkhai:storefront-bar-foo" not in images


def test_the_command_prints_the_images_instead(capsys: pytest.CaptureFixture[str]) -> None:
    assert change_namespace.main(["pilot", "--images"]) == 0

    assert capsys.readouterr().out.splitlines() == change_namespace.change_images("pilot")


def test_the_command_refuses_a_name_that_is_not_a_change(
        capsys: pytest.CaptureFixture[str]) -> None:
    assert change_namespace.main(["Not_A_Change", "--images"]) == 2
    assert change_namespace.main(["Not_A_Change"]) == 2

    captured = capsys.readouterr()
    assert captured.out == "" and "not a change name" in captured.err
