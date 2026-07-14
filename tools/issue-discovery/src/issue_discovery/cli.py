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

    cont = subparsers.add_parser("continue", help="Continue discovery with named workaround(s).")
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
        "--destination-repo-root",
        type=Path,
        default=None,
        help=(
            "Exact checkout in which gh should file the issue. Required when a "
            "private-infra finding is ingested by the public SCM harness."
        ),
    )
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

    issue_propose = issue_subparsers.add_parser(
        "propose-fix",
        help="Write a proposal-only child fix PR packet for a capacity finding.",
    )
    issue_propose.add_argument("run_dir", type=Path)
    issue_propose.add_argument("fingerprint")
    issue_propose.add_argument("--head-branch", required=True)
    issue_propose.set_defaults(handler=_issue_propose_fix)

    issue_transition = issue_subparsers.add_parser(
        "transition",
        help="Append a validated capacity-finding lifecycle transition.",
    )
    issue_transition.add_argument("run_dir", type=Path)
    issue_transition.add_argument("fingerprint")
    issue_transition.add_argument(
        "--state",
        required=True,
        choices=["triaged", "filed", "fix_in_progress", "fixed_unverified", "verified", "closed", "reopened"],
    )
    issue_transition.add_argument("--detail", required=True)
    issue_transition.set_defaults(handler=_issue_transition)

    capacity = subparsers.add_parser("capacity", help="Validate VM capacity scenarios and findings.")
    capacity_subparsers = capacity.add_subparsers(dest="capacity_command", required=True)

    scenario_validate = capacity_subparsers.add_parser(
        "scenario-validate",
        help="Validate a public VM-only capacity scenario.",
    )
    scenario_validate.add_argument("scenario", type=Path)
    scenario_validate.set_defaults(handler=_capacity_scenario_validate)

    scenario_hash = capacity_subparsers.add_parser(
        "scenario-sha256",
        help="Validate a public capacity scenario and print its canonical SHA-256.",
    )
    scenario_hash.add_argument("scenario", type=Path)
    scenario_hash.set_defaults(handler=_capacity_scenario_sha256)

    finding_ingest = capacity_subparsers.add_parser(
        "finding-ingest",
        help="Validate and ingest a sanitized capacity finding occurrence.",
    )
    finding_ingest.add_argument("run_dir", type=Path)
    finding_ingest.add_argument("finding", type=Path)
    finding_ingest.set_defaults(handler=_capacity_finding_ingest)

    clean_room = subparsers.add_parser("clean-room", help="Plan clean-room discovery runs.")
    clean_room_subparsers = clean_room.add_subparsers(dest="clean_room_command", required=True)

    clean_room_plan = clean_room_subparsers.add_parser("plan", help="Print a clean-room run plan.")
    clean_room_plan.add_argument("sequence", help="Clean-room sequence id.")
    clean_room_plan.set_defaults(handler=_clean_room_plan)

    clean_room_script = clean_room_subparsers.add_parser(
        "script",
        help="Print an executable clean-room run script.",
    )
    clean_room_script.add_argument("sequence", help="Clean-room sequence id.")
    clean_room_script.set_defaults(handler=_clean_room_script)

    return parser


def _runner(args: argparse.Namespace) -> DiscoveryRunner:
    return DiscoveryRunner(repo_root=args.repo_root, output_dir=args.output_dir, dry_run=args.dry_run)


def _run_strict(args: argparse.Namespace) -> int:
    return _runner(args).run_strict()


def _run_continue(args: argparse.Namespace) -> int:
    return _runner(args).run_continue(tuple(args.workarounds))


def _run_profile(args: argparse.Namespace) -> int:
    return _runner(args).run_profile(args.name)


def _run_dir(args: argparse.Namespace) -> Path:
    if args.run_dir.is_absolute():
        return args.run_dir
    return args.repo_root / args.run_dir


def _repo_path(args: argparse.Namespace, path: Path) -> Path:
    if path.is_absolute():
        return path
    return args.repo_root / path


def _issue_list(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).issue_list(_run_dir(args))


def _issue_show(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).issue_show(_run_dir(args), args.fingerprint)


def _issue_create(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).issue_create(
        _run_dir(args),
        args.fingerprint,
        dry_run=args.dry_run,
        force=args.force,
        destination_repo_root=(
            _repo_path(args, args.destination_repo_root)
            if args.destination_repo_root is not None
            else None
        ),
    )


def _issue_propose_fix(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).issue_propose_fix(
        _run_dir(args),
        args.fingerprint,
        args.head_branch,
    )


def _issue_transition(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).issue_transition(
        _run_dir(args),
        args.fingerprint,
        args.state,
        args.detail,
    )


def _capacity_scenario_validate(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_scenario_validate(
        _repo_path(args, args.scenario)
    )


def _capacity_scenario_sha256(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_scenario_sha256(
        _repo_path(args, args.scenario)
    )


def _capacity_finding_ingest(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_finding_ingest(
        _run_dir(args),
        _repo_path(args, args.finding),
    )


def _clean_room_plan(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).clean_room_plan(args.sequence)


def _clean_room_script(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).clean_room_script(args.sequence)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
