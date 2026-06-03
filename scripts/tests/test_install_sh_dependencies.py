import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "install.sh"


def _installer_text() -> str:
    return INSTALLER.read_text(encoding="utf-8")


def test_installer_does_not_require_literal_python312_command():
    text = _installer_text()

    assert '"python3.12:python3.12"' not in text
    assert "python3.12-dev" not in text
    assert "deadsnakes" not in text
    assert "add-apt-repository" not in text


def test_installer_has_explicit_noninteractive_dependency_path():
    text = _installer_text()

    assert "MARKET_INSTALL_ASSUME_YES" in text
    assert "--yes|-y" in text
    assert "Cannot prompt for dependency installation because no TTY is available" in text
    assert "read -r answer </dev/tty" in text
    assert "elif [ -e /dev/tty ] && [ -r /dev/tty ]" in text


def test_installer_shell_syntax_is_valid():
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)
