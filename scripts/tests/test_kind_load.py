from __future__ import annotations

from pathlib import Path

import kind_load


def test_a_change_loads_its_own_suffixed_images() -> None:
    images = kind_load.images("pilot")

    assert images and all(image.startswith("arkhai:") and image.endswith("-pilot")
                          for image in images)


def test_without_a_change_the_bare_tags_are_loaded() -> None:
    assert "arkhai:registry" in kind_load.images(None)


def test_an_image_is_loaded_under_the_name_a_pod_resolves_it_to(tmp_path: Path) -> None:
    archive = tmp_path / "image.tar"
    commands = kind_load.load_commands("scm", "arkhai:registry-pilot", archive)

    assert commands == [
        ["docker", "tag", "arkhai:registry-pilot", "docker.io/library/arkhai:registry-pilot"],
        ["docker", "save", "--output", str(archive), "docker.io/library/arkhai:registry-pilot"],
        ["kind", "load", "image-archive", str(archive), "--name", "scm"]]
