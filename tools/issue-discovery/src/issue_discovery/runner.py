from __future__ import annotations

from pathlib import Path


class DiscoveryRunner:
    """Coordinates issue-discovery workflows.

    This skeleton owns the CLI surface first. Phase execution, artifact
    collection, continuations, and issue packets are implemented in later
    commits.
    """

    def __init__(self, repo_root: Path, output_dir: Path | None = None, dry_run: bool = False) -> None:
        self.repo_root = repo_root.resolve()
        self.output_dir = output_dir
        self.dry_run = dry_run

    def run_strict(self) -> int:
        self._print_pending("strict")
        return 0

    def run_continue(self, workaround: str) -> int:
        self._print_pending(f"continue --with {workaround}")
        return 0

    def run_profile(self, name: str) -> int:
        self._print_pending(f"profile {name}")
        return 0

    def issue_list(self, run_dir: Path) -> int:
        self._print_pending(f"issue list {run_dir}")
        return 0

    def issue_show(self, run_dir: Path, fingerprint: str) -> int:
        self._print_pending(f"issue show {run_dir} {fingerprint}")
        return 0

    def issue_create(self, run_dir: Path, fingerprint: str, dry_run: bool) -> int:
        suffix = " --dry-run" if dry_run else ""
        self._print_pending(f"issue create {run_dir} {fingerprint}{suffix}")
        return 0

    def _print_pending(self, command: str) -> None:
        output = self.output_dir if self.output_dir is not None else self.repo_root / ".scm-local"
        dry_run = "yes" if self.dry_run else "no"
        print(f"issue-discovery command: {command}")
        print(f"repo_root: {self.repo_root}")
        print(f"output: {output}")
        print(f"dry_run: {dry_run}")
