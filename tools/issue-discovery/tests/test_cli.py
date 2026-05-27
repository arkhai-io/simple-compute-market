from __future__ import annotations

from pathlib import Path

from issue_discovery.cli import build_parser, main


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_parser_requires_subcommand() -> None:
    parser = build_parser()
    try:
        parser.parse_args([])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover
        raise AssertionError("parser accepted missing subcommand")


def test_strict_dry_run_prints_repo_root(capsys) -> None:
    root = repo_root()
    code = main(["--repo-root", str(root), "--dry-run", "strict"])

    captured = capsys.readouterr()
    assert code == 0
    assert "issue-discovery command: strict" in captured.out
    assert f"repo_root: {root}" in captured.out
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
    run_dir = tmp_path / "run"
    issue_dir = run_dir / "issue-candidates"
    issue_dir.mkdir(parents=True)
    (issue_dir / "candidate.md").write_text("# Candidate\n", encoding="utf-8")
    (issue_dir / "candidates.jsonl").write_text(
        '{"fingerprint":"fingerprint","title":"Candidate","labels":["bug"],'
        '"classification":"test","phase":"phase","body_file":"issue-candidates/candidate.md",'
        '"evidence":[]}\n',
        encoding="utf-8",
    )

    code = main(
        [
            "--repo-root",
            str(tmp_path),
            "issue",
            "create",
            str(run_dir),
            "fingerprint",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "gh issue create" in captured.out
    assert f"cd {tmp_path}" in captured.out
    assert "--body-file" in captured.out


def test_issue_commands_resolve_relative_run_dir_from_repo_root(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    run_dir = repo / ".scm-local" / "issue-discovery" / "runs" / "run"
    issue_dir = run_dir / "issue-candidates"
    issue_dir.mkdir(parents=True)
    (issue_dir / "candidate.md").write_text("# Candidate\n", encoding="utf-8")
    (issue_dir / "candidates.jsonl").write_text(
        '{"fingerprint":"fingerprint","title":"Candidate","labels":["bug"],'
        '"classification":"test","phase":"phase","body_file":"issue-candidates/candidate.md",'
        '"evidence":[]}\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "--repo-root",
            str(repo),
            "issue",
            "list",
            ".scm-local/issue-discovery/runs/run",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "fingerprint" in captured.out
