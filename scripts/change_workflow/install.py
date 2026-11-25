"""`change-workflow install`: the distribution's skills written into each supported
harness's user skill directory, and a checkout's local configuration where it has
none; and the check every other subcommand of an installed engine makes that the
installed skills are its own version's.

Each adapter names its harness's user skill directory (`Adapter.skills`). The
installer writes there a copy of each skill the distribution ships, stamped with the
distribution's version in a file beside its `SKILL.md` (`STAMP`), and records the
names it wrote, with the version, in a manifest in the same directory (`MANIFEST`).
The manifest is how it tells its own skills from the user's: a skill the manifest
names that the version does not ship is removed, and a skill of a name the version
ships that the manifest does not record is someone else's, so the installer refuses,
naming it, before it writes anything in any directory.

Run in a checkout, it writes the checkout's local configuration,
`.agents/workflow.local.toml`, where there is none: from the repository's committed
template, `.agents/workflow.local.template.toml`, where there is one, and otherwise
as a skeleton naming each required local field. It never overwrites a local
configuration holding anything; an empty one is the sandbox's empty form of an
absent protected file, holding no setting, and is written like an absent one.

`install` reads no configuration, so it is not refused for the range it fixes; nor
does it check the installed skills, which it is how to repair. Every other
subcommand of an installed engine refuses while a supported harness's user skill
directory lacks the manifest or a skill the version ships, or holds one stamped with
another version, naming what and `change-workflow install` (`problems`); `check
skills` among them, which so holds the installed half of its rule. The engine
run from the source tree it is built from checks nothing installed: its skills are
the tree's own sources, which no installation stamps.

Contract: openspec/specs/change-workflow/spec.md, CW-1rhd and CW-sv3u.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Iterable, Mapping

from . import config, documents
from .adapters import ADAPTERS
from .common import NotInRepository, StepError, repository_root
from .harness import Adapter
from .scope import absolute

# In each user skill directory: the names the installer wrote and their version.
MANIFEST = ".change-workflow-manifest.json"
# In each installed skill's directory: the version it was installed from.
STAMP = ".change-workflow-version"
TEMPLATE = Path(".agents/workflow.local.template.toml")
# What a checkout's local configuration starts as where its repository commits no
# template: each required local field, named for the developer to fill in.
SKELETON = """\
# This checkout's own change workflow settings: those developers on this repository
# may give different values. Git should ignore this file. Fill in each field below.

[guidance]
# The directory of the engineering guidance every step's skill reads first, from
# the checkout's root or from `~`; or `none`, with the reason none applies.
# engineering = { path = "<directory>" }
# engineering = { none = "<reason>" }

[models]
# The orchestrating session's model, then each step's models in order of preference.
""" + "".join(f"# {step} = {value}\n" for step, value in (
    (config.ORCHESTRATOR, '{ model = "<model>", effort = "<effort>" }'),
    *((step, '[{ harness = "<harness>", model = "<model>", effort = "<effort>" }]')
      for step in config.STEPS)))


class InstallError(StepError):
    """The installation was refused, or what is installed is not the engine's."""


def _directory(adapter: Adapter, home: Path) -> Path:
    return absolute(adapter.skills, home, home)


def _manifest(directory: Path) -> dict | None:
    try:
        return json.loads((directory / MANIFEST).read_text("utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise InstallError(f"{directory / MANIFEST} cannot be read: {exc}") from exc


def _recorded(directory: Path) -> set[str]:
    manifest = _manifest(directory)
    return set(manifest.get("skills", ())) if isinstance(manifest, dict) else set()


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def install_skills(skills: Mapping[str, Path], version: str, home: Path,
                   adapters: Iterable[Adapter] = ADAPTERS.values()) -> list[str]:
    """Write `skills`, each name's source directory, into each adapter's user skill
    directory under `home`, stamped with `version`, and return what was done, a line
    each; refused, writing nothing anywhere, when a directory holds a skill of a
    shipped name its manifest does not record."""
    directories = [(adapter, _directory(adapter, home)) for adapter in adapters]
    foreign = [directory / name for _, directory in directories
               for name in skills
               if (directory / name).exists() or (directory / name).is_symlink()
               if name not in _recorded(directory)]
    if foreign:
        raise InstallError("these skills are of names the workflow ships, and the installer "
                           "did not write them, so nothing was installed: "
                           + ", ".join(map(str, foreign))
                           + "; move them aside and run `change-workflow install` again")
    done: list[str] = []
    for adapter, directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        for retired in sorted(_recorded(directory) - set(skills)):
            _remove(directory / retired)
            done.append(f"removed {directory / retired}, which {version} does not ship")
        for name, source in sorted(skills.items()):
            target = directory / name
            _remove(target)
            shutil.copytree(source, target)
            (target / STAMP).write_text(f"{version}\n", "utf-8")
        (directory / MANIFEST).write_text(
            json.dumps({"version": version, "skills": sorted(skills)}, indent=2) + "\n",
            "utf-8")
        done.append(f"wrote {len(skills)} skills of {version} into {directory} "
                    f"({adapter.harness})")
    return done


def install_local(root: Path) -> str | None:
    """Write the checkout's local configuration where it has none, or an empty one,
    from the template or as the skeleton; what was done, or None when it holds one."""
    local = root / config.LOCAL
    if local.exists() and local.stat().st_size > 0:
        return None
    template = root / TEMPLATE
    text, source = ((template.read_text("utf-8"), TEMPLATE.as_posix()) if template.is_file()
                    else (SKELETON, "the skeleton naming each required local field"))
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(text, "utf-8")
    return f"wrote {config.LOCAL.as_posix()} from {source}"


def problems(distribution: documents.Distribution, home: Path,
             adapters: Iterable[Adapter] = ADAPTERS.values()) -> list[str]:
    """Where the installed skills are not the engine's: a user skill directory
    without the manifest, a shipped skill missing, or one stamped with another
    version, each naming the directory or skill."""
    version = distribution.version()
    found: list[str] = []
    for adapter in adapters:
        directory = _directory(adapter, home)
        if _manifest(directory) is None:
            found.append(f"{directory} ({adapter.harness}) has no manifest of the workflow's "
                         "skills")
            continue
        for name in distribution.skills():
            stamp = directory / name / STAMP
            if not (directory / name / "SKILL.md").is_file():
                found.append(f"{directory / name} is missing, which {version} ships")
            elif (stamped := stamp.read_text("utf-8").strip() if stamp.is_file()
                  else "no version") != version:
                found.append(f"{directory / name} is stamped {stamped}, and the engine is "
                             f"{version}")
    return found


def require_installed(distribution: documents.Distribution, home: Path,
                      adapters: Iterable[Adapter] = ADAPTERS.values()) -> None:
    """Refuse, naming each problem and `change-workflow install`, while an installed
    engine's skills are not its own version's; the source tree's engine checks
    nothing installed."""
    if not distribution.installed:
        return
    if found := problems(distribution, home, adapters):
        raise InstallError("the installed workflow skills are not the engine's: "
                           + "; ".join(found) + "; run `change-workflow install`")


def main(*, home: Path | None = None,
         distribution: documents.Distribution = documents.RUNNING,
         directory: Path | None = None) -> int:
    """`install`: the skills into every supported harness's user skill directory,
    then, in a checkout, its local configuration."""
    home = Path.home() if home is None else home
    try:
        done = install_skills(distribution.skills(), distribution.version(), home)
        try:
            root = repository_root(directory)
        except NotInRepository:
            root = None
        if root is not None and (written := install_local(root)) is not None:
            done.append(written)
    except (StepError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("\n".join(done))
    return 0
