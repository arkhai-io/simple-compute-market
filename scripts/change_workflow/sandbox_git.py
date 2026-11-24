"""The engine's `git`: the program the sandbox mounts over the system's Git
executables, which refuses every `git push` of an unattended run but the guarded
push's (CW-j4cs).

The sandbox mounts it over both of the system's Git executables, the one on `PATH`
and the one in Git's exec path, which Git puts first on `PATH` for its scripted
commands and its `!` aliases, so a push a script or an alias starts meets it too. It
reads the command line as Git does, past Git's own options, to the subcommand, and
refuses a `push` while the unattended-run marker is set and the guarded push's is
not, whatever options stand before or after it: `--no-verify`, `-c
core.hooksPath=…`, and `-C <dir>` change where and how Git pushes, never whether. A
refusal is said on standard error, kept among the session's invocations for its
line, and ends the command non-zero; any other command runs the system's Git, which
the sandbox mounts at `REAL_GIT`, a path nothing else names, with the command line
unchanged.

A command Git would expand from a plain alias, such as `p = push`, is read as the
alias's name, not the command it names: the refusal guards against a step's
mistakes, a plain push and its retry with the hooks skipped, and an alias set to
reach past it is a step working around it, which the checks after the run and the
Git host's authorization are there for.

The repository's hooks and `core.hooksPath` are left as they are, so the guarded
push runs the repository's pre-push hook as it does outside any sandbox, and the
owner's own pushes, outside every sandbox, never meet this program.
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path
from typing import Mapping, Sequence

from .common import GUARDED_PUSH, SESSION_ID, UNATTENDED_RUN, Clock, StepError, utc_now
from .running import REFUSED_PUSH, invocations_directory, keep_invocations

# Where the sandbox mounts the system's Git. The sandbox's root is read-only, so a
# mount point can be made only on a file system the sandbox makes its own: its
# `/dev`, a fresh one, leaves nothing on the owner's disk.
REAL_GIT = Path("/dev/change-workflow-git")
PUSH = "push"
# Git's own options that take their value as the next argument. Each also takes it
# after `=` in one argument, as does every option of Git's not named here, which
# stands alone.
_VALUED = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                     "--config-env", "--attr-source", "--super-prefix"})


def subcommand(arguments: Sequence[str], name: str = "git") -> str | None:
    """The subcommand of `<name> <arguments>`: the first argument past Git's own
    options, or None where there is none, as for `git --version`; or, where Git is run
    by a dashed name, `git-<subcommand>`, the subcommand that name gives."""
    if (dashed := os.path.basename(name)).startswith("git-"):
        return dashed.removeprefix("git-")
    skip = False
    for argument in arguments:
        if skip:
            skip = False
        elif argument in _VALUED:
            skip = True
        elif not argument.startswith("-"):
            return argument
    return None


def refusal(arguments: Sequence[str], environ: Mapping[str, str],
            name: str = "git") -> str | None:
    """Why `<name> <arguments>` is refused, or None where it runs: a push, while the
    unattended-run marker is set and the guarded push's is not."""
    if (environ.get(UNATTENDED_RUN) and not environ.get(GUARDED_PUSH)
            and subcommand(arguments, name) == PUSH):
        return (f"git push is refused during an unattended {environ[UNATTENDED_RUN]} run: a "
                "step pushes its change's branch through `scripts/change-workflow push`, the "
                "guarded push, and no other push leaves the checkout")
    return None


def main(arguments: Sequence[str], name: str = "git", environ: Mapping[str, str] = os.environ,
         root: Path | None = None, clock: Clock = utc_now) -> int:
    """Refuse `<name> <arguments>` as `refusal` says, keeping the refusal for the
    session's line, or run the system's Git with them in this process's place; `name`
    the name Git was run by, and `root` the directory it would run in, whose checkout
    keeps the session's invocations."""
    # Git chooses what it does by the name it is run as: Git's own transport runs
    # `git-receive-pack` and `git-upload-pack`, each a link to Git, to serve a push or
    # a fetch with a remote that is a local path. So Git is given the name it was run
    # by, as it would be given it outside the sandbox.
    called = os.path.basename(name)
    if (why := refusal(arguments, environ, called)) is None:
        os.execv(REAL_GIT, [called, *arguments])
    command = shlex.join([called, *arguments])
    print(f"REFUSED: {command}: {why}", file=sys.stderr)
    entry = {"hook": REFUSED_PUSH, "command": command, "error": why,
             "started": clock().strftime("%Y-%m-%dT%H:%M:%SZ")}
    # A refusal that cannot be kept still refuses: the push is what matters.
    try:
        keep_invocations(invocations_directory(Path.cwd() if root is None else root),
                         environ.get(SESSION_ID), [entry])
    except (OSError, StepError) as exc:
        print(f"WARNING: the refused push could not be kept for the session's line: {exc}",
              file=sys.stderr)
    return 1
