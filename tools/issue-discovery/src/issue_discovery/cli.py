from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from issue_discovery.runner import DiscoveryRunner


class _SingleUseAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        if getattr(namespace, self.dest, None) is not None:
            raise argparse.ArgumentError(
                self,
                f"{option_string or self.dest} may only be supplied once",
            )
        setattr(namespace, self.dest, values)


def _add_role_plan_artifact_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("role_plan", type=Path)
    parser.add_argument(
        "--expected-scm-ref",
        default=None,
        help="Optional exact campaign commit the role plan must bind.",
    )


def _add_role_receipt_artifact_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("role_receipt", type=Path)
    parser.add_argument("--role-plan", type=Path, required=True)
    parser.add_argument("--expected-scm-ref", default=None)


def _add_oracle_authority_artifact_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("oracle_authority", type=Path)
    parser.add_argument(
        "--observer-plan",
        type=Path,
        default=None,
        help="Required for real oracle authority; forbidden by mock authority.",
    )
    parser.add_argument("--expected-scm-ref", default=None)


def _add_concurrency_policy_artifact_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("concurrency_policy", type=Path)
    parser.add_argument(
        "--role-plan",
        dest="role_plans",
        type=Path,
        action="append",
        required=True,
        help="Exact role plan bound by the policy. Repeat for every actor.",
    )
    parser.add_argument("--expected-scm-ref", default=None)


def _add_frozen_action_artifact_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("frozen_action", type=Path)
    parser.add_argument("--role-plan", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--oracle-authority", type=Path, required=True)
    parser.add_argument("--observer-plan", type=Path, default=None)
    parser.add_argument("--concurrency-policy", type=Path, default=None)
    parser.add_argument(
        "--policy-role-plan",
        dest="policy_role_plans",
        type=Path,
        action="append",
        default=[],
        help=(
            "Role plan needed to validate a real concurrency policy. Repeat for "
            "every actor; the action owner's --role-plan is included automatically."
        ),
    )
    parser.add_argument("--expected-scm-ref", default=None)


def _add_action_result_artifact_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("action_result", type=Path)
    parser.add_argument("--frozen-action", type=Path, required=True)
    parser.add_argument("--role-plan", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--oracle-authority", type=Path, required=True)
    parser.add_argument("--observer-plan", type=Path, default=None)
    parser.add_argument("--concurrency-policy", type=Path, default=None)
    parser.add_argument(
        "--policy-role-plan",
        dest="policy_role_plans",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument("--expected-scm-ref", default=None)


def _add_role_evidence_bundle_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--role-plan",
        dest="role_plans",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument(
        "--role-receipt",
        dest="role_receipts",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument(
        "--frozen-action",
        dest="frozen_actions",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument(
        "--payload",
        dest="payloads",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument(
        "--oracle-authority",
        dest="oracle_authorities",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument(
        "--action-result",
        dest="action_results",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument("--expected-scm-ref", default=None)


def _add_actor_set_artifact_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("actor_set", type=Path)
    parser.add_argument("--concurrency-policy", type=Path, required=True)
    _add_role_evidence_bundle_args(parser)


def _add_mock_capture_artifact_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("mock_capture", type=Path)
    _add_role_evidence_bundle_args(parser)


def _add_evaluation_policy_artifact_args(
    parser: argparse.ArgumentParser,
) -> None:
    parser.add_argument("evaluation_policy", type=Path)
    parser.add_argument(
        "--expected-scm-ref",
        required=True,
        help="Exact campaign commit the policy and all derived evidence must bind.",
    )


def _add_reference_policy_artifact_args(
    parser: argparse.ArgumentParser,
) -> None:
    parser.add_argument("reference_policy", type=Path)
    parser.add_argument("--evaluation-policy", type=Path, required=True)
    parser.add_argument("--observer-plan", type=Path, required=True)
    parser.add_argument("--host-plan", type=Path, required=True)
    parser.add_argument("--expected-scm-ref", required=True)


def _add_capacity_result_artifact_args(
    parser: argparse.ArgumentParser,
) -> None:
    parser.add_argument(
        "context_manifest",
        type=Path,
        help=(
            "Strict path-only context identifying the result and every authority "
            "needed to reconstruct it."
        ),
    )
    parser.add_argument("--evaluation-policy", type=Path, required=True)
    parser.add_argument(
        "--predecessor-context",
        type=Path,
        default=None,
        help=(
            "Exact reuse-A context required for reuse B and for reconstructing "
            "a seller stage's reuse baseline."
        ),
    )
    parser.add_argument(
        "--reuse-baseline-context",
        type=Path,
        default=None,
        help="Exact validated reuse-B context required for seller stages.",
    )
    parser.add_argument(
        "--buyer-frontier",
        type=Path,
        default=None,
        help="Validated buyer-frontier receipt required for seller stages.",
    )
    parser.add_argument(
        "--buyer-result-context",
        dest="buyer_result_contexts",
        type=Path,
        action="append",
        default=[],
        help=(
            "Ordered buyer result context used to reconstruct the seller "
            "stage's frontier. Repeat in exact frontier order."
        ),
    )
    parser.add_argument(
        "--prior-seller-context",
        dest="prior_seller_contexts",
        type=Path,
        action="append",
        default=[],
        help=(
            "Ordered prior seller result context. Repeat in exact progression order."
        ),
    )
    parser.add_argument("--expected-scm-ref", required=True)


def _add_serialized_reuse_artifact_args(
    parser: argparse.ArgumentParser,
) -> None:
    parser.add_argument("reuse_a_context", type=Path)
    parser.add_argument("reuse_b_context", type=Path)
    parser.add_argument("--evaluation-policy", type=Path, required=True)
    parser.add_argument("--buyer-frontier", type=Path, default=None)
    parser.add_argument(
        "--buyer-result-context",
        dest="buyer_result_contexts",
        type=Path,
        action="append",
        default=[],
        help=(
            "Ordered buyer result context used to reconstruct the exact "
            "frontier that authorizes reuse A."
        ),
    )
    parser.add_argument("--expected-scm-ref", required=True)


def _add_buyer_frontier_artifact_args(
    parser: argparse.ArgumentParser,
) -> None:
    parser.add_argument("buyer_frontier", type=Path)
    parser.add_argument("--evaluation-policy", type=Path, required=True)
    parser.add_argument(
        "--result-context",
        dest="result_contexts",
        type=Path,
        action="append",
        required=True,
        help=(
            "Ordered result context. Repeat in exact B1/B2/B4/B8 and "
            "derived-refinement order."
        ),
    )
    parser.add_argument("--expected-scm-ref", required=True)


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
        choices=[
            "triaged",
            "filed",
            "fix_in_progress",
            "fixed_unverified",
            "verified",
            "closed",
            "reopened",
        ],
    )
    issue_transition.add_argument("--detail", required=True)
    issue_transition.set_defaults(handler=_issue_transition)

    capacity = subparsers.add_parser(
        "capacity", help="Validate VM capacity scenarios and findings."
    )
    capacity_subparsers = capacity.add_subparsers(
        dest="capacity_command", required=True
    )

    scenario_validate = capacity_subparsers.add_parser(
        "scenario-validate",
        help="Validate a pinned public VM-only capacity scenario.",
    )
    scenario_validate.add_argument(
        "scenario",
        help="Known repository-relative capacity-scenario path.",
    )
    scenario_validate.add_argument(
        "--scm-ref",
        required=True,
        help="Exact 40-character SCM commit containing the scenario.",
    )
    scenario_validate.add_argument(
        "--expected-sha256",
        required=True,
        help="Expected canonical SHA-256 of the pinned scenario.",
    )
    scenario_validate.set_defaults(handler=_capacity_scenario_validate)

    scenario_hash = capacity_subparsers.add_parser(
        "scenario-sha256",
        help="Validate a pinned public capacity scenario and print its canonical SHA-256.",
    )
    scenario_hash.add_argument(
        "scenario",
        help="Known repository-relative capacity-scenario path.",
    )
    scenario_hash.add_argument(
        "--scm-ref",
        required=True,
        help="Exact 40-character SCM commit containing the scenario.",
    )
    scenario_hash.set_defaults(handler=_capacity_scenario_sha256)

    finding_ingest = capacity_subparsers.add_parser(
        "finding-ingest",
        help="Validate and ingest a sanitized capacity finding occurrence.",
    )
    finding_ingest.add_argument("run_dir", type=Path)
    finding_ingest.add_argument("finding", type=Path)
    finding_ingest.set_defaults(handler=_capacity_finding_ingest)

    evaluation_policy_validate = capacity_subparsers.add_parser(
        "evaluation-policy-validate",
        help="Validate a frozen pre-Q0 capacity evaluation policy.",
    )
    _add_evaluation_policy_artifact_args(evaluation_policy_validate)
    evaluation_policy_validate.set_defaults(
        handler=_capacity_evaluation_policy_validate
    )

    evaluation_policy_hash = capacity_subparsers.add_parser(
        "evaluation-policy-sha256",
        help="Validate and canonical-hash a capacity evaluation policy.",
    )
    _add_evaluation_policy_artifact_args(evaluation_policy_hash)
    evaluation_policy_hash.set_defaults(handler=_capacity_evaluation_policy_sha256)

    reference_policy_validate = capacity_subparsers.add_parser(
        "reference-policy-validate",
        help="Validate a frozen deterministic controller-reference policy.",
    )
    _add_reference_policy_artifact_args(reference_policy_validate)
    reference_policy_validate.set_defaults(handler=_capacity_reference_policy_validate)

    reference_policy_hash = capacity_subparsers.add_parser(
        "reference-policy-sha256",
        help="Validate and canonical-hash a controller-reference policy.",
    )
    _add_reference_policy_artifact_args(reference_policy_hash)
    reference_policy_hash.set_defaults(handler=_capacity_reference_policy_sha256)

    capacity_result_validate = capacity_subparsers.add_parser(
        "capacity-result-validate",
        help="Reconstruct and validate one independently observed VM result.",
    )
    _add_capacity_result_artifact_args(capacity_result_validate)
    capacity_result_validate.set_defaults(handler=_capacity_result_validate)

    capacity_result_hash = capacity_subparsers.add_parser(
        "capacity-result-sha256",
        help="Reconstruct, validate, and canonical-hash one VM result.",
    )
    _add_capacity_result_artifact_args(capacity_result_hash)
    capacity_result_hash.set_defaults(handler=_capacity_result_sha256)

    serialized_reuse_validate = capacity_subparsers.add_parser(
        "serialized-reuse-validate",
        help="Validate reuse A followed by baseline-fenced reuse B.",
    )
    _add_serialized_reuse_artifact_args(serialized_reuse_validate)
    serialized_reuse_validate.set_defaults(handler=_capacity_serialized_reuse_validate)

    serialized_reuse_hash = capacity_subparsers.add_parser(
        "serialized-reuse-sha256",
        help="Validate serialized reuse and emit the reuse-B chain-head hash.",
    )
    _add_serialized_reuse_artifact_args(serialized_reuse_hash)
    serialized_reuse_hash.set_defaults(handler=_capacity_serialized_reuse_sha256)

    buyer_frontier_validate = capacity_subparsers.add_parser(
        "buyer-frontier-validate",
        help="Validate the ordered buyer search and its external frontier receipt.",
    )
    _add_buyer_frontier_artifact_args(buyer_frontier_validate)
    buyer_frontier_validate.set_defaults(handler=_capacity_buyer_frontier_validate)

    buyer_frontier_hash = capacity_subparsers.add_parser(
        "buyer-frontier-sha256",
        help="Validate and canonical-hash a buyer-frontier receipt.",
    )
    _add_buyer_frontier_artifact_args(buyer_frontier_hash)
    buyer_frontier_hash.set_defaults(handler=_capacity_buyer_frontier_sha256)

    role_plan_validate = capacity_subparsers.add_parser(
        "role-plan-validate",
        help="Validate a Git-pinned substantive capacity role plan.",
    )
    _add_role_plan_artifact_args(role_plan_validate)
    role_plan_validate.set_defaults(handler=_capacity_role_plan_validate)

    role_plan_hash = capacity_subparsers.add_parser(
        "role-plan-sha256",
        help="Validate and canonical-hash a substantive capacity role plan.",
    )
    _add_role_plan_artifact_args(role_plan_hash)
    role_plan_hash.set_defaults(handler=_capacity_role_plan_sha256)

    role_receipt_validate = capacity_subparsers.add_parser(
        "role-receipt-validate",
        help="Validate a substantive role receipt against its exact role plan.",
    )
    _add_role_receipt_artifact_args(role_receipt_validate)
    role_receipt_validate.set_defaults(handler=_capacity_role_receipt_validate)

    role_receipt_hash = capacity_subparsers.add_parser(
        "role-receipt-sha256",
        help="Validate and canonical-hash a substantive role receipt.",
    )
    _add_role_receipt_artifact_args(role_receipt_hash)
    role_receipt_hash.set_defaults(handler=_capacity_role_receipt_sha256)

    oracle_validate = capacity_subparsers.add_parser(
        "oracle-authority-validate",
        help="Validate a closed independent-oracle-authority artifact.",
    )
    _add_oracle_authority_artifact_args(oracle_validate)
    oracle_validate.set_defaults(handler=_capacity_oracle_authority_validate)

    oracle_hash = capacity_subparsers.add_parser(
        "oracle-authority-sha256",
        help="Validate and canonical-hash an independent-oracle authority.",
    )
    _add_oracle_authority_artifact_args(oracle_hash)
    oracle_hash.set_defaults(handler=_capacity_oracle_authority_sha256)

    policy_validate = capacity_subparsers.add_parser(
        "concurrency-policy-validate",
        help="Validate a pre-release concurrency policy against every role plan.",
    )
    _add_concurrency_policy_artifact_args(policy_validate)
    policy_validate.set_defaults(handler=_capacity_concurrency_policy_validate)

    policy_hash = capacity_subparsers.add_parser(
        "concurrency-policy-sha256",
        help="Validate and canonical-hash a pre-release concurrency policy.",
    )
    _add_concurrency_policy_artifact_args(policy_hash)
    policy_hash.set_defaults(handler=_capacity_concurrency_policy_sha256)

    action_validate = capacity_subparsers.add_parser(
        "frozen-action-validate",
        help="Validate one actor-bound frozen action and all of its authority.",
    )
    _add_frozen_action_artifact_args(action_validate)
    action_validate.set_defaults(handler=_capacity_frozen_action_validate)

    action_hash = capacity_subparsers.add_parser(
        "frozen-action-sha256",
        help="Validate and canonical-hash one actor-bound frozen action.",
    )
    _add_frozen_action_artifact_args(action_hash)
    action_hash.set_defaults(handler=_capacity_frozen_action_sha256)

    result_validate = capacity_subparsers.add_parser(
        "action-result-validate",
        help="Validate an action result against its exact frozen action.",
    )
    _add_action_result_artifact_args(result_validate)
    result_validate.set_defaults(handler=_capacity_action_result_validate)

    result_hash = capacity_subparsers.add_parser(
        "action-result-sha256",
        help="Validate and canonical-hash an action result.",
    )
    _add_action_result_artifact_args(result_hash)
    result_hash.set_defaults(handler=_capacity_action_result_sha256)

    actor_set_validate = capacity_subparsers.add_parser(
        "actor-set-validate",
        help="Validate a complete substantive actor-set aggregate.",
    )
    _add_actor_set_artifact_args(actor_set_validate)
    actor_set_validate.set_defaults(handler=_capacity_actor_set_validate)

    actor_set_hash = capacity_subparsers.add_parser(
        "actor-set-sha256",
        help="Validate and canonical-hash a substantive actor-set aggregate.",
    )
    _add_actor_set_artifact_args(actor_set_hash)
    actor_set_hash.set_defaults(handler=_capacity_actor_set_sha256)

    mock_capture_validate = capacity_subparsers.add_parser(
        "mock-capture-validate",
        help="Validate the standalone capture-only B1 composition.",
    )
    _add_mock_capture_artifact_args(mock_capture_validate)
    mock_capture_validate.set_defaults(handler=_capacity_mock_capture_validate)

    mock_capture_hash = capacity_subparsers.add_parser(
        "mock-capture-sha256",
        help="Validate and canonical-hash a capture-only B1 composition.",
    )
    _add_mock_capture_artifact_args(mock_capture_hash)
    mock_capture_hash.set_defaults(handler=_capacity_mock_capture_sha256)

    action_capture = capacity_subparsers.add_parser(
        "action-capture",
        help="Atomically capture one validated one-shot mock action.",
    )
    action_capture.add_argument(
        "--expected-action-kind",
        required=True,
        action=_SingleUseAction,
        choices=[
            "buyer-request",
            "seller-service-start",
            "seller-listing-publication",
        ],
    )
    _add_frozen_action_artifact_args(action_capture)
    action_capture.add_argument("--runtime-binding", type=Path, required=True)
    action_capture.add_argument(
        "--concrete-payload-binding",
        type=Path,
        required=True,
    )
    action_capture.add_argument(
        "--actor-invocation-capability",
        type=Path,
        required=True,
    )
    action_capture.add_argument(
        "--current-frozen-action",
        type=Path,
        default=None,
        help=(
            "Optional just-in-time frozen-action snapshot. When omitted, the "
            "validated authority file is rechecked."
        ),
    )
    action_capture.add_argument(
        "--current-role-plan",
        type=Path,
        default=None,
        help=(
            "Optional just-in-time role-plan snapshot used to produce a typed "
            "authority-changed rejection."
        ),
    )
    action_capture.add_argument(
        "--current-payload",
        type=Path,
        default=None,
        help=(
            "Optional just-in-time payload snapshot used to produce a typed "
            "payload/selection rejection."
        ),
    )
    action_capture.add_argument(
        "--current-oracle-authority",
        type=Path,
        default=None,
        help=(
            "Optional just-in-time oracle snapshot used to produce a typed "
            "authority-changed rejection."
        ),
    )
    action_capture.add_argument(
        "--actor-alive-at-invocation",
        action="store_true",
        required=True,
        help=(
            "Explicit mock liveness assertion. Real process authentication "
            "remains private-infrastructure authority."
        ),
    )
    action_capture.add_argument("--claim-ledger", type=Path, required=True)
    action_capture.add_argument("--result-output", type=Path, required=True)
    action_capture.set_defaults(handler=_capacity_action_capture)

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

    return parser


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
    return DiscoveryRunner(repo_root=args.repo_root).issue_show(
        _run_dir(args), args.fingerprint
    )


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
        args.scenario,
        scm_ref=args.scm_ref,
        expected_sha256=args.expected_sha256,
    )


def _capacity_scenario_sha256(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_scenario_sha256(
        args.scenario,
        scm_ref=args.scm_ref,
    )


def _capacity_finding_ingest(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_finding_ingest(
        _run_dir(args),
        _repo_path(args, args.finding),
    )


def _capacity_evaluation_policy_validate(
    args: argparse.Namespace,
) -> int:
    return DiscoveryRunner(
        repo_root=args.repo_root
    ).capacity_evaluation_policy_validate(
        _repo_path(args, args.evaluation_policy),
        expected_scm_ref=args.expected_scm_ref,
    )


def _capacity_evaluation_policy_sha256(
    args: argparse.Namespace,
) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_evaluation_policy_sha256(
        _repo_path(args, args.evaluation_policy),
        expected_scm_ref=args.expected_scm_ref,
    )


def _capacity_reference_policy_paths(
    args: argparse.Namespace,
) -> dict[str, object]:
    return {
        "evaluation_policy": _repo_path(args, args.evaluation_policy),
        "observer_plan": _repo_path(args, args.observer_plan),
        "host_plan": _repo_path(args, args.host_plan),
        "expected_scm_ref": args.expected_scm_ref,
    }


def _capacity_reference_policy_validate(
    args: argparse.Namespace,
) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_reference_policy_validate(
        _repo_path(args, args.reference_policy),
        **_capacity_reference_policy_paths(args),
    )


def _capacity_reference_policy_sha256(
    args: argparse.Namespace,
) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_reference_policy_sha256(
        _repo_path(args, args.reference_policy),
        **_capacity_reference_policy_paths(args),
    )


def _capacity_result_paths(args: argparse.Namespace) -> dict[str, object]:
    return {
        "evaluation_policy": _repo_path(args, args.evaluation_policy),
        "predecessor_context": (
            _repo_path(args, args.predecessor_context)
            if args.predecessor_context is not None
            else None
        ),
        "reuse_baseline_context": (
            _repo_path(args, args.reuse_baseline_context)
            if args.reuse_baseline_context is not None
            else None
        ),
        "buyer_frontier": (
            _repo_path(args, args.buyer_frontier)
            if args.buyer_frontier is not None
            else None
        ),
        "buyer_result_contexts": tuple(
            _repo_path(args, path) for path in args.buyer_result_contexts
        ),
        "prior_seller_contexts": tuple(
            _repo_path(args, path) for path in args.prior_seller_contexts
        ),
        "expected_scm_ref": args.expected_scm_ref,
    }


def _capacity_result_validate(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_result_validate(
        _repo_path(args, args.context_manifest),
        **_capacity_result_paths(args),
    )


def _capacity_result_sha256(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_result_sha256(
        _repo_path(args, args.context_manifest),
        **_capacity_result_paths(args),
    )


def _capacity_serialized_reuse_paths(
    args: argparse.Namespace,
) -> dict[str, object]:
    return {
        "evaluation_policy": _repo_path(args, args.evaluation_policy),
        "buyer_frontier": (
            _repo_path(args, args.buyer_frontier)
            if args.buyer_frontier is not None
            else None
        ),
        "buyer_result_contexts": tuple(
            _repo_path(args, path) for path in args.buyer_result_contexts
        ),
        "expected_scm_ref": args.expected_scm_ref,
    }


def _capacity_serialized_reuse_validate(
    args: argparse.Namespace,
) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_serialized_reuse_validate(
        _repo_path(args, args.reuse_a_context),
        _repo_path(args, args.reuse_b_context),
        **_capacity_serialized_reuse_paths(args),
    )


def _capacity_serialized_reuse_sha256(
    args: argparse.Namespace,
) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_serialized_reuse_sha256(
        _repo_path(args, args.reuse_a_context),
        _repo_path(args, args.reuse_b_context),
        **_capacity_serialized_reuse_paths(args),
    )


def _capacity_buyer_frontier_paths(
    args: argparse.Namespace,
) -> dict[str, object]:
    return {
        "evaluation_policy": _repo_path(args, args.evaluation_policy),
        "result_contexts": tuple(
            _repo_path(args, path) for path in args.result_contexts
        ),
        "expected_scm_ref": args.expected_scm_ref,
    }


def _capacity_buyer_frontier_validate(
    args: argparse.Namespace,
) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_buyer_frontier_validate(
        _repo_path(args, args.buyer_frontier),
        **_capacity_buyer_frontier_paths(args),
    )


def _capacity_buyer_frontier_sha256(
    args: argparse.Namespace,
) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_buyer_frontier_sha256(
        _repo_path(args, args.buyer_frontier),
        **_capacity_buyer_frontier_paths(args),
    )


def _capacity_role_plan_validate(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_role_plan_validate(
        _repo_path(args, args.role_plan),
        expected_scm_ref=args.expected_scm_ref,
    )


def _capacity_role_plan_sha256(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_role_plan_sha256(
        _repo_path(args, args.role_plan),
        expected_scm_ref=args.expected_scm_ref,
    )


def _capacity_role_receipt_validate(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_role_receipt_validate(
        _repo_path(args, args.role_receipt),
        role_plan=_repo_path(args, args.role_plan),
        expected_scm_ref=args.expected_scm_ref,
    )


def _capacity_role_receipt_sha256(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_role_receipt_sha256(
        _repo_path(args, args.role_receipt),
        role_plan=_repo_path(args, args.role_plan),
        expected_scm_ref=args.expected_scm_ref,
    )


def _capacity_oracle_authority_validate(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_oracle_authority_validate(
        _repo_path(args, args.oracle_authority),
        observer_plan=(
            _repo_path(args, args.observer_plan)
            if args.observer_plan is not None
            else None
        ),
        expected_scm_ref=args.expected_scm_ref,
    )


def _capacity_oracle_authority_sha256(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_oracle_authority_sha256(
        _repo_path(args, args.oracle_authority),
        observer_plan=(
            _repo_path(args, args.observer_plan)
            if args.observer_plan is not None
            else None
        ),
        expected_scm_ref=args.expected_scm_ref,
    )


def _capacity_concurrency_policy_validate(args: argparse.Namespace) -> int:
    return DiscoveryRunner(
        repo_root=args.repo_root
    ).capacity_concurrency_policy_validate(
        _repo_path(args, args.concurrency_policy),
        role_plans=tuple(_repo_path(args, path) for path in args.role_plans),
        expected_scm_ref=args.expected_scm_ref,
    )


def _capacity_concurrency_policy_sha256(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_concurrency_policy_sha256(
        _repo_path(args, args.concurrency_policy),
        role_plans=tuple(_repo_path(args, path) for path in args.role_plans),
        expected_scm_ref=args.expected_scm_ref,
    )


def _frozen_action_paths(args: argparse.Namespace) -> dict[str, object]:
    return {
        "frozen_action": _repo_path(args, args.frozen_action),
        "role_plan": _repo_path(args, args.role_plan),
        "payload": _repo_path(args, args.payload),
        "oracle_authority": _repo_path(args, args.oracle_authority),
        "observer_plan": (
            _repo_path(args, args.observer_plan)
            if args.observer_plan is not None
            else None
        ),
        "concurrency_policy": (
            _repo_path(args, args.concurrency_policy)
            if args.concurrency_policy is not None
            else None
        ),
        "policy_role_plans": tuple(
            _repo_path(args, path) for path in args.policy_role_plans
        ),
        "expected_scm_ref": args.expected_scm_ref,
    }


def _capacity_frozen_action_validate(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_frozen_action_validate(
        **_frozen_action_paths(args),
    )


def _capacity_frozen_action_sha256(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_frozen_action_sha256(
        **_frozen_action_paths(args),
    )


def _capacity_action_result_validate(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_action_result_validate(
        _repo_path(args, args.action_result),
        **_frozen_action_paths(args),
    )


def _capacity_action_result_sha256(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_action_result_sha256(
        _repo_path(args, args.action_result),
        **_frozen_action_paths(args),
    )


def _role_evidence_paths(args: argparse.Namespace) -> dict[str, object]:
    return {
        "role_plans": tuple(_repo_path(args, path) for path in args.role_plans),
        "role_receipts": tuple(_repo_path(args, path) for path in args.role_receipts),
        "frozen_actions": tuple(_repo_path(args, path) for path in args.frozen_actions),
        "payloads": tuple(_repo_path(args, path) for path in args.payloads),
        "oracle_authorities": tuple(
            _repo_path(args, path) for path in args.oracle_authorities
        ),
        "action_results": tuple(_repo_path(args, path) for path in args.action_results),
        "expected_scm_ref": args.expected_scm_ref,
    }


def _capacity_actor_set_validate(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_actor_set_validate(
        _repo_path(args, args.actor_set),
        concurrency_policy=_repo_path(args, args.concurrency_policy),
        **_role_evidence_paths(args),
    )


def _capacity_actor_set_sha256(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_actor_set_sha256(
        _repo_path(args, args.actor_set),
        concurrency_policy=_repo_path(args, args.concurrency_policy),
        **_role_evidence_paths(args),
    )


def _capacity_mock_capture_validate(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_mock_capture_validate(
        _repo_path(args, args.mock_capture),
        **_role_evidence_paths(args),
    )


def _capacity_mock_capture_sha256(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_mock_capture_sha256(
        _repo_path(args, args.mock_capture),
        **_role_evidence_paths(args),
    )


def _capacity_action_capture(args: argparse.Namespace) -> int:
    return DiscoveryRunner(repo_root=args.repo_root).capacity_action_capture(
        **_frozen_action_paths(args),
        expected_action_kind=args.expected_action_kind,
        current_runtime_binding=_repo_path(args, args.runtime_binding),
        current_concrete_payload_binding=_repo_path(
            args,
            args.concrete_payload_binding,
        ),
        current_actor_invocation_capability=_repo_path(
            args,
            args.actor_invocation_capability,
        ),
        current_action=(
            _repo_path(args, args.current_frozen_action)
            if args.current_frozen_action is not None
            else None
        ),
        current_plan=(
            _repo_path(args, args.current_role_plan)
            if args.current_role_plan is not None
            else None
        ),
        current_payload=(
            _repo_path(args, args.current_payload)
            if args.current_payload is not None
            else None
        ),
        current_oracle_authority=(
            _repo_path(args, args.current_oracle_authority)
            if args.current_oracle_authority is not None
            else None
        ),
        actor_alive_at_invocation=args.actor_alive_at_invocation,
        claim_ledger=_repo_path(args, args.claim_ledger),
        result_output=_repo_path(args, args.result_output),
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
