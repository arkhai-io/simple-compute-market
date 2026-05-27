from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from issue_discovery.runner import DiscoveryRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="issue-discovery",
        description="Run SCM issue-discovery workflows and inspect generated issue packets.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root. The scripts/issue-discovery wrapper sets this automatically.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Override the artifact output directory for this run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the selected workflow without executing commands.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    strict = subparsers.add_parser("strict", help="Run strict local discovery without workarounds.")
    strict.set_defaults(handler=_run_strict)

    cont = subparsers.add_parser("continue", help="Continue discovery with one named workaround.")
    cont.add_argument("--with", dest="workaround", required=True, help="Workaround id to apply.")
    cont.set_defaults(handler=_run_continue)

    profile = subparsers.add_parser("profile", help="Run a named discovery profile.")
    profile.add_argument("name", help="Profile name.")
    profile.set_defaults(handler=_run_profile)

    issue = subparsers.add_parser("issue", help="List, show, or create issue candidates.")
    issue_subparsers = issue.add_subparsers(dest="issue_command", required=True)

    issue_list = issue_subparsers.add_parser("list", help="List candidates for a run.")
    issue_list.add_argument("run_dir", type=Path)
    issue_list.set_defaults(handler=_issue_list)

    issue_show = issue_subparsers.add_parser("show", help="Show a candidate body.")
    issue_show.add_argument("run_dir", type=Path)
    issue_show.add_argument("fingerprint")
    issue_show.set_defaults(handler=_issue_show)

    issue_create = issue_subparsers.add_parser("create", help="Create a GitHub issue candidate.")
    issue_create.add_argument("run_dir", type=Path)
    issue_create.add_argument("fingerprint")
    issue_create.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print the gh command/body path without creating an issue.",
    )
    issue_create.set_defaults(handler=_issue_create)

    return parser


def _runner(args: argparse.Namespace) -> DiscoveryRunner:
    return DiscoveryRunner(repo_root=args.repo_root, output_dir=args.output_dir, dry_run=args.dry_run)


def _run_strict(args: argparse.Namespace) -> int:
    return _runner(args).run_strict()


def _run_continue(args: argparse.Namespace) -> int:
    return _runner(args).run_continue(args.workaround)


def _run_profile(args: argparse.Namespace) -> int:
    return _runner(args).run_profile(args.name)


def _run_dir(args: argparse.Namespace) -> Path:
    if args.run_dir.is_absolute():
        return args.run_dir
    return args.repo_root / args.run_dir


def _issue_list(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).issue_list(_run_dir(args))


def _issue_show(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).issue_show(_run_dir(args), args.fingerprint)


def _issue_create(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).issue_create(
        _run_dir(args),
        args.fingerprint,
        dry_run=args.dry_run,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
