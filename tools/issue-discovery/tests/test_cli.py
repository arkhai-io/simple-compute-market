from __future__ import annotations

from pathlib import Path

from issue_discovery.cli import build_parser, main


def test_parser_requires_subcommand() -> None:
    parser = build_parser()
    try:
        parser.parse_args([])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover
        raise AssertionError("parser accepted missing subcommand")


def test_strict_dry_run_prints_repo_root(tmp_path: Path, capsys) -> None:
    code = main(["--repo-root", str(tmp_path), "--dry-run", "strict"])

    captured = capsys.readouterr()
    assert code == 0
    assert "issue-discovery command: strict" in captured.out
    assert f"repo_root: {tmp_path}" in captured.out
    assert "dry_run: yes" in captured.out


def test_continue_requires_workaround() -> None:
    parser = build_parser()
    try:
        parser.parse_args(["continue"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover
        raise AssertionError("parser accepted continuation without workaround")


def test_issue_create_has_independent_dry_run(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "--repo-root",
            str(tmp_path),
            "issue",
            "create",
            str(tmp_path / "run"),
            "fingerprint",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "issue create" in captured.out
    assert "--dry-run" in captured.out
