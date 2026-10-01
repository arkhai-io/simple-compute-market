from __future__ import annotations

import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
APICREDITS = REPO / "domains" / "apicredits"


def test_no_apicredits_project_declares_an_internal_editable_source() -> None:
    """Scoped to the API-credit domain only. The repository-wide version
    of this check -- covering every consumable project, not just this
    domain -- belongs to `remove-relative-uv-sources`, an existing,
    separate change already scoped to exactly that; this test does not
    duplicate it.
    """
    apicredits_pyprojects = sorted(APICREDITS.glob("**/pyproject.toml"))
    assert apicredits_pyprojects, "expected to find at least one pyproject.toml"

    violations: list[str] = []
    for path in apicredits_pyprojects:
        text = path.read_text()
        if "[tool.uv.sources]" in text:
            violations.append(str(path.relative_to(REPO)))

    assert violations == [], (
        f"internal editable [tool.uv.sources] override(s) found: {violations}"
    )


def _members(wheel: Path) -> set[str]:
    with zipfile.ZipFile(wheel) as archive:
        return set(archive.namelist())


def _metadata(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        return archive.read(metadata_name).decode()
