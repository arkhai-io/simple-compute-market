from pathlib import Path
import pytest

from typer import BadParameter

from market_buyer.groups.config import _init_env_file


def test_init_env_creates_env_when_none_exist(tmp_path: Path) -> None:
    _init_env_file("agent", tmp_path, overwrite=False)
    env_path = tmp_path / ".env"
    assert env_path.exists()
    assert env_path.read_text(encoding="utf-8") == ""


def test_init_env_errors_if_env_exists_without_overwrite(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("EXISTING=1\n", encoding="utf-8")
    with pytest.raises(BadParameter):
        _init_env_file("agent", tmp_path, overwrite=False)


def test_init_env_overwrites_when_flag_set(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("EXISTING=1\n", encoding="utf-8")
    _init_env_file("agent", tmp_path, overwrite=True)
    assert env_path.read_text(encoding="utf-8") == ""


def test_init_env_warns_when_env_local_exists(tmp_path: Path, capsys) -> None:
    (tmp_path / ".env.local").write_text("PORT=8080\n", encoding="utf-8")
    _init_env_file("registry", tmp_path, overwrite=False)
    captured = capsys.readouterr()
    assert "Warning" in captured.out
    assert (tmp_path / ".env").exists()


def test_init_env_warns_when_other_env_exists(tmp_path: Path, capsys) -> None:
    (tmp_path / ".alice.env").write_text("PORT=9000\n", encoding="utf-8")
    _init_env_file("agent", tmp_path, overwrite=False)
    captured = capsys.readouterr()
    assert "Warning" in captured.out
    assert (tmp_path / ".env").exists()


def test_init_env_ignores_env_sample(tmp_path: Path, capsys) -> None:
    (tmp_path / ".env.sample").write_text("PORT=8000\n", encoding="utf-8")
    _init_env_file("agent", tmp_path, overwrite=False)
    captured = capsys.readouterr()
    assert "Warning" not in captured.out
    assert (tmp_path / ".env").exists()
