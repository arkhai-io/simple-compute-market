from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Callable, Mapping, Sequence
import unicodedata
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, FormatChecker

from issue_discovery.capacity import (
    CapacityValidationError,
    canonical_json_bytes,
    canonical_sha256,
)
from issue_discovery import capacity_findings
from issue_discovery.redaction import Redactor


FINDING_V2_CONSUMED_REF = "5ece6f908605f58d7b1143c37316ef4aa9845508"
PUBLICATION_CAPABILITY = "guard-issue-fix-publication"
PUBLICATION_OPERATION_FAMILY = "issue"

_PUBLICATION_TOKEN = object()
_RENDERED_PREVIEW_TOKEN = object()
_OWNER_REPLAY_TOKEN = object()
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_REF_RE = re.compile(r"^[0-9a-f]{40}$")
_FINGERPRINT_RE = re.compile(r"^capacity-[0-9a-f]{64}$")
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9_=-]{3,160}$")
_MARKER_PREFIX = "<!-- scm.finding-publication."
_MARKER_RE = re.compile(
    r"^<!-- scm\.finding-publication\.(scope|occurrence)\.v1 (\{.*\}) -->$"
)
_AUTO_CLOSE_RE = re.compile(
    r"(?ix)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?[ \t]+(?:"
    r"\#[1-9][0-9]*|"
    r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\#[1-9][0-9]*|"
    r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*"
    r")\b"
)
_IGNORED_POLICY_PREFIXES = (
    "tools/issue-discovery/src/",
    "tools/issue-discovery/config/",
    "tools/issue-discovery/schemas/",
)
_IGNORED_EXTERNAL_VENV_PREFIX = "tools/issue-discovery/.venv/"
_IGNORED_SOURCE_SUFFIXES = frozenset(
    {
        ".bash",
        ".dll",
        ".dylib",
        ".egg",
        ".fish",
        ".json",
        ".pth",
        ".py",
        ".pyc",
        ".pyd",
        ".pyi",
        ".pyo",
        ".pyz",
        ".sh",
        ".so",
        ".toml",
        ".whl",
        ".yaml",
        ".yml",
        ".zip",
        ".zsh",
    }
)

_DESTINATION_POLICIES: dict[str, dict[str, str]] = {
    "simple-compute-market": {
        "repository": "arkhai-io/simple-compute-market",
        "working_branch": "feat/issue-discovery-harness",
        "upstream_branch": "dev",
        "default_branch": "main",
    },
    "compute-market-internal-infra": {
        "repository": "arkhai-io/compute-market-internal-infra",
        "working_branch": "tools/agent-orchestration-scratch",
        "upstream_branch": "main",
        "default_branch": "main",
    },
}
_SCOPE_KEYS = frozenset(
    {
        "destination",
        "fingerprint",
        "scenario_id",
        "scenario_sha256",
        "working_branch",
    }
)
_OCCURRENCE_KEYS = frozenset(
    {"finding_id", "finding_sha256", "occurrence_payload_sha256"}
)


@dataclass(frozen=True, slots=True)
class RenderedPublicationPreview:
    """Schema-valid offline rendering without authenticated finding authority."""

    canonical_sha256: str
    _canonical_bytes: bytes = field(repr=False)
    _render_token: object = field(repr=False)

    @property
    def value(self) -> dict[str, Any]:
        return _decode_canonical_object(self._canonical_bytes, label="rendered preview")


@dataclass(frozen=True, slots=True)
class ValidatedPublicationPreview:
    canonical_sha256: str
    _canonical_bytes: bytes = field(repr=False)
    _validation_token: object = field(repr=False)

    @property
    def value(self) -> dict[str, Any]:
        return _decode_canonical_object(self._canonical_bytes, label="preview")


@dataclass(frozen=True, slots=True)
class ValidatedPublicationObservation:
    canonical_sha256: str
    _canonical_bytes: bytes = field(repr=False)
    _validation_token: object = field(repr=False)

    @property
    def value(self) -> dict[str, Any]:
        return _decode_canonical_object(self._canonical_bytes, label="observation")


@dataclass(frozen=True, slots=True)
class ValidatedGitPublicationAuthority:
    canonical_sha256: str
    _canonical_bytes: bytes = field(repr=False)
    _validation_token: object = field(repr=False)

    @property
    def value(self) -> dict[str, Any]:
        return _decode_canonical_object(self._canonical_bytes, label="git authority")


@dataclass(frozen=True, slots=True)
class ValidatedIssuePublicationAction:
    canonical_sha256: str
    _canonical_bytes: bytes = field(repr=False)
    _validation_token: object = field(repr=False)

    @property
    def value(self) -> dict[str, Any]:
        return _decode_canonical_object(self._canonical_bytes, label="issue action")


@dataclass(frozen=True, slots=True)
class _ParsedIssue:
    issue: dict[str, Any]
    scope: dict[str, str] | None
    occurrences: tuple[dict[str, str], ...]
    occurrence_sources: dict[str, str]


GitRunner = Callable[..., subprocess.CompletedProcess[str]]


def _sealed_git_environment() -> dict[str, str]:
    environment = {
        "PATH": os.environ.get("PATH", os.defpath),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_COUNT": "6",
        "GIT_CONFIG_KEY_0": "core.fsmonitor",
        "GIT_CONFIG_VALUE_0": "false",
        "GIT_CONFIG_KEY_1": "core.untrackedCache",
        "GIT_CONFIG_VALUE_1": "false",
        "GIT_CONFIG_KEY_2": "core.filemode",
        "GIT_CONFIG_VALUE_2": "true",
        "GIT_CONFIG_KEY_3": "core.ignorecase",
        "GIT_CONFIG_VALUE_3": "false",
        "GIT_CONFIG_KEY_4": "core.symlinks",
        "GIT_CONFIG_VALUE_4": "true",
        "GIT_CONFIG_KEY_5": "core.hooksPath",
        "GIT_CONFIG_VALUE_5": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
    }
    for name in ("LANG", "LC_ALL", "LC_CTYPE", "TMPDIR"):
        value = os.environ.get(name)
        if value is not None:
            environment[name] = value
    return environment


def _decode_canonical_object(content: bytes, *, label: str) -> dict[str, Any]:
    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, dict):  # pragma: no cover - construction invariant
        raise CapacityValidationError(f"validated {label} is not an object")
    return value


def _require_validated(
    value: object,
    expected_type: type[
        ValidatedPublicationPreview
        | ValidatedPublicationObservation
        | ValidatedGitPublicationAuthority
        | ValidatedIssuePublicationAction
    ],
    *,
    label: str,
) -> dict[str, Any]:
    if (
        not isinstance(value, expected_type)
        or value._validation_token is not _PUBLICATION_TOKEN
    ):
        raise CapacityValidationError(
            f"{label} requires an authenticated validated model"
        )
    current = value.value
    content = canonical_json_bytes(current)
    if (
        content != value._canonical_bytes
        or hashlib.sha256(content).hexdigest() != value.canonical_sha256
    ):
        raise CapacityValidationError(f"validated {label} changed after validation")
    return current


def _require_rendered_preview(value: object) -> dict[str, Any]:
    if (
        not isinstance(value, RenderedPublicationPreview)
        or value._render_token is not _RENDERED_PREVIEW_TOKEN
    ):
        raise CapacityValidationError(
            "offline rendering requires an authenticated rendered-preview model"
        )
    current = value.value
    content = canonical_json_bytes(current)
    if (
        content != value._canonical_bytes
        or hashlib.sha256(content).hexdigest() != value.canonical_sha256
    ):
        raise CapacityValidationError("rendered preview changed after validation")
    return current


def _mint_validated_publication_preview(
    rendered: RenderedPublicationPreview,
    *,
    replay_token: object,
) -> ValidatedPublicationPreview:
    if replay_token is not _OWNER_REPLAY_TOKEN:
        raise CapacityValidationError(
            "validated publication preview requires owner-only finding replay"
        )
    value = _require_rendered_preview(rendered)
    content = canonical_json_bytes(value)
    return ValidatedPublicationPreview(
        canonical_sha256=hashlib.sha256(content).hexdigest(),
        _canonical_bytes=content,
        _validation_token=_PUBLICATION_TOKEN,
    )


def _schema_path(repo_root: Path, name: str) -> Path:
    return repo_root / "tools" / "issue-discovery" / "schemas" / name


def _canonical_checkout_root(candidate: Path, *, label: str) -> Path:
    expanded = candidate.expanduser()
    lexical_absolute = (
        expanded if expanded.is_absolute() else Path.cwd() / expanded
    )
    try:
        resolved = lexical_absolute.resolve(strict=True)
    except OSError as exc:
        raise CapacityValidationError(
            f"{label} checkout is unavailable: {exc}"
        ) from exc
    if lexical_absolute != resolved:
        raise CapacityValidationError(
            f"{label} checkout must be a canonical non-symlink directory"
        )
    try:
        candidate_stat = lexical_absolute.lstat()
    except OSError as exc:  # pragma: no cover - resolved immediately above
        raise CapacityValidationError(
            f"{label} checkout is unavailable: {exc}"
        ) from exc
    if stat.S_ISLNK(candidate_stat.st_mode) or not stat.S_ISDIR(
        candidate_stat.st_mode
    ):
        raise CapacityValidationError(
            f"{label} checkout must be a canonical non-symlink directory"
        )
    return resolved


def _reject_ignored_publication_authority(
    checkout: Path,
    entries: Sequence[str],
    *,
    label: str,
) -> None:
    for entry in entries:
        if not entry:
            continue
        if entry.startswith("/") or ".." in Path(entry).parts:
            raise CapacityValidationError(
                f"{label} checkout reports an unsafe ignored path"
            )
        if not entry.startswith("tools/issue-discovery/"):
            continue
        if entry.startswith(_IGNORED_EXTERNAL_VENV_PREFIX):
            continue
        if entry.startswith(_IGNORED_POLICY_PREFIXES) or Path(entry).suffix.lower() in (
            _IGNORED_SOURCE_SUFFIXES
        ):
            raise CapacityValidationError(
                f"{label} checkout contains ignored publication-authority artifacts"
            )
        artifact = checkout / entry
        try:
            artifact_stat = artifact.lstat()
        except OSError as exc:
            raise CapacityValidationError(
                f"cannot inspect {label} ignored publication authority: {exc}"
            ) from exc
        if artifact_stat.st_mode & 0o111:
            raise CapacityValidationError(
                f"{label} checkout contains ignored publication-authority artifacts"
            )


def _validate_schema(value: Mapping[str, Any], *, repo_root: Path, name: str) -> None:
    path = _schema_path(repo_root, name)
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CapacityValidationError(
            f"publication schema is unavailable: {name}"
        ) from exc
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(dict(value)), key=lambda item: list(item.path)
    )
    if errors:
        details = "; ".join(
            f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise CapacityValidationError(f"{name} validation failed: {details}")


def _strict_json_object(path: Path, *, label: str) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite number {value!r} is invalid")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key {key!r}")
            result[key] = value
        return result

    try:
        content = path.read_bytes()
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CapacityValidationError(f"{label} is not strict JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise CapacityValidationError(f"{label} must be a JSON object")
    return value


def _require_digest(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise CapacityValidationError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _require_ref(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _REF_RE.fullmatch(value) is None:
        raise CapacityValidationError(
            f"{label} must be a 40-character lowercase Git ref"
        )
    return value


def _normalize_occurrence_payload(value: str) -> str:
    return value.rstrip("\r\n") + "\n"


def _reject_auto_closing_text(value: str, *, label: str) -> None:
    # JSON Schema closes packet shape. This semantic seam additionally rejects
    # every supported GitHub closing-keyword target before a validated preview
    # token can exist, including cross-repository and canonical URL forms.
    if _AUTO_CLOSE_RE.search(value) is not None:
        raise CapacityValidationError(
            f"{label} contains a GitHub auto-closing issue reference"
        )


def _has_nonprinting_unicode(value: str) -> bool:
    return any(
        unicodedata.category(character).startswith("C")
        or unicodedata.category(character) in {"Zl", "Zp"}
        for character in value
    )


def _marker(kind: str, payload: Mapping[str, str]) -> str:
    if kind == "scope":
        expected = _SCOPE_KEYS
    elif kind == "occurrence":
        expected = _OCCURRENCE_KEYS
    else:  # pragma: no cover - private caller invariant
        raise CapacityValidationError(f"unsupported publication marker kind: {kind}")
    if set(payload) != expected:
        raise CapacityValidationError(f"{kind} marker fields are not closed")
    for key, value in payload.items():
        if (
            not isinstance(value, str)
            or not value
            or any(token in value for token in ("--", "<", ">"))
        ):
            raise CapacityValidationError(f"unsafe {kind} marker value for {key}")
    encoded = canonical_json_bytes(dict(payload)).decode("utf-8").removesuffix("\n")
    return f"<!-- scm.finding-publication.{kind}.v1 {encoded} -->"


def _scope_payload(authority: Mapping[str, Any]) -> dict[str, str]:
    return {
        "destination": str(authority["destination_repository"]),
        "fingerprint": str(authority["fingerprint"]),
        "scenario_id": str(authority["scenario_id"]),
        "scenario_sha256": str(authority["scenario_sha256"]),
        "working_branch": str(authority["working_branch"]),
    }


def _occurrence_payload(authority: Mapping[str, Any]) -> dict[str, str]:
    return {
        "finding_id": str(authority["finding_id"]),
        "finding_sha256": str(authority["finding_sha256"]),
        "occurrence_payload_sha256": str(authority["occurrence_payload_sha256"]),
    }


def _scope_sha256(scope: Mapping[str, str]) -> str:
    return hashlib.sha256(
        b"scm.finding-publication.scope.v1\0" + canonical_json_bytes(dict(scope))
    ).hexdigest()


def _validate_preview_rendered_authority(packet: Mapping[str, Any]) -> None:
    authority = packet.get("authority")
    if not isinstance(authority, Mapping):
        raise CapacityValidationError("publication preview lacks frozen authority")
    if (
        packet.get("issue_body_sha256") != authority.get("issue_body_sha256")
        or packet.get("occurrence_comment_sha256")
        != authority.get("occurrence_comment_sha256")
        or hashlib.sha256(str(packet.get("issue_body")).encode("utf-8")).hexdigest()
        != authority.get("issue_body_sha256")
        or hashlib.sha256(
            str(packet.get("occurrence_comment")).encode("utf-8")
        ).hexdigest()
        != authority.get("occurrence_comment_sha256")
    ):
        raise CapacityValidationError(
            "publication preview rendered bytes differ from frozen authority"
        )


def build_issue_publication_preview(
    index_record: Mapping[str, Any],
    *,
    private_authorization_sha256: str,
    repo_root: Path,
) -> RenderedPublicationPreview:
    """Render schema-valid bytes without granting publication capability."""
    index = dict(index_record)
    if (
        index.get("schema_version") != 1
        or index.get("candidate_kind") != "capacity-finding-v2"
    ):
        raise CapacityValidationError("guarded publication requires a finding-v2 index")
    if index.get("publication_capability") != PUBLICATION_CAPABILITY:
        raise CapacityValidationError(
            "finding-v2 index lacks guarded publication authority"
        )
    readiness = index.get("filing_readiness")
    if not isinstance(readiness, Mapping) or readiness.get("ready_to_file") is not True:
        raise CapacityValidationError(
            "guarded publication requires ready_to_file finding v2"
        )
    finding_sha256 = _require_digest(
        index.get("finding_sha256"), label="finding_sha256"
    )
    occurrence_payload_sha256 = _require_digest(
        index.get("occurrence_body_sha256"), label="occurrence_payload_sha256"
    )
    fingerprint = index.get("fingerprint")
    if (
        not isinstance(fingerprint, str)
        or _FINGERPRINT_RE.fullmatch(fingerprint) is None
    ):
        raise CapacityValidationError("publication fingerprint is not SCM-derived")
    destination = index.get("destination_repo")
    if destination not in _DESTINATION_POLICIES:
        raise CapacityValidationError("unsupported publication destination")
    policy = _DESTINATION_POLICIES[str(destination)]
    observed = index.get("observed_authority")
    if not isinstance(observed, Mapping):
        raise CapacityValidationError("finding-v2 index lacks observed authority")
    working_branch = observed.get("working_branch")
    upstream_branch = observed.get("upstream_branch")
    if (
        working_branch != policy["working_branch"]
        or upstream_branch != policy["upstream_branch"]
    ):
        raise CapacityValidationError(
            "finding branch authority violates destination policy"
        )
    if working_branch in {policy["upstream_branch"], policy["default_branch"]}:
        raise CapacityValidationError(
            "default/upstream branch cannot be a publication working branch"
        )
    body = index.get("occurrence_body")
    if not isinstance(body, str) or not body:
        raise CapacityValidationError("finding-v2 index lacks occurrence body")
    normalized_body = _normalize_occurrence_payload(body)
    if body != normalized_body:
        raise CapacityValidationError(
            "occurrence payload must have exactly one trailing newline"
        )
    if hashlib.sha256(body.encode("utf-8")).hexdigest() != occurrence_payload_sha256:
        raise CapacityValidationError(
            "occurrence payload digest does not match its bytes"
        )
    redaction_path = (
        repo_root / "tools" / "issue-discovery" / "config" / "redactions.yaml"
    )
    try:
        redactor = Redactor.from_file(redaction_path)
    except (OSError, ValueError) as exc:
        raise CapacityValidationError(
            "SCM publication redaction policy is unavailable"
        ) from exc
    if redactor.redact(body) != body:
        raise CapacityValidationError(
            "occurrence payload contains data denied by publication redaction"
        )
    if _MARKER_PREFIX in body:
        raise CapacityValidationError(
            "occurrence payload uses the reserved publication-marker namespace"
        )
    _reject_auto_closing_text(body, label="occurrence payload")
    private_digest = _require_digest(
        private_authorization_sha256,
        label="private_authorization_sha256",
    )
    authority = {
        "schema_version": 1,
        "operation_family": PUBLICATION_OPERATION_FAMILY,
        "destination_repo": destination,
        "destination_repository": policy["repository"],
        "working_branch": working_branch,
        "working_ref": _require_ref(observed.get("working_ref"), label="working_ref"),
        "upstream_branch": upstream_branch,
        "upstream_ref": _require_ref(
            observed.get("upstream_ref"), label="upstream_ref"
        ),
        "default_branch": policy["default_branch"],
        "inbound_merge_ref": observed.get("inbound_merge_ref"),
        "reconciliation_epoch_id": observed.get("reconciliation_epoch_id"),
        "finding_schema_version": 2,
        "finding_v2_contract_ref": FINDING_V2_CONSUMED_REF,
        "scm_contract_ref": _require_ref(
            index.get("scm_contract_ref"), label="scm_contract_ref"
        ),
        "finding_id": index.get("finding_id"),
        "finding_sha256": finding_sha256,
        "fingerprint": fingerprint,
        "scenario_id": index.get("scenario_id"),
        "scenario_sha256": _require_digest(
            index.get("scenario_sha256"), label="scenario_sha256"
        ),
        "occurrence_payload_sha256": occurrence_payload_sha256,
        "private_authorization_sha256": private_digest,
    }
    inbound = authority["inbound_merge_ref"]
    if inbound is not None:
        authority["inbound_merge_ref"] = _require_ref(
            inbound, label="inbound_merge_ref"
        )
    scope = _scope_payload(authority)
    occurrence = _occurrence_payload(authority)
    scope_marker = _marker("scope", scope)
    occurrence_marker = _marker("occurrence", occurrence)
    issue_body = f"{scope_marker}\n{occurrence_marker}\n\n{body}"
    occurrence_comment = f"{occurrence_marker}\n\n{body}"
    rendered_scopes, rendered_occurrences = _parse_markers(
        issue_body, source="rendered issue body"
    )
    comment_scopes, comment_occurrences = _parse_markers(
        occurrence_comment, source="rendered occurrence comment"
    )
    if (
        rendered_scopes != (scope,)
        or rendered_occurrences != (occurrence,)
        or comment_scopes
        or comment_occurrences != (occurrence,)
    ):
        raise CapacityValidationError(
            "publication renderer did not produce exact marker authority"
        )
    issue_body_sha256 = hashlib.sha256(issue_body.encode("utf-8")).hexdigest()
    occurrence_comment_sha256 = hashlib.sha256(
        occurrence_comment.encode("utf-8")
    ).hexdigest()
    authority["issue_body_sha256"] = issue_body_sha256
    authority["occurrence_comment_sha256"] = occurrence_comment_sha256
    _validate_schema(
        authority,
        repo_root=repo_root,
        name="finding-publication-authority.schema.json",
    )
    semantics = index.get("defect_semantics")
    if not isinstance(semantics, Mapping):
        raise CapacityValidationError(
            "finding-v2 index lacks immutable defect semantics for its title"
        )
    stable_signature = semantics.get("stable_signature")
    if (
        not isinstance(stable_signature, str)
        or not stable_signature.strip()
        or stable_signature != stable_signature.strip()
        or _has_nonprinting_unicode(stable_signature)
    ):
        raise CapacityValidationError(
            "publication stable signature must be non-empty single-line text"
        )
    _reject_auto_closing_text(stable_signature, label="publication title source")
    title_prefix = f"[{fingerprint}] "
    available = 240 - len(title_prefix)
    if len(stable_signature) > available:
        stable_signature = stable_signature[: available - 3].rstrip() + "..."
    title = title_prefix + stable_signature
    if redactor.redact(title) != title:
        raise CapacityValidationError(
            "publication title contains data denied by publication redaction"
        )
    preview = {
        "schema_version": 1,
        "preview_only": True,
        "authority": authority,
        "scope_sha256": _scope_sha256(scope),
        "title": title,
        "issue_body": issue_body,
        "issue_body_sha256": issue_body_sha256,
        "occurrence_comment": occurrence_comment,
        "occurrence_comment_sha256": occurrence_comment_sha256,
    }
    _validate_schema(
        preview,
        repo_root=repo_root,
        name="finding-publication-preview.schema.json",
    )
    content = canonical_json_bytes(preview)
    return RenderedPublicationPreview(
        canonical_sha256=hashlib.sha256(content).hexdigest(),
        _canonical_bytes=content,
        _render_token=_RENDERED_PREVIEW_TOKEN,
    )


def load_issue_publication_preview(
    run_dir: Path,
    finding_id: str,
    *,
    private_authorization_sha256: str,
    repo_root: Path,
) -> ValidatedPublicationPreview:
    """Load one owner-only durable finding-v2 occurrence and freeze its preview."""
    canonical_repo_root = _canonical_checkout_root(repo_root, label="SCM policy")
    with capacity_findings.capacity_finding_run_selection(run_dir) as selection:
        if not selection.is_capacity_v2 or selection.authority is None:
            raise CapacityValidationError(
                "guarded publication requires a finding-v2 run"
            )
        sources = capacity_findings.read_capacity_finding_canonical_jsonl(
            run_dir / capacity_findings.CAPACITY_FINDING_SOURCE_NAME,
            root=run_dir,
            authority=selection.authority,
        )
        indexes = capacity_findings.read_capacity_finding_canonical_jsonl(
            run_dir / capacity_findings.CAPACITY_FINDING_INDEX_NAME,
            root=run_dir,
            authority=selection.authority,
        )
        source_by_id = _records_by_finding_id(sources, label="finding source ledger")
        index_by_id = _records_by_finding_id(indexes, label="finding index ledger")
        if set(source_by_id) != set(index_by_id):
            raise CapacityValidationError("finding-v2 source/index ledgers disagree")
        if finding_id not in source_by_id:
            raise CapacityValidationError(f"unknown finding_id: {finding_id}")
        capacity_findings.validate_capacity_finding_artifact_inventory(
            index_by_id,
            evidence_root=run_dir,
            authority=selection.authority,
        )
        manifest = capacity_findings.read_capacity_finding_manifest(
            run_dir / capacity_findings.CAPACITY_FINDING_MANIFEST_NAME,
            root=run_dir,
            authority=selection.authority,
        )
        capacity_findings.validate_capacity_finding_manifest(manifest, indexes)
        verified = capacity_findings.load_capacity_finding_index_artifacts(
            run_dir
            / capacity_findings.CAPACITY_FINDING_SOURCE_DIRECTORY
            / f"{finding_id}.json",
            run_dir
            / capacity_findings.CAPACITY_FINDING_INDEX_DIRECTORY
            / f"{finding_id}.json",
            run_dir
            / capacity_findings.CAPACITY_FINDING_BODY_DIRECTORY
            / f"{finding_id}.md",
            repo_root=canonical_repo_root,
            evidence_root=run_dir,
            authority=selection.authority,
        )
        if verified != index_by_id[finding_id]:
            raise CapacityValidationError(
                "finding-v2 index ledger differs from immutable artifact"
            )
        if canonical_sha256(source_by_id[finding_id]) != verified["finding_sha256"]:
            raise CapacityValidationError(
                "finding-v2 source ledger digest differs from index"
            )
        selection.authority.revalidate()
    rendered = build_issue_publication_preview(
        verified,
        private_authorization_sha256=private_authorization_sha256,
        repo_root=canonical_repo_root,
    )
    return _mint_validated_publication_preview(
        rendered,
        replay_token=_OWNER_REPLAY_TOKEN,
    )


def _records_by_finding_id(
    records: Sequence[Mapping[str, Any]], *, label: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        finding_id = record.get("finding_id")
        if not isinstance(finding_id, str) or not finding_id or finding_id in result:
            raise CapacityValidationError(
                f"{label} has missing or duplicate finding_id"
            )
        result[finding_id] = dict(record)
    if not result:
        raise CapacityValidationError(f"{label} is empty")
    return result


def validate_publication_observation(
    value: Mapping[str, Any], *, repo_root: Path
) -> ValidatedPublicationObservation:
    observation = dict(value)
    _validate_schema(
        observation,
        repo_root=repo_root,
        name="finding-publication-observation.schema.json",
    )
    repository = str(observation["destination_repository"])
    query = observation["issue_query"]
    assert isinstance(query, Mapping)
    if query["repository"] != repository:
        raise CapacityValidationError(
            "issue observation query does not name the canonical destination"
        )
    _validate_paginated_objects(
        observation["issue_pages"],
        observation["issues"],
        label="issue search",
    )
    issues = observation["issues"]
    rereads = observation["direct_rereads"]
    assert isinstance(issues, list) and isinstance(rereads, list)
    issue_by_id: dict[str, dict[str, Any]] = {}
    issue_numbers: set[int] = set()
    all_object_ids: set[str] = set()
    for raw_issue in issues:
        assert isinstance(raw_issue, dict)
        _validate_issue_snapshot(raw_issue, repository=repository)
        node_id = str(raw_issue["node_id"])
        number = int(raw_issue["number"])
        if node_id in issue_by_id or node_id in all_object_ids:
            raise CapacityValidationError("issue observation repeats an object ID")
        if number in issue_numbers:
            raise CapacityValidationError("issue observation repeats an issue number")
        issue_numbers.add(number)
        all_object_ids.add(node_id)
        for comment in raw_issue["comments"]:
            comment_id = str(comment["node_id"])
            if comment_id in all_object_ids:
                raise CapacityValidationError(
                    "issue observation repeats a comment object ID"
                )
            all_object_ids.add(comment_id)
        issue_by_id[node_id] = raw_issue
    reread_by_id: dict[str, dict[str, Any]] = {}
    for raw_issue in rereads:
        assert isinstance(raw_issue, dict)
        _validate_issue_snapshot(raw_issue, repository=repository)
        node_id = str(raw_issue["node_id"])
        if node_id in reread_by_id:
            raise CapacityValidationError("direct rereads repeat an object ID")
        reread_by_id[node_id] = raw_issue
    if set(issue_by_id) != set(reread_by_id):
        raise CapacityValidationError(
            "every observed issue must have exactly one direct reread"
        )
    for node_id, issue in issue_by_id.items():
        if issue != reread_by_id[node_id]:
            raise CapacityValidationError(
                f"direct issue reread drifted for object {node_id}"
            )
    content = canonical_json_bytes(observation)
    return ValidatedPublicationObservation(
        canonical_sha256=hashlib.sha256(content).hexdigest(),
        _canonical_bytes=content,
        _validation_token=_PUBLICATION_TOKEN,
    )


def load_publication_observation(
    path: Path, *, repo_root: Path
) -> ValidatedPublicationObservation:
    return validate_publication_observation(
        _strict_json_object(path, label="GitHub observation"),
        repo_root=repo_root,
    )


def _validate_paginated_objects(
    page_set: Mapping[str, Any],
    objects: Sequence[Mapping[str, Any]],
    *,
    label: str,
) -> None:
    if page_set.get("complete") is not True:
        raise CapacityValidationError(f"{label} is incomplete")
    pages = page_set.get("pages")
    if not isinstance(pages, list) or not pages:
        raise CapacityValidationError(f"{label} must contain a terminal page")
    flattened: list[str] = []
    seen_request_cursors: set[str] = set()
    expected_cursor: str | None = None
    for index, raw_page in enumerate(pages):
        if not isinstance(raw_page, Mapping):
            raise CapacityValidationError(f"{label} page {index} is not an object")
        request_cursor = raw_page.get("request_cursor")
        end_cursor = raw_page.get("end_cursor")
        has_next = raw_page.get("has_next_page")
        if isinstance(request_cursor, str):
            if request_cursor in seen_request_cursors:
                raise CapacityValidationError(f"{label} repeats a request cursor")
        if request_cursor != expected_cursor:
            raise CapacityValidationError(f"{label} cursor chain is not contiguous")
        if isinstance(request_cursor, str):
            seen_request_cursors.add(request_cursor)
        if has_next is True:
            if (
                index == len(pages) - 1
                or not isinstance(end_cursor, str)
                or not end_cursor
            ):
                raise CapacityValidationError(
                    f"{label} has a non-terminal final cursor"
                )
            if end_cursor in seen_request_cursors:
                raise CapacityValidationError(f"{label} repeats a cursor")
            expected_cursor = end_cursor
        elif has_next is False:
            if index != len(pages) - 1:
                raise CapacityValidationError(
                    f"{label} terminates before its final page"
                )
            expected_cursor = None
        else:
            raise CapacityValidationError(f"{label} page lacks boolean has_next_page")
        node_ids = raw_page.get("node_ids")
        if not isinstance(node_ids, list) or any(
            not isinstance(item, str) or _NODE_ID_RE.fullmatch(item) is None
            for item in node_ids
        ):
            raise CapacityValidationError(f"{label} page has invalid object IDs")
        flattened.extend(node_ids)
    if len(flattened) != len(set(flattened)):
        raise CapacityValidationError(f"{label} repeats an object ID")
    actual_ids = [str(item.get("node_id")) for item in objects]
    if flattened != actual_ids:
        raise CapacityValidationError(f"{label} pages do not exactly enumerate objects")
    if page_set.get("total_count") != len(objects):
        raise CapacityValidationError(f"{label} total_count is not exact")


def _validate_issue_snapshot(issue: Mapping[str, Any], *, repository: str) -> None:
    body = issue.get("body")
    if not isinstance(body, str) or hashlib.sha256(
        body.encode("utf-8")
    ).hexdigest() != issue.get("body_sha256"):
        raise CapacityValidationError("issue body digest does not match exact bytes")
    _validate_github_issue_url(
        issue.get("url"), repository=repository, number=issue.get("number")
    )
    comments = issue.get("comments")
    comment_pages = issue.get("comment_pages")
    if not isinstance(comments, list) or not isinstance(comment_pages, Mapping):
        raise CapacityValidationError("issue comments are not a complete observation")
    _validate_paginated_objects(
        comment_pages, comments, label=f"comments for issue {issue.get('number')}"
    )
    for comment in comments:
        assert isinstance(comment, Mapping)
        comment_body = comment.get("body")
        if not isinstance(comment_body, str) or hashlib.sha256(
            comment_body.encode("utf-8")
        ).hexdigest() != comment.get("body_sha256"):
            raise CapacityValidationError(
                "issue comment digest does not match exact bytes"
            )
        _validate_github_comment_url(
            comment.get("url"),
            repository=repository,
            issue_number=issue.get("number"),
        )


def _validate_github_issue_url(
    value: object, *, repository: str, number: object
) -> None:
    if not isinstance(value, str) or not isinstance(number, int):
        raise CapacityValidationError("issue observation has invalid URL authority")
    if value != f"https://github.com/{repository}/issues/{number}":
        raise CapacityValidationError("issue URL does not match canonical destination")


def _validate_github_comment_url(
    value: object,
    *,
    repository: str,
    issue_number: object,
) -> None:
    if not isinstance(value, str) or not isinstance(issue_number, int):
        raise CapacityValidationError("comment observation has invalid URL authority")
    parsed = urlparse(value)
    expected_path = f"/{repository}/issues/{issue_number}"
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.path != expected_path
        or not parsed.fragment.startswith("issuecomment-")
    ):
        raise CapacityValidationError(
            "comment URL does not match canonical destination"
        )


def _observe_git_publication_authority_from_packet(
    packet: Mapping[str, Any],
    destination_repo_root: Path,
    *,
    repo_root: Path,
    git_runner: GitRunner = subprocess.run,
    remote_git_runner: GitRunner | None = None,
) -> ValidatedGitPublicationAuthority:
    """Perform only exact read-only Git checks required by dry/live planning."""
    authority = packet["authority"]
    assert isinstance(authority, dict)
    _validate_preview_rendered_authority(packet)
    root = _canonical_checkout_root(destination_repo_root, label="destination")
    contract_root = _canonical_checkout_root(repo_root, label="SCM policy")

    def run(
        arguments: Sequence[str],
        *,
        allowed: frozenset[int] = frozenset({0}),
        cwd: Path = root,
        remote_only: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        environment = _sealed_git_environment()
        if remote_only:
            # `ls-remote` needs no repository. Pointing GIT_DIR at the null
            # device prevents destination-local config from affecting the
            # explicitly named canonical remote after that config was audited.
            environment["GIT_DIR"] = os.devnull
        try:
            # Private infrastructure may inject a credentialed read-only
            # runner for canonical private remotes. No credential material
            # crosses this interface into the returned observation.
            selected_runner = remote_git_runner if remote_only else git_runner
            if selected_runner is None:  # pragma: no cover - default invariant
                selected_runner = git_runner
            completed = selected_runner(
                ["git", *arguments],
                check=False,
                text=True,
                cwd=cwd,
                capture_output=True,
                env=environment,
            )
        except (OSError, UnicodeError) as exc:
            raise CapacityValidationError(
                f"cannot execute hermetic Git authority read: {exc}"
            ) from exc
        if completed.returncode not in allowed:
            raise CapacityValidationError(
                f"Git authority check failed: git {' '.join(arguments)}"
            )
        return completed

    def inspect_checkout(
        checkout: Path,
        *,
        label: str,
        expected_repository: str,
        require_clean: bool,
    ) -> str:
        top = run(["rev-parse", "--show-toplevel"], cwd=checkout).stdout.strip()
        if not top or Path(top).expanduser().resolve() != checkout:
            raise CapacityValidationError(f"{label} checkout is not the exact Git root")
        grafts_raw = run(
            ["rev-parse", "--git-path", "info/grafts"], cwd=checkout
        ).stdout.strip()
        if not grafts_raw:
            raise CapacityValidationError(f"{label} Git graft path is missing")
        grafts_path = Path(grafts_raw)
        if not grafts_path.is_absolute():
            grafts_path = checkout / grafts_path
        try:
            grafts_stat = grafts_path.lstat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise CapacityValidationError(
                f"cannot inspect {label} Git graft authority: {exc}"
            ) from exc
        else:
            del grafts_stat
            raise CapacityValidationError(
                f"{label} Git graft authority is not permitted"
            )
        replace_refs = run(
            ["for-each-ref", "--format=%(refname)", "refs/replace"],
            cwd=checkout,
        ).stdout.splitlines()
        if replace_refs:
            raise CapacityValidationError(
                f"{label} Git replace refs are not permitted"
            )
        rewrite_config = run(
            [
                "config",
                "--null",
                "--name-only",
                "--get-regexp",
                r"^url\..*\.(insteadof|pushinsteadof)$",
            ],
            cwd=checkout,
            allowed=frozenset({0, 1}),
        )
        if rewrite_config.returncode == 0 or rewrite_config.stdout:
            raise CapacityValidationError(
                f"{label} Git URL rewrite config is not permitted"
            )
        remote_url = run(
            ["remote", "get-url", "origin"], cwd=checkout
        ).stdout.strip()
        remote = _canonical_github_repository(remote_url)
        if remote != expected_repository:
            raise CapacityValidationError(
                f"{label} Git remote does not match publication authority"
            )
        if require_clean:
            index_entries = run(
                ["ls-files", "-v", "-z"], cwd=checkout
            ).stdout.split("\0")
            for entry in index_entries:
                if not entry:
                    continue
                if len(entry) < 3 or entry[1] != " " or entry[0] != "H":
                    raise CapacityValidationError(
                        "publication rejects hidden or nonordinary Git index flags"
                    )
            status = run(
                [
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                    "--ignore-submodules=none",
                ],
                cwd=checkout,
            ).stdout
            if status.strip():
                raise CapacityValidationError(
                    "publication requires an exact clean checkout"
                )
        ignored = run(
            ["ls-files", "--others", "--ignored", "--exclude-standard", "-z"],
            cwd=checkout,
        ).stdout.split("\0")
        _reject_ignored_publication_authority(checkout, ignored, label=label)
        return f"https://github.com/{expected_repository}.git"

    remote_url = inspect_checkout(
        root,
        label="destination",
        expected_repository=str(authority["destination_repository"]),
        require_clean=True,
    )
    if contract_root != root:
        inspect_checkout(
            contract_root,
            label="SCM policy",
            expected_repository="arkhai-io/simple-compute-market",
            require_clean=True,
        )
    checked_branch = run(["branch", "--show-current"]).stdout.strip()
    checked_ref = run(["rev-parse", "HEAD"]).stdout.strip()
    if (
        checked_branch != authority["working_branch"]
        or checked_ref != authority["working_ref"]
    ):
        raise CapacityValidationError(
            "checked-out working branch/ref differs from finding authority"
        )
    if checked_branch in {
        authority["upstream_branch"],
        authority["default_branch"],
    }:
        raise CapacityValidationError(
            "publication from a default/upstream branch is forbidden"
        )
    if contract_root == root:
        scm_policy_branch = checked_branch
        scm_policy_ref = checked_ref
    else:
        scm_policy_branch = run(
            ["branch", "--show-current"], cwd=contract_root
        ).stdout.strip()
        scm_policy_ref = run(
            ["rev-parse", "HEAD"], cwd=contract_root
        ).stdout.strip()
    expected_policy_branch = _DESTINATION_POLICIES["simple-compute-market"][
        "working_branch"
    ]
    if scm_policy_branch != expected_policy_branch:
        raise CapacityValidationError(
            "SCM policy checkout is not on the canonical harness branch"
        )
    _require_ref(scm_policy_ref, label="SCM policy checkout HEAD")
    remote_working = _one_ls_remote_ref(
        run(
            [
                "ls-remote",
                "--exit-code",
                remote_url,
                f"refs/heads/{authority['working_branch']}",
            ],
            remote_only=True,
        ).stdout,
        expected_name=f"refs/heads/{authority['working_branch']}",
    )
    remote_upstream = _one_ls_remote_ref(
        run(
            [
                "ls-remote",
                "--exit-code",
                remote_url,
                f"refs/heads/{authority['upstream_branch']}",
            ],
            remote_only=True,
        ).stdout,
        expected_name=f"refs/heads/{authority['upstream_branch']}",
    )
    remote_default_branch, remote_default_ref = _one_ls_remote_head(
        run(
            ["ls-remote", "--symref", remote_url, "HEAD"],
            remote_only=True,
        ).stdout
    )
    if remote_default_branch != authority["default_branch"]:
        raise CapacityValidationError(
            "current remote default branch differs from publication policy"
        )
    if (
        remote_default_branch == authority["upstream_branch"]
        and remote_default_ref != remote_upstream
    ):
        raise CapacityValidationError(
            "remote default/upstream observations changed during authority read"
        )
    if remote_working != authority["working_ref"]:
        raise CapacityValidationError("current remote working ref drifted")
    ancestry = run(
        [
            "merge-base",
            "--is-ancestor",
            str(authority["upstream_ref"]),
            str(authority["working_ref"]),
        ],
        allowed=frozenset({0, 1}),
    )
    if ancestry.returncode != 0:
        raise CapacityValidationError(
            "working ref does not contain pinned upstream ref"
        )
    contract_descends = run(
        [
            "merge-base",
            "--is-ancestor",
            str(authority["finding_v2_contract_ref"]),
            str(authority["scm_contract_ref"]),
        ],
        allowed=frozenset({0, 1}),
        cwd=contract_root,
    )
    if contract_descends.returncode != 0:
        raise CapacityValidationError(
            "finding SCM contract ref does not contain consumed finding-v2 contract"
        )
    policy_contains_contract = run(
        [
            "merge-base",
            "--is-ancestor",
            str(authority["scm_contract_ref"]),
            scm_policy_ref,
        ],
        allowed=frozenset({0, 1}),
        cwd=contract_root,
    )
    if policy_contains_contract.returncode != 0:
        raise CapacityValidationError(
            "SCM policy checkout HEAD does not contain the finding contract ref"
        )
    working_contains_contract: bool | None = None
    if authority["destination_repo"] == "simple-compute-market":
        contract_contained = run(
            [
                "merge-base",
                "--is-ancestor",
                str(authority["scm_contract_ref"]),
                str(authority["working_ref"]),
            ],
            allowed=frozenset({0, 1}),
        )
        working_contains_contract = contract_contained.returncode == 0
        if not working_contains_contract:
            raise CapacityValidationError(
                "SCM working ref does not contain the finding contract ref"
            )
    inbound = authority.get("inbound_merge_ref")
    inbound_contained: bool | None = None
    if inbound is not None:
        contained = run(
            [
                "merge-base",
                "--is-ancestor",
                str(inbound),
                str(authority["working_ref"]),
            ],
            allowed=frozenset({0, 1}),
        )
        inbound_contained = contained.returncode == 0
        if not inbound_contained:
            raise CapacityValidationError(
                "working ref does not contain reconciliation merge ref"
            )
    observation = {
        "schema_version": 1,
        "publication_preview_sha256": canonical_sha256(packet),
        "destination_repository": authority["destination_repository"],
        "checked_out_branch": checked_branch,
        "checked_out_ref": checked_ref,
        "remote_working_branch": authority["working_branch"],
        "remote_working_ref": remote_working,
        "remote_upstream_branch": authority["upstream_branch"],
        "remote_upstream_ref": remote_upstream,
        "pinned_upstream_ref": authority["upstream_ref"],
        "remote_upstream_drifted": remote_upstream != authority["upstream_ref"],
        "remote_default_branch": remote_default_branch,
        "remote_default_ref": remote_default_ref,
        "clean": True,
        "working_contains_pinned_upstream": True,
        "pinned_inbound_merge_ref": inbound,
        "working_contains_inbound_merge": inbound_contained,
        "finding_v2_contract_ref": authority["finding_v2_contract_ref"],
        "scm_contract_ref": authority["scm_contract_ref"],
        "scm_contract_contains_finding_v2_contract": True,
        "scm_policy_repository": "arkhai-io/simple-compute-market",
        "scm_policy_checkout_branch": scm_policy_branch,
        "scm_policy_checkout_ref": scm_policy_ref,
        "scm_policy_checkout_clean": True,
        "scm_policy_checkout_contains_contract": True,
        "working_contains_scm_contract": working_contains_contract,
        "working_contains_finding_v2_contract": working_contains_contract,
    }
    _validate_schema(
        observation,
        repo_root=repo_root,
        name="finding-publication-git-observation.schema.json",
    )
    content = canonical_json_bytes(observation)
    return ValidatedGitPublicationAuthority(
        canonical_sha256=hashlib.sha256(content).hexdigest(),
        _canonical_bytes=content,
        _validation_token=_PUBLICATION_TOKEN,
    )


def observe_git_publication_authority(
    preview: ValidatedPublicationPreview,
    destination_repo_root: Path,
    *,
    repo_root: Path,
    git_runner: GitRunner = subprocess.run,
    remote_git_runner: GitRunner | None = None,
) -> ValidatedGitPublicationAuthority:
    """Observe Git only for an owner-replayed finding publication preview."""
    packet = _require_validated(
        preview, ValidatedPublicationPreview, label="publication preview"
    )
    return _observe_git_publication_authority_from_packet(
        packet,
        destination_repo_root,
        repo_root=repo_root,
        git_runner=git_runner,
        remote_git_runner=remote_git_runner,
    )


def _observe_rendered_git_publication_authority(
    preview: RenderedPublicationPreview,
    destination_repo_root: Path,
    *,
    repo_root: Path,
    git_runner: GitRunner,
    remote_git_runner: GitRunner | None = None,
) -> ValidatedGitPublicationAuthority:
    """Exercise read-only guards for a non-capability offline rendering."""
    packet = _require_rendered_preview(preview)
    return _observe_git_publication_authority_from_packet(
        packet,
        destination_repo_root,
        repo_root=repo_root,
        git_runner=git_runner,
        remote_git_runner=remote_git_runner,
    )


def _canonical_github_repository(remote: str) -> str | None:
    value = remote.strip()
    if value.startswith("git@github.com:"):
        path = value.removeprefix("git@github.com:")
    else:
        parsed = urlparse(value)
        try:
            port = parsed.port
        except ValueError:
            return None
        if (
            parsed.scheme != "https"
            or parsed.hostname != "github.com"
            or port is not None
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            return None
        path = parsed.path.lstrip("/")
    path = path.removesuffix(".git").rstrip("/")
    parts = path.split("/")
    if len(parts) != 2 or any(not part for part in parts):
        return None
    return f"{parts[0]}/{parts[1]}"


def _one_ls_remote_ref(output: str, *, expected_name: str) -> str:
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) != 1:
        raise CapacityValidationError(
            f"remote ref observation is not unique: {expected_name}"
        )
    fields = lines[0].split("\t")
    if len(fields) != 2 or fields[1] != expected_name:
        raise CapacityValidationError(
            f"remote ref observation is malformed: {expected_name}"
        )
    return _require_ref(fields[0], label=f"remote {expected_name}")


def _one_ls_remote_head(output: str) -> tuple[str, str]:
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) != 2:
        raise CapacityValidationError(
            "remote default HEAD observation is not one symbolic ref and commit"
        )
    symbolic = lines[0].split("\t")
    direct = lines[1].split("\t")
    prefix = "ref: refs/heads/"
    if (
        len(symbolic) != 2
        or symbolic[1] != "HEAD"
        or not symbolic[0].startswith(prefix)
        or len(direct) != 2
        or direct[1] != "HEAD"
    ):
        raise CapacityValidationError("remote default HEAD observation is malformed")
    branch = symbolic[0].removeprefix(prefix)
    if not branch or branch.startswith("/") or branch.endswith("/") or ".." in branch:
        raise CapacityValidationError("remote default branch name is malformed")
    return branch, _require_ref(direct[0], label="remote default HEAD")


def _select_issue_publication_action_from_packet(
    packet: Mapping[str, Any],
    observed: Mapping[str, Any],
    git: Mapping[str, Any],
    *,
    observation_sha256: str,
    git_observation_sha256: str,
    repo_root: Path,
) -> dict[str, Any]:
    """Purely select one issue action from frozen authority and complete reads."""
    authority = packet["authority"]
    assert isinstance(authority, Mapping)
    _validate_preview_rendered_authority(packet)
    expected_inbound_containment = (
        True if authority["inbound_merge_ref"] is not None else None
    )
    if observed["destination_repository"] != authority["destination_repository"]:
        raise CapacityValidationError(
            "GitHub observation destination differs from finding authority"
        )
    if (
        git["publication_preview_sha256"] != canonical_sha256(packet)
        or git["destination_repository"] != authority["destination_repository"]
        or git["checked_out_branch"] != authority["working_branch"]
        or git["checked_out_ref"] != authority["working_ref"]
        or git["remote_working_branch"] != authority["working_branch"]
        or git["remote_working_ref"] != authority["working_ref"]
        or git["remote_upstream_branch"] != authority["upstream_branch"]
        or git["pinned_upstream_ref"] != authority["upstream_ref"]
        or git["remote_upstream_drifted"]
        is not (git["remote_upstream_ref"] != git["pinned_upstream_ref"])
        or git["remote_default_branch"] != authority["default_branch"]
        or (
            authority["default_branch"] == authority["upstream_branch"]
            and git["remote_default_ref"] != git["remote_upstream_ref"]
        )
        or git["finding_v2_contract_ref"] != authority["finding_v2_contract_ref"]
        or git["scm_contract_ref"] != authority["scm_contract_ref"]
        or git["scm_contract_contains_finding_v2_contract"] is not True
        or git["scm_policy_repository"] != "arkhai-io/simple-compute-market"
        or git["scm_policy_checkout_branch"]
        != _DESTINATION_POLICIES["simple-compute-market"]["working_branch"]
        or git["scm_policy_checkout_clean"] is not True
        or git["scm_policy_checkout_contains_contract"] is not True
        or git["clean"] is not True
        or git["working_contains_pinned_upstream"] is not True
        or git["pinned_inbound_merge_ref"] != authority["inbound_merge_ref"]
        or git["working_contains_inbound_merge"]
        is not expected_inbound_containment
    ):
        raise CapacityValidationError(
            "Git authority does not satisfy frozen publication packet"
        )
    scope = _scope_payload(authority)
    occurrence = _occurrence_payload(authority)
    parsed = tuple(_parse_issue(item) for item in observed["issues"])
    matching = [item for item in parsed if item.scope == scope]
    if len(matching) > 1:
        raise CapacityValidationError(
            "complete observation contains ambiguous scoped issues"
        )
    for issue in parsed:
        for existing in issue.occurrences:
            if existing["finding_id"] != occurrence["finding_id"]:
                continue
            if existing != occurrence:
                raise CapacityValidationError(
                    "finding_id is reused with changed occurrence digests"
                )
            if issue.scope != scope:
                raise CapacityValidationError(
                    "finding_id is reused in a different publication scope"
                )
    selected_issue = matching[0] if matching else None
    if selected_issue is None:
        action_kind = "create"
        issue_number: int | None = None
        issue_url: str | None = None
        rendered_body = str(packet["issue_body"])
        rendered_body_sha256 = str(packet["issue_body_sha256"])
        rendered_body_source = "issue_body"
        steps = ["create_issue"]
    else:
        issue_number = int(selected_issue.issue["number"])
        issue_url = str(selected_issue.issue["url"])
        rendered_body = str(packet["occurrence_comment"])
        rendered_body_sha256 = str(packet["occurrence_comment_sha256"])
        rendered_body_source = "occurrence_comment"
        if occurrence in selected_issue.occurrences:
            action_kind = "no_op"
            steps = []
            if (
                selected_issue.occurrence_sources[occurrence["finding_id"]]
                == "issue_body"
            ):
                rendered_body = str(packet["issue_body"])
                rendered_body_sha256 = str(packet["issue_body_sha256"])
                rendered_body_source = "issue_body"
        elif selected_issue.issue["state"] == "OPEN":
            action_kind = "comment"
            steps = ["comment_occurrence"]
        else:
            action_kind = "comment_then_reopen"
            steps = ["comment_occurrence", "reopen_issue"]
    expected_rendered_sha256 = (
        authority["issue_body_sha256"]
        if rendered_body_source == "issue_body"
        else authority["occurrence_comment_sha256"]
    )
    if rendered_body_sha256 != expected_rendered_sha256:
        raise CapacityValidationError(
            "selected publication bytes differ from frozen authority"
        )
    action_core = {
        "schema_version": 1,
        "action_kind": action_kind,
        "authority": authority,
        "scope_sha256": packet["scope_sha256"],
        "observation_sha256": observation_sha256,
        "git_observation_sha256": git_observation_sha256,
        "issue_number": issue_number,
        "issue_url": issue_url,
        "title": packet["title"],
        "rendered_body": rendered_body,
        "rendered_body_sha256": rendered_body_sha256,
        "rendered_body_source": rendered_body_source,
        "mutation_steps": steps,
    }
    action_id = (
        "issue-action-"
        + hashlib.sha256(
            b"scm.finding-publication.issue-action.v1\0"
            + canonical_json_bytes(action_core)
        ).hexdigest()
    )
    action = {"action_id": action_id, **action_core}
    _validate_schema(
        action,
        repo_root=repo_root,
        name="finding-publication-action.schema.json",
    )
    return action


def select_issue_publication_action(
    preview: ValidatedPublicationPreview,
    observation: ValidatedPublicationObservation,
    git_authority: ValidatedGitPublicationAuthority,
    *,
    repo_root: Path,
) -> ValidatedIssuePublicationAction:
    """Select a capability action only from owner-replayed finding authority."""
    packet = _require_validated(
        preview, ValidatedPublicationPreview, label="publication preview"
    )
    observed = _require_validated(
        observation, ValidatedPublicationObservation, label="publication observation"
    )
    git = _require_validated(
        git_authority,
        ValidatedGitPublicationAuthority,
        label="Git publication authority",
    )
    action = _select_issue_publication_action_from_packet(
        packet,
        observed,
        git,
        observation_sha256=observation.canonical_sha256,
        git_observation_sha256=git_authority.canonical_sha256,
        repo_root=repo_root,
    )
    content = canonical_json_bytes(action)
    return ValidatedIssuePublicationAction(
        canonical_sha256=hashlib.sha256(content).hexdigest(),
        _canonical_bytes=content,
        _validation_token=_PUBLICATION_TOKEN,
    )


def _select_rendered_issue_publication_action(
    preview: RenderedPublicationPreview,
    observation: ValidatedPublicationObservation,
    git_authority: ValidatedGitPublicationAuthority,
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Exercise the pure selector without minting a publication capability."""
    packet = _require_rendered_preview(preview)
    observed = _require_validated(
        observation, ValidatedPublicationObservation, label="publication observation"
    )
    git = _require_validated(
        git_authority,
        ValidatedGitPublicationAuthority,
        label="Git publication authority",
    )
    return _select_issue_publication_action_from_packet(
        packet,
        observed,
        git,
        observation_sha256=observation.canonical_sha256,
        git_observation_sha256=git_authority.canonical_sha256,
        repo_root=repo_root,
    )


def _parse_issue(issue: Mapping[str, Any]) -> _ParsedIssue:
    body_scope, body_occurrences = _parse_markers(
        str(issue["body"]), source="issue body"
    )
    scopes = list(body_scope)
    occurrences: list[dict[str, str]] = []
    occurrence_sources: dict[str, str] = {}
    if len(scopes) > 1:
        raise CapacityValidationError(
            "issue body contains duplicate/conflicting scope markers"
        )
    if scopes:
        if len(body_occurrences) != 1:
            raise CapacityValidationError(
                "scoped issue body must contain exactly one initial occurrence"
            )
        scope = scopes[0]
        initial = body_occurrences[0]
        prefix = f"{_marker('scope', scope)}\n{_marker('occurrence', initial)}\n\n"
        raw_body = str(issue["body"])
        if not raw_body.startswith(prefix):
            raise CapacityValidationError(
                "scoped issue markers are not in the canonical body placement"
            )
        _validate_observed_occurrence_payload(raw_body[len(prefix) :], initial)
        occurrences.append(initial)
        occurrence_sources[initial["finding_id"]] = "issue_body"
    elif body_occurrences:
        raise CapacityValidationError("occurrence marker has no issue scope authority")
    for comment in issue["comments"]:
        assert isinstance(comment, Mapping)
        comment_scopes, comment_occurrences = _parse_markers(
            str(comment["body"]), source="issue comment"
        )
        if comment_scopes:
            raise CapacityValidationError(
                "scope markers are forbidden in occurrence comments"
            )
        if len(comment_occurrences) > 1:
            raise CapacityValidationError(
                "one comment contains multiple occurrence markers"
            )
        if comment_occurrences:
            if not scopes:
                raise CapacityValidationError(
                    "occurrence comment has no canonical issue scope authority"
                )
            occurrence = comment_occurrences[0]
            prefix = f"{_marker('occurrence', occurrence)}\n\n"
            raw_comment = str(comment["body"])
            if not raw_comment.startswith(prefix):
                raise CapacityValidationError(
                    "occurrence marker is not in canonical comment placement"
                )
            _validate_observed_occurrence_payload(
                raw_comment[len(prefix) :], occurrence
            )
            occurrences.append(occurrence)
            occurrence_sources[occurrence["finding_id"]] = "occurrence_comment"
    seen: dict[str, dict[str, str]] = {}
    for occurrence in occurrences:
        prior = seen.get(occurrence["finding_id"])
        if prior is not None:
            if prior != occurrence:
                raise CapacityValidationError(
                    "one issue contains conflicting occurrence identity"
                )
            raise CapacityValidationError("one issue repeats an occurrence marker")
        seen[occurrence["finding_id"]] = occurrence
    return _ParsedIssue(
        issue=dict(issue),
        scope=scopes[0] if scopes else None,
        occurrences=tuple(occurrences),
        occurrence_sources=occurrence_sources,
    )


def _validate_observed_occurrence_payload(
    human_payload: str,
    occurrence: Mapping[str, str],
) -> None:
    normalized = _normalize_occurrence_payload(human_payload)
    actual = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    if actual != occurrence["occurrence_payload_sha256"]:
        raise CapacityValidationError(
            "observed occurrence payload does not match its marker digest"
        )


def _parse_markers(
    text: str, *, source: str
) -> tuple[tuple[dict[str, str], ...], tuple[dict[str, str], ...]]:
    scopes: list[dict[str, str]] = []
    occurrences: list[dict[str, str]] = []
    for line in text.splitlines():
        if _MARKER_PREFIX not in line:
            continue
        match = _MARKER_RE.fullmatch(line)
        if match is None:
            raise CapacityValidationError(
                f"malformed finding-publication marker in {source}"
            )
        kind, encoded = match.groups()
        try:
            payload = _strict_marker_json(encoded)
        except ValueError as exc:
            raise CapacityValidationError(
                f"invalid {kind} marker in {source}: {exc}"
            ) from exc
        canonical = canonical_json_bytes(payload).decode("utf-8").removesuffix("\n")
        if canonical != encoded:
            raise CapacityValidationError(f"non-canonical {kind} marker in {source}")
        if kind == "scope":
            if set(payload) != _SCOPE_KEYS:
                raise CapacityValidationError("scope marker fields are not closed")
            if (
                not isinstance(payload.get("fingerprint"), str)
                or _FINGERPRINT_RE.fullmatch(str(payload["fingerprint"])) is None
            ):
                raise CapacityValidationError("scope marker fingerprint is invalid")
            _require_digest(
                payload.get("scenario_sha256"), label="scope scenario_sha256"
            )
            scopes.append({str(key): str(value) for key, value in payload.items()})
        else:
            if set(payload) != _OCCURRENCE_KEYS:
                raise CapacityValidationError("occurrence marker fields are not closed")
            _require_digest(
                payload.get("finding_sha256"), label="marker finding_sha256"
            )
            _require_digest(
                payload.get("occurrence_payload_sha256"),
                label="marker occurrence_payload_sha256",
            )
            occurrences.append({str(key): str(value) for key, value in payload.items()})
        for key, value in payload.items():
            if (
                not isinstance(value, str)
                or not value
                or any(token in value for token in ("--", "<", ">"))
            ):
                raise CapacityValidationError(f"unsafe {kind} marker value for {key}")
    return tuple(scopes), tuple(occurrences)


def _strict_marker_json(value: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate key {key!r}")
            result[key] = item
        return result

    parsed = json.loads(value, object_pairs_hook=reject_duplicates)
    if not isinstance(parsed, dict):
        raise ValueError("marker payload is not an object")
    return parsed


def publication_preview_json(
    preview: RenderedPublicationPreview | ValidatedPublicationPreview,
) -> str:
    if isinstance(preview, RenderedPublicationPreview):
        value = _require_rendered_preview(preview)
    else:
        value = _require_validated(
            preview, ValidatedPublicationPreview, label="publication preview"
        )
    return canonical_json_bytes(value).decode("utf-8")


def publication_action_json(action: ValidatedIssuePublicationAction) -> str:
    return canonical_json_bytes(
        _require_validated(
            action, ValidatedIssuePublicationAction, label="issue action"
        )
    ).decode("utf-8")
