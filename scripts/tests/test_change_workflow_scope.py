"""A step's scope for one run, `change_workflow.scope`: its baseline, the adapter's and
the repository's paths, the protected paths kept read-only inside them, and the run's
grants, each path with its source.

`absolute` and `grant_paths` read an entry alone, and are unit tests. Whether a path is
protected, and a scope's resolution, are library integration: they ask a real Git for
the Git directory and the checkout's files, inside a checkout or outside one. What the
tests show is the scope as resolved; mounting it is the sandbox's."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from change_workflow import scope
from change_workflow.graph import STEP_DEFINITIONS
from change_workflow.scope import ADAPTER, ENGINE, GRANT, REPOSITORY, ScopeError

TMP = Path("/tmp")

INERT = ("openspec/", "docs/", "**/README.md", "AGENTS.md")


# Reading an entry.

@pytest.mark.parametrize("entry,expected", [
    ("docs/", "/repo/docs"),
    ("./kit/../docs", "/repo/docs"),
    ("~/.cache", "/user-home/.cache"),
    ("~", "/user-home"),
    ("/usr/bin/git", "/usr/bin/git"),
])
def test_an_entry_reads_from_the_root_the_home_directory_or_as_it_is(entry: str,
                                                                    expected: str) -> None:
    assert scope.absolute(entry, Path("/repo"), Path("/user-home")) == Path(expected)


@pytest.mark.parametrize("entry,protected,expected", [
    (".agents/workflow.toml", (".agents/workflow.toml",), ".agents/workflow.toml"),
    (".git/config/x", (".git/config",), ".git/config"),
    ("/usr/bin/git", scope.PROTECTED, "/usr/bin/git"),
    # A directory holding a protected path is admitted; the path stays read-only.
    (".agents/", (".agents/workflow.toml",), None),
    (".", scope.PROTECTED, None),
    ("~/.codex", ("~/.codex/config.toml",), None),
    # A pattern is judged by the directory its matches lie under.
    ("secrets/*/key", ("secrets/",), "secrets/"),
    ("**/README.md", scope.PROTECTED, None),
])
def test_a_path_is_protected_where_it_is_or_lies_under_a_protected_path(
        tmp_path: Path, entry: str, protected: tuple[str, ...], expected: str | None) -> None:
    # Outside a Git checkout an entry under `.git/` reads as any path from the root.
    assert scope.protected_by(entry, tmp_path, tmp_path / "home", protected) == expected


def test_each_grant_value_is_split_trimmed_and_emptied() -> None:
    assert scope.grant_paths(["kit/site/.venv; docs/ ;;", " ~/.npm "]) == [
        ("kit/site/.venv; docs/ ;;", "kit/site/.venv"), ("kit/site/.venv; docs/ ;;", "docs/"),
        (" ~/.npm ", "~/.npm")]


# A scope resolved on a real checkout.

def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A Git checkout holding a package whose README sits beside its code, an
    environment Git ignores holding a README of its own, and `AGENTS.md` at the root,
    which holds no README."""
    root = tmp_path / "checkout"
    for path in ("openspec/specs/x/spec.md", "docs/guide.md", "kit/site/README.md",
                 "kit/site/src/code.py", "kit/site/.venv/lib/README.md", "AGENTS.md",
                 ".agents/workflow.toml", "src/main.py"):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text("x\n", "utf-8")
    (root / ".gitignore").write_text(".venv/\n", "utf-8")
    _git(root, "init", "-q")
    return root


def _resolve(step: str, root: Path, **more) -> scope.Scope:
    more.setdefault("inert_paths", INERT)
    return scope.resolve(step, root, home=root.parent / "home", **more)


def _writable(found: scope.Scope) -> dict[Path, str]:
    return {path.path: path.source for path in found.writable}


def _protected(found: scope.Scope) -> dict[Path, str]:
    return {path.path: path.source for path in found.protected}


def test_designs_scope_is_openspec_and_git_with_the_repositorys_documents(
        checkout: Path) -> None:
    home = checkout.parent / "home"

    found = _resolve("design", checkout, writable=("docs/",))

    assert _writable(found) == {checkout / "openspec": ENGINE, checkout / ".git": ENGINE,
                                TMP: ENGINE, home / ".cache": ENGINE,
                                checkout / "docs": REPOSITORY}
    assert _protected(found) == {checkout / ".agents/workflow.toml": ENGINE,
                                 checkout / ".git/config": ENGINE,
                                 Path("/usr/bin/git"): ENGINE,
                                 Path("/usr/lib/git-core/git"): ENGINE}


def test_the_reviews_scope_holds_no_path_of_its_checkout_but_the_invocation_record(
        checkout: Path) -> None:
    found = _resolve("review", checkout, writable=())
    record = checkout / ".git/change-invocations"

    assert _writable(found) == {record: ENGINE, TMP: ENGINE,
                                checkout.parent / "home/.cache": ENGINE}
    # Absent until a session first invokes something, so created before launch.
    (invocations,) = [path for path in found.writable if path.path == record]
    assert invocations.create


@pytest.mark.parametrize("step", sorted(STEP_DEFINITIONS))
def test_every_steps_temporary_entry_is_its_private_tmp(checkout: Path, step: str) -> None:
    """CW-m8wq: every step, the review included, writes a private `/tmp` of its own,
    from the engine, which resolves to no path of the host's temporary directory."""
    found = _resolve(step, checkout)

    (private,) = [path for path in found.writable if path.private]
    assert (private.path, private.source, private.entry) == (TMP, ENGINE,
                                                             "<temporary directory>")
    assert private.shown() == {"path": "/tmp", "source": "engine",
                               "entry": "<temporary directory>", "private": True}


def test_closeouts_scope_mounts_each_inert_files_directory(checkout: Path) -> None:
    """Each README's directory, the package's code beside it included, and the root for
    `AGENTS.md`; a README inside an ignored environment is no match."""
    found = _resolve("closeout", checkout)

    assert set(_writable(found)) == {checkout / "openspec", checkout / "docs",
                                     checkout / "kit/site", checkout, checkout / ".git",
                                     TMP, checkout.parent / "home/.cache"}
    assert checkout / "kit/site/.venv/lib" not in _writable(found)
    entries = {path.path: path.entry for path in found.writable}
    assert entries[checkout / "kit/site"] == "**/README.md"
    assert entries[checkout] == "AGENTS.md"


def test_the_configuration_stays_protected_inside_a_writable_checkout(checkout: Path) -> None:
    found = _resolve("implement", checkout)

    assert checkout in _writable(found)
    assert _protected(found)[checkout / ".agents/workflow.toml"] == ENGINE


def test_the_adapters_and_the_repositorys_paths_carry_their_source(checkout: Path) -> None:
    home = checkout.parent / "home"

    found = _resolve("plan", checkout, writable=("~/.local/share/uv",),
                     protected=("secrets/",), adapter_writable=("~/.claude",),
                     adapter_protected=(".claude/settings.json",))

    assert _writable(found)[home / ".claude"] == ADAPTER
    assert _writable(found)[home / ".local/share/uv"] == REPOSITORY
    assert _protected(found)[checkout / ".claude/settings.json"] == ADAPTER
    assert _protected(found)[checkout / "secrets"] == REPOSITORY


def test_a_linked_worktrees_git_paths_resolve_through_git(checkout: Path) -> None:
    """A worktree's `.git` is a file; its Git directory, and the common directory its
    commits write, are where Git says, and so is the configuration Git reads."""
    _git(checkout, "add", "-A")
    _git(checkout, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "commit", "-qm", "x")
    linked = checkout.parent / "linked"
    _git(checkout, "worktree", "add", "-q", str(linked))

    found = _resolve("design", linked)

    assert checkout / ".git/worktrees/linked" in _writable(found)
    assert checkout / ".git" in _writable(found)
    assert checkout / ".git/config" in _protected(found)
    # The configuration's check and a grant judge Git's paths as Git resolves them.
    home = checkout.parent / "home"
    assert scope.protected_by(".git/config", linked, home, scope.PROTECTED) == ".git/config"
    assert scope.protected_by(".git/", linked, home, scope.PROTECTED) is None
    with pytest.raises(ScopeError, match="protected path .git/config"):
        _resolve("design", linked, grants=(".git/config",))


def test_designs_scope_holds_each_proposal_worktree_registered_beside_it(
        checkout: Path) -> None:
    """CW-k8dn: a worktree registered in the checkout, beside it and named
    `<prerequisite>-proposal`, is writable to design, and not to planning; an unrelated
    worktree, or one elsewhere so named, is not."""
    _git(checkout, "add", "-A")
    _git(checkout, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "commit", "-qm", "x")
    proposal = checkout.parent / "shape-floor-proposal"
    unrelated, elsewhere = checkout.parent / "linked", checkout.parent / "deep/x-proposal"
    for path, branch in ((proposal, "propose-shape-floor"), (unrelated, "linked"),
                         (elsewhere, "deep")):
        _git(checkout, "worktree", "add", "-q", "-b", branch, str(path))

    design, plan = _resolve("design", checkout), _resolve("plan", checkout)

    assert _writable(design)[proposal] == ENGINE
    assert {path.entry for path in design.writable if path.path == proposal} == {
        "<proposal worktrees>"}
    assert unrelated not in _writable(design) and elsewhere not in _writable(design)
    assert proposal not in _writable(plan)


# Grants.

def test_a_grant_names_a_pattern(checkout: Path) -> None:
    """CW-tl5v's "A grant names a pattern": the scope is refused, naming the value."""
    with pytest.raises(ScopeError, match=r"the grant 'kit/\*/.venv' names kit/\*/.venv, a "
                                         "pattern"):
        _resolve("implement", checkout, grants=("kit/*/.venv",))


@pytest.mark.parametrize("value", ["/tmp", "/tmp/", "/tmp/x/..", "/"])
def test_a_grant_names_the_hosts_temporary_directory(checkout: Path, value: str) -> None:
    """CW-tl5v's "A grant names the host's temporary directory": the scope is refused,
    naming the value, since the step writes a private `/tmp` already; a directory
    holding `/tmp` would hide it as well."""
    with pytest.raises(ScopeError, match=rf"the grant '{value}' names {value}, which is or "
                                         "holds the host's temporary directory; every step "
                                         "writes a private /tmp of its own"):
        _resolve("implement", checkout, grants=(value,))


def test_a_grant_of_a_link_to_the_hosts_temporary_directory_is_refused(checkout: Path) -> None:
    (checkout / "scratch").symlink_to("/tmp")

    with pytest.raises(ScopeError, match="the grant 'scratch' names scratch, which is or "
                                         "holds the host's"):
        _resolve("implement", checkout, grants=("scratch",))


def test_a_grant_under_the_hosts_temporary_directory_is_admitted(checkout: Path) -> None:
    """A path under `/tmp` is granted as any path is, and mounted at its own path inside
    the private `/tmp` (the sandbox's rendering)."""
    under = Path(f"/tmp/change-workflow-grant-{checkout.parent.name}")

    found = _resolve("implement", checkout, grants=(str(under),))

    assert _writable(found)[under] == GRANT
    assert _writable(found)[TMP] == ENGINE
    assert not under.exists()


def test_a_grant_of_a_protected_path_is_refused_naming_it(checkout: Path) -> None:
    with pytest.raises(ScopeError, match=r"the grant 'docs/; \.agents/workflow\.toml' names "
                                         r"\.agents/workflow\.toml, which is or lies under the "
                                         "protected path"):
        _resolve("design", checkout, grants=("docs/; .agents/workflow.toml",))


def test_a_grant_of_an_adapters_protected_path_is_refused(checkout: Path) -> None:
    with pytest.raises(ScopeError, match="settings.local.json"):
        _resolve("implement", checkout, grants=(".claude/settings.local.json",),
                 adapter_protected=(".claude/settings.local.json",))


def test_a_grant_of_a_directory_holding_a_protected_path_keeps_it_read_only(
        checkout: Path) -> None:
    found = _resolve("design", checkout, grants=(".agents/",))

    assert _writable(found)[checkout / ".agents"] == GRANT
    assert checkout / ".agents/workflow.toml" in _protected(found)


def test_a_grant_of_a_link_into_a_protected_directory_is_refused(checkout: Path) -> None:
    """The sandbox mounts a path where its links lead, so a link into a protected
    directory is under it, though its own name is not."""
    (checkout / "data/subdir").mkdir(parents=True)
    (checkout / "alias").symlink_to(checkout / "data/subdir")

    with pytest.raises(ScopeError, match="the grant 'alias' names alias, which is or lies "
                                         "under the protected path data/"):
        _resolve("design", checkout, grants=("alias",), protected=("data/",))


def test_a_grant_under_a_protected_path_that_is_a_link_is_refused(checkout: Path) -> None:
    """A protected entry is compared where its links lead too."""
    (checkout / "data/subdir").mkdir(parents=True)
    (checkout / "guarded").symlink_to(checkout / "data")

    with pytest.raises(ScopeError, match="the protected path guarded"):
        _resolve("design", checkout, grants=("data/subdir",), protected=("guarded",))


def test_a_grant_of_a_link_to_a_directory_holding_a_protected_path_is_admitted(
        checkout: Path) -> None:
    """As a directory holding a protected path is: the protected path stays read-only
    inside the directory the link leads to, where the sandbox mounts it."""
    (checkout / "alias").symlink_to(checkout / ".agents")

    found = _resolve("design", checkout, grants=("alias",))

    assert _writable(found)[checkout / "alias"] == GRANT
    assert checkout / ".agents/workflow.toml" in _protected(found)


def test_a_granted_file_mounts_its_directory_and_an_absent_path_is_created(
        checkout: Path) -> None:
    found = _resolve("design", checkout, grants=("src/main.py;kit/site/.venv/cache",))
    granted = {path.path: path for path in found.writable if path.source == GRANT}

    assert set(granted) == {checkout / "src", checkout / "kit/site/.venv/cache"}
    assert not granted[checkout / "src"].create
    assert granted[checkout / "kit/site/.venv/cache"].create
