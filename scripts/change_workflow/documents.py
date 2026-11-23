"""The workflow's own distribution: its version, and each of its documents by role,
found beside the engine with no field of any configuration naming them.

The documents belong to the same version as the skills that cite them, so nothing
about them varies between repositories or developers. Installed, the distribution
carries them as package data under the package's `data/` directory, where its
project file gathers them; run from the source tree the wheel is built from, as
`scripts/change-workflow` runs it, they are at the places that tree keeps them, and
the version is the project file's. Which of the two the engine runs as is read from
its own package: an installed package holds `data/`, and the tree's never does.

A caller names a document by its role (`ROLES`), never a path inside the package, so
the package's layout stays internal; the skills' sources are `skills()`.

Contract: openspec/specs/change-workflow/spec.md, CW-5kl9 and CW-lm42.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib import metadata, resources
from pathlib import Path
from typing import Callable

# The distribution's name, as an index and `uv tool install` know it.
DISTRIBUTION = "arkhai-change-workflow"
# The engine's own package directory, wherever it is installed or checked out.
PACKAGE = Path(str(resources.files(__package__)))
# Where an installed package keeps the documents its project file gathers.
DATA = "data"
# The project file the wheel is built from, beside the package in the source tree.
PROJECT = Path("change-workflow-wheel/pyproject.toml")

SPECIFICATION, INDEX, COMPANION, DIAGRAMS = "specification", "index", "companion", "diagrams"
GUIDANCE, HANDBOOK, SCHEMA, FRAGMENT = "guidance", "handbook", "schema", "fragment"
# Every document the distribution names by role, in the order `config --json` gives
# them.
ROLES = (SPECIFICATION, INDEX, COMPANION, DIAGRAMS, GUIDANCE, HANDBOOK, SCHEMA, FRAGMENT)

# Each role's place inside an installed package's `data/`; the fragment is a file of
# the package itself in either form.
_INSTALLED = {
    SPECIFICATION: "specification/spec.md",
    INDEX: "specification/index.md",
    COMPANION: "specification/README.md",
    DIAGRAMS: "specification/diagrams",
    GUIDANCE: "guidance",
    HANDBOOK: "change-workflow-handbook.md",
    SCHEMA: "change-outcome.schema.json",
}
# Each role's place in the source tree, from its root.
_TREE = {
    SPECIFICATION: "openspec/specs/change-workflow/spec.md",
    INDEX: "openspec/specs/change-workflow/index.md",
    COMPANION: "openspec/specs/change-workflow/README.md",
    DIAGRAMS: "openspec/specs/change-workflow/diagrams",
    GUIDANCE: "docs/guidance/workflow",
    HANDBOOK: "docs/change-workflow-handbook.md",
    SCHEMA: ".agents/change-outcome.schema.json",
}
FRAGMENT_FILE = "workflow.mk"
# The skills' sources: an installed package's own, every one of which it ships; and
# in the source tree, the directory the repository's own skills share, of which the
# workflow ships `guidance-review` and every `change-` skill.
_INSTALLED_SKILLS = "skills"
_TREE_SKILLS = ".agents/skills"
_TREE_SKILL_NAMES = ("change-*", "guidance-review")


@dataclass(frozen=True)
class Distribution:
    """The workflow's distribution as the engine at `package` runs it: installed, its
    documents the package's data, or from the source tree. An installed
    distribution's version is read from its metadata by `metadata_version`."""

    package: Path
    metadata_version: Callable[[str], str] = metadata.version

    @property
    def installed(self) -> bool:
        return (self.package / DATA).is_dir()

    @property
    def tree(self) -> Path:
        """The source tree's root, which holds the package under `scripts/`."""
        return self.package.parent.parent

    def path(self, role: str) -> Path:
        """The document of `role`."""
        if role == FRAGMENT:
            return self.package / FRAGMENT_FILE
        if role not in _INSTALLED:
            raise KeyError(f"{role!r} is no document of the workflow's; its roles: "
                           + ", ".join(ROLES))
        return (self.package / DATA / _INSTALLED[role] if self.installed
                else self.tree / _TREE[role])

    def documents(self) -> dict[str, Path]:
        """Every document by its role, in `ROLES` order."""
        return {role: self.path(role) for role in ROLES}

    def skills(self) -> dict[str, Path]:
        """Each skill the distribution ships, by name, its source directory, in name
        order."""
        if self.installed:
            found = list((self.package / DATA / _INSTALLED_SKILLS).iterdir())
        else:
            source = self.tree / _TREE_SKILLS
            found = [path for pattern in _TREE_SKILL_NAMES for path in source.glob(pattern)]
        return {path.name: path for path in sorted(found) if (path / "SKILL.md").is_file()}

    def version(self) -> str:
        """The distribution's version: the installed distribution's metadata, or the
        source tree's project file."""
        if self.installed:
            return self.metadata_version(DISTRIBUTION)
        project = self.package.parent / PROJECT
        return tomllib.loads(project.read_text("utf-8"))["project"]["version"]

    def installed_paths(self) -> tuple[Path, ...]:
        """What the installed distribution is on disk, which the sandbox keeps
        read-only: its package and its metadata directory beside it; nothing for the
        source tree, whose engine a step edits."""
        if not self.installed:
            return ()
        metadata_directory = f"{DISTRIBUTION.replace('-', '_')}-*.dist-info"
        return (self.package, *sorted(self.package.parent.glob(metadata_directory)))

    def described(self) -> dict[str, str]:
        """The distribution as `config --json` gives it under `workflow`: its version,
        then each document by role, the two directories ending in `/`."""
        return {"version": self.version(),
                **{role: path.as_posix() + ("/" if role in (DIAGRAMS, GUIDANCE) else "")
                   for role, path in self.documents().items()}}


# The distribution the running engine belongs to.
RUNNING = Distribution(PACKAGE)


def path(role: str) -> Path:
    """The running engine's document of `role`."""
    return RUNNING.path(role)


def version() -> str:
    """The running engine's version."""
    return RUNNING.version()
