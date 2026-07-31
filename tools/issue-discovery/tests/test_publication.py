from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from jsonschema import Draft202012Validator
import pytest

from issue_discovery.capacity import CapacityValidationError, canonical_json_bytes
from issue_discovery.cli import build_parser, main
from issue_discovery.issues import GuardedIssuePublicationPlanner
from issue_discovery.publication import (
    FINDING_V2_CONSUMED_REF,
    RenderedPublicationPreview,
    ValidatedPublicationPreview,
    _observe_rendered_git_publication_authority,
    _select_rendered_issue_publication_action,
    build_issue_publication_preview,
    observe_git_publication_authority,
    publication_preview_json,
    select_issue_publication_action,
    validate_publication_observation,
)
from issue_discovery.runner import DiscoveryRunner


ROOT = Path(__file__).resolve().parents[3]
WORKING_REF = "1" * 40
UPSTREAM_REF = "2" * 40
INBOUND_REF = "3" * 40


def index_record(
    *,
    finding_id: str = "finding-001",
    destination_repo: str = "simple-compute-market",
    scenario_id: str = "b2-s1-g1",
    scenario_sha256: str = "c" * 64,
    body: str | None = None,
    ready_to_file: bool = True,
    working_branch: str = "feat/issue-discovery-harness",
    working_ref: str = WORKING_REF,
    upstream_branch: str = "dev",
    inbound_ref: str | None = INBOUND_REF,
    contract_ref: str = FINDING_V2_CONSUMED_REF,
    stable_signature: str = "durable capacity fault",
) -> dict[str, Any]:
    occurrence = body or f"# Capacity fault {finding_id}\n\nObserved a durable fault.\n"
    return {
        "schema_version": 1,
        "candidate_kind": "capacity-finding-v2",
        "publication_capability": "guard-issue-fix-publication",
        "finding_id": finding_id,
        "finding_sha256": "a" * 64,
        "fingerprint": "capacity-" + "b" * 64,
        "destination_repo": destination_repo,
        "scenario_id": scenario_id,
        "scenario_sha256": scenario_sha256,
        "scm_contract_ref": contract_ref,
        "defect_semantics": {"stable_signature": stable_signature},
        "occurrence_body": occurrence,
        "occurrence_body_sha256": hashlib.sha256(
            occurrence.encode("utf-8")
        ).hexdigest(),
        "observed_authority": {
            "working_branch": working_branch,
            "working_ref": working_ref,
            "upstream_branch": upstream_branch,
            "upstream_ref": UPSTREAM_REF,
            "inbound_merge_ref": inbound_ref,
            "reconciliation_epoch_id": "epoch-001",
        },
        "filing_readiness": {"ready_to_file": ready_to_file},
    }


def preview(**overrides: Any):
    return build_issue_publication_preview(
        index_record(**overrides),
        private_authorization_sha256="d" * 64,
        repo_root=ROOT,
    )


def terminal_pages(node_ids: list[str]) -> dict[str, Any]:
    return {
        "complete": True,
        "total_count": len(node_ids),
        "pages": [
            {
                "request_cursor": None,
                "end_cursor": None,
                "has_next_page": False,
                "node_ids": node_ids,
            }
        ],
    }


def issue_snapshot(
    body: str,
    *,
    number: int = 7,
    state: str = "OPEN",
    comments: list[dict[str, Any]] | None = None,
    title: str = "Observed capacity fault",
) -> dict[str, Any]:
    selected_comments = comments or []
    return {
        "node_id": f"ISSUE_{number}",
        "number": number,
        "url": f"https://github.com/arkhai-io/simple-compute-market/issues/{number}",
        "state": state,
        "title": title,
        "body": body,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "comment_pages": terminal_pages(
            [str(comment["node_id"]) for comment in selected_comments]
        ),
        "comments": selected_comments,
    }


def issue_comment(
    body: str, *, number: int = 7, comment_id: int = 41
) -> dict[str, Any]:
    return {
        "node_id": f"COMMENT_{comment_id}",
        "url": (
            "https://github.com/arkhai-io/simple-compute-market/issues/"
            f"{number}#issuecomment-{comment_id}"
        ),
        "body": body,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }


def observation(
    issues: list[dict[str, Any]] | None = None,
    *,
    repository: str = "arkhai-io/simple-compute-market",
) -> dict[str, Any]:
    selected = issues or []
    return {
        "schema_version": 1,
        "destination_repository": repository,
        "issue_query": {
            "repository": repository,
            "object_type": "ISSUE",
            "states": ["OPEN", "CLOSED"],
        },
        "issue_pages": terminal_pages([str(issue["node_id"]) for issue in selected]),
        "issues": selected,
        "direct_rereads": deepcopy(selected),
    }


def git_runner(
    root: Path,
    *,
    repository: str = "arkhai-io/simple-compute-market",
    working_branch: str = "feat/issue-discovery-harness",
    upstream_branch: str = "dev",
    default_branch: str = "main",
    remote_working: str = WORKING_REF,
    remote_upstream: str = UPSTREAM_REF,
    remote_default: str = "4" * 40,
    default_head_mode: str = "valid",
    dirty: bool = False,
    index_tag: str = "H",
    replace_ref: bool = False,
    url_rewrite: bool = False,
    ancestry_returncode: int = 0,
    contract_ancestry_returncode: int = 0,
    policy_ancestry_returncode: int = 0,
    checked_branch: str | None = None,
    checked_ref: str = WORKING_REF,
    policy_branch: str = "feat/issue-discovery-harness",
    policy_ref: str = WORKING_REF,
    policy_dirty: bool = False,
    policy_index_tag: str = "H",
    origin_url: str | None = None,
    ignored_entries: list[str] | None = None,
    policy_ignored_entries: list[str] | None = None,
) -> tuple[Any, list[tuple[str, ...]]]:
    calls: list[tuple[str, ...]] = []

    def run(
        command: list[str],
        *,
        check: bool,
        text: bool,
        cwd: Path,
        capture_output: bool,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        assert command[0] == "git"
        assert check is False and text is True and capture_output is True
        assert cwd in {root.resolve(), ROOT.resolve()}
        arguments = tuple(command[1:])
        assert env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"
        assert env["GIT_CONFIG_COUNT"] == "6"
        assert env["GIT_CONFIG_KEY_0"] == "core.fsmonitor"
        assert env["GIT_CONFIG_VALUE_0"] == "false"
        assert env["GIT_CONFIG_KEY_2"] == "core.filemode"
        assert env["GIT_CONFIG_VALUE_2"] == "true"
        assert env["GIT_CONFIG_KEY_5"] == "core.hooksPath"
        assert env["GIT_CONFIG_VALUE_5"] == "/dev/null"
        assert env["GIT_ATTR_NOSYSTEM"] == "1"
        assert env["GIT_NO_REPLACE_OBJECTS"] == "1"
        assert env["GIT_OPTIONAL_LOCKS"] == "0"
        assert "GITHUB_TOKEN" not in env
        if arguments and arguments[0] == "ls-remote":
            assert env["GIT_DIR"] == "/dev/null"
        else:
            assert "GIT_DIR" not in env
        calls.append(arguments)
        output = ""
        returncode = 0
        if arguments == ("rev-parse", "--show-toplevel"):
            output = f"{cwd}\n"
        elif arguments == ("rev-parse", "--git-path", "info/grafts"):
            grafts_path = (
                root / ".git" / "info" / "grafts"
                if cwd == root.resolve()
                else ROOT / ".publication-test-no-grafts"
            )
            output = f"{grafts_path}\n"
        elif arguments == (
            "for-each-ref",
            "--format=%(refname)",
            "refs/replace",
        ):
            output = "refs/replace/" + "a" * 40 + "\n" if replace_ref else ""
        elif arguments == (
            "config",
            "--null",
            "--name-only",
            "--get-regexp",
            r"^url\..*\.(insteadof|pushinsteadof)$",
        ):
            if url_rewrite:
                output = "url.https://mirror.invalid/.insteadof\0"
            else:
                returncode = 1
        elif arguments == ("remote", "get-url", "origin"):
            observed_repository = (
                repository
                if cwd == root.resolve()
                else "arkhai-io/simple-compute-market"
            )
            output = (
                f"{origin_url}\n"
                if origin_url is not None and cwd == root.resolve()
                else f"https://github.com/{observed_repository}.git\n"
            )
        elif arguments == ("branch", "--show-current"):
            branch = (
                checked_branch or working_branch
                if cwd == root.resolve()
                else policy_branch
            )
            output = f"{branch}\n"
        elif arguments == ("rev-parse", "HEAD"):
            output = f"{checked_ref if cwd == root.resolve() else policy_ref}\n"
        elif arguments == ("ls-files", "-v", "-z"):
            selected_index_tag = (
                index_tag if cwd == root.resolve() else policy_index_tag
            )
            output = f"{selected_index_tag} tracked.txt\0"
        elif arguments == (
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=none",
        ):
            selected_dirty = dirty if cwd == root.resolve() else policy_dirty
            output = " M tracked.txt\n" if selected_dirty else ""
        elif arguments == (
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
        ):
            selected_ignored = (
                ignored_entries
                if cwd == root.resolve()
                else policy_ignored_entries
            )
            output = "\0".join(selected_ignored or [])
            if output:
                output += "\0"
        elif arguments == (
            "ls-remote",
            "--exit-code",
            f"https://github.com/{repository}.git",
            f"refs/heads/{working_branch}",
        ):
            output = f"{remote_working}\trefs/heads/{working_branch}\n"
        elif arguments == (
            "ls-remote",
            "--exit-code",
            f"https://github.com/{repository}.git",
            f"refs/heads/{upstream_branch}",
        ):
            output = f"{remote_upstream}\trefs/heads/{upstream_branch}\n"
        elif arguments == (
            "ls-remote",
            "--symref",
            f"https://github.com/{repository}.git",
            "HEAD",
        ):
            if default_head_mode == "valid":
                output = (
                    f"ref: refs/heads/{default_branch}\tHEAD\n"
                    f"{remote_default}\tHEAD\n"
                )
            elif default_head_mode == "nonsymbolic":
                output = f"{remote_default}\tHEAD\n"
            else:
                output = f"ref: refs/tags/{default_branch}\tHEAD\nmalformed\tHEAD\n"
        elif arguments[:2] == ("merge-base", "--is-ancestor"):
            if cwd == ROOT.resolve():
                returncode = (
                    contract_ancestry_returncode
                    if arguments[2] == FINDING_V2_CONSUMED_REF
                    and arguments[3] != policy_ref
                    else policy_ancestry_returncode
                )
            else:
                returncode = ancestry_returncode
        else:  # pragma: no cover - proves the implementation adds no ambient read
            raise AssertionError(f"unexpected Git command: {arguments}")
        return subprocess.CompletedProcess(command, returncode, output, "")

    return run, calls


def git_authority(packet: Any, tmp_path: Path):
    runner, _ = git_runner(tmp_path)
    assert isinstance(packet, RenderedPublicationPreview)
    return _observe_rendered_git_publication_authority(
        packet,
        tmp_path,
        repo_root=ROOT,
        git_runner=runner,
    )


def select_action(
    packet: RenderedPublicationPreview,
    observed: Any,
    git: Any,
) -> dict[str, Any]:
    return _select_rendered_issue_publication_action(
        packet,
        observed,
        git,
        repo_root=ROOT,
    )


def test_preview_freezes_finding_v2_authority_and_is_explicitly_offline() -> None:
    packet = preview()
    value = json.loads(publication_preview_json(packet))

    assert value["preview_only"] is True
    assert value["authority"] == {
        "schema_version": 1,
        "operation_family": "issue",
        "destination_repo": "simple-compute-market",
        "destination_repository": "arkhai-io/simple-compute-market",
        "working_branch": "feat/issue-discovery-harness",
        "working_ref": WORKING_REF,
        "upstream_branch": "dev",
        "upstream_ref": UPSTREAM_REF,
        "default_branch": "main",
        "inbound_merge_ref": INBOUND_REF,
        "reconciliation_epoch_id": "epoch-001",
        "finding_schema_version": 2,
        "finding_v2_contract_ref": FINDING_V2_CONSUMED_REF,
        "scm_contract_ref": FINDING_V2_CONSUMED_REF,
        "finding_id": "finding-001",
        "finding_sha256": "a" * 64,
        "fingerprint": "capacity-" + "b" * 64,
        "scenario_id": "b2-s1-g1",
        "scenario_sha256": "c" * 64,
        "occurrence_payload_sha256": index_record()["occurrence_body_sha256"],
        "issue_body_sha256": value["issue_body_sha256"],
        "occurrence_comment_sha256": value["occurrence_comment_sha256"],
        "private_authorization_sha256": "d" * 64,
    }
    assert value["issue_body"].startswith("<!-- scm.finding-publication.scope.v1 {")
    assert "<!-- scm.finding-publication.occurrence.v1 {" in value["issue_body"]
    assert (
        hashlib.sha256(value["issue_body"].encode()).hexdigest()
        == value["issue_body_sha256"]
    )
    assert (
        hashlib.sha256(value["occurrence_comment"].encode()).hexdigest()
        == value["occurrence_comment_sha256"]
    )
    assert value["authority"]["issue_body_sha256"] == value["issue_body_sha256"]
    assert (
        value["authority"]["occurrence_comment_sha256"]
        == value["occurrence_comment_sha256"]
    )
    assert value["title"] == ("[capacity-" + "b" * 64 + "] durable capacity fault")


def test_raw_rendering_cannot_mint_authenticated_publication_capability(
    tmp_path: Path,
) -> None:
    packet = preview()

    assert isinstance(packet, RenderedPublicationPreview)
    assert not isinstance(packet, ValidatedPublicationPreview)
    with pytest.raises(CapacityValidationError, match="authenticated validated"):
        observe_git_publication_authority(
            packet,  # type: ignore[arg-type]
            tmp_path,
            repo_root=ROOT,
        )
    with pytest.raises(CapacityValidationError, match="authenticated validated"):
        select_issue_publication_action(
            packet,  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            repo_root=ROOT,
        )


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"ready_to_file": False}, "ready_to_file"),
        ({"working_branch": "dev"}, "branch authority"),
        ({"upstream_branch": "main"}, "branch authority"),
    ],
)
def test_preview_rejects_unready_default_mismatched_or_unpinned_authority(
    change: dict[str, Any], match: str
) -> None:
    with pytest.raises(CapacityValidationError, match=match):
        preview(**change)


def test_preview_preserves_future_result_contract_separately_from_consumed_v2() -> None:
    packet = preview(contract_ref="9" * 40).value

    assert packet["authority"]["finding_v2_contract_ref"] == FINDING_V2_CONSUMED_REF
    assert packet["authority"]["scm_contract_ref"] == "9" * 40


def test_private_destination_uses_exact_scratch_and_main_policy(
    tmp_path: Path,
) -> None:
    packet = preview(
        destination_repo="compute-market-internal-infra",
        working_branch="tools/agent-orchestration-scratch",
        upstream_branch="main",
    )
    runner, _ = git_runner(
        tmp_path,
        repository="arkhai-io/compute-market-internal-infra",
        working_branch="tools/agent-orchestration-scratch",
        upstream_branch="main",
        remote_default=UPSTREAM_REF,
        origin_url="git@github.com:arkhai-io/compute-market-internal-infra.git",
    )
    credential_material = "private-read-credential-must-not-serialize"
    credentialed_reads: list[tuple[str, ...]] = []

    def local_runner(command: list[str], **kwargs: Any):
        assert command[1] != "ls-remote"
        return runner(command, **kwargs)

    def credentialed_remote_runner(command: list[str], **kwargs: Any):
        assert command[1] == "ls-remote"
        credentialed_reads.append(tuple(command[1:]))
        assert credential_material
        return runner(command, **kwargs)

    git_authority = _observe_rendered_git_publication_authority(
        packet,
        tmp_path,
        repo_root=ROOT,
        git_runner=local_runner,
        remote_git_runner=credentialed_remote_runner,
    )
    git = git_authority.value
    observed = validate_publication_observation(
        observation(repository="arkhai-io/compute-market-internal-infra"),
        repo_root=ROOT,
    )
    action = select_action(packet, observed, git_authority)

    assert packet.value["authority"]["destination_repository"] == (
        "arkhai-io/compute-market-internal-infra"
    )
    assert git["checked_out_branch"] == "tools/agent-orchestration-scratch"
    assert git["remote_default_branch"] == "main"
    assert git["remote_default_ref"] == UPSTREAM_REF
    assert git["scm_policy_repository"] == "arkhai-io/simple-compute-market"
    assert git["scm_policy_checkout_branch"] == "feat/issue-discovery-harness"
    assert git["scm_policy_checkout_ref"] == WORKING_REF
    assert git["scm_policy_checkout_clean"] is True
    assert git["scm_policy_checkout_contains_contract"] is True
    assert git["working_contains_scm_contract"] is None
    assert len(credentialed_reads) == 3
    assert all(
        "https://github.com/arkhai-io/compute-market-internal-infra.git" in call
        for call in credentialed_reads
    )
    assert all(
        all("git@github.com:" not in argument for argument in call)
        for call in credentialed_reads
    )
    assert all(
        all(credential_material not in argument for argument in call)
        for call in credentialed_reads
    )
    assert credential_material not in canonical_json_bytes(git).decode("utf-8")
    assert credential_material not in canonical_json_bytes(action).decode("utf-8")


@pytest.mark.parametrize(
    ("runner_kwargs", "match"),
    [
        ({"policy_dirty": True}, "clean checkout"),
        ({"policy_index_tag": "S"}, "index flags"),
        ({"policy_branch": "dev"}, "canonical harness branch"),
        ({"policy_ancestry_returncode": 1}, "does not contain"),
        (
            {
                "policy_ignored_entries": [
                    "tools/issue-discovery/src/issue_discovery/"
                    "__pycache__/publication.pyc"
                ]
            },
            "ignored publication-authority",
        ),
    ],
)
def test_private_destination_rejects_untrusted_scm_policy_checkout(
    tmp_path: Path,
    runner_kwargs: dict[str, Any],
    match: str,
) -> None:
    packet = preview(
        destination_repo="compute-market-internal-infra",
        working_branch="tools/agent-orchestration-scratch",
        upstream_branch="main",
    )
    runner, _ = git_runner(
        tmp_path,
        repository="arkhai-io/compute-market-internal-infra",
        working_branch="tools/agent-orchestration-scratch",
        upstream_branch="main",
        remote_default=UPSTREAM_REF,
        **runner_kwargs,
    )

    with pytest.raises(CapacityValidationError, match=match):
        _observe_rendered_git_publication_authority(
            packet,
            tmp_path,
            repo_root=ROOT,
            git_runner=runner,
        )


def test_preview_rejects_finding_v1_and_changed_rendered_digest() -> None:
    legacy = index_record()
    legacy["candidate_kind"] = "legacy-issue-candidate"
    with pytest.raises(CapacityValidationError, match="finding-v2"):
        build_issue_publication_preview(
            legacy,
            private_authorization_sha256="d" * 64,
            repo_root=ROOT,
        )

    changed = index_record()
    changed["occurrence_body_sha256"] = "f" * 64
    with pytest.raises(CapacityValidationError, match="digest"):
        build_issue_publication_preview(
            changed,
            private_authorization_sha256="d" * 64,
            repo_root=ROOT,
        )


@pytest.mark.parametrize(
    "signature",
    [
        "line one\nline two",
        "bidi \u202eoverride",
        "zero\u200bwidth",
        "line\u2028separator",
        "paragraph\u2029separator",
        "Fixes #123",
        "Closes arkhai-io/simple-compute-market#123",
        "Resolves https://github.com/arkhai-io/simple-compute-market/issues/123",
        "password = exposed-value",
    ],
)
def test_preview_rejects_control_auto_close_or_redacted_title_source(
    signature: str,
) -> None:
    with pytest.raises(CapacityValidationError):
        preview(stable_signature=signature)


def test_preview_bounds_long_signature_without_parsing_generic_heading() -> None:
    packet = preview(
        body="# VM capacity finding occurrence\n\nGeneric heading.\n",
        stable_signature="bounded signature " + "x" * 300,
    ).value

    assert len(packet["title"]) == 240
    assert packet["title"].startswith("[capacity-")
    assert "VM capacity finding occurrence" not in packet["title"]
    assert packet["title"].endswith("...")


@pytest.mark.parametrize(
    "closing_text",
    [
        "Fixes #123",
        "Closes arkhai-io/simple-compute-market#123",
        "Resolved: https://github.com/arkhai-io/simple-compute-market/issues/123",
    ],
)
def test_preview_rejects_auto_closing_forms_anywhere_in_action_text(
    closing_text: str,
) -> None:
    with pytest.raises(CapacityValidationError, match="auto-closing"):
        preview(body=f"# Capacity fault\n\n{closing_text}\n")


@pytest.mark.parametrize(
    "reserved_text",
    [
        (
            '<!-- scm.finding-publication.occurrence.v1 {"finding_id":"extra",'
            '"finding_sha256":"' + "a" * 64 + '","occurrence_payload_sha256":"'
            + "b" * 64
            + '"} -->'
        ),
        "<!-- scm.finding-publication.malformed",
        "  <!-- scm.finding-publication.scope.v1 {} -->",
        "inline prose <!-- scm.finding-publication.occurrence.v1 {} --> remains",
    ],
)
def test_preview_rejects_reserved_marker_namespace_in_human_payload(
    reserved_text: str,
) -> None:
    with pytest.raises(CapacityValidationError, match="reserved"):
        preview(body=f"# Capacity fault\n\n{reserved_text}\n")


def test_complete_empty_observation_is_valid() -> None:
    fixture = json.loads(
        (
            ROOT
            / "tools/issue-discovery/tests/fixtures/publication/empty-observation.json"
        ).read_text(encoding="utf-8")
    )
    validated = validate_publication_observation(fixture, repo_root=ROOT)
    assert validated.value["issue_pages"]["complete"] is True
    assert validated.value["direct_rereads"] == []


@pytest.mark.parametrize("failure", ["incomplete", "missing", "drift", "duplicate"])
def test_observation_fails_closed_without_complete_stable_pagination(
    failure: str,
) -> None:
    packet = preview()
    issue = issue_snapshot(packet.value["issue_body"])
    value = observation([issue])
    if failure == "incomplete":
        value["issue_pages"]["complete"] = False
    elif failure == "missing":
        value["issue_pages"]["pages"][0]["node_ids"] = []
    elif failure == "drift":
        value["direct_rereads"][0]["state"] = "CLOSED"
    else:
        value["issues"].append(deepcopy(issue))
        value["direct_rereads"].append(deepcopy(issue))
        value["issue_pages"] = terminal_pages([issue["node_id"], issue["node_id"]])

    with pytest.raises(CapacityValidationError):
        validate_publication_observation(value, repo_root=ROOT)


def test_observation_accepts_two_page_issue_and_comment_chains() -> None:
    first = issue_snapshot("unscoped\n", number=7)
    second = issue_snapshot("unscoped\n", number=8)
    issue_value = observation([first, second])
    issue_value["issue_pages"] = {
        "complete": True,
        "total_count": 2,
        "pages": [
            {
                "request_cursor": None,
                "end_cursor": "issue-cursor-one",
                "has_next_page": True,
                "node_ids": ["ISSUE_7"],
            },
            {
                "request_cursor": "issue-cursor-one",
                "end_cursor": "issue-cursor-two",
                "has_next_page": False,
                "node_ids": ["ISSUE_8"],
            },
        ],
    }

    first_comment = issue_comment("first\n", comment_id=41)
    second_comment = issue_comment("second\n", comment_id=42)
    commented = issue_snapshot(
        "unscoped\n",
        comments=[first_comment, second_comment],
    )
    commented["comment_pages"] = {
        "complete": True,
        "total_count": 2,
        "pages": [
            {
                "request_cursor": None,
                "end_cursor": "comment-cursor-one",
                "has_next_page": True,
                "node_ids": ["COMMENT_41"],
            },
            {
                "request_cursor": "comment-cursor-one",
                "end_cursor": "comment-cursor-two",
                "has_next_page": False,
                "node_ids": ["COMMENT_42"],
            },
        ],
    }
    comment_value = observation([commented])

    assert validate_publication_observation(issue_value, repo_root=ROOT).value[
        "issues"
    ] == [first, second]
    assert validate_publication_observation(comment_value, repo_root=ROOT).value[
        "issues"
    ][0]["comments"] == [first_comment, second_comment]


def test_observation_rejects_nonterminal_final_page() -> None:
    first = issue_snapshot("unscoped\n", number=7)
    second = issue_snapshot("unscoped\n", number=8)
    value = observation([first, second])
    value["issue_pages"] = {
        "complete": True,
        "total_count": 2,
        "pages": [
            {
                "request_cursor": None,
                "end_cursor": "cursor-one",
                "has_next_page": True,
                "node_ids": ["ISSUE_7"],
            },
            {
                "request_cursor": "cursor-one",
                "end_cursor": "cursor-one",
                "has_next_page": True,
                "node_ids": ["ISSUE_8"],
            },
        ],
    }

    with pytest.raises(CapacityValidationError, match="cursor"):
        validate_publication_observation(value, repo_root=ROOT)


@pytest.mark.parametrize("failure", ["cycle", "repeated_request"])
def test_observation_rejects_cursor_cycles_or_repeated_requests(
    failure: str,
) -> None:
    issues = [issue_snapshot("unscoped\n", number=number) for number in (7, 8, 9)]
    value = observation(issues)
    third_request = "cursor-one" if failure == "repeated_request" else "cursor-two"
    second_end = "cursor-one" if failure == "cycle" else "cursor-two"
    value["issue_pages"] = {
        "complete": True,
        "total_count": 3,
        "pages": [
            {
                "request_cursor": None,
                "end_cursor": "cursor-one",
                "has_next_page": True,
                "node_ids": ["ISSUE_7"],
            },
            {
                "request_cursor": "cursor-one",
                "end_cursor": second_end,
                "has_next_page": True,
                "node_ids": ["ISSUE_8"],
            },
            {
                "request_cursor": third_request,
                "end_cursor": "cursor-three",
                "has_next_page": False,
                "node_ids": ["ISSUE_9"],
            },
        ],
    }

    with pytest.raises(CapacityValidationError, match="repeats"):
        validate_publication_observation(value, repo_root=ROOT)


def test_observation_query_must_cover_open_and_closed_issues_explicitly() -> None:
    value = observation()
    value["issue_query"]["states"] = ["OPEN"]

    with pytest.raises(CapacityValidationError):
        validate_publication_observation(value, repo_root=ROOT)


def test_observation_rejects_comment_from_another_issue_or_reused_object_id() -> None:
    comment = issue_comment("unmarked\n", number=8)
    value = observation([issue_snapshot("unscoped\n", comments=[comment])])
    with pytest.raises(CapacityValidationError, match="comment URL"):
        validate_publication_observation(value, repo_root=ROOT)

    shared = issue_comment("unmarked\n", number=7)
    first = issue_snapshot("unscoped\n", number=7, comments=[shared])
    second_shared = issue_comment("unmarked\n", number=8)
    second_shared["node_id"] = shared["node_id"]
    second = issue_snapshot("unscoped\n", number=8, comments=[second_shared])
    value = observation([first, second])
    with pytest.raises(CapacityValidationError, match="comment object ID"):
        validate_publication_observation(value, repo_root=ROOT)


def test_selector_creates_when_complete_observation_has_no_scope(
    tmp_path: Path,
) -> None:
    packet = preview()
    observed = validate_publication_observation(
        observation([issue_snapshot("Title-only capacity fault\n")]), repo_root=ROOT
    )
    action = select_action(packet, observed, git_authority(packet, tmp_path))

    assert action["action_kind"] == "create"
    assert action["issue_number"] is None
    assert action["mutation_steps"] == ["create_issue"]
    assert action["rendered_body"] == packet.value["issue_body"]
    assert action["rendered_body_sha256"] == action["authority"]["issue_body_sha256"]
    assert action["rendered_body_source"] == "issue_body"


@pytest.mark.parametrize(
    ("state", "expected_kind", "expected_steps"),
    [
        ("OPEN", "comment", ["comment_occurrence"]),
        ("CLOSED", "comment_then_reopen", ["comment_occurrence", "reopen_issue"]),
    ],
)
def test_selector_updates_or_plans_comment_before_reopen(
    tmp_path: Path,
    state: str,
    expected_kind: str,
    expected_steps: list[str],
) -> None:
    current = preview()
    prior = preview(finding_id="finding-000")
    issue = issue_snapshot(prior.value["issue_body"], state=state)
    observed = validate_publication_observation(observation([issue]), repo_root=ROOT)

    action = select_action(current, observed, git_authority(current, tmp_path))

    assert action["action_kind"] == expected_kind
    assert action["issue_number"] == 7
    assert action["mutation_steps"] == expected_steps
    assert action["rendered_body"] == current.value["occurrence_comment"]
    assert (
        action["rendered_body_sha256"]
        == action["authority"]["occurrence_comment_sha256"]
    )
    assert action["rendered_body_source"] == "occurrence_comment"


def test_selector_exact_occurrence_is_no_op_even_from_comment(
    tmp_path: Path,
) -> None:
    current = preview()
    prior = preview(finding_id="finding-000")
    comment = issue_comment(current.value["occurrence_comment"])
    issue = issue_snapshot(prior.value["issue_body"], comments=[comment])
    observed = validate_publication_observation(observation([issue]), repo_root=ROOT)

    action = select_action(current, observed, git_authority(current, tmp_path))

    assert action["action_kind"] == "no_op"
    assert action["mutation_steps"] == []
    assert action["issue_number"] == 7
    assert (
        action["rendered_body_sha256"]
        == action["authority"]["occurrence_comment_sha256"]
    )
    assert action["rendered_body_source"] == "occurrence_comment"


def test_selector_initial_body_exact_occurrence_preserves_body_provenance(
    tmp_path: Path,
) -> None:
    current = preview()
    issue = issue_snapshot(current.value["issue_body"])
    observed = validate_publication_observation(observation([issue]), repo_root=ROOT)

    action = select_action(current, observed, git_authority(current, tmp_path))

    assert action["action_kind"] == "no_op"
    assert action["rendered_body"] == current.value["issue_body"]
    assert action["rendered_body_sha256"] == action["authority"]["issue_body_sha256"]
    assert action["rendered_body_source"] == "issue_body"


def test_selector_closed_exact_occurrence_is_fresh_replay_no_op(
    tmp_path: Path,
) -> None:
    current = preview()
    prior = preview(finding_id="finding-000")
    comment = issue_comment(current.value["occurrence_comment"])
    issue = issue_snapshot(
        prior.value["issue_body"],
        state="CLOSED",
        comments=[comment],
    )
    observed = validate_publication_observation(observation([issue]), repo_root=ROOT)

    action = select_action(current, observed, git_authority(current, tmp_path))

    assert action["action_kind"] == "no_op"
    assert action["mutation_steps"] == []
    assert action["issue_number"] == 7


def test_selector_rejects_reused_finding_id_with_changed_digest(
    tmp_path: Path,
) -> None:
    current = preview()
    changed = current.value["issue_body"].replace(
        '"finding_sha256":"' + "a" * 64 + '"',
        '"finding_sha256":"' + "f" * 64 + '"',
    )
    issue = issue_snapshot(changed)
    observed = validate_publication_observation(observation([issue]), repo_root=ROOT)

    with pytest.raises(CapacityValidationError, match="reused"):
        select_action(current, observed, git_authority(current, tmp_path))


def test_selector_rejects_occurrence_comment_without_issue_scope(
    tmp_path: Path,
) -> None:
    current = preview()
    comment = issue_comment(current.value["occurrence_comment"])
    issue = issue_snapshot("unscoped issue body\n", comments=[comment])
    observed = validate_publication_observation(observation([issue]), repo_root=ROOT)

    with pytest.raises(CapacityValidationError, match="no canonical issue scope"):
        select_action(current, observed, git_authority(current, tmp_path))


def test_selector_rejects_ambiguous_scoped_issues(tmp_path: Path) -> None:
    current = preview()
    prior = preview(finding_id="finding-000")
    first = issue_snapshot(prior.value["issue_body"], number=7)
    second = issue_snapshot(prior.value["issue_body"], number=8)
    observed = validate_publication_observation(
        observation([first, second]), repo_root=ROOT
    )

    with pytest.raises(CapacityValidationError, match="ambiguous"):
        select_action(current, observed, git_authority(current, tmp_path))


def test_different_scenario_scope_does_not_deduplicate(tmp_path: Path) -> None:
    current = preview()
    other_scope = preview(
        finding_id="finding-000",
        scenario_id="b4-s1-g1",
        scenario_sha256="e" * 64,
    )
    issue = issue_snapshot(other_scope.value["issue_body"])
    observed = validate_publication_observation(observation([issue]), repo_root=ROOT)

    action = select_action(current, observed, git_authority(current, tmp_path))
    assert action["action_kind"] == "create"


def test_different_destination_scope_does_not_deduplicate(tmp_path: Path) -> None:
    current = preview()
    prior = preview(finding_id="finding-000")
    other_destination = prior.value["issue_body"].replace(
        '"destination":"arkhai-io/simple-compute-market"',
        '"destination":"arkhai-io/compute-market-internal-infra"',
    )
    issue = issue_snapshot(other_destination)
    observed = validate_publication_observation(observation([issue]), repo_root=ROOT)

    action = select_action(current, observed, git_authority(current, tmp_path))
    assert action["action_kind"] == "create"


def test_new_working_sha_remains_a_new_occurrence_of_the_same_issue(
    tmp_path: Path,
) -> None:
    current = preview()
    prior = preview(finding_id="finding-000", working_ref="9" * 40)
    issue = issue_snapshot(prior.value["issue_body"])
    observed = validate_publication_observation(observation([issue]), repo_root=ROOT)

    action = select_action(current, observed, git_authority(current, tmp_path))
    assert action["action_kind"] == "comment"
    assert action["authority"]["working_ref"] == WORKING_REF


def test_git_guard_names_only_exact_reads_and_binds_remote_refs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ambient-token-must-not-reach-git")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'url.evil.insteadOf=github:'")
    packet = preview()
    runner, calls = git_runner(tmp_path)
    authority = _observe_rendered_git_publication_authority(
        packet,
        tmp_path,
        repo_root=ROOT,
        git_runner=runner,
    ).value

    assert authority["remote_working_ref"] == WORKING_REF
    assert authority["publication_preview_sha256"] == packet.canonical_sha256
    assert authority["remote_upstream_ref"] == UPSTREAM_REF
    assert authority["pinned_upstream_ref"] == UPSTREAM_REF
    assert authority["remote_upstream_drifted"] is False
    assert authority["remote_default_branch"] == "main"
    assert authority["remote_default_ref"] == "4" * 40
    assert authority["working_contains_pinned_upstream"] is True
    assert authority["pinned_inbound_merge_ref"] == INBOUND_REF
    assert authority["working_contains_inbound_merge"] is True
    assert authority["finding_v2_contract_ref"] == FINDING_V2_CONSUMED_REF
    assert authority["scm_contract_contains_finding_v2_contract"] is True
    assert authority["scm_policy_repository"] == "arkhai-io/simple-compute-market"
    assert authority["scm_policy_checkout_branch"] == (
        "feat/issue-discovery-harness"
    )
    assert authority["scm_policy_checkout_ref"] == WORKING_REF
    assert authority["scm_policy_checkout_clean"] is True
    assert authority["scm_policy_checkout_contains_contract"] is True
    assert authority["working_contains_scm_contract"] is True
    assert authority["working_contains_finding_v2_contract"] is True
    assert all(call[0] not in {"fetch", "push", "checkout", "switch"} for call in calls)
    assert (
        "ls-remote",
        "--exit-code",
        "https://github.com/arkhai-io/simple-compute-market.git",
        "refs/heads/feat/issue-discovery-harness",
    ) in calls


def test_git_guard_constructs_fixed_https_remote_from_ssh_origin(
    tmp_path: Path,
) -> None:
    packet = preview()
    configured_origin = "git@github.com:arkhai-io/simple-compute-market.git"
    runner, calls = git_runner(tmp_path, origin_url=configured_origin)

    _observe_rendered_git_publication_authority(
        packet,
        tmp_path,
        repo_root=ROOT,
        git_runner=runner,
    )

    remote_calls = [call for call in calls if call[0] == "ls-remote"]
    assert len(remote_calls) == 3
    assert all(
        "https://github.com/arkhai-io/simple-compute-market.git" in call
        for call in remote_calls
    )
    assert all(
        all(configured_origin not in argument for argument in call)
        for call in remote_calls
    )


@pytest.mark.parametrize(
    "origin_url",
    [
        "https://github.com:443/arkhai-io/simple-compute-market.git",
        "https://user@github.com/arkhai-io/simple-compute-market.git",
        "file:///tmp/simple-compute-market.git",
    ],
)
def test_git_guard_rejects_port_userinfo_or_local_origin(
    tmp_path: Path,
    origin_url: str,
) -> None:
    packet = preview()
    runner, calls = git_runner(tmp_path, origin_url=origin_url)

    with pytest.raises(CapacityValidationError, match="remote does not match"):
        _observe_rendered_git_publication_authority(
            packet,
            tmp_path,
            repo_root=ROOT,
            git_runner=runner,
        )
    assert not any(call[0] == "ls-remote" for call in calls)


@pytest.mark.parametrize(
    "ignored_entry",
    [
        "tools/issue-discovery/src/issue_discovery/__pycache__/publication.pyc",
        "tools/issue-discovery/sitecustomize.py",
        "tools/issue-discovery/config/ignored.private",
        "tools/issue-discovery/schemas/ignored.private",
    ],
)
def test_git_guard_rejects_ignored_policy_or_source_artifacts(
    tmp_path: Path,
    ignored_entry: str,
) -> None:
    packet = preview()
    runner, _ = git_runner(tmp_path, ignored_entries=[ignored_entry])

    with pytest.raises(CapacityValidationError, match="ignored publication-authority"):
        _observe_rendered_git_publication_authority(
            packet,
            tmp_path,
            repo_root=ROOT,
            git_runner=runner,
        )


def test_git_guard_rejects_ignored_executable_but_allows_external_venv(
    tmp_path: Path,
) -> None:
    executable_entry = "tools/issue-discovery/generated/authority-helper"
    executable = tmp_path / executable_entry
    executable.parent.mkdir(parents=True)
    executable.write_text("helper\n", encoding="utf-8")
    executable.chmod(0o755)
    packet = preview()
    rejected_runner, _ = git_runner(
        tmp_path,
        ignored_entries=[executable_entry],
    )
    allowed_runner, _ = git_runner(
        tmp_path,
        ignored_entries=[
            "tools/issue-discovery/.venv/lib/python3.11/site-packages/sitecustomize.py"
        ],
    )

    with pytest.raises(CapacityValidationError, match="ignored publication-authority"):
        _observe_rendered_git_publication_authority(
            packet,
            tmp_path,
            repo_root=ROOT,
            git_runner=rejected_runner,
        )
    assert _observe_rendered_git_publication_authority(
        packet,
        tmp_path,
        repo_root=ROOT,
        git_runner=allowed_runner,
    ).value["clean"] is True


def test_advanced_remote_upstream_is_recorded_without_retargeting_frozen_series(
    tmp_path: Path,
) -> None:
    packet = preview()
    advanced_upstream = "9" * 40
    runner, _ = git_runner(tmp_path, remote_upstream=advanced_upstream)
    git_authority = _observe_rendered_git_publication_authority(
        packet,
        tmp_path,
        repo_root=ROOT,
        git_runner=runner,
    )
    observed = validate_publication_observation(observation(), repo_root=ROOT)

    action = select_action(packet, observed, git_authority)

    assert git_authority.value["pinned_upstream_ref"] == UPSTREAM_REF
    assert git_authority.value["remote_upstream_ref"] == advanced_upstream
    assert git_authority.value["remote_upstream_drifted"] is True
    assert action["authority"]["upstream_ref"] == UPSTREAM_REF
    assert action["action_kind"] == "create"


def test_scm_policy_checkout_head_is_bound_into_action_id(tmp_path: Path) -> None:
    packet = preview()
    observed = validate_publication_observation(observation(), repo_root=ROOT)
    first_runner, _ = git_runner(tmp_path, policy_ref="8" * 40)
    second_runner, _ = git_runner(tmp_path, policy_ref="9" * 40)
    first_git = _observe_rendered_git_publication_authority(
        packet,
        tmp_path,
        repo_root=ROOT,
        git_runner=first_runner,
    )
    second_git = _observe_rendered_git_publication_authority(
        packet,
        tmp_path,
        repo_root=ROOT,
        git_runner=second_runner,
    )
    first = select_action(packet, observed, first_git)
    second = select_action(packet, observed, second_git)

    assert first_git.canonical_sha256 != second_git.canonical_sha256
    assert first["git_observation_sha256"] != second["git_observation_sha256"]
    assert first["action_id"] != second["action_id"]


@pytest.mark.parametrize(
    ("first_inbound", "second_inbound"),
    [
        (None, INBOUND_REF),
        (INBOUND_REF, "4" * 40),
    ],
)
def test_git_token_cannot_cross_preview_inbound_authority(
    tmp_path: Path,
    first_inbound: str | None,
    second_inbound: str,
) -> None:
    first_preview = preview(inbound_ref=first_inbound)
    second_preview = preview(inbound_ref=second_inbound)
    first_git = git_authority(first_preview, tmp_path)
    observed = validate_publication_observation(observation(), repo_root=ROOT)

    assert first_git.value["publication_preview_sha256"] == (
        first_preview.canonical_sha256
    )
    assert first_git.value["pinned_inbound_merge_ref"] == first_inbound
    with pytest.raises(CapacityValidationError, match="Git authority"):
        select_action(second_preview, observed, first_git)


@pytest.mark.parametrize(
    ("runner_kwargs", "match"),
    [
        ({"remote_working": "9" * 40}, "drifted"),
        ({"checked_ref": "9" * 40}, "checked-out"),
        ({"checked_branch": "other-branch"}, "checked-out"),
        ({"dirty": True}, "clean checkout"),
        ({"index_tag": "h"}, "index flags"),
        ({"index_tag": "S"}, "index flags"),
        ({"replace_ref": True}, "replace refs"),
        ({"url_rewrite": True}, "URL rewrite"),
        ({"default_head_mode": "nonsymbolic"}, "not one symbolic"),
        ({"default_head_mode": "malformed"}, "malformed"),
        ({"default_branch": "trunk"}, "differs from publication policy"),
        ({"ancestry_returncode": 1}, "does not contain"),
        (
            {"contract_ancestry_returncode": 1},
            "does not contain consumed finding-v2 contract",
        ),
    ],
)
def test_git_guard_fails_closed_on_ref_worktree_or_ancestry_drift(
    tmp_path: Path,
    runner_kwargs: dict[str, Any],
    match: str,
) -> None:
    packet = preview()
    runner, _ = git_runner(tmp_path, **runner_kwargs)
    with pytest.raises(CapacityValidationError, match=match):
        _observe_rendered_git_publication_authority(
            packet,
            tmp_path,
            repo_root=ROOT,
            git_runner=runner,
        )


@pytest.mark.parametrize("content", ["", f"{WORKING_REF} {UPSTREAM_REF}\n"])
def test_git_guard_rejects_any_grafts_file(tmp_path: Path, content: str) -> None:
    grafts = tmp_path / ".git" / "info" / "grafts"
    grafts.parent.mkdir(parents=True)
    grafts.write_text(content, encoding="ascii")
    packet = preview()
    runner, _ = git_runner(tmp_path)

    with pytest.raises(CapacityValidationError, match="graft authority"):
        _observe_rendered_git_publication_authority(
            packet,
            tmp_path,
            repo_root=ROOT,
            git_runner=runner,
        )


@pytest.mark.parametrize("linked_checkout", ["destination", "policy"])
def test_git_guard_rejects_symlinked_checkout_roots(
    tmp_path: Path,
    linked_checkout: str,
) -> None:
    destination = tmp_path / "destination"
    destination.mkdir()
    destination_link = tmp_path / "destination-link"
    destination_link.symlink_to(destination, target_is_directory=True)
    policy_link = tmp_path / "policy-link"
    policy_link.symlink_to(ROOT, target_is_directory=True)
    destination_argument = (
        destination_link if linked_checkout == "destination" else destination
    )
    policy_argument = policy_link if linked_checkout == "policy" else ROOT
    packet = preview()

    def must_not_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise AssertionError("Git must not run before checkout-root validation")

    planner = GuardedIssuePublicationPlanner(
        tmp_path / "run",
        destination_repo_root=destination_argument,
        policy_root=policy_argument,
    )
    assert planner.destination_repo_root == destination_argument
    assert planner.policy_root == policy_argument
    with pytest.raises(CapacityValidationError, match="non-symlink directory"):
        _observe_rendered_git_publication_authority(
            packet,
            planner.destination_repo_root,
            repo_root=planner.policy_root,
            git_runner=must_not_run,
        )


@pytest.mark.parametrize("path_kind", ["final_symlink", "ancestor_symlink", "dotdot"])
@pytest.mark.parametrize("surface", ["publish-preview", "publish"])
def test_runner_cli_rejects_noncanonical_policy_root_before_owner_replay(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    path_kind: str,
    surface: str,
) -> None:
    if path_kind == "final_symlink":
        supplied_root = tmp_path / "scm-link"
        supplied_root.symlink_to(ROOT, target_is_directory=True)
    elif path_kind == "ancestor_symlink":
        linked_parent = tmp_path / "linked-parent"
        linked_parent.symlink_to(ROOT.parent, target_is_directory=True)
        supplied_root = linked_parent / ROOT.name
    else:
        supplied_root = ROOT / ".." / ROOT.name

    arguments = [
        "--repo-root",
        str(supplied_root),
        "issue",
        surface,
        "missing-run",
        "finding-001",
    ]
    if surface == "publish":
        arguments.extend(
            [
                "--mode",
                "dry-run",
                "--observation",
                "missing-observation.json",
                "--destination-repo-root",
                str(ROOT),
            ]
        )
    arguments.extend(["--private-authorization-sha256", "d" * 64])

    code = main(arguments)

    assert code == 1
    assert "canonical non-symlink directory" in capsys.readouterr().out


def test_runner_cli_preserves_ordinary_dot_policy_root(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(ROOT)

    code = main(
        [
            "--repo-root",
            ".",
            "issue",
            "publish-preview",
            "missing-run",
            "finding-001",
            "--private-authorization-sha256",
            "d" * 64,
        ]
    )

    assert code == 1
    assert "canonical non-symlink directory" not in capsys.readouterr().out


def test_publication_schemas_are_closed_against_secret_or_private_fields() -> None:
    packet = preview().value
    packet["github_token"] = "secret"
    schema = json.loads(
        (
            ROOT
            / "tools/issue-discovery/schemas/finding-publication-preview.schema.json"
        ).read_text(encoding="utf-8")
    )
    errors = list(Draft202012Validator(schema).iter_errors(packet))
    assert errors

    observed = observation()
    observed["private_evidence_path"] = "/home/person/run"
    with pytest.raises(CapacityValidationError, match="Additional"):
        validate_publication_observation(observed, repo_root=ROOT)

    authority = preview().value["authority"]
    authority["destination_repository"] = "arkhai-io/compute-market-internal-infra"
    authority_schema = json.loads(
        (
            ROOT
            / "tools/issue-discovery/schemas/finding-publication-authority.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(authority_schema).iter_errors(authority))


def test_action_schema_rejects_missing_authority_or_kind_step_mismatch(
    tmp_path: Path,
) -> None:
    packet = preview()
    observed = validate_publication_observation(observation(), repo_root=ROOT)
    action = select_action(packet, observed, git_authority(packet, tmp_path))
    action_schema = json.loads(
        (
            ROOT
            / "tools/issue-discovery/schemas/finding-publication-action.schema.json"
        ).read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(action_schema)
    assert not list(validator.iter_errors(action))

    missing = deepcopy(action)
    missing.pop("authority")
    assert list(validator.iter_errors(missing))

    mismatched = deepcopy(action)
    mismatched["mutation_steps"] = []
    assert list(validator.iter_errors(mismatched))


def test_preview_rechecks_redaction_before_freezing_public_bytes() -> None:
    body = "# Capacity fault\n\npassword = exposed-value\n"
    with pytest.raises(CapacityValidationError, match="redaction"):
        preview(body=body)


def test_publish_parser_has_no_force_and_requires_explicit_inputs() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "issue",
            "publish",
            "run",
            "finding-001",
            "--mode",
            "dry-run",
            "--observation",
            "observation.json",
            "--destination-repo-root",
            "destination",
            "--private-authorization-sha256",
            "d" * 64,
        ]
    )
    assert args.mode == "dry-run"
    assert not hasattr(args, "force")

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "issue",
                "publish",
                "run",
                "finding-001",
                "--force",
            ]
        )


def test_runner_dry_and_live_select_byte_identical_action_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    packet = preview()
    observed = validate_publication_observation(observation(), repo_root=ROOT)
    action = select_action(packet, observed, git_authority(packet, tmp_path))
    expected = canonical_json_bytes(action).decode("utf-8")

    monkeypatch.setattr(
        "issue_discovery.issues.GuardedIssuePublicationPlanner.preview",
        lambda self, finding_id, private_authorization_sha256: packet,
    )
    monkeypatch.setattr(
        "issue_discovery.publication.load_publication_observation",
        lambda path, repo_root: observed,
    )
    monkeypatch.setattr(
        "issue_discovery.publication.publication_action_json",
        lambda selected_action: expected,
    )
    monkeypatch.setattr(
        "issue_discovery.issues.GuardedIssuePublicationPlanner.select",
        lambda self, selected_preview, selected_observation: action,
    )
    runner = DiscoveryRunner(repo_root=ROOT)

    dry_code = runner.issue_publish_plan(
        tmp_path / "run",
        "finding-001",
        destination_repo_root=tmp_path,
        observation_path=tmp_path / "observation.json",
        private_authorization_sha256="d" * 64,
        mode="dry-run",
    )
    dry_output = capsys.readouterr().out
    live_code = runner.issue_publish_plan(
        tmp_path / "run",
        "finding-001",
        destination_repo_root=tmp_path,
        observation_path=tmp_path / "observation.json",
        private_authorization_sha256="d" * 64,
        mode="live",
    )
    live_output = capsys.readouterr().out

    assert dry_code == 0
    assert live_code == 2
    assert dry_output == live_output == expected


def test_cleanup_workflow_does_not_reference_publication_planner() -> None:
    # Cleanup remains phase-owned. Publication is reachable only from explicit
    # issue_publish_* entry points, never from the generic workflow executor.
    generic_names = {
        name
        for name in DiscoveryRunner.__dict__
        if name.startswith("_run_")
        or name in {"run_strict", "run_continue", "run_profile"}
    }
    assert generic_names
    for name in generic_names:
        code = DiscoveryRunner.__dict__[name].__code__
        assert "GuardedIssuePublicationPlanner" not in code.co_names
        assert "issue_publish_plan" not in code.co_names
