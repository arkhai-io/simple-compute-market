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

    strict = subparsers.add_parser(
        "strict", help="Run strict local discovery without workarounds."
    )
    strict.set_defaults(handler=_run_strict)

    cont = subparsers.add_parser(
        "continue", help="Continue discovery with named workaround(s)."
    )
    cont.add_argument(
        "--with",
        dest="workarounds",
        action="append",
        required=True,
        help="Workaround id to apply. Repeat to apply multiple workarounds in order.",
    )
    cont.set_defaults(handler=_run_continue)

    profile = subparsers.add_parser("profile", help="Run a named discovery profile.")
    profile.add_argument("name", help="Profile name.")
    profile.set_defaults(handler=_run_profile)

    issue = subparsers.add_parser(
        "issue", help="List, show, or create issue candidates."
    )
    issue_subparsers = issue.add_subparsers(dest="issue_command", required=True)

    issue_list = issue_subparsers.add_parser("list", help="List candidates for a run.")
    issue_list.add_argument("run_dir", type=Path)
    issue_list.set_defaults(handler=_issue_list)

    issue_show = issue_subparsers.add_parser("show", help="Show a candidate body.")
    issue_show.add_argument("run_dir", type=Path)
    issue_show.add_argument("fingerprint")
    issue_show.set_defaults(handler=_issue_show)

    issue_create = issue_subparsers.add_parser(
        "create", help="Create a GitHub issue candidate."
    )
    issue_create.add_argument("run_dir", type=Path)
    issue_create.add_argument("fingerprint")
    issue_create.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print the gh command/body path without creating an issue.",
    )
    issue_create.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Allow creation for candidates that are not marked ready_to_file.",
    )
    issue_create.set_defaults(handler=_issue_create)

    clean_room = subparsers.add_parser(
        "clean-room", help="Plan clean-room discovery runs."
    )
    clean_room_subparsers = clean_room.add_subparsers(
        dest="clean_room_command", required=True
    )

    clean_room_plan = clean_room_subparsers.add_parser(
        "plan", help="Print a clean-room run plan."
    )
    clean_room_plan.add_argument("sequence", help="Clean-room sequence id.")
    clean_room_plan.set_defaults(handler=_clean_room_plan)

    clean_room_script = clean_room_subparsers.add_parser(
        "script",
        help="Print an executable clean-room run script.",
    )
    clean_room_script.add_argument("sequence", help="Clean-room sequence id.")
    clean_room_script.set_defaults(handler=_clean_room_script)

    capacity = subparsers.add_parser(
        "capacity",
        help="Validate and evaluate portable capacity artifacts.",
    )
    capacity_subparsers = capacity.add_subparsers(
        dest="capacity_command", required=True
    )

    capacity_validate = capacity_subparsers.add_parser(
        "validate",
        help="Validate a capacity scenario.",
    )
    capacity_validate.add_argument("scenario", type=Path)
    capacity_validate.set_defaults(handler=_capacity_validate)

    capacity_hash = capacity_subparsers.add_parser(
        "hash",
        help="Print the canonical hash of a capacity scenario.",
    )
    capacity_hash.add_argument("scenario", type=Path)
    capacity_hash.set_defaults(handler=_capacity_hash)

    capacity_evaluate = capacity_subparsers.add_parser(
        "evaluate",
        help="Evaluate a capacity result against its scenario.",
    )
    capacity_evaluate.add_argument("result", type=Path)
    capacity_evaluate.add_argument("--scenario", type=Path, required=True)
    _add_capacity_context_arguments(capacity_evaluate)
    capacity_evaluate.set_defaults(handler=_capacity_evaluate)

    capacity_finding = capacity_subparsers.add_parser(
        "finding",
        help="Validate and render a capacity finding.",
    )
    capacity_finding.add_argument("finding", type=Path)
    capacity_finding.add_argument("--scenario", type=Path, required=True)
    _add_capacity_context_arguments(capacity_finding)
    capacity_finding.set_defaults(handler=_capacity_finding)

    capacity_issue_plan = capacity_subparsers.add_parser(
        "issue-plan",
        help="Evaluate a capacity result and plan its issue actions.",
    )
    capacity_issue_plan.add_argument("result", type=Path)
    capacity_issue_plan.add_argument("--scenario", type=Path, required=True)
    capacity_issue_plan.add_argument("--issues-snapshot", type=Path, default=None)
    capacity_issue_plan.add_argument("--fix-proposal", type=Path, default=None)
    capacity_issue_plan.add_argument("--fix-fingerprint", default=None)
    _add_capacity_context_arguments(capacity_issue_plan)
    capacity_issue_plan.set_defaults(handler=_capacity_issue_plan)

    capacity_cancel = capacity_subparsers.add_parser(
        "cancel",
        help="Plan or record cancellation for a capacity scenario.",
    )
    _add_capacity_termination_arguments(capacity_cancel)
    capacity_cancel.set_defaults(handler=_capacity_cancel)

    capacity_cleanup = capacity_subparsers.add_parser(
        "cleanup",
        help="Plan or record cleanup for a capacity scenario.",
    )
    _add_capacity_termination_arguments(capacity_cleanup)
    capacity_cleanup.set_defaults(handler=_capacity_cleanup)

    return parser


def _add_capacity_context_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repository", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--timeout-seconds", required=True)
    parser.add_argument(
        "--adapter",
        dest="adapters",
        action="append",
        required=True,
        metavar="KIND=MODE",
        help="Adapter mode. Repeat for each adapter.",
    )


def _add_capacity_termination_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--termination", required=True)
    parser.add_argument("--receipt", type=Path, default=None)
    _add_capacity_context_arguments(parser)


def _runner(args: argparse.Namespace) -> DiscoveryRunner:
    return DiscoveryRunner(
        repo_root=args.repo_root, output_dir=args.output_dir, dry_run=args.dry_run
    )


def _run_strict(args: argparse.Namespace) -> int:
    return _runner(args).run_strict()


def _run_continue(args: argparse.Namespace) -> int:
    return _runner(args).run_continue(tuple(args.workarounds))


def _run_profile(args: argparse.Namespace) -> int:
    return _runner(args).run_profile(args.name)


def _repo_path(args: argparse.Namespace, path: Path) -> Path:
    if path.is_absolute():
        return path
    return args.repo_root / path


def _run_dir(args: argparse.Namespace) -> Path:
    return _repo_path(args, args.run_dir)


def _issue_list(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).issue_list(_run_dir(args))


def _issue_show(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).issue_show(
        _run_dir(args), args.fingerprint
    )


def _issue_create(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).issue_create(
        _run_dir(args),
        args.fingerprint,
        dry_run=args.dry_run,
        force=args.force,
    )


def _clean_room_plan(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).clean_room_plan(args.sequence)


def _clean_room_script(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).clean_room_script(args.sequence)


def _capacity_context(args: argparse.Namespace) -> dict[str, object]:
    return {
        "repository": args.repository,
        "branch": args.branch,
        "sha": args.sha,
        "run_id": args.run_id,
        "timeout_seconds": args.timeout_seconds,
        "adapters": tuple(args.adapters),
    }


def _capacity_validate(args: argparse.Namespace) -> int:
    return _runner(args).capacity_validate(_repo_path(args, args.scenario))


def _capacity_hash(args: argparse.Namespace) -> int:
    return _runner(args).capacity_hash(_repo_path(args, args.scenario))


def _capacity_evaluate(args: argparse.Namespace) -> int:
    return _runner(args).capacity_evaluate(
        _repo_path(args, args.scenario),
        _repo_path(args, args.result),
        **_capacity_context(args),
    )


def _capacity_finding(args: argparse.Namespace) -> int:
    return _runner(args).capacity_finding(
        _repo_path(args, args.scenario),
        _repo_path(args, args.finding),
        **_capacity_context(args),
    )


def _capacity_issue_plan(args: argparse.Namespace) -> int:
    fix_proposal = (
        _repo_path(args, args.fix_proposal) if args.fix_proposal is not None else None
    )
    issues_snapshot = (
        _repo_path(args, args.issues_snapshot)
        if args.issues_snapshot is not None
        else None
    )
    return _runner(args).capacity_issue_plan(
        _repo_path(args, args.scenario),
        _repo_path(args, args.result),
        issues_snapshot,
        fix_proposal,
        args.fix_fingerprint,
        **_capacity_context(args),
    )


def _capacity_cancel(args: argparse.Namespace) -> int:
    receipt = _repo_path(args, args.receipt) if args.receipt is not None else None
    return _runner(args).capacity_cancel(
        _repo_path(args, args.scenario),
        termination=args.termination,
        receipt=receipt,
        **_capacity_context(args),
    )


def _capacity_cleanup(args: argparse.Namespace) -> int:
    receipt = _repo_path(args, args.receipt) if args.receipt is not None else None
    return _runner(args).capacity_cleanup(
        _repo_path(args, args.scenario),
        termination=args.termination,
        receipt=receipt,
        **_capacity_context(args),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
