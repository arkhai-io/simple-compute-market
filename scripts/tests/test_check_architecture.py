"""The four architecture check scripts: exit codes, warnings, --strict, --change."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_architecture import Tree  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1]
GROUPS = ("layers", "scope", "dependencies", "kinds")


def _run(group: str, root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / f"check_architecture_{group}.py"), "--root", str(root), *args],
        capture_output=True, text=True, check=False)


def _clean(tmp_path: Path) -> Tree:
    tree = Tree(tmp_path)
    tree.project("core", "core-carrier")
    tree.project("kit/base", "kit-base", deps=["core-carrier"], modules={"a.py": "import core_carrier\n"})
    return tree


@pytest.mark.parametrize("group", GROUPS)
def test_a_clean_tree_passes_every_script(tmp_path, group):
    _clean(tmp_path)

    result = _run(group, tmp_path)

    assert result.returncode == 0, result.stdout
    assert f"OK: the {group} rules hold." in result.stdout


@pytest.mark.parametrize("group, setup", [
    ("layers", lambda t: t.project("kit/up", "kit-up", deps=["dom-storefront"])),
    ("scope", lambda t: t.project("domains/dom/x-storefront", "dom-x", deps=["sib-storefront"])),
    ("dependencies", lambda t: t.project("kit/u", "kit-u", modules={"a.py": "import core_carrier\n"})),
    ("kinds", lambda t: t.project("kit/x-client", "kit-x-client", deps=["kit-base"])),
])
def test_a_failing_rule_fails_its_script_and_names_the_site(tmp_path, group, setup):
    tree = _clean(tmp_path)
    tree.project("domains/dom/storefront", "dom-storefront")
    tree.project("domains/sib/storefront", "sib-storefront")
    setup(tree)

    result = _run(group, tmp_path)

    assert result.returncode == 1, result.stdout
    assert "FAIL:" in result.stdout
    assert any(line.split(":", 1)[0].endswith((".py", ".toml")) for line in result.stdout.splitlines())


def test_a_warning_alone_does_not_fail(tmp_path):
    tree = _clean(tmp_path)
    tree.project("kit/b", "kit-b", deps=["core-carrier"])

    result = _run("dependencies", tmp_path)

    assert result.returncode == 0
    assert "warning:" in result.stdout and "(1 warning(s))" in result.stdout


def test_strict_applies_no_exception_row(tmp_path):
    tree = _clean(tmp_path)
    tree.project("kit/u", "kit-u", modules={"a.py": "import core_carrier\n"})
    tree.write_rules('[[exceptions]]\nrule = "undeclared_import"\nproject = "kit-u"\n'
                     'target = "core-carrier"\nowner = "fix-it"\nsince = 2026-01-01\n')

    assert _run("dependencies", tmp_path).returncode == 0
    assert _run("dependencies", tmp_path, "--strict").returncode == 1


def test_change_fails_while_the_change_owns_a_row_and_passes_once_none_remains(tmp_path):
    tree = _clean(tmp_path)
    tree.project("kit/u", "kit-u", modules={"a.py": "import core_carrier\n"})
    tree.write_rules('[[exceptions]]\nrule = "undeclared_import"\nproject = "kit-u"\n'
                     'target = "core-carrier"\nowner = "fix-it"\nsince = 2026-01-01\n')

    owned = _run("dependencies", tmp_path, "--change", "fix-it")
    assert owned.returncode == 1
    assert "fix-it owns exception: undeclared_import kit-u -> core-carrier" in owned.stdout
    assert _run("dependencies", tmp_path, "--change", "another").returncode == 0
    assert _run("layers", tmp_path, "--change", "fix-it").returncode == 0


def test_an_expired_row_fails_the_script_that_owns_its_rule(tmp_path):
    tree = _clean(tmp_path)
    tree.write_rules('[[exceptions]]\nrule = "layer"\nproject = "kit-base"\ntarget = "core-carrier"\n'
                     'owner = "fix-it"\nsince = 2026-01-01\n')

    assert _run("layers", tmp_path).returncode == 1
    assert _run("scope", tmp_path).returncode == 0
