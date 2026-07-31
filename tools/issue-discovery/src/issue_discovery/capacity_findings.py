from __future__ import annotations

from contextlib import contextmanager
import ctypes
from dataclasses import dataclass, field
from datetime import UTC, datetime
import errno
import fcntl
import hashlib
import html
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from typing import Any, Iterable, Iterator, Mapping, Sequence
import unicodedata

from jsonschema import Draft202012Validator, FormatChecker
import yaml
from yaml.tokens import (
    AliasToken,
    AnchorToken,
    KeyToken,
    ScalarToken,
    TagToken,
    ValueToken,
)

from issue_discovery.capacity import (
    CapacityValidationError,
    canonical_json_bytes,
    canonical_sha256,
)
from issue_discovery.capacity_outcomes import (
    ValidatedCapacityResult,
    require_validated_capacity_result,
)


CAPACITY_FINDING_SCHEMA_PATH = PurePosixPath(
    "tools/issue-discovery/schemas/capacity-finding.schema.json"
)
CAPACITY_REDACTION_CONFIG_PATH = PurePosixPath(
    "tools/issue-discovery/config/redactions.yaml"
)
CAPACITY_FINDING_FINGERPRINT_DOMAIN = b"scm.capacity.finding-fingerprint.v1\0"
CAPACITY_FINDING_SOURCE_NAME = "capacity-findings.jsonl"
CAPACITY_FINDING_INDEX_NAME = "capacity-finding-index.jsonl"
CAPACITY_FINDING_MANIFEST_NAME = "manifest.json"
CAPACITY_FINDING_LIFECYCLE_NAME = "issue-lifecycle.jsonl"
CAPACITY_FINDING_INGEST_LOCK_NAME = ".capacity-finding-ingest.lock"
CAPACITY_FINDING_SOURCE_DIRECTORY = "capacity-findings"
CAPACITY_FINDING_INDEX_DIRECTORY = "capacity-finding-index"
CAPACITY_FINDING_BODY_DIRECTORY = "capacity-finding-bodies"
CAPACITY_FINDING_PUBLICATION_CAPABILITY = "guard-issue-fix-publication"

_RENAME_EXCHANGE = 2

REQUEST_FAILURE_CATEGORIES = frozenset(
    {
        "generic-failure",
        "provisioning-error",
        "policy-denial",
        "unknown-reason",
        "uncompensated",
        "atomic-refusal-incomplete",
        "timeout",
        "missing-durable-correlation",
        "cleanup-incomplete",
        "generator-failure",
    }
)
ACTUAL_FAULT_CATEGORIES = REQUEST_FAILURE_CATEGORIES | {
    "double-allocation",
    "unexpected-outcome",
}
LIFECYCLE_PHASES = frozenset(
    {
        "pre-emission",
        "negotiation",
        "escrow",
        "reservation",
        "settlement",
        "provisioning",
        "guest-verification",
        "teardown",
        "cleanup",
        "load-generation",
    }
)

_FINDING_VALIDATION_TOKEN = object()
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_REF_RE = re.compile(r"^[0-9a-f]{40}$")
_FAILURE_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,79}$")
_REPOSITORY_REMOTE_RE = re.compile(
    r"^(?:https://github\.com/|git@github\.com:)"
    r"(?P<slug>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)
_MAX_EVIDENCE_BYTES = 1024 * 1024
_MAX_TOTAL_EVIDENCE_BYTES = 4 * 1024 * 1024
_MAX_SEMANTIC_DECODE_DEPTH = 8
_MAX_SEMANTIC_PROJECTIONS = 16_384
_MAX_SEMANTIC_PROJECTION_BYTES = 32 * 1024 * 1024
_UNRESOLVED_SENTINEL_RE = re.compile(
    r"(?is)(?:\$\{[^}]*\}|\{\{[^}]*\}\}|<placeholder[^>]*>|"
    r"\b(?:todo|tbd|fixme|xxx|changeme|change_me|replaceme|replace_me|"
    r"your_[a-z0-9_]+|example[-_](?:id|sha|hash|ref|value))\b)"
)
_DISALLOWED_ASCII_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DEFAULT_IGNORABLE_CODE_POINT_RE = re.compile(
    "["
    "\u00ad\u034f\u061c"
    "\u115f-\u1160\u17b4-\u17b5\u180b-\u180f"
    "\u200b-\u200f\u202a-\u202e\u2060-\u206f"
    "\u3164\ufe00-\ufe0f\ufeff\uffa0\ufff0-\ufff8"
    "\U0001bca0-\U0001bca3\U0001d173-\U0001d17a"
    "\U000e0000-\U000e0fff"
    "]"
)

_DESTINATION_POLICIES: dict[str, dict[str, object]] = {
    "simple-compute-market": {
        "repository": "arkhai-io/simple-compute-market",
        "classifications": frozenset({"public-product", "public-harness"}),
        "working_branch": "feat/issue-discovery-harness",
        "upstream_branch": "dev",
    },
    "compute-market-internal-infra": {
        "repository": "arkhai-io/compute-market-internal-infra",
        "classifications": frozenset({"private-orchestration", "environment-provider"}),
        "working_branch": "tools/agent-orchestration-scratch",
        "upstream_branch": "main",
    },
}

_FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "account_address",
        "account_id",
        "admin_key",
        "api_key",
        "authorization",
        "bearer_token",
        "cloud_project_id",
        "credential",
        "credentials",
        "gcp_project",
        "gcp_project_id",
        "gpu_id",
        "gpu_uuid",
        "host_id",
        "hostname",
        "instance_id",
        "mac_address",
        "mnemonic",
        "password",
        "pci_bdf",
        "private_endpoint",
        "private_key",
        "project_id",
        "secret",
        "seed_phrase",
        "ssh_private_key",
        "token",
        "wallet",
        "wallet_address",
    }
)
_SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "authorization credential",
        re.compile(
            r"(?i)\bauthorization\s*[:=]\s*[\"']?bearer\s+"
            r"[A-Za-z0-9._~+/=-]+"
        ),
    ),
    (
        "assigned secret",
        re.compile(
            r"(?i)\b(?:admin[_-]?key|api[_-]?key|password|private[_-]?key|"
            r"secret|token)\b[\"']?\s*[:=]\s*[\"']?[^\s,\"'}]+"
        ),
    ),
    (
        "OAuth authorization code",
        re.compile(r"\b4/0A[A-Za-z0-9_-]{20,}\b"),
    ),
    (
        "wallet or account address",
        re.compile(r"\b0x[0-9a-fA-F]{40}\b"),
    ),
    (
        "service-account identity",
        re.compile(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+"
            r"\.iam\.gserviceaccount\.com\b"
        ),
    ),
    (
        "cloud project identity",
        re.compile(
            r"(?i)\b(?:cloud[_ -]?project|gcp[_ -]?project|project[_ -]?id)"
            r"\b[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9][A-Za-z0-9:._-]+"
        ),
    ),
    (
        "host identity",
        re.compile(
            r"(?i)\b(?:host[_ -]?id|hostname|instance[_ -]?id)"
            r"\b[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9][A-Za-z0-9:._-]+"
        ),
    ),
    (
        "GPU identity",
        re.compile(r"(?i)\bGPU-[0-9a-f-]{16,}\b"),
    ),
    (
        "PCI device identity",
        re.compile(r"(?i)\b[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]\b"),
    ),
    (
        "MAC address",
        re.compile(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b"),
    ),
    (
        "private IPv4 endpoint",
        re.compile(
            r"(?<![0-9.])(?:10(?:\.\d{1,3}){3}|"
            r"192\.168(?:\.\d{1,3}){2}|"
            r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|"
            r"127(?:\.\d{1,3}){3}|169\.254(?:\.\d{1,3}){2})(?![0-9.])"
        ),
    ),
    (
        "localhost identity",
        re.compile(
            r"(?i)(?<![A-Za-z0-9.-])localhost(?:\.localdomain)?"
            r"(?![A-Za-z0-9.-])"
        ),
    ),
    (
        "private filesystem identity",
        re.compile(r"(?:^|[\s\"'])/(?:home|Users)/[^/\s\"']+"),
    ),
    (
        "private endpoint",
        re.compile(
            r"(?i)\b(?:https?|ssh)://(?:localhost|"
            r"(?:10|127|192\.168|169\.254)\.[^\s/:]+|"
            r"172\.(?:1[6-9]|2\d|3[01])\.[^\s/:]+)"
        ),
    ),
)
_SENSITIVE_PATTERN_TRIGGERS: dict[str, tuple[str, ...]] = {
    "authorization credential": ("authorization",),
    "assigned secret": (
        "admin",
        "api",
        "password",
        "private",
        "secret",
        "token",
    ),
    "OAuth authorization code": ("4/0a",),
    "wallet or account address": ("0x",),
    "service-account identity": ("@",),
    "cloud project identity": ("project",),
    "host identity": ("host", "instance"),
    "GPU identity": ("gpu-",),
    "PCI device identity": (":",),
    "MAC address": (":",),
    "private IPv4 endpoint": (".",),
    "localhost identity": ("localhost",),
    "private filesystem identity": ("/home/", "/users/"),
    "private endpoint": ("://",),
}
_CONFIGURED_REDACTION_TRIGGER_AUTHORITY: dict[
    str,
    tuple[str, tuple[str, ...]],
] = {
    "private_key_hex": (
        "e3e28bb86859b4b5798f80bc9eed55f28e00fa7c27ad718358f046a3a03c1f9c",
        ("private",),
    ),
    "admin_key": (
        "a2802ac2d1ea5477ba0bb59eff33407c5d5ecabbb8966a72ce4ac78c13a00d52",
        ("admin",),
    ),
    "bearer_token": (
        "da3efc8747c711b28cfbb498c1642816ecd5fa4de4802a5f78d9ecf73baa7f5a",
        ("authorization",),
    ),
    "generic_secret_assignment": (
        "3b8eca8982434bf3a6956325c2468ae716d468544ab195ada2f1e5f0b423390c",
        (
            "api",
            "access",
            "refresh",
            "password",
            "passphrase",
            "client",
            "credential",
            "private",
            "ssh",
            "seed",
            "mnemonic",
        ),
    ),
    "private_key_pem": (
        "cd6964feea1a526ff4a876f05f052b16af04d3de7b89e2c74e9c3d26af44eed1",
        ("private key",),
    ),
    "wallet_account_identity": (
        "a87f4cb24299d40238639e5d1dc7695107a1a495465130a35b418586333744f1",
        ("0x",),
    ),
    "email_account_identity": (
        "4b189c94ff82e69694a8cc629f07f7678c5d542366fb661f4cfc6c573e81c6e0",
        ("@",),
    ),
    "gcp_project_identity": (
        "e37da9e1c7830a1c0899681e73b5ff5fe1ab6d54cfc9c53f4fb3333e0193b1d7",
        ("project",),
    ),
    "gcp_project_resource": (
        "2d78ea6b01fe7cf14b2ec84b5fc489537f0ef5e9ac994d8f3461ee76443b4a3f",
        ("projects/",),
    ),
    "host_identity": (
        "35f761157ed59bcb7623f2c78338b70f4de0d830945b82ad88954b44f63855e0",
        ("host", "machine"),
    ),
    "gpu_uuid": (
        "30e29c4c8441c6d3b4c7a4c88372f036ce08d4903cc8264e240f3eaca2e1b2ff",
        ("gpu-",),
    ),
    "pci_bdf": (
        "4432f421a204f8e938a9621beb7ab0401052782e6ffda16dc9eefe5ab4136832",
        (":",),
    ),
    "private_ipv4": (
        "5dfc60486509ea3da3e096b258050dd6606f8ade4c3c11ac32945821d07eca5b",
        (".",),
    ),
    "private_ipv6": (
        "0eaed7572fad1954893bd476c255edfd067657fcebf62f207259ecba0b2ab97f",
        (":",),
    ),
    "localhost_identity": (
        "45f976be4b30a2b547b751be72524c0b2e6ee96c0d9b33bfe804bcd2acd2b323",
        ("localhost",),
    ),
    "home_path": (
        "289b6a24ca622429719cf8f59950a4ac90c02abbfea2053e41b0e8ad220a91c1",
        ("/home/",),
    ),
    "macos_home_path": (
        "747e40389449e74b89fc664dfb6dcf7d484f5ed4fed7e378324188cb5200857d",
        ("/users/",),
    ),
}
_UNRESOLVED_SENTINEL_TRIGGERS = (
    "${",
    "{{",
    "<placeholder",
    "todo",
    "tbd",
    "fixme",
    "xxx",
    "changeme",
    "change_me",
    "replaceme",
    "replace_me",
    "your_",
    "example-id",
    "example_id",
    "example-sha",
    "example_sha",
    "example-hash",
    "example_hash",
    "example-ref",
    "example_ref",
    "example-value",
    "example_value",
)
_IPV6_TOKEN_RE = re.compile(
    r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{0,4}:){2,}"
    r"[0-9A-Fa-f]{0,4}(?![0-9A-Fa-f:])"
)
_PRIVATE_IPV6_NETWORKS = (
    ipaddress.IPv6Network("::1/128"),
    ipaddress.IPv6Network("fe80::/10"),
    ipaddress.IPv6Network("fc00::/7"),
)
_QUOTED_FIELD_ASSIGNMENT_RE = re.compile(
    r"""(?x)["'](?P<key>[A-Za-z][A-Za-z0-9 ._-]{0,79})["']\s*:"""
)
_LINE_FIELD_ASSIGNMENT_RE = re.compile(
    r"""(?x)(?:\A|[\n\r\u0085\u2028\u2029])[ \t]*(?:\ufeff)?(?:-[ \t]+)?
    (?:(?:&[A-Za-z0-9_-]+|
    !(?:![A-Za-z0-9_-]+|<[^>\r\n\u0085\u2028\u2029]+>|[A-Za-z0-9_-]+)?)
    [ \t]+)*
    (?P<key>[^\[\]\{\},=\r\n\u0085\u2028\u2029]+?)[ \t]*
    (?::(?=[ \t\r\n\u0085\u2028\u2029]|$)|=)"""
)
_FLOW_FIELD_ASSIGNMENT_RE = re.compile(
    r"""(?x)(?:\{|\[|,)\s*\??\s*
    (?:(?:&[A-Za-z0-9_-]+|
    !(?:![A-Za-z0-9_-]+|<[^>\r\n\u0085\u2028\u2029]+>|[A-Za-z0-9_-]+)?)
    [ \t]+)*
    (?P<key>[^\[\]\{\},=\r\n\u0085\u2028\u2029]+?)[ \t]*
    (?::(?=[ \t\r\n\u0085\u2028\u2029,\}\]"']|$)|[=,}])"""
)
_QUOTED_SCALAR_RE = re.compile(
    r"""(?P<quoted>
    "(?:\\(?:(?:\r\n|[\r\n\u0085\u2028\u2029])[ \t]*|
    [^\r\n\u0085\u2028\u2029])|[^"\\\r\n\u0085\u2028\u2029])*"
    |
    '(?:''|[^'\r\n])*'
    )""",
    re.VERBOSE,
)
_QUOTED_SCALAR_DELIMITER_RE = re.compile(r"\s*[:},]")
_QUOTED_SCALAR_COLON_RE = re.compile(r"\s*:")
_YAML_EXPLICIT_KEY_RE = re.compile(
    r"(?:\A|[\r\n\u0085\u2028\u2029]|\{|\[|,)[ \t]*\?[ \t\r\n\u0085\u2028\u2029]"
)
_YAML_PROPERTY_KEY_RE = re.compile(r"(?m)(?:^\s*(?:-\s*)?[!&]|[\{\[,]\s*[!&])")
_YAML_FRAGMENT_MAPPING_RE = re.compile(r":(?:[ \t]+|(?=[\r\n\u0085\u2028\u2029]|$))")
_YAML_FRAGMENT_PROPERTY_RE = re.compile(
    r"(?:\A|[ \t\{\[,])(?:[!&][^\s\{\}\[\],:]+|\*[A-Za-z0-9_-]+)"
)
_MARKDOWN_BACKSLASH_ESCAPE_RE = re.compile(
    r"""\\([!"#$%&'()*+,\-./:;<=>?@\[\]^_`{|}~])"""
)


@dataclass(frozen=True, slots=True)
class ValidatedCapacityFinding:
    """An immutable finding occurrence bound to a validated VM capacity result."""

    finding_id: str
    fingerprint: str
    canonical_sha256: str
    destination_repo: str
    destination_repository: str
    classification: str
    frontier: str
    scenario_id: str
    scenario_sha256: str
    profile_stage_id: str
    profile_stage_sha256: str
    result_id: str
    result_sha256: str
    scm_contract_ref: str
    ready_to_file: bool
    evidence_root: Path
    _canonical_bytes: bytes = field(repr=False)
    _evidence: tuple[tuple[str, str], ...] = field(repr=False)
    _redaction_rules: tuple[tuple[str, re.Pattern[str], str], ...] = field(
        repr=False,
        compare=False,
    )
    _validation_token: object = field(repr=False, compare=False)

    @property
    def finding(self) -> dict[str, Any]:
        value = json.loads(self._canonical_bytes.decode("utf-8"))
        if not isinstance(value, dict):
            raise CapacityValidationError(
                "validated capacity-finding snapshot is not an object"
            )
        return value


@dataclass(frozen=True, slots=True)
class IngestedCapacityFinding:
    """One validated source occurrence and its durable derived index record."""

    finding: ValidatedCapacityFinding
    source_path: Path
    index_path: Path
    index_record: dict[str, Any]
    appended_source: bool
    appended_index: bool


def _run_git(repo_root: Path, *arguments: str) -> bytes:
    git_environment = {
        "PATH": os.environ.get("PATH", os.defpath),
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
    }
    for name in ("LANG", "LC_ALL", "LC_CTYPE", "TMPDIR"):
        value = os.environ.get(name)
        if value is not None:
            git_environment[name] = value
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            check=False,
            capture_output=True,
            env=git_environment,
        )
    except OSError as error:
        raise CapacityValidationError(f"cannot execute Git: {error}") from error
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise CapacityValidationError(
            f"Git {' '.join(arguments)} failed" + (f": {detail}" if detail else "")
        )
    return completed.stdout


def _validate_git_root(repo_root: Path, *, expected_repository: str) -> Path:
    candidate = repo_root.expanduser()
    try:
        candidate_stat = candidate.stat()
    except OSError as error:
        raise CapacityValidationError(
            f"authority repository root is unavailable: {error}"
        ) from error
    if not stat.S_ISDIR(candidate_stat.st_mode) or candidate.is_symlink():
        raise CapacityValidationError(
            "authority repository root must be a non-symlink directory"
        )
    top_level = Path(
        _run_git(candidate, "rev-parse", "--show-toplevel")
        .decode("utf-8", errors="strict")
        .strip()
    )
    try:
        same_root = os.path.samefile(candidate, top_level)
    except OSError as error:
        raise CapacityValidationError(
            f"cannot verify authority repository root: {error}"
        ) from error
    if not same_root:
        raise CapacityValidationError(
            "authority repository root must be the exact Git worktree root"
        )
    raw_common_directory = (
        _run_git(candidate, "rev-parse", "--git-common-dir")
        .decode("utf-8", errors="strict")
        .strip()
    )
    common_directory = Path(raw_common_directory)
    if not common_directory.is_absolute():
        common_directory = candidate / common_directory
    try:
        common_directory = common_directory.resolve(strict=True)
    except OSError as error:
        raise CapacityValidationError(
            f"cannot verify Git common directory: {error}"
        ) from error
    grafts_path = common_directory / "info" / "grafts"
    if _path_present(grafts_path):
        try:
            grafts_stat = grafts_path.lstat()
        except OSError as error:
            raise CapacityValidationError(
                f"cannot inspect Git graft authority: {error}"
            ) from error
        if (
            stat.S_ISLNK(grafts_stat.st_mode)
            or not stat.S_ISREG(grafts_stat.st_mode)
            or grafts_stat.st_size != 0
        ):
            raise CapacityValidationError(
                "Git graft authority is not permitted for capacity findings"
            )
    replace_refs = (
        _run_git(candidate, "for-each-ref", "--format=%(refname)", "refs/replace")
        .decode("utf-8", errors="strict")
        .splitlines()
    )
    if replace_refs:
        raise CapacityValidationError(
            "Git replace refs are not permitted for capacity findings"
        )
    remote = (
        _run_git(candidate, "remote", "get-url", "origin")
        .decode("utf-8", errors="strict")
        .strip()
    )
    match = _REPOSITORY_REMOTE_RE.fullmatch(remote)
    if match is None or match.group("slug").lower() != expected_repository.lower():
        raise CapacityValidationError(
            "authority repository origin does not match destination repository "
            f"{expected_repository}"
        )
    return top_level


def _validate_commit(repo_root: Path, value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not _REF_RE.fullmatch(value):
        raise CapacityValidationError(
            f"{field_name} must be an exact lowercase 40-character commit"
        )
    _raw_commit_parents(repo_root, value, field_name=field_name)
    return value


def _raw_commit_parents(
    repo_root: Path,
    commit: str,
    *,
    field_name: str,
) -> tuple[str, ...]:
    try:
        raw_commit = _run_git(repo_root, "cat-file", "commit", commit)
    except CapacityValidationError as error:
        raise CapacityValidationError(
            f"{field_name} must identify a Git commit"
        ) from error
    header, separator, _ = raw_commit.partition(b"\n\n")
    if not separator:
        raise CapacityValidationError(f"{field_name} has a malformed raw commit object")
    tree_headers: list[bytes] = []
    parent_headers: list[bytes] = []
    for line in header.splitlines():
        if line.startswith(b"tree "):
            tree_headers.append(line[5:])
        elif line.startswith(b"parent "):
            parent_headers.append(line[7:])
    if len(tree_headers) != 1:
        raise CapacityValidationError(
            f"{field_name} raw commit must contain exactly one tree"
        )
    try:
        tree = tree_headers[0].decode("ascii", errors="strict")
        parents = tuple(
            parent.decode("ascii", errors="strict") for parent in parent_headers
        )
    except UnicodeDecodeError as error:
        raise CapacityValidationError(
            f"{field_name} contains non-ASCII object identity"
        ) from error
    if not _REF_RE.fullmatch(tree) or any(
        not _REF_RE.fullmatch(parent) for parent in parents
    ):
        raise CapacityValidationError(
            f"{field_name} contains a malformed raw object identity"
        )
    return parents


def _load_pinned_finding_schema(
    scm_repo_root: Path,
    scm_contract_ref: str,
) -> dict[str, Any]:
    content = _run_git(
        scm_repo_root,
        "show",
        f"{scm_contract_ref}:{CAPACITY_FINDING_SCHEMA_PATH.as_posix()}",
    )
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CapacityValidationError(
            f"pinned capacity-finding schema is invalid: {error}"
        ) from error
    if not isinstance(value, dict):
        raise CapacityValidationError(
            "pinned capacity-finding schema must be a JSON object"
        )
    return value


def _redaction_rules_from_bytes(
    content: bytes,
    *,
    source: str,
) -> tuple[tuple[str, re.Pattern[str], str], ...]:
    try:
        value = yaml.safe_load(content.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise CapacityValidationError(
            f"configured redaction policy is invalid at {source}: {error}"
        ) from error
    if not isinstance(value, Mapping) or value.get("schema_version") != 1:
        raise CapacityValidationError(
            f"configured redaction policy at {source} must use schema_version 1"
        )
    raw_patterns = value.get("patterns")
    if not isinstance(raw_patterns, list):
        raise CapacityValidationError(
            f"configured redaction policy at {source} must contain patterns"
        )
    rules: list[tuple[str, re.Pattern[str], str]] = []
    for index, item in enumerate(raw_patterns):
        if not isinstance(item, Mapping) or set(item) != {
            "id",
            "regex",
            "replacement",
        }:
            raise CapacityValidationError(
                f"configured redaction rule {index} at {source} is not closed"
            )
        rule_id = item.get("id")
        expression = item.get("regex")
        replacement = item.get("replacement")
        if not all(
            isinstance(part, str) for part in (rule_id, expression, replacement)
        ):
            raise CapacityValidationError(
                f"configured redaction rule {index} at {source} is invalid"
            )
        try:
            pattern = re.compile(expression)
        except re.error as error:
            raise CapacityValidationError(
                f"configured redaction rule {rule_id} is invalid: {error}"
            ) from error
        rules.append((rule_id, pattern, replacement))
    return tuple(rules)


def _load_pinned_redaction_rules(
    scm_repo_root: Path,
    scm_contract_ref: str,
) -> tuple[tuple[str, re.Pattern[str], str], ...]:
    content = _run_git(
        scm_repo_root,
        "show",
        f"{scm_contract_ref}:{CAPACITY_REDACTION_CONFIG_PATH.as_posix()}",
    )
    return _redaction_rules_from_bytes(
        content,
        source=f"{scm_contract_ref}:{CAPACITY_REDACTION_CONFIG_PATH}",
    )


def _schema_errors(
    value: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> list[str]:
    validator = Draft202012Validator(
        dict(schema),
        format_checker=FormatChecker(),
    )
    errors: list[str] = []
    for error in sorted(
        validator.iter_errors(dict(value)),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    ):
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        errors.append(f"{location}: {error.message}")
    return errors


def _raise_errors(label: str, errors: Iterable[str]) -> None:
    unique = list(dict.fromkeys(errors))
    if unique:
        raise CapacityValidationError(
            f"{label} validation failed:\n- " + "\n- ".join(unique)
        )


def _normalize_stable_signature(value: object) -> str:
    if not isinstance(value, str):
        raise CapacityValidationError(
            "defect_semantics.stable_signature must be a string"
        )
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def capacity_finding_fingerprint_input(
    finding: Mapping[str, Any],
) -> dict[str, str]:
    """Return the closed normalized defect identity, excluding occurrence data."""
    semantics = finding.get("defect_semantics")
    if not isinstance(semantics, Mapping):
        raise CapacityValidationError(
            "defect_semantics must be an object before deriving a fingerprint"
        )
    failure_code = semantics.get("failure_code")
    if not isinstance(failure_code, str) or not _FAILURE_CODE_RE.fullmatch(
        failure_code
    ):
        raise CapacityValidationError(
            "defect_semantics.failure_code must be a normalized lowercase code"
        )
    actual_fault_category = semantics.get("actual_fault_category")
    if actual_fault_category not in ACTUAL_FAULT_CATEGORIES:
        raise CapacityValidationError(
            "defect_semantics.actual_fault_category is not a supported fault"
        )
    lifecycle_phase = semantics.get("lifecycle_phase")
    if lifecycle_phase not in LIFECYCLE_PHASES:
        raise CapacityValidationError(
            "defect_semantics.lifecycle_phase is not a supported lifecycle phase"
        )
    expected_outcome_kind = semantics.get("expected_outcome_kind")
    if expected_outcome_kind not in {
        "vm-succeeded",
        "capacity-refused",
    }:
        raise CapacityValidationError(
            "defect_semantics.expected_outcome_kind is invalid"
        )
    stable_signature = semantics.get("stable_signature")
    normalized_signature = _normalize_stable_signature(stable_signature)
    if stable_signature != normalized_signature:
        raise CapacityValidationError(
            "defect_semantics.stable_signature must already be NFKC-normalized, "
            "case-folded, trimmed, and whitespace-collapsed"
        )

    names = (
        "destination_repo",
        "classification",
        "scenario_id",
        "scenario_sha256",
        "frontier",
    )
    identity: dict[str, str] = {}
    for name in names:
        item = finding.get(name)
        if not isinstance(item, str):
            raise CapacityValidationError(
                f"{name} must be a string before deriving a fingerprint"
            )
        identity[name] = item
    identity.update(
        {
            "failure_code": failure_code,
            "stable_signature": normalized_signature,
            "expected_outcome_kind": expected_outcome_kind,
            "actual_fault_category": actual_fault_category,
            "lifecycle_phase": lifecycle_phase,
        }
    )
    return identity


def derive_capacity_finding_fingerprint(finding: Mapping[str, Any]) -> str:
    """Derive SCM's stable defect fingerprint from normalized semantics only."""
    identity = capacity_finding_fingerprint_input(finding)
    digest = hashlib.sha256(
        CAPACITY_FINDING_FINGERPRINT_DOMAIN + canonical_json_bytes(identity)
    ).hexdigest()
    return f"capacity-{digest}"


def _walk_json(value: Any) -> Iterable[tuple[str | None, Any]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key), item
            yield from _walk_json(item)
    elif isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        for item in value:
            yield None, item
            yield from _walk_json(item)


def _normalized_private_field_name(value: str) -> str:
    compatible = unicodedata.normalize("NFKC", value)
    separated = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", compatible)
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", separated)
    return re.sub(r"[^A-Za-z0-9]+", "_", separated).strip("_").casefold()


def _sensitive_findings(value: Any, *, source: str) -> list[str]:
    errors: list[str] = []
    for key, item in _walk_json(value):
        if key is not None:
            errors.extend(
                _sensitive_scalar_text_findings(
                    key,
                    source=source,
                    semantic_observations=((True, key),),
                )
            )
        if not isinstance(item, str):
            continue
        errors.extend(_sensitive_scalar_text_findings(item, source=source))
    return errors


def _private_ipv6_findings(text: str, *, source: str) -> list[str]:
    errors: list[str] = []
    if ":" not in text:
        return errors
    for match in _IPV6_TOKEN_RE.finditer(text):
        token = match.group(0)
        try:
            address = ipaddress.ip_address(token)
        except ValueError:
            continue
        if not isinstance(address, ipaddress.IPv6Address):
            continue
        if any(address in network for network in _PRIVATE_IPV6_NETWORKS):
            errors.append(f"{source} contains private IPv6 endpoint")
    return errors


def _raw_sensitive_field_findings(text: str, *, source: str) -> list[str]:
    errors: list[str] = []
    if not any(delimiter in text for delimiter in (":", "=", "{", "[", ",")):
        return errors
    raw_keys: set[str] = set()
    for pattern in (
        _QUOTED_FIELD_ASSIGNMENT_RE,
        _LINE_FIELD_ASSIGNMENT_RE,
        _FLOW_FIELD_ASSIGNMENT_RE,
    ):
        for match in pattern.finditer(text):
            raw_keys.add(match.group("key"))
    for key in raw_keys:
        if _normalized_private_field_name(key) in _FORBIDDEN_FIELD_NAMES:
            errors.append(f"{source} contains forbidden private field {key!r}")
    return errors


def _scan_yaml_scalars(
    text: str,
) -> tuple[tuple[tuple[bool, str], ...], bool]:
    """Decode YAML scalars without constructing an object graph."""
    observations: list[tuple[bool, str]] = []
    anchors: dict[str, str] = {}
    pending_anchor: str | None = None
    expecting_key = False
    try:
        for token in yaml.scan(text, Loader=yaml.SafeLoader):
            if pending_anchor is not None:
                if isinstance(token, ScalarToken):
                    anchors[pending_anchor] = token.value
                    pending_anchor = None
                elif not isinstance(token, TagToken):
                    pending_anchor = None
            if isinstance(token, KeyToken):
                expecting_key = True
            elif isinstance(token, ValueToken):
                expecting_key = False
            elif isinstance(token, AnchorToken):
                pending_anchor = token.value
            elif isinstance(token, AliasToken):
                anchored = anchors.get(token.value)
                if anchored is not None:
                    observations.append((expecting_key, anchored))
            elif isinstance(token, ScalarToken):
                observations.append((expecting_key, token.value))
    except yaml.YAMLError:
        return tuple(observations), False
    return tuple(observations), True


def _yaml_scalar_observations(text: str) -> tuple[tuple[bool, str], ...]:
    """Decode YAML scalar spellings without constructing an object graph."""
    observations, _ = _scan_yaml_scalars(text)
    return observations


def _quoted_scalar_observations(text: str) -> tuple[tuple[bool, str], ...]:
    if "\\" not in text and "''" not in text:
        return ()
    observations: list[tuple[bool, str]] = []
    for match in _QUOTED_SCALAR_RE.finditer(text):
        quoted = match.group("quoted")
        if (
            quoted.startswith('"')
            and "\\" not in quoted
            or quoted.startswith("'")
            and "''" not in quoted
            and "\\" not in quoted
        ):
            continue
        try:
            if quoted.startswith('"'):
                try:
                    value = json.loads(quoted)
                except (json.JSONDecodeError, ValueError):
                    value = yaml.safe_load(quoted)
            else:
                value = quoted[1:-1].replace("''", "'")
        except yaml.YAMLError:
            continue
        if not isinstance(value, str):
            continue
        prefix_index = match.start() - 1
        while prefix_index >= 0 and text[prefix_index].isspace():
            prefix_index -= 1
        starts_mapping_entry = prefix_index >= 0 and text[prefix_index] in "{,?"
        followed_by_mapping_delimiter = (
            _QUOTED_SCALAR_DELIMITER_RE.match(text, match.end()) is not None
        )
        observations.append(
            (
                _QUOTED_SCALAR_COLON_RE.match(text, match.end()) is not None
                or (starts_mapping_entry and followed_by_mapping_delimiter),
                value,
            )
        )
    return tuple(observations)


def _yaml_fragment_scalar_observations(
    text: str,
) -> tuple[tuple[bool, str], ...]:
    """Recover YAML fragments embedded in otherwise unstructured evidence."""
    lines = text.splitlines(keepends=True)
    if not lines:
        return ()
    direct: list[bool] = []
    for line in lines:
        stripped = line.lstrip(" \t\ufeff")
        direct.append(
            stripped.startswith(("?", ":", "{", "[", "- ", "!", "&", "*"))
            or _YAML_FRAGMENT_MAPPING_RE.search(line) is not None
            or _YAML_FRAGMENT_PROPERTY_RE.search(line) is not None
        )
    included = direct[:]
    for index in range(1, len(lines)):
        if included[index - 1] and lines[index].startswith((" ", "\t")):
            included[index] = True

    observations: list[tuple[bool, str]] = []
    index = 0
    while index < len(lines):
        if not included[index]:
            index += 1
            continue
        end = index + 1
        while end < len(lines) and included[end]:
            end += 1
        scanned, _ = _scan_yaml_scalars("".join(lines[index:end]))
        observations.extend(scanned)
        index = end
    return tuple(observations)


def _semantic_scalar_observations(text: str) -> tuple[tuple[bool, str], ...]:
    observations: list[tuple[bool, str]] = []
    needs_yaml_scan = (
        ("&" in text and "*" in text)
        or "\\\n" in text
        or "\\\r\n" in text
        or text.startswith("\ufeff")
        or ("?" in text and _YAML_EXPLICIT_KEY_RE.search(text) is not None)
        or (
            ("!" in text or "&" in text)
            and _YAML_PROPERTY_KEY_RE.search(text) is not None
        )
    )
    if needs_yaml_scan:
        scanned, _ = _scan_yaml_scalars(text)
        observations.extend(scanned)
    observations.extend(_yaml_fragment_scalar_observations(text))
    if '"' in text or "'" in text:
        observations.extend(_quoted_scalar_observations(text))
    return tuple(dict.fromkeys(observations))


def _markdown_text_projection(text: str) -> str:
    """Project CommonMark-visible text for portable privacy checks."""
    projected = text
    for _ in range(8):
        decoded = _MARKDOWN_BACKSLASH_ESCAPE_RE.sub(
            r"\1",
            html.unescape(projected),
        )
        if decoded == projected:
            return projected
        projected = decoded
    decoded = _MARKDOWN_BACKSLASH_ESCAPE_RE.sub(
        r"\1",
        html.unescape(projected),
    )
    if decoded != projected:
        raise CapacityValidationError(
            "privacy text contains excessively nested CommonMark encodings"
        )
    return projected


def _text_projections(text: str) -> tuple[str, ...]:
    markdown_projection = (
        _markdown_text_projection(text) if "&" in text or "\\" in text else text
    )
    base_projections = tuple(dict.fromkeys((text, markdown_projection)))
    if all(projection.isascii() for projection in base_projections):
        return base_projections

    projections = list(base_projections)
    for projection in base_projections:
        compatible = unicodedata.normalize("NFKC", projection)
        projections.append(compatible)
        decomposed = unicodedata.normalize("NFKD", projection)
        projections.append(
            "".join(
                character
                for character in decomposed
                if not unicodedata.category(character).startswith("M")
            )
        )
        if any(unicodedata.category(character) == "Cf" for character in compatible):
            projections.append(
                "".join(
                    character
                    for character in compatible
                    if unicodedata.category(character) != "Cf"
                )
            )
    return tuple(dict.fromkeys(projections))


def _semantic_text_projection_closure(
    text: str,
    *,
    semantic_observations: Sequence[tuple[bool, str]] | None = None,
) -> tuple[tuple[bool, str], ...]:
    """Return every bounded visible/decoded spelling with key provenance.

    Representation decoding is deliberately a fixed-point traversal rather
    than a single pass. Otherwise a JSON string containing another escaped
    JSON/YAML scalar can hide a sensitive value one layer beyond the scanner.
    The closed work and depth budgets make adversarial nesting fail closed.
    """

    pending: list[
        tuple[
            bool,
            str,
            int,
            Sequence[tuple[bool, str]] | None,
        ]
    ] = [(False, text, 0, semantic_observations)]
    observed: list[tuple[bool, str]] = []
    seen: set[tuple[bool, str]] = set()
    projection_bytes = 0

    while pending:
        inherited_key, current, depth, supplied = pending.pop()
        for projection_index, projection in enumerate(_text_projections(current)):
            identity = (inherited_key, projection)
            if identity not in seen:
                seen.add(identity)
                observed.append(identity)
                try:
                    projection_bytes += len(projection.encode("utf-8"))
                except UnicodeEncodeError as error:
                    raise CapacityValidationError(
                        "privacy semantic decoding produced an invalid "
                        "Unicode surrogate"
                    ) from error
                if (
                    len(observed) > _MAX_SEMANTIC_PROJECTIONS
                    or projection_bytes > _MAX_SEMANTIC_PROJECTION_BYTES
                ):
                    raise CapacityValidationError(
                        "privacy semantic decoding exceeded its closed work budget"
                    )
            else:
                continue

            nested = (
                supplied
                if projection_index == 0 and supplied is not None
                else _semantic_scalar_observations(projection)
            )
            novel_nested = [
                (inherited_key or is_key, scalar)
                for is_key, scalar in nested
                if (inherited_key or is_key, scalar) not in seen
            ]
            if novel_nested and depth >= _MAX_SEMANTIC_DECODE_DEPTH:
                raise CapacityValidationError(
                    "privacy semantic decoding exceeded its closed depth budget"
                )
            for is_key, scalar in reversed(novel_nested):
                pending.append((is_key, scalar, depth + 1, None))

    return tuple(observed)


def _unicode_control_findings(text: str, *, source: str) -> list[str]:
    if text.isascii():
        if _DISALLOWED_ASCII_CONTROL_RE.search(text):
            return [f"{source} contains a disallowed Unicode control"]
        return []
    if _DEFAULT_IGNORABLE_CODE_POINT_RE.search(text):
        return [f"{source} contains a Unicode format/default-ignorable code point"]
    has_disallowed_control = False
    for character in text:
        category = unicodedata.category(character)
        if category == "Cf":
            return [f"{source} contains a Unicode format or bidi control"]
        if category == "Cc" and character not in {"\t", "\n", "\r"}:
            has_disallowed_control = True
    if has_disallowed_control:
        return [f"{source} contains a disallowed Unicode control"]
    return []


def _sensitive_scalar_text_findings(
    text: str,
    *,
    source: str,
    semantic_observations: Sequence[tuple[bool, str]] | None = None,
) -> list[str]:
    errors: list[str] = []
    for is_key, projection in _semantic_text_projection_closure(
        text,
        semantic_observations=semantic_observations,
    ):
        errors.extend(_unicode_control_findings(projection, source=source))
        lowered_projection = projection.casefold()
        for label, pattern in _SENSITIVE_PATTERNS:
            triggers = _SENSITIVE_PATTERN_TRIGGERS[label]
            if not any(trigger in lowered_projection for trigger in triggers):
                continue
            if pattern.search(projection):
                errors.append(f"{source} contains {label}")
        errors.extend(_raw_sensitive_field_findings(projection, source=source))
        errors.extend(_private_ipv6_findings(projection, source=source))
        if (
            is_key
            and _normalized_private_field_name(projection) in _FORBIDDEN_FIELD_NAMES
        ):
            errors.append(f"{source} contains forbidden private field {projection!r}")
    return errors


def _unresolved_sentinel_findings(value: Any, *, source: str) -> list[str]:
    errors: list[str] = []
    for key, item in _walk_json(value):
        if key is not None and _unresolved_scalar_text_findings(key):
            errors.append(f"{source} contains unresolved field sentinel {key!r}")
        if isinstance(item, str) and _unresolved_scalar_text_findings(item):
            errors.append(f"{source} contains an unresolved placeholder sentinel")
    return errors


def _sensitive_text_findings(
    content: bytes,
    *,
    source: str,
    semantic_observations: Sequence[tuple[bool, str]] | None = None,
) -> list[str]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return [f"{source} must be UTF-8 text suitable for public review"]
    errors = _sensitive_scalar_text_findings(
        text,
        source=source,
        semantic_observations=semantic_observations,
    )
    return errors


def _unresolved_scalar_text_findings(
    text: str,
    *,
    semantic_observations: Sequence[tuple[bool, str]] | None = None,
) -> bool:
    for _, projection in _semantic_text_projection_closure(
        text,
        semantic_observations=semantic_observations,
    ):
        lowered_projection = projection.casefold()
        if any(
            trigger in lowered_projection for trigger in _UNRESOLVED_SENTINEL_TRIGGERS
        ) and _UNRESOLVED_SENTINEL_RE.search(projection):
            return True
    return False


def _unresolved_text_findings(
    content: bytes,
    *,
    source: str,
    semantic_observations: Sequence[tuple[bool, str]] | None = None,
) -> list[str]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return [f"{source} must be UTF-8 text suitable for public review"]
    if _unresolved_scalar_text_findings(
        text,
        semantic_observations=semantic_observations,
    ):
        return [f"{source} contains an unresolved placeholder sentinel"]
    return []


def _configured_redaction_triggers(
    rule_id: str,
    pattern: re.Pattern[str],
) -> tuple[str, ...] | None:
    """Return a fast-path only for the exact reviewed regex expression."""
    authority = _CONFIGURED_REDACTION_TRIGGER_AUTHORITY.get(rule_id)
    if authority is None:
        return None
    expected_sha256, triggers = authority
    expression_sha256 = hashlib.sha256(pattern.pattern.encode("utf-8")).hexdigest()
    if expression_sha256 != expected_sha256:
        return None
    return triggers


def _configured_redaction_findings(
    content: bytes,
    *,
    source: str,
    rules: Sequence[tuple[str, re.Pattern[str], str]],
    semantic_observations: Sequence[tuple[bool, str]] | None = None,
) -> list[str]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return [f"{source} must be UTF-8 text suitable for public review"]
    errors: list[str] = []
    for _, projection in _semantic_text_projection_closure(
        text,
        semantic_observations=semantic_observations,
    ):
        lowered_projection = projection.casefold()
        for rule_id, pattern, replacement in rules:
            triggers = _configured_redaction_triggers(rule_id, pattern)
            projection_may_match = triggers is None or any(
                trigger in lowered_projection for trigger in triggers
            )
            if (
                projection_may_match
                and pattern.search(projection) is not None
                and pattern.sub(
                    replacement,
                    projection,
                )
                != projection
            ):
                errors.append(f"{source} matches configured redaction rule {rule_id!r}")
    return errors


def _configured_value_findings(
    value: Any,
    *,
    source: str,
    rules: Sequence[tuple[str, re.Pattern[str], str]],
) -> list[str]:
    errors: list[str] = []
    for key, item in _walk_json(value):
        if key is not None:
            errors.extend(
                _configured_redaction_findings(
                    key.encode("utf-8"),
                    source=source,
                    rules=rules,
                )
            )
        if isinstance(item, str):
            errors.extend(
                _configured_redaction_findings(
                    item.encode("utf-8"),
                    source=source,
                    rules=rules,
                )
            )
    return errors


def _normalized_evidence_path(
    raw_path: object,
    *,
    field_name: str,
) -> PurePosixPath:
    if (
        not isinstance(raw_path, str)
        or not raw_path
        or "\0" in raw_path
        or "\\" in raw_path
    ):
        raise CapacityValidationError(
            f"{field_name} must be a non-empty relative POSIX path"
        )
    path = PurePosixPath(raw_path)
    if (
        path.is_absolute()
        or path.as_posix() != raw_path
        or "." in path.parts
        or ".." in path.parts
    ):
        raise CapacityValidationError(
            f"{field_name} must be normalized and cannot escape evidence_root"
        )
    if len(path.parts) < 2 or path.parts[0] != "evidence":
        raise CapacityValidationError(
            f"{field_name} must be inside the immutable evidence/ namespace"
        )
    return path


def _validate_evidence_root(evidence_root: Path) -> Path:
    candidate = evidence_root.expanduser()
    try:
        candidate_stat = candidate.lstat()
    except OSError as error:
        raise CapacityValidationError(
            f"evidence_root is unavailable: {error}"
        ) from error
    if stat.S_ISLNK(candidate_stat.st_mode) or not stat.S_ISDIR(candidate_stat.st_mode):
        raise CapacityValidationError("evidence_root must be a non-symlink directory")
    try:
        return candidate.resolve(strict=True)
    except OSError as error:
        raise CapacityValidationError(
            f"cannot resolve evidence_root: {error}"
        ) from error


@dataclass(frozen=True, slots=True)
class _EvidenceFileSnapshot:
    root_identity: tuple[int, int]
    directory_identities: tuple[tuple[str, tuple[int, int]], ...]
    file_identity: tuple[int, int]
    stat_fingerprint: tuple[int, int, int, int, int, int]
    content: bytes


def _read_evidence_file_snapshot(
    evidence_root: Path,
    relative_path: PurePosixPath,
) -> _EvidenceFileSnapshot:
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise CapacityValidationError(
            "secure descriptor-relative evidence traversal is unavailable"
        )
    try:
        root_pathname_before = evidence_root.lstat()
    except OSError as error:
        raise CapacityValidationError(
            f"evidence_root changed before evidence read: {error}"
        ) from error
    if stat.S_ISLNK(root_pathname_before.st_mode) or not stat.S_ISDIR(
        root_pathname_before.st_mode
    ):
        raise CapacityValidationError(
            "evidence_root must remain a non-symlink directory"
        )

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    if hasattr(os, "O_CLOEXEC"):
        directory_flags |= os.O_CLOEXEC
        file_flags |= os.O_CLOEXEC

    directory_descriptors: list[int] = []
    directory_chain: list[tuple[int, str, int, tuple[int, int]]] = []
    file_descriptor: int | None = None
    try:
        try:
            root_descriptor = os.open(evidence_root, directory_flags)
        except OSError as error:
            raise CapacityValidationError(
                f"cannot open evidence_root: {error}"
            ) from error
        directory_descriptors.append(root_descriptor)
        root_descriptor_before = os.fstat(root_descriptor)
        root_identity = (
            root_descriptor_before.st_dev,
            root_descriptor_before.st_ino,
        )
        if (
            not stat.S_ISDIR(root_descriptor_before.st_mode)
            or (
                root_pathname_before.st_dev,
                root_pathname_before.st_ino,
            )
            != root_identity
        ):
            raise CapacityValidationError(
                "evidence_root identity changed before evidence read"
            )

        parent_descriptor = root_descriptor
        for part in relative_path.parts[:-1]:
            try:
                component_descriptor = os.open(
                    part,
                    directory_flags,
                    dir_fd=parent_descriptor,
                )
            except OSError as error:
                raise CapacityValidationError(
                    "evidence path traverses a symlink, non-directory, or "
                    f"unavailable component: {relative_path}: {error}"
                ) from error
            component_stat = os.fstat(component_descriptor)
            if not stat.S_ISDIR(component_stat.st_mode):
                os.close(component_descriptor)
                raise CapacityValidationError(
                    f"evidence path traverses a non-directory: {relative_path}"
                )
            component_identity = (
                component_stat.st_dev,
                component_stat.st_ino,
            )
            directory_descriptors.append(component_descriptor)
            directory_chain.append(
                (
                    parent_descriptor,
                    part,
                    component_descriptor,
                    component_identity,
                )
            )
            parent_descriptor = component_descriptor

        try:
            file_descriptor = os.open(
                relative_path.parts[-1],
                file_flags,
                dir_fd=parent_descriptor,
            )
        except OSError as error:
            raise CapacityValidationError(
                f"cannot open evidence path {relative_path}: {error}"
            ) from error
        before = os.fstat(file_descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise CapacityValidationError(
                f"evidence path must identify a regular file: {relative_path}"
            )
        if before.st_size > _MAX_EVIDENCE_BYTES:
            raise CapacityValidationError(
                f"evidence file exceeds {_MAX_EVIDENCE_BYTES} bytes: {relative_path}"
            )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(file_descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_EVIDENCE_BYTES:
                raise CapacityValidationError(
                    f"evidence file exceeds {_MAX_EVIDENCE_BYTES} bytes: "
                    f"{relative_path}"
                )
            chunks.append(chunk)
        after = os.fstat(file_descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if identity_before != identity_after:
            raise CapacityValidationError(
                f"evidence file changed while it was read: {relative_path}"
            )

        try:
            leaf_pathname_after = os.stat(
                relative_path.parts[-1],
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as error:
            raise CapacityValidationError(
                f"evidence pathname changed while it was read: {relative_path}: {error}"
            ) from error
        descriptor_identity = (after.st_dev, after.st_ino)
        if (
            stat.S_ISLNK(leaf_pathname_after.st_mode)
            or not stat.S_ISREG(leaf_pathname_after.st_mode)
            or (
                leaf_pathname_after.st_dev,
                leaf_pathname_after.st_ino,
            )
            != descriptor_identity
        ):
            raise CapacityValidationError(
                f"evidence pathname identity changed while it was read: {relative_path}"
            )

        for (
            held_parent,
            part,
            held_component,
            component_identity,
        ) in reversed(directory_chain):
            try:
                pathname_after = os.stat(
                    part,
                    dir_fd=held_parent,
                    follow_symlinks=False,
                )
            except OSError as error:
                raise CapacityValidationError(
                    "evidence path ancestor changed while it was read: "
                    f"{relative_path}: {error}"
                ) from error
            descriptor_after = os.fstat(held_component)
            if (
                stat.S_ISLNK(pathname_after.st_mode)
                or not stat.S_ISDIR(pathname_after.st_mode)
                or not stat.S_ISDIR(descriptor_after.st_mode)
                or (
                    pathname_after.st_dev,
                    pathname_after.st_ino,
                )
                != component_identity
                or (
                    descriptor_after.st_dev,
                    descriptor_after.st_ino,
                )
                != component_identity
            ):
                raise CapacityValidationError(
                    "evidence path ancestor identity changed while it was read: "
                    f"{relative_path}"
                )

        try:
            root_pathname_after = evidence_root.lstat()
        except OSError as error:
            raise CapacityValidationError(
                f"evidence_root changed while evidence was read: {error}"
            ) from error
        root_descriptor_after = os.fstat(root_descriptor)
        if (
            stat.S_ISLNK(root_pathname_after.st_mode)
            or not stat.S_ISDIR(root_pathname_after.st_mode)
            or not stat.S_ISDIR(root_descriptor_after.st_mode)
            or (
                root_pathname_after.st_dev,
                root_pathname_after.st_ino,
            )
            != root_identity
            or (
                root_descriptor_after.st_dev,
                root_descriptor_after.st_ino,
            )
            != root_identity
        ):
            raise CapacityValidationError(
                "evidence_root identity changed while evidence was read"
            )
        return _EvidenceFileSnapshot(
            root_identity=root_identity,
            directory_identities=tuple(
                (part, component_identity)
                for _, part, _, component_identity in directory_chain
            ),
            file_identity=descriptor_identity,
            stat_fingerprint=(
                after.st_mode,
                after.st_uid,
                after.st_nlink,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ),
            content=b"".join(chunks),
        )
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        for descriptor in reversed(directory_descriptors):
            os.close(descriptor)


def _read_evidence_file(
    evidence_root: Path,
    relative_path: PurePosixPath,
) -> bytes:
    return _read_evidence_file_snapshot(evidence_root, relative_path).content


def _validate_evidence(
    authorities: object,
    evidence_root: Path,
    *,
    redaction_rules: Sequence[tuple[str, re.Pattern[str], str]],
) -> tuple[tuple[str, str], ...]:
    if not isinstance(authorities, list) or not authorities:
        raise CapacityValidationError("evidence must be a non-empty array")
    validated: list[tuple[str, str]] = []
    seen_paths: set[str] = set()
    total_evidence_bytes = 0
    for index, authority in enumerate(authorities):
        if not isinstance(authority, Mapping) or set(authority) != {
            "path",
            "sha256",
        }:
            raise CapacityValidationError(
                f"evidence[{index}] must contain exactly path and sha256"
            )
        path = _normalized_evidence_path(
            authority.get("path"),
            field_name=f"evidence[{index}].path",
        )
        path_text = path.as_posix()
        if path_text in seen_paths:
            raise CapacityValidationError("evidence paths must be distinct")
        seen_paths.add(path_text)
        declared = authority.get("sha256")
        if not isinstance(declared, str) or not _DIGEST_RE.fullmatch(declared):
            raise CapacityValidationError(
                f"evidence[{index}].sha256 must be a lowercase SHA-256"
            )
        content = _read_evidence_file(evidence_root, path)
        total_evidence_bytes += len(content)
        if total_evidence_bytes > _MAX_TOTAL_EVIDENCE_BYTES:
            raise CapacityValidationError(
                f"total evidence exceeds {_MAX_TOTAL_EVIDENCE_BYTES} bytes"
            )
        actual = hashlib.sha256(content).hexdigest()
        if actual != declared:
            raise CapacityValidationError(
                f"evidence[{index}].sha256 does not match raw evidence bytes"
            )
        try:
            evidence_text = content.decode("utf-8")
        except UnicodeDecodeError:
            semantic_observations: tuple[tuple[bool, str], ...] = ()
        else:
            semantic_observations = _semantic_scalar_observations(evidence_text)
        privacy_errors = _sensitive_text_findings(
            content,
            source=f"evidence {path_text}",
            semantic_observations=semantic_observations,
        )
        privacy_errors.extend(
            _unresolved_text_findings(
                content,
                source=f"evidence {path_text}",
                semantic_observations=semantic_observations,
            )
        )
        privacy_errors.extend(
            _configured_redaction_findings(
                content,
                source=f"evidence {path_text}",
                rules=redaction_rules,
                semantic_observations=semantic_observations,
            )
        )
        _raise_errors("capacity finding privacy", privacy_errors)
        validated.append((path_text, declared))
    return tuple(validated)


def _first_parent_chain(repo_root: Path, commit: str) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    current = commit
    while True:
        if current in seen:
            raise CapacityValidationError(
                "raw Git first-parent authority contains a cycle"
            )
        seen.add(current)
        values.append(current)
        parents = _raw_commit_parents(
            repo_root,
            current,
            field_name="working first-parent commit",
        )
        if not parents:
            return tuple(values)
        current = parents[0]


def _validate_observed_authority(
    authority: object,
    *,
    destination_repo: str,
    authority_repo_root: Path,
    expected_stage_id: str,
) -> None:
    if not isinstance(authority, Mapping):
        raise CapacityValidationError("observed_authority must be an object")
    policy = _DESTINATION_POLICIES[destination_repo]
    if authority.get("stage_id") != expected_stage_id:
        raise CapacityValidationError(
            "observed_authority.stage_id must equal the result profile stage"
        )
    for field_name in ("working_branch", "upstream_branch"):
        expected = policy[field_name]
        if authority.get(field_name) != expected:
            raise CapacityValidationError(
                f"observed_authority.{field_name} must equal {expected}"
            )

    working_ref = _validate_commit(
        authority_repo_root,
        authority.get("working_ref"),
        field_name="observed_authority.working_ref",
    )
    upstream_ref = _validate_commit(
        authority_repo_root,
        authority.get("upstream_ref"),
        field_name="observed_authority.upstream_ref",
    )
    first_parent_chain = _first_parent_chain(authority_repo_root, working_ref)
    inbound_merge_ref = authority.get("inbound_merge_ref")
    if inbound_merge_ref is None:
        if upstream_ref not in first_parent_chain:
            raise CapacityValidationError(
                "without inbound_merge_ref, upstream_ref must be on the "
                "working first-parent chain"
            )
        return

    inbound_merge = _validate_commit(
        authority_repo_root,
        inbound_merge_ref,
        field_name="observed_authority.inbound_merge_ref",
    )
    if inbound_merge not in first_parent_chain:
        raise CapacityValidationError(
            "inbound_merge_ref must be on the working first-parent chain"
        )
    parents = _raw_commit_parents(
        authority_repo_root,
        inbound_merge,
        field_name="observed_authority.inbound_merge_ref",
    )
    if len(parents) != 2:
        raise CapacityValidationError(
            "inbound_merge_ref must identify an exact two-parent merge commit"
        )
    if parents[1] != upstream_ref:
        raise CapacityValidationError(
            "inbound_merge_ref second parent must equal upstream_ref"
        )


def _parse_observed_at(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CapacityValidationError(
            "observed_authority.observed_at must be an exact UTC timestamp"
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise CapacityValidationError(
            f"observed_authority.observed_at is invalid: {error}"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise CapacityValidationError(
            "observed_authority.observed_at must identify UTC"
        )
    return parsed


def _request_outcomes_by_id(
    result_value: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    raw_outcomes = result_value.get("request_outcomes")
    if not isinstance(raw_outcomes, list) or not raw_outcomes:
        raise CapacityValidationError(
            "validated result does not contain request outcomes"
        )
    outcomes: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for item in raw_outcomes:
        if not isinstance(item, dict):
            raise CapacityValidationError(
                "validated result request outcome is not an object"
            )
        request_id = item.get("request_id")
        if not isinstance(request_id, str) or request_id in by_id:
            raise CapacityValidationError(
                "validated result request IDs are missing or duplicated"
            )
        outcomes.append(item)
        by_id[request_id] = item
    return outcomes, by_id


def _double_allocation_witness(
    outcomes: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    intervals: list[tuple[int, int, str]] = []
    for outcome in outcomes:
        if outcome.get("outcome_kind") != "vm-succeeded":
            continue
        observation = outcome.get("success_observation")
        interval = (
            observation.get("active_interval")
            if isinstance(observation, Mapping)
            else None
        )
        if not isinstance(interval, Mapping):
            continue
        start = interval.get("start_offset_ns")
        end = interval.get("end_offset_ns")
        request_id = outcome.get("request_id")
        if (
            isinstance(start, int)
            and isinstance(end, int)
            and isinstance(request_id, str)
        ):
            intervals.append((start, end, request_id))
    for instant in sorted({start for start, _, _ in intervals}):
        active = sorted(
            request_id for start, end, request_id in intervals if start <= instant < end
        )
        if len(active) > 1:
            return tuple(active)
    raise CapacityValidationError(
        "double-allocation result does not retain an overlapping VM witness"
    )


def _expected_observed_outcome(
    finding: Mapping[str, Any],
    result_value: Mapping[str, Any],
    result: ValidatedCapacityResult,
) -> tuple[tuple[str, ...], tuple[dict[str, Any], ...]]:
    semantics = finding.get("defect_semantics")
    observed = finding.get("observed_outcome")
    if not isinstance(semantics, Mapping) or not isinstance(observed, Mapping):
        raise CapacityValidationError(
            "finding semantics and observed outcome must be objects"
        )
    actual_category = semantics.get("actual_fault_category")
    failure_code = semantics.get("failure_code")
    lifecycle_phase = semantics.get("lifecycle_phase")
    outcomes, by_id = _request_outcomes_by_id(result_value)
    declared_request_ids = observed.get("request_ids")
    if not isinstance(declared_request_ids, list) or not all(
        isinstance(item, str) for item in declared_request_ids
    ):
        raise CapacityValidationError(
            "observed_outcome.request_ids must be an array of request IDs"
        )
    request_ids = tuple(declared_request_ids)
    if request_ids != tuple(sorted(request_ids)):
        raise CapacityValidationError(
            "observed_outcome.request_ids must use lexicographic canonical order"
        )

    expected_kind: str
    expected_diagnostic: str | None
    expected_request_ids: tuple[str, ...]
    if actual_category in REQUEST_FAILURE_CATEGORIES:
        if len(request_ids) != 1 or request_ids[0] not in by_id:
            raise CapacityValidationError(
                "a request fault finding must select exactly one result request"
            )
        outcome = by_id[request_ids[0]]
        fault = outcome.get("fault_observation")
        if (
            outcome.get("outcome_kind") != "fault"
            or outcome.get("failure_category") != actual_category
            or not isinstance(fault, Mapping)
        ):
            raise CapacityValidationError(
                "actual fault category does not match the selected result request"
            )
        expected_diagnostic = fault.get("diagnostic_code")
        if expected_diagnostic != failure_code:
            raise CapacityValidationError(
                "failure_code must equal the result diagnostic_code"
            )
        if fault.get("phase") != lifecycle_phase:
            raise CapacityValidationError(
                "lifecycle_phase must equal the result fault phase"
            )
        expected_kind = "fault"
        expected_request_ids = request_ids
    elif actual_category == "double-allocation":
        if "double-allocation" not in result.derived_faults:
            raise CapacityValidationError(
                "double-allocation finding requires the derived result fault"
            )
        expected_request_ids = _double_allocation_witness(outcomes)
        if request_ids != expected_request_ids:
            raise CapacityValidationError(
                "double-allocation request_ids must equal the deterministic "
                "overlap witness"
            )
        if failure_code != "double-allocation":
            raise CapacityValidationError(
                "double-allocation failure_code must equal double-allocation"
            )
        if lifecycle_phase != "provisioning":
            raise CapacityValidationError(
                "double-allocation lifecycle_phase must equal provisioning"
            )
        expected_kind = "vm-succeeded"
        expected_diagnostic = None
    elif actual_category == "unexpected-outcome":
        declared_kind = observed.get("outcome_kind")
        if declared_kind not in {"vm-succeeded", "capacity-refused"}:
            raise CapacityValidationError(
                "unexpected-outcome must select a non-fault terminal outcome"
            )
        expected_counts = result_value.get("expected_outcomes")
        observed_counts = result_value.get("observed_outcomes")
        if (
            not isinstance(expected_counts, Mapping)
            or not isinstance(observed_counts, Mapping)
            or not isinstance(expected_counts.get(declared_kind), int)
            or not isinstance(observed_counts.get(declared_kind), int)
            or observed_counts[declared_kind] <= expected_counts[declared_kind]
        ):
            raise CapacityValidationError(
                "unexpected-outcome must select a terminal outcome whose "
                "observed count exceeds the frozen expected count"
            )
        all_kind_request_ids = sorted(
            str(outcome["request_id"])
            for outcome in outcomes
            if outcome.get("outcome_kind") == declared_kind
        )
        expected_request_ids = tuple(all_kind_request_ids)
        if request_ids != expected_request_ids:
            raise CapacityValidationError(
                "unexpected-outcome request_ids must equal the lexicographically "
                "canonical full set for the surplus outcome kind"
            )
        if (
            declared_kind == "vm-succeeded"
            and "double-allocation" in result.derived_faults
        ):
            raise CapacityValidationError(
                "overlapping excess VM success must use double-allocation"
            )
        opposite_kind = {
            "vm-succeeded": "capacity-refused",
            "capacity-refused": "vm-succeeded",
        }[declared_kind]
        if semantics.get("expected_outcome_kind") != opposite_kind:
            raise CapacityValidationError(
                "unexpected-outcome expected kind must equal the displaced "
                "non-fault outcome kind"
            )
        expected_failure_code = f"unexpected-{declared_kind}"
        if failure_code != expected_failure_code:
            raise CapacityValidationError(
                f"unexpected outcome failure_code must equal {expected_failure_code}"
            )
        expected_phase = {
            "vm-succeeded": "guest-verification",
            "capacity-refused": "reservation",
        }[declared_kind]
        if lifecycle_phase != expected_phase:
            raise CapacityValidationError(
                f"unexpected {declared_kind} lifecycle_phase must equal "
                f"{expected_phase}"
            )
        expected_kind = declared_kind
        expected_diagnostic = None
    else:
        raise CapacityValidationError("unsupported actual fault category")

    if observed.get("outcome_kind") != expected_kind:
        raise CapacityValidationError(
            "observed_outcome.outcome_kind does not match the result"
        )
    if observed.get("diagnostic_code") != expected_diagnostic:
        raise CapacityValidationError(
            "observed_outcome.diagnostic_code does not match the result"
        )
    selected = tuple(by_id[request_id] for request_id in expected_request_ids)
    return expected_request_ids, selected


def _correlation_projection(outcome: Mapping[str, Any]) -> dict[str, Any]:
    settlement_record = outcome.get("settlement_record")
    return {
        "request_id": outcome["request_id"],
        "outcome_kind": outcome["outcome_kind"],
        "deal_reference_sha256": canonical_sha256(outcome["deal_reference"]),
        "capacity_reservation_id": outcome.get("capacity_reservation_id"),
        "fulfillment_id": outcome.get("fulfillment_id"),
        "settlement_record_sha256": (
            canonical_sha256(settlement_record)
            if isinstance(settlement_record, Mapping)
            else None
        ),
        "provisioned_resource_id": outcome.get("provisioned_resource_id"),
        "allocation_id": outcome.get("allocation_id"),
        "provisioning_job_id": outcome.get("provisioning_job_id"),
        "commercial_resolution_sha256": canonical_sha256(
            outcome["commercial_resolution"]
        ),
        "request_cleanup_sha256": canonical_sha256(outcome["request_cleanup"]),
    }


def _validate_durable_correlations(
    declared: object,
    selected_outcomes: Sequence[Mapping[str, Any]],
) -> None:
    expected = [_correlation_projection(outcome) for outcome in selected_outcomes]
    if declared != expected:
        raise CapacityValidationError(
            "durable_correlations must exactly project the selected result "
            "request outcomes in canonical request order"
        )


def _expected_filing_readiness(
    result_value: Mapping[str, Any],
    result: ValidatedCapacityResult,
) -> dict[str, bool]:
    cleanup = result_value.get("cleanup")
    outcomes = result_value.get("request_outcomes")
    if not isinstance(cleanup, Mapping) or not isinstance(outcomes, list):
        raise CapacityValidationError(
            "validated result is missing cleanup readiness authority"
        )
    residue = cleanup.get("residue_counts")
    zero_active_residue = (
        isinstance(residue, Mapping)
        and bool(residue)
        and all(value == 0 for value in residue.values())
        and all(
            isinstance(outcome, Mapping)
            and isinstance(outcome.get("request_cleanup"), Mapping)
            and outcome["request_cleanup"].get("zero_active_residue") is True
            for outcome in outcomes
        )
    )
    components = cleanup.get("reversible_components")
    accounting = cleanup.get("accounting_deltas")
    baseline_equivalent = (
        isinstance(components, list)
        and bool(components)
        and all(
            isinstance(component, Mapping) and component.get("exactly_equal") is True
            for component in components
        )
        and isinstance(accounting, list)
        and bool(accounting)
        and all(
            isinstance(delta, Mapping)
            and delta.get("reconciled") is True
            and delta.get("active_lock") is False
            and delta.get("unexplained_value") is False
            for delta in accounting
        )
    )
    terminal = cleanup.get("terminal_correlations_complete") is True
    teardown = cleanup.get("teardown_complete") is True and all(
        isinstance(outcome, Mapping)
        and isinstance(outcome.get("request_cleanup"), Mapping)
        and outcome["request_cleanup"].get("teardown_complete") is True
        for outcome in outcomes
    )
    ready = (
        terminal
        and teardown
        and zero_active_residue
        and baseline_equivalent
        and result.cleanup_passed is True
    )
    return {
        "terminal_correlations_complete": terminal,
        "teardown_complete": teardown,
        "zero_active_residue": zero_active_residue,
        "baseline_equivalent": baseline_equivalent,
        "ready_to_file": ready,
    }


def validate_capacity_finding(
    value: Mapping[str, Any],
    result: ValidatedCapacityResult,
    *,
    authority_repo_root: Path,
    evidence_root: Path,
) -> ValidatedCapacityFinding:
    """Validate one sanitized finding against an already validated VM result."""
    result_value = require_validated_capacity_result(result)
    public_root = _validate_git_root(
        result.repo_root,
        expected_repository="arkhai-io/simple-compute-market",
    )
    scm_contract_ref = value.get("scm_contract_ref")
    if scm_contract_ref != result.scm_ref:
        raise CapacityValidationError(
            "scm_contract_ref must equal the validated result SCM ref"
        )
    schema = _load_pinned_finding_schema(public_root, result.scm_ref)
    schema_errors = _schema_errors(value, schema)
    _raise_errors("capacity finding schema", schema_errors)
    if value.get("schema_version") != 2:
        raise CapacityValidationError(
            "current capacity findings require schema_version 2"
        )

    exact_result_authority = {
        "scenario_id": result.scenario_id,
        "scenario_sha256": result.scenario_sha256,
        "profile_stage_id": result.profile_stage_id,
        "profile_stage_sha256": result.profile_stage_sha256,
        "result_id": result.result_id,
        "result_sha256": result.canonical_sha256,
    }
    for field_name, expected in exact_result_authority.items():
        if value.get(field_name) != expected:
            raise CapacityValidationError(
                f"{field_name} does not match the validated capacity result"
            )

    destination_repo = value.get("destination_repo")
    if destination_repo not in _DESTINATION_POLICIES:
        raise CapacityValidationError("capacity finding destination is unsupported")
    assert isinstance(destination_repo, str)
    policy = _DESTINATION_POLICIES[destination_repo]
    classifications = policy["classifications"]
    assert isinstance(classifications, frozenset)
    classification = value.get("classification")
    if classification not in classifications:
        raise CapacityValidationError(
            "capacity finding classification does not map to its destination"
        )
    assert isinstance(classification, str)

    authority_root = _validate_git_root(
        authority_repo_root,
        expected_repository=str(policy["repository"]),
    )
    observed_authority = value.get("observed_authority")
    _validate_observed_authority(
        observed_authority,
        destination_repo=destination_repo,
        authority_repo_root=authority_root,
        expected_stage_id=result.profile_stage_id,
    )
    assert isinstance(observed_authority, Mapping)
    if destination_repo == "simple-compute-market":
        working_ref = observed_authority["working_ref"]
        assert isinstance(working_ref, str)
        if result.scm_ref not in _first_parent_chain(authority_root, working_ref):
            raise CapacityValidationError(
                "SCM working_ref must contain scm_contract_ref on its "
                "first-parent chain"
            )
    observed_at = _parse_observed_at(observed_authority.get("observed_at"))
    if observed_at < result.progression_ready_at:
        raise CapacityValidationError(
            "finding observation cannot precede result progression readiness"
        )

    semantics = value.get("defect_semantics")
    assert isinstance(semantics, Mapping)
    stable_signature = semantics.get("stable_signature")
    normalized_signature = _normalize_stable_signature(stable_signature)
    if stable_signature != normalized_signature:
        raise CapacityValidationError(
            "defect_semantics.stable_signature must already be NFKC-normalized, "
            "case-folded, trimmed, and whitespace-collapsed"
        )
    if semantics.get("expected_outcome_kind") == "fault":
        raise CapacityValidationError(
            "a capacity finding cannot declare fault as the expected outcome"
        )
    if (
        semantics.get("actual_fault_category") == "double-allocation"
        and value.get("frontier") != "simultaneous-fulfillment"
    ):
        raise CapacityValidationError(
            "double-allocation findings belong to simultaneous-fulfillment"
        )

    _, selected_outcomes = _expected_observed_outcome(
        value,
        result_value,
        result,
    )
    _validate_durable_correlations(
        value.get("durable_correlations"),
        selected_outcomes,
    )
    expected_readiness = _expected_filing_readiness(result_value, result)
    if value.get("filing_readiness") != expected_readiness:
        raise CapacityValidationError(
            "filing_readiness must equal the cleanup-gated result projection"
        )

    privacy_errors = _sensitive_findings(
        dict(value),
        source="capacity finding",
    )
    privacy_errors.extend(
        _unresolved_sentinel_findings(
            dict(value),
            source="capacity finding",
        )
    )
    redaction_rules = _load_pinned_redaction_rules(
        public_root,
        result.scm_ref,
    )
    privacy_errors.extend(
        _configured_value_findings(
            dict(value),
            source="capacity finding",
            rules=redaction_rules,
        )
    )
    privacy_errors.extend(
        _configured_redaction_findings(
            canonical_json_bytes(dict(value)),
            source="capacity finding",
            rules=redaction_rules,
        )
    )
    _raise_errors("capacity finding privacy", privacy_errors)
    root = _validate_evidence_root(evidence_root)
    evidence = _validate_evidence(
        value.get("evidence"),
        root,
        redaction_rules=redaction_rules,
    )
    fingerprint = derive_capacity_finding_fingerprint(value)
    canonical_bytes = canonical_json_bytes(dict(value))
    return ValidatedCapacityFinding(
        finding_id=str(value["finding_id"]),
        fingerprint=fingerprint,
        canonical_sha256=hashlib.sha256(canonical_bytes).hexdigest(),
        destination_repo=destination_repo,
        destination_repository=str(policy["repository"]),
        classification=classification,
        frontier=str(value["frontier"]),
        scenario_id=result.scenario_id,
        scenario_sha256=result.scenario_sha256,
        profile_stage_id=result.profile_stage_id,
        profile_stage_sha256=result.profile_stage_sha256,
        result_id=result.result_id,
        result_sha256=result.canonical_sha256,
        scm_contract_ref=result.scm_ref,
        ready_to_file=expected_readiness["ready_to_file"],
        evidence_root=root,
        _canonical_bytes=canonical_bytes,
        _evidence=evidence,
        _redaction_rules=redaction_rules,
        _validation_token=_FINDING_VALIDATION_TOKEN,
    )


def require_validated_capacity_finding(
    finding: ValidatedCapacityFinding,
) -> dict[str, Any]:
    """Recheck source and evidence immutability before downstream use."""
    if (
        not isinstance(finding, ValidatedCapacityFinding)
        or finding._validation_token is not _FINDING_VALIDATION_TOKEN
    ):
        raise CapacityValidationError("operation requires a validated capacity finding")
    value = finding.finding
    canonical_bytes = canonical_json_bytes(value)
    if (
        canonical_bytes != finding._canonical_bytes
        or hashlib.sha256(canonical_bytes).hexdigest() != finding.canonical_sha256
    ):
        raise CapacityValidationError(
            "capacity-finding snapshot changed after validation"
        )
    if derive_capacity_finding_fingerprint(value) != finding.fingerprint:
        raise CapacityValidationError(
            "capacity-finding fingerprint changed after validation"
        )
    authorities = [
        {"path": path, "sha256": digest} for path, digest in finding._evidence
    ]
    if (
        _validate_evidence(
            authorities,
            finding.evidence_root,
            redaction_rules=finding._redaction_rules,
        )
        != finding._evidence
    ):
        raise CapacityValidationError(
            "capacity-finding evidence changed after validation"
        )
    return value


def _pretty_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def _markdown_literal_lines(value: str) -> list[str]:
    """Render agent prose as an indented CommonMark code block."""
    lines = value.splitlines()
    return [f"    {line}" for line in (lines or [""])]


def _render_finding_occurrence_value(
    value: Mapping[str, Any],
    fingerprint: str,
) -> str:
    semantics = value["defect_semantics"]
    authority = value["observed_authority"]
    lines = [
        "# VM capacity finding occurrence",
        "",
        "Preparatory VM capacity finding (detected occurrence).",
        "",
        (
            "This artifact does not authorize branch promotion, GitHub mutation, "
            "live capacity execution, or live publication."
        ),
        "",
        "## Summary",
        "",
        *_markdown_literal_lines(str(value["summary"])),
        "",
        "## Stable defect identity",
        "",
        f"- Finding occurrence: `{value['finding_id']}`",
        f"- SCM-derived fingerprint: `{fingerprint}`",
        f"- Destination repository: `{value['destination_repo']}`",
        f"- Classification: `{value['classification']}`",
        f"- Frontier: `{value['frontier']}`",
        (f"- Scenario: `{value['scenario_id']}` (`{value['scenario_sha256']}`)"),
        (
            f"- Profile stage: `{value['profile_stage_id']}` "
            f"(`{value['profile_stage_sha256']}`)"
        ),
        f"- Result: `{value['result_id']}` (`{value['result_sha256']}`)",
        f"- SCM contract ref: `{value['scm_contract_ref']}`",
        f"- Expected outcome: `{semantics['expected_outcome_kind']}`",
        f"- Actual fault: `{semantics['actual_fault_category']}`",
        f"- Failure code: `{semantics['failure_code']}`",
        f"- Lifecycle phase: `{semantics['lifecycle_phase']}`",
        "",
        "Stable signature:",
        "",
        *_markdown_literal_lines(str(semantics["stable_signature"])),
        "",
        "## Observation",
        "",
        "Expected:",
        "",
        *_markdown_literal_lines(str(value["expected"])),
        "",
        "Actual:",
        "",
        *_markdown_literal_lines(str(value["actual"])),
        "",
        "```json",
        _pretty_json(value["observed_outcome"]),
        "```",
        "",
        "## Exact occurrence authority",
        "",
        f"- Run: `{authority['run_id']}`",
        f"- Stage: `{authority['stage_id']}`",
        (
            f"- Working branch/ref: `{authority['working_branch']}` / "
            f"`{authority['working_ref']}`"
        ),
        (
            f"- Upstream branch/ref: `{authority['upstream_branch']}` / "
            f"`{authority['upstream_ref']}`"
        ),
        f"- Inbound merge ref: `{authority['inbound_merge_ref']}`",
        f"- Reconciliation epoch: `{authority['reconciliation_epoch_id']}`",
        f"- Observed at: `{authority['observed_at']}`",
        "",
        "## Durable correlations",
        "",
        "```json",
        _pretty_json(value["durable_correlations"]),
        "```",
        "",
        "## Evidence authority",
        "",
        "```json",
        _pretty_json(value["evidence"]),
        "```",
        "",
        "## Cleanup-gated filing readiness",
        "",
        "```json",
        _pretty_json(value["filing_readiness"]),
        "```",
        "",
    ]
    body = "\n".join(lines)
    if "scm.finding-publication." in body:
        raise CapacityValidationError(
            "preparatory occurrence body cannot contain publication markers"
        )
    privacy_errors = _sensitive_text_findings(
        body.encode("utf-8"),
        source="rendered capacity finding",
    )
    _raise_errors("capacity finding privacy", privacy_errors)
    return body


def render_finding_occurrence(finding: ValidatedCapacityFinding) -> str:
    """Render a deterministic marker-free human review packet."""
    value = require_validated_capacity_finding(finding)
    body = _render_finding_occurrence_value(value, finding.fingerprint)
    configured_errors = _configured_redaction_findings(
        body.encode("utf-8"),
        source="rendered capacity finding",
        rules=finding._redaction_rules,
    )
    _raise_errors("capacity finding privacy", configured_errors)
    return body


def _index_record_from_source(
    source_finding: Mapping[str, Any],
) -> dict[str, Any]:
    source = dict(source_finding)
    fingerprint = derive_capacity_finding_fingerprint(source)
    body = _render_finding_occurrence_value(source, fingerprint)
    body_bytes = body.encode("utf-8")
    authority = source.get("observed_authority")
    if not isinstance(authority, Mapping):
        raise CapacityValidationError(
            "source finding observed_authority must be an object"
        )
    source_bytes = canonical_json_bytes(source)
    return {
        "schema_version": 1,
        "candidate_kind": "capacity-finding-v2",
        "publication_capability": CAPACITY_FINDING_PUBLICATION_CAPABILITY,
        "finding_id": source["finding_id"],
        "finding_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "fingerprint": fingerprint,
        "destination_repo": source["destination_repo"],
        "classification": source["classification"],
        "frontier": source["frontier"],
        "scenario_id": source["scenario_id"],
        "scenario_sha256": source["scenario_sha256"],
        "profile_stage_id": source["profile_stage_id"],
        "profile_stage_sha256": source["profile_stage_sha256"],
        "result_id": source["result_id"],
        "result_sha256": source["result_sha256"],
        "scm_contract_ref": source["scm_contract_ref"],
        "defect_semantics": source["defect_semantics"],
        "observed_outcome": source["observed_outcome"],
        "durable_correlations": source["durable_correlations"],
        "observed_authority": source["observed_authority"],
        "evidence": source["evidence"],
        "filing_readiness": source["filing_readiness"],
        "lifecycle": {
            "state": "detected",
            "detected_at": authority["observed_at"],
        },
        "occurrence_body_path": (
            f"{CAPACITY_FINDING_BODY_DIRECTORY}/{source['finding_id']}.md"
        ),
        "occurrence_body": body,
        "occurrence_body_sha256": hashlib.sha256(body_bytes).hexdigest(),
    }


def capacity_finding_index_record(
    finding: ValidatedCapacityFinding,
) -> dict[str, Any]:
    """Build the exact derived record consumed by packet generation."""
    source = require_validated_capacity_finding(finding)
    record = _index_record_from_source(source)
    rendered_body = render_finding_occurrence(finding)
    if record["occurrence_body"] != rendered_body:
        raise CapacityValidationError(
            "derived index occurrence body does not match validated rendering"
        )
    if record["finding_sha256"] != finding.canonical_sha256:
        raise CapacityValidationError(
            "derived index finding digest does not match validated source"
        )
    if record["fingerprint"] != finding.fingerprint:
        raise CapacityValidationError(
            "derived index fingerprint does not match validated source"
        )
    return record


def validate_capacity_finding_index_record(
    record: Mapping[str, Any],
    source_finding: Mapping[str, Any],
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Verify a persisted index from source bytes without rebuilding its result."""
    source = dict(source_finding)
    if source.get("schema_version") != 2:
        raise CapacityValidationError(
            "capacity-finding index requires a schema-v2 source finding"
        )
    public_root = _validate_git_root(
        repo_root,
        expected_repository="arkhai-io/simple-compute-market",
    )
    contract_ref = _validate_commit(
        public_root,
        source.get("scm_contract_ref"),
        field_name="capacity finding SCM contract ref",
    )
    _raise_errors(
        "capacity-finding index source schema",
        _schema_errors(
            source,
            _load_pinned_finding_schema(public_root, contract_ref),
        ),
    )
    privacy_errors = _sensitive_findings(
        source,
        source="capacity-finding index source",
    )
    privacy_errors.extend(
        _unresolved_sentinel_findings(
            source,
            source="capacity-finding index source",
        )
    )
    contract_rules = _load_pinned_redaction_rules(public_root, contract_ref)
    privacy_errors.extend(
        _configured_value_findings(
            source,
            source="capacity-finding index source",
            rules=contract_rules,
        )
    )
    privacy_errors.extend(
        _configured_redaction_findings(
            canonical_json_bytes(source),
            source="capacity-finding index source",
            rules=contract_rules,
        )
    )
    _raise_errors("capacity finding privacy", privacy_errors)
    expected = _index_record_from_source(source)
    if dict(record) != expected:
        raise CapacityValidationError(
            "capacity-finding index record does not exactly match source"
        )
    body = expected["occurrence_body"]
    assert isinstance(body, str)
    body_digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if expected["occurrence_body_sha256"] != body_digest:
        raise CapacityValidationError(
            "capacity-finding index occurrence body digest is invalid"
        )
    if expected["lifecycle"] != {
        "state": "detected",
        "detected_at": source["observed_authority"]["observed_at"],
    }:
        raise CapacityValidationError(
            "capacity-finding index may only record detected lifecycle"
        )
    body = expected["occurrence_body"]
    assert isinstance(body, str)
    configured_body_errors = _configured_redaction_findings(
        body.encode("utf-8"),
        source="capacity-finding index body",
        rules=contract_rules,
    )
    _raise_errors("capacity finding privacy", configured_body_errors)
    return expected


def _private_path_identity(path_stat: os.stat_result) -> tuple[int, int]:
    return path_stat.st_dev, path_stat.st_ino


def _renameat2(
    directory_descriptor: int,
    source_name: str,
    destination_name: str,
    *,
    flags: int,
) -> None:
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError as error:
        raise CapacityValidationError(
            "secure private publication requires Linux renameat2"
        ) from error
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        directory_descriptor,
        os.fsencode(source_name),
        directory_descriptor,
        os.fsencode(destination_name),
        flags,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
            raise CapacityValidationError(
                "secure private publication requires filesystem support for "
                "Linux renameat2 exchange"
            )
        raise OSError(
            error_number,
            os.strerror(error_number),
            f"{source_name} -> {destination_name}",
        )


@dataclass(slots=True)
class _PrivatePathAuthority:
    root: Path
    root_descriptor: int
    root_identity: tuple[int, int]
    parent_descriptor: int
    leaf_name: str
    directory_descriptors: list[int]
    directory_chain: list[tuple[int, str, int, tuple[int, int]]]

    def revalidate(self) -> None:
        for (
            held_parent,
            part,
            held_component,
            component_identity,
        ) in reversed(self.directory_chain):
            try:
                pathname = os.stat(
                    part,
                    dir_fd=held_parent,
                    follow_symlinks=False,
                )
                descriptor_stat = os.fstat(held_component)
            except OSError as error:
                raise CapacityValidationError(
                    "private finding path ancestor changed under held "
                    f"authority: {error}"
                ) from error
            if (
                stat.S_ISLNK(pathname.st_mode)
                or not stat.S_ISDIR(pathname.st_mode)
                or not stat.S_ISDIR(descriptor_stat.st_mode)
                or pathname.st_uid != os.geteuid()
                or descriptor_stat.st_uid != os.geteuid()
                or stat.S_IMODE(pathname.st_mode) != 0o700
                or stat.S_IMODE(descriptor_stat.st_mode) != 0o700
                or _private_path_identity(pathname) != component_identity
                or _private_path_identity(descriptor_stat) != component_identity
            ):
                raise CapacityValidationError(
                    "private finding path ancestor identity changed under "
                    "held authority"
                )
        try:
            root_pathname = self.root.lstat()
            root_descriptor_stat = os.fstat(self.root_descriptor)
        except OSError as error:
            raise CapacityValidationError(
                f"private finding root changed under held authority: {error}"
            ) from error
        if (
            stat.S_ISLNK(root_pathname.st_mode)
            or not stat.S_ISDIR(root_pathname.st_mode)
            or not stat.S_ISDIR(root_descriptor_stat.st_mode)
            or root_pathname.st_uid != os.geteuid()
            or root_descriptor_stat.st_uid != os.geteuid()
            or stat.S_IMODE(root_pathname.st_mode) != 0o700
            or stat.S_IMODE(root_descriptor_stat.st_mode) != 0o700
            or _private_path_identity(root_pathname) != self.root_identity
            or _private_path_identity(root_descriptor_stat) != self.root_identity
        ):
            raise CapacityValidationError(
                "private finding root identity changed under held authority"
            )


@contextmanager
def _private_parent_authority(
    root: Path,
    path: Path,
    *,
    held_root: _PrivatePathAuthority | None = None,
) -> Iterator[_PrivatePathAuthority]:
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise CapacityValidationError(
            "secure descriptor-relative private artifact traversal is unavailable"
        )
    if held_root is None:
        validated_root = _validate_evidence_root(root)
    else:
        held_root.revalidate()
        validated_root = held_root.root
        if root.expanduser().absolute() != validated_root:
            raise CapacityValidationError(
                "private operation root does not equal held run authority"
            )
    candidate = path.expanduser().absolute()
    try:
        relative = candidate.relative_to(validated_root)
    except ValueError as error:
        raise CapacityValidationError(
            f"private finding path is outside its explicit root: {path}"
        ) from error
    if len(relative.parts) < 1 or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise CapacityValidationError(
            f"private finding path is not canonical below its root: {path}"
        )

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    directory_descriptors: list[int] = []
    directory_chain: list[tuple[int, str, int, tuple[int, int]]] = []
    try:
        root_pathname = validated_root.lstat()
        if held_root is None:
            root_descriptor = os.open(validated_root, flags)
        else:
            root_descriptor = os.dup(held_root.root_descriptor)
        directory_descriptors.append(root_descriptor)
        root_descriptor_stat = os.fstat(root_descriptor)
        root_identity = _private_path_identity(root_descriptor_stat)
        if (
            stat.S_ISLNK(root_pathname.st_mode)
            or not stat.S_ISDIR(root_pathname.st_mode)
            or not stat.S_ISDIR(root_descriptor_stat.st_mode)
            or root_pathname.st_uid != os.geteuid()
            or root_descriptor_stat.st_uid != os.geteuid()
            or stat.S_IMODE(root_pathname.st_mode) != 0o700
            or stat.S_IMODE(root_descriptor_stat.st_mode) != 0o700
            or _private_path_identity(root_pathname) != root_identity
        ):
            raise CapacityValidationError(
                "private finding root must remain a current-user mode 0700 "
                "directory with stable identity"
            )

        parent_descriptor = root_descriptor
        for part in relative.parts[:-1]:
            try:
                component_descriptor = os.open(
                    part,
                    flags,
                    dir_fd=parent_descriptor,
                )
            except OSError as error:
                raise CapacityValidationError(
                    "private finding path traverses a symlink, non-directory, "
                    f"or unavailable component: {path}: {error}"
                ) from error
            directory_descriptors.append(component_descriptor)
            component_stat = os.fstat(component_descriptor)
            if (
                not stat.S_ISDIR(component_stat.st_mode)
                or component_stat.st_uid != os.geteuid()
                or stat.S_IMODE(component_stat.st_mode) != 0o700
            ):
                raise CapacityValidationError(
                    "private finding path ancestors must be current-user "
                    f"mode 0700 directories: {path}"
                )
            component_identity = _private_path_identity(component_stat)
            directory_chain.append(
                (
                    parent_descriptor,
                    part,
                    component_descriptor,
                    component_identity,
                )
            )
            parent_descriptor = component_descriptor

        authority = _PrivatePathAuthority(
            root=validated_root,
            root_descriptor=root_descriptor,
            root_identity=root_identity,
            parent_descriptor=parent_descriptor,
            leaf_name=relative.parts[-1],
            directory_descriptors=directory_descriptors,
            directory_chain=directory_chain,
        )
        authority.revalidate()
        try:
            yield authority
        finally:
            authority.revalidate()
            if held_root is not None:
                held_root.revalidate()
    except OSError as error:
        raise CapacityValidationError(
            f"cannot establish private finding path authority: {error}"
        ) from error
    finally:
        for descriptor in reversed(directory_descriptors):
            os.close(descriptor)


def _validate_held_private_directory(
    path: Path,
    path_authority: _PrivatePathAuthority,
    descriptor: int,
    *,
    expected_identity: tuple[int, int] | None = None,
) -> tuple[int, int]:
    try:
        pathname = os.stat(
            path_authority.leaf_name,
            dir_fd=path_authority.parent_descriptor,
            follow_symlinks=False,
        )
        descriptor_stat = os.fstat(descriptor)
    except OSError as error:
        raise CapacityValidationError(
            f"private finding directory changed under held authority: {path}: "
            f"{error}"
        ) from error
    pathname_identity = _private_path_identity(pathname)
    descriptor_identity = _private_path_identity(descriptor_stat)
    if (
        stat.S_ISLNK(pathname.st_mode)
        or not stat.S_ISDIR(pathname.st_mode)
        or not stat.S_ISDIR(descriptor_stat.st_mode)
        or pathname.st_uid != os.geteuid()
        or descriptor_stat.st_uid != os.geteuid()
        or stat.S_IMODE(pathname.st_mode) != 0o700
        or stat.S_IMODE(descriptor_stat.st_mode) != 0o700
        or pathname_identity != descriptor_identity
        or (
            expected_identity is not None
            and descriptor_identity != expected_identity
        )
    ):
        raise CapacityValidationError(
            "private finding directory must retain one stable current-user "
            f"mode 0700 non-symlink identity: {path}"
        )
    return descriptor_identity


@contextmanager
def _held_private_directory(
    path: Path,
    *,
    root: Path,
    authority: _PrivatePathAuthority | None = None,
) -> Iterator[int]:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    with _private_parent_authority(
        root,
        path,
        held_root=authority,
    ) as path_authority:
        try:
            descriptor = os.open(
                path_authority.leaf_name,
                flags,
                dir_fd=path_authority.parent_descriptor,
            )
        except OSError as error:
            raise CapacityValidationError(
                f"cannot open private finding directory {path}: {error}"
            ) from error
        try:
            directory_identity = _validate_held_private_directory(
                path,
                path_authority,
                descriptor,
            )
            try:
                yield descriptor
            finally:
                _validate_held_private_directory(
                    path,
                    path_authority,
                    descriptor,
                    expected_identity=directory_identity,
                )
        finally:
            os.close(descriptor)
        path_authority.revalidate()


def _validate_private_directory(
    path: Path,
    *,
    root: Path | None = None,
    authority: _PrivatePathAuthority | None = None,
) -> None:
    explicit_root = path.parent if root is None else root
    with _held_private_directory(
        path,
        root=explicit_root,
        authority=authority,
    ):
        pass


class _UnspecifiedPrivateDirectory:
    pass


_UNSPECIFIED_PRIVATE_DIRECTORY = _UnspecifiedPrivateDirectory()


def _private_directory(
    path: Path,
    *,
    root: Path | None = None,
    authority: _PrivatePathAuthority | None = None,
    expected_existing_identity: (
        tuple[int, int] | None | _UnspecifiedPrivateDirectory
    ) = _UNSPECIFIED_PRIVATE_DIRECTORY,
) -> tuple[int, int]:
    explicit_root = path.parent if root is None else root
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    with _private_parent_authority(
        explicit_root,
        path,
        held_root=authority,
    ) as path_authority:
        created = False
        created_identity: tuple[int, int] | None = None
        if isinstance(expected_existing_identity, tuple):
            try:
                existing_pathname = os.stat(
                    path_authority.leaf_name,
                    dir_fd=path_authority.parent_descriptor,
                    follow_symlinks=False,
                )
            except OSError as error:
                raise CapacityValidationError(
                    "private finding directory disappeared after preflight: "
                    f"{path}: {error}"
                ) from error
            if (
                _private_path_identity(existing_pathname)
                != expected_existing_identity
            ):
                raise CapacityValidationError(
                    "private finding directory identity differs from preflight: "
                    f"{path}"
                )
        else:
            try:
                os.mkdir(
                    path_authority.leaf_name,
                    mode=0o700,
                    dir_fd=path_authority.parent_descriptor,
                )
                created = True
                created_pathname = os.stat(
                    path_authority.leaf_name,
                    dir_fd=path_authority.parent_descriptor,
                    follow_symlinks=False,
                )
                if (
                    stat.S_ISLNK(created_pathname.st_mode)
                    or not stat.S_ISDIR(created_pathname.st_mode)
                    or created_pathname.st_uid != os.geteuid()
                ):
                    raise CapacityValidationError(
                        "new private finding directory did not retain its "
                        f"owner/type authority: {path}"
                    )
                created_identity = _private_path_identity(created_pathname)
            except FileExistsError:
                if expected_existing_identity is None:
                    raise CapacityValidationError(
                        "private finding directory appeared after absent "
                        f"preflight: {path}"
                    )
            except OSError as error:
                raise CapacityValidationError(
                    f"cannot create private finding directory {path}: {error}"
                ) from error
        if created:
            try:
                os.chmod(
                    path_authority.leaf_name,
                    0o700,
                    dir_fd=path_authority.parent_descriptor,
                    follow_symlinks=False,
                )
            except OSError as error:
                raise CapacityValidationError(
                    f"cannot secure private finding directory {path}: {error}"
                ) from error
        try:
            descriptor = os.open(
                path_authority.leaf_name,
                flags,
                dir_fd=path_authority.parent_descriptor,
            )
        except OSError as error:
            raise CapacityValidationError(
                f"private finding path must be a non-symlink directory: {path}: {error}"
            ) from error
        try:
            if created:
                os.fchmod(descriptor, 0o700)
                os.fsync(descriptor)
                os.fsync(path_authority.parent_descriptor)
            directory_identity = _validate_held_private_directory(
                path,
                path_authority,
                descriptor,
                expected_identity=(
                    created_identity
                    if created
                    else expected_existing_identity
                    if isinstance(expected_existing_identity, tuple)
                    else None
                ),
            )
            if created and directory_identity != created_identity:
                raise CapacityValidationError(
                    "new private finding directory identity changed during "
                    f"creation: {path}"
                )
            _validate_held_private_directory(
                path,
                path_authority,
                descriptor,
                expected_identity=directory_identity,
            )
        finally:
            os.close(descriptor)
        path_authority.revalidate()
        return directory_identity


def ensure_capacity_finding_private_directory(
    path: Path,
    *,
    root: Path,
    authority: _PrivatePathAuthority | None = None,
) -> None:
    """Create or validate one current-user mode-0700 artifact directory."""
    _private_directory(path, root=root, authority=authority)


def validate_capacity_finding_private_directory(
    path: Path,
    *,
    root: Path,
    authority: _PrivatePathAuthority | None = None,
) -> None:
    """Validate an existing current-user mode-0700 artifact directory."""
    _validate_private_directory(path, root=root, authority=authority)


def _path_present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _private_path_present(
    path: Path,
    *,
    root: Path,
    authority: _PrivatePathAuthority,
) -> bool:
    with _private_parent_authority(
        root,
        path,
        held_root=authority,
    ) as path_authority:
        try:
            os.stat(
                path_authority.leaf_name,
                dir_fd=path_authority.parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return False
        except OSError as error:
            raise CapacityValidationError(
                f"cannot inspect private finding path {path}: {error}"
            ) from error
        return True


@dataclass(frozen=True, slots=True)
class _PrivateFileSnapshot:
    identity: tuple[int, int]
    stat_fingerprint: tuple[int, int, int]
    content: bytes


@dataclass(frozen=True, slots=True)
class CapacityFindingReplaySnapshot:
    run_files: tuple[tuple[str, _PrivateFileSnapshot], ...]
    artifact_directories: tuple[
        tuple[
            str,
            tuple[int, int],
            tuple[tuple[str, _PrivateFileSnapshot], ...],
        ],
        ...,
    ]
    evidence_files: tuple[tuple[str, _EvidenceFileSnapshot], ...]


def _read_private_file_snapshot_at(
    parent_descriptor: int,
    name: str,
    *,
    display_path: Path,
) -> _PrivateFileSnapshot:
    flags = os.O_RDONLY | os.O_NONBLOCK
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        pathname_before = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        descriptor = os.open(
            name,
            flags,
            dir_fd=parent_descriptor,
        )
    except OSError as error:
        raise CapacityValidationError(
            f"cannot open private finding file {display_path}: {error}"
        ) from error
    try:
        file_stat_before = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat_before.st_mode):
            raise CapacityValidationError(
                f"private finding path must be a regular file: {display_path}"
            )
        if file_stat_before.st_uid != os.geteuid():
            raise CapacityValidationError(
                "private finding file must be owned by the current user: "
                f"{display_path}"
            )
        if file_stat_before.st_nlink != 1:
            raise CapacityValidationError(
                "private finding file must have exactly one hard link: "
                f"{display_path}"
            )
        if stat.S_IMODE(file_stat_before.st_mode) != 0o600:
            raise CapacityValidationError(
                f"private finding file must have mode 0600: {display_path}"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        file_stat_after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    before_identity = (
        file_stat_before.st_dev,
        file_stat_before.st_ino,
        file_stat_before.st_size,
        file_stat_before.st_mtime_ns,
        file_stat_before.st_ctime_ns,
    )
    after_identity = (
        file_stat_after.st_dev,
        file_stat_after.st_ino,
        file_stat_after.st_size,
        file_stat_after.st_mtime_ns,
        file_stat_after.st_ctime_ns,
    )
    try:
        pathname_after = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except OSError as error:
        raise CapacityValidationError(
            "private finding pathname changed while it was read: "
            f"{display_path}: {error}"
        ) from error
    if (
        before_identity != after_identity
        or stat.S_ISLNK(pathname_before.st_mode)
        or stat.S_ISLNK(pathname_after.st_mode)
        or not stat.S_ISREG(pathname_before.st_mode)
        or not stat.S_ISREG(pathname_after.st_mode)
        or _private_path_identity(pathname_before)
        != _private_path_identity(file_stat_before)
        or _private_path_identity(pathname_after)
        != _private_path_identity(file_stat_after)
    ):
        raise CapacityValidationError(
            "private finding pathname or bytes changed while it was read: "
            f"{display_path}"
        )
    return _PrivateFileSnapshot(
        identity=_private_path_identity(file_stat_after),
        stat_fingerprint=(
            file_stat_after.st_size,
            file_stat_after.st_mtime_ns,
            file_stat_after.st_ctime_ns,
        ),
        content=b"".join(chunks),
    )


def _read_private_file_at(
    parent_descriptor: int,
    name: str,
    *,
    display_path: Path,
) -> bytes:
    return _read_private_file_snapshot_at(
        parent_descriptor,
        name,
        display_path=display_path,
    ).content


def _read_private_file_snapshot(
    path: Path,
    *,
    root: Path | None = None,
    authority: _PrivatePathAuthority | None = None,
) -> _PrivateFileSnapshot:
    explicit_root = path.parent if root is None else root
    with _private_parent_authority(
        explicit_root,
        path,
        held_root=authority,
    ) as path_authority:
        snapshot = _read_private_file_snapshot_at(
            path_authority.parent_descriptor,
            path_authority.leaf_name,
            display_path=path,
        )
        path_authority.revalidate()
        return snapshot


def _read_private_file(
    path: Path,
    *,
    root: Path | None = None,
    authority: _PrivatePathAuthority | None = None,
) -> bytes:
    return _read_private_file_snapshot(
        path,
        root=root,
        authority=authority,
    ).content


def _temporary_peer(path: Path) -> Path:
    nonce = os.urandom(12).hex()
    return path.with_name(f".{path.name}.{os.getpid()}.{nonce}.tmp")


_PRIVATE_TEMPORARY_NAME_RE = re.compile(
    r"^\.(?P<destination>.+)\.(?P<pid>[1-9][0-9]*)\."
    r"(?P<nonce>[0-9a-f]{24})\.tmp$"
)
_PRIVATE_FINDING_JSON_DESTINATION_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,79}\.json$"
)
_PRIVATE_FINDING_BODY_DESTINATION_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,79}\.md$"
)


def _unlink_held_private_file(
    parent_descriptor: int,
    name: str,
    descriptor: int,
    *,
    expected_links: int,
    context: str,
) -> None:
    try:
        pathname = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        held_before = os.fstat(descriptor)
    except OSError as error:
        raise CapacityValidationError(
            f"{context} changed before unlink: {error}"
        ) from error
    identity = _private_path_identity(held_before)
    if (
        stat.S_ISLNK(pathname.st_mode)
        or not stat.S_ISREG(pathname.st_mode)
        or not stat.S_ISREG(held_before.st_mode)
        or pathname.st_uid != os.geteuid()
        or held_before.st_uid != os.geteuid()
        or stat.S_IMODE(pathname.st_mode) != 0o600
        or stat.S_IMODE(held_before.st_mode) != 0o600
        or pathname.st_nlink != expected_links
        or held_before.st_nlink != expected_links
        or _private_path_identity(pathname) != identity
    ):
        raise CapacityValidationError(
            f"{context} lost its exact identity before unlink"
        )
    os.unlink(name, dir_fd=parent_descriptor)
    held_after = os.fstat(descriptor)
    if (
        _private_path_identity(held_after) != identity
        or held_after.st_nlink != expected_links - 1
    ):
        raise CapacityValidationError(
            f"{context} lost its exact identity during unlink"
        )
    try:
        os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    except OSError as error:
        raise CapacityValidationError(
            f"cannot verify {context} removal: {error}"
        ) from error
    raise CapacityValidationError(f"{context} pathname reappeared during unlink")


def _validate_held_private_file_content(
    descriptor: int,
    expected_content: bytes,
    *,
    context: str,
) -> None:
    try:
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        offset = 0
        while offset < before.st_size:
            chunk = os.pread(
                descriptor,
                min(1024 * 1024, before.st_size - offset),
                offset,
            )
            if not chunk:
                raise OSError("held private file read made no progress")
            chunks.append(chunk)
            offset += len(chunk)
        after = os.fstat(descriptor)
    except OSError as error:
        raise CapacityValidationError(
            f"cannot reauthenticate {context} bytes: {error}"
        ) from error
    if (
        not stat.S_ISREG(before.st_mode)
        or not stat.S_ISREG(after.st_mode)
        or before.st_uid != os.geteuid()
        or after.st_uid != os.geteuid()
        or stat.S_IMODE(before.st_mode) != 0o600
        or stat.S_IMODE(after.st_mode) != 0o600
        or _private_path_identity(before) != _private_path_identity(after)
        or (
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        or b"".join(chunks) != expected_content
    ):
        raise CapacityValidationError(
            f"{context} bytes or descriptor authority changed"
        )


def _recover_private_temporary_files(
    directory: Path,
    *,
    root: Path,
    authority: _PrivatePathAuthority,
    managed_destination_names: frozenset[str] = frozenset(),
    managed_destination_pattern: re.Pattern[str] | None = None,
) -> None:
    """Remove only authenticated temp peers left by an interrupted writer."""

    def recover_from_descriptor(directory_descriptor: int) -> None:
        try:
            names = sorted(os.listdir(directory_descriptor))
        except OSError as error:
            raise CapacityValidationError(
                f"cannot enumerate private temporary files in {directory}: {error}"
            ) from error
        changed = False
        read_flags = os.O_RDONLY | os.O_NONBLOCK
        if hasattr(os, "O_CLOEXEC"):
            read_flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            read_flags |= os.O_NOFOLLOW
        try:
            for name in names:
                match = _PRIVATE_TEMPORARY_NAME_RE.fullmatch(name)
                if match is None:
                    continue
                destination_name = match.group("destination")
                if destination_name not in managed_destination_names and (
                    managed_destination_pattern is None
                    or managed_destination_pattern.fullmatch(destination_name) is None
                ):
                    # A syntactically similar peer is not proof that this harness
                    # owns the file. Leave unrelated current-user data untouched.
                    continue
                try:
                    pathname = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                    if stat.S_ISLNK(pathname.st_mode) or not stat.S_ISREG(
                        pathname.st_mode
                    ):
                        raise CapacityValidationError(
                            "unsafe private temporary file requires operator "
                            f"review: {name}"
                        )
                    temporary_descriptor = os.open(
                        name,
                        read_flags,
                        dir_fd=directory_descriptor,
                    )
                    held = os.fstat(temporary_descriptor)
                except CapacityValidationError:
                    raise
                except OSError as error:
                    raise CapacityValidationError(
                        f"cannot hold private temporary file {name}: {error}"
                    ) from error
                try:
                    links_before = held.st_nlink
                    temporary_identity = _private_path_identity(held)
                    if (
                        stat.S_ISLNK(pathname.st_mode)
                        or not stat.S_ISREG(pathname.st_mode)
                        or not stat.S_ISREG(held.st_mode)
                        or pathname.st_uid != os.geteuid()
                        or held.st_uid != os.geteuid()
                        or stat.S_IMODE(pathname.st_mode) != 0o600
                        or stat.S_IMODE(held.st_mode) != 0o600
                        or links_before not in {1, 2}
                        or pathname.st_nlink != links_before
                        or _private_path_identity(pathname) != temporary_identity
                    ):
                        raise CapacityValidationError(
                            "unsafe private temporary file requires operator "
                            f"review: {name}"
                        )
                    if links_before == 2:
                        try:
                            destination_stat = os.stat(
                                destination_name,
                                dir_fd=directory_descriptor,
                                follow_symlinks=False,
                            )
                        except OSError as error:
                            raise CapacityValidationError(
                                "linked private temporary file lacks its exact "
                                f"destination {destination_name}: {error}"
                            ) from error
                        if (
                            stat.S_ISLNK(destination_stat.st_mode)
                            or not stat.S_ISREG(destination_stat.st_mode)
                            or destination_stat.st_uid != os.geteuid()
                            or stat.S_IMODE(destination_stat.st_mode) != 0o600
                            or _private_path_identity(destination_stat)
                            != temporary_identity
                        ):
                            raise CapacityValidationError(
                                "linked private temporary file does not match "
                                f"its exact destination: {name}"
                            )
                    _unlink_held_private_file(
                        directory_descriptor,
                        name,
                        temporary_descriptor,
                        expected_links=links_before,
                        context=f"private temporary recovery file {name}",
                    )
                    changed = True
                finally:
                    os.close(temporary_descriptor)
        finally:
            if changed:
                os.fsync(directory_descriptor)

    if directory.expanduser().absolute() == authority.root:
        authority.revalidate()
        descriptor = os.dup(authority.root_descriptor)
        try:
            recover_from_descriptor(descriptor)
        finally:
            os.close(descriptor)
        authority.revalidate()
        return

    if not _private_path_present(
        directory,
        root=root,
        authority=authority,
    ):
        return
    with _held_private_directory(
        directory,
        root=root,
        authority=authority,
    ) as descriptor:
        recover_from_descriptor(descriptor)


def _write_new_private_file(
    path: Path,
    content: bytes,
    *,
    root: Path | None = None,
    authority: _PrivatePathAuthority | None = None,
    expected_parent_identity: tuple[int, int] | None = None,
) -> None:
    explicit_root = path.parent if root is None else root
    temporary_name = _temporary_peer(path).name
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    with _private_parent_authority(
        explicit_root,
        path,
        held_root=authority,
    ) as path_authority:
        def validate_expected_parent() -> None:
            path_authority.revalidate()
            if expected_parent_identity is not None and _private_path_identity(
                os.fstat(path_authority.parent_descriptor)
            ) != expected_parent_identity:
                raise CapacityValidationError(
                    "private finding parent directory differs from preflight: "
                    f"{path.parent}"
                )

        validate_expected_parent()
        _recover_private_temporary_files(
            path.parent,
            root=explicit_root,
            authority=path_authority,
            managed_destination_names=frozenset({path_authority.leaf_name}),
        )
        validate_expected_parent()
        try:
            descriptor = os.open(
                temporary_name,
                flags,
                0o600,
                dir_fd=path_authority.parent_descriptor,
            )
        except OSError as error:
            raise CapacityValidationError(
                f"cannot create private finding temporary file: {error}"
            ) from error

        def temporary_stat(*, links: int) -> os.stat_result:
            try:
                pathname = os.stat(
                    temporary_name,
                    dir_fd=path_authority.parent_descriptor,
                    follow_symlinks=False,
                )
                descriptor_stat = os.fstat(descriptor)
            except OSError as error:
                raise CapacityValidationError(
                    f"private finding temporary identity changed: {error}"
                ) from error
            if (
                not stat.S_ISREG(pathname.st_mode)
                or not stat.S_ISREG(descriptor_stat.st_mode)
                or pathname.st_uid != os.geteuid()
                or descriptor_stat.st_uid != os.geteuid()
                or stat.S_IMODE(pathname.st_mode) != 0o600
                or stat.S_IMODE(descriptor_stat.st_mode) != 0o600
                or pathname.st_nlink != links
                or descriptor_stat.st_nlink != links
                or _private_path_identity(pathname)
                != _private_path_identity(descriptor_stat)
            ):
                raise CapacityValidationError(
                    "private finding temporary file lost its exact "
                    "owner/type/mode/link/descriptor identity"
                )
            return descriptor_stat

        temporary_present = True
        try:
            try:
                os.fchmod(descriptor, 0o600)
                offset = 0
                while offset < len(content):
                    written = os.write(descriptor, content[offset:])
                    if written <= 0:
                        raise OSError("private finding write made no progress")
                    offset += written
                os.fsync(descriptor)
            except OSError as error:
                raise CapacityValidationError(
                    f"cannot write private finding file {path}: {error}"
                ) from error

            _validate_held_private_file_content(
                descriptor,
                content,
                context="private create-once temporary file",
            )
            path_authority.revalidate()
            validate_expected_parent()
            held_temporary = temporary_stat(links=1)
            temporary_identity = _private_path_identity(held_temporary)
            os.link(
                temporary_name,
                path_authority.leaf_name,
                src_dir_fd=path_authority.parent_descriptor,
                dst_dir_fd=path_authority.parent_descriptor,
                follow_symlinks=False,
            )

            destination = os.stat(
                path_authority.leaf_name,
                dir_fd=path_authority.parent_descriptor,
                follow_symlinks=False,
            )
            linked_temporary = temporary_stat(links=2)
            if (
                not stat.S_ISREG(destination.st_mode)
                or destination.st_uid != os.geteuid()
                or stat.S_IMODE(destination.st_mode) != 0o600
                or destination.st_nlink != 2
                or _private_path_identity(destination) != temporary_identity
                or _private_path_identity(linked_temporary) != temporary_identity
            ):
                raise CapacityValidationError(
                    f"linked private finding destination is invalid: {path}"
                )

            _unlink_held_private_file(
                path_authority.parent_descriptor,
                temporary_name,
                descriptor,
                expected_links=2,
                context="private create-once temporary file",
            )
            temporary_present = False
            _validate_held_private_file_content(
                descriptor,
                content,
                context="published private create-once file",
            )
            destination = os.stat(
                path_authority.leaf_name,
                dir_fd=path_authority.parent_descriptor,
                follow_symlinks=False,
            )
            held_temporary = os.fstat(descriptor)
            if (
                not stat.S_ISREG(destination.st_mode)
                or destination.st_uid != os.geteuid()
                or stat.S_IMODE(destination.st_mode) != 0o600
                or destination.st_nlink != 1
                or held_temporary.st_nlink != 1
                or _private_path_identity(destination) != temporary_identity
                or _private_path_identity(held_temporary) != temporary_identity
            ):
                raise CapacityValidationError(
                    f"published private finding file identity is invalid: {path}"
                )
            path_authority.revalidate()
            os.fsync(path_authority.parent_descriptor)
            _validate_held_private_file_content(
                descriptor,
                content,
                context="durable private create-once file",
            )
            destination = os.stat(
                path_authority.leaf_name,
                dir_fd=path_authority.parent_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(destination.st_mode)
                or destination.st_uid != os.geteuid()
                or stat.S_IMODE(destination.st_mode) != 0o600
                or destination.st_nlink != 1
                or _private_path_identity(destination) != temporary_identity
            ):
                raise CapacityValidationError(
                    f"durable private finding file identity is invalid: {path}"
                )
            path_authority.revalidate()
            validate_expected_parent()
        finally:
            if temporary_present:
                try:
                    pathname = os.stat(
                        temporary_name,
                        dir_fd=path_authority.parent_descriptor,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    temporary_present = False
                else:
                    descriptor_stat = os.fstat(descriptor)
                    if stat.S_ISREG(pathname.st_mode) and _private_path_identity(
                        pathname
                    ) == _private_path_identity(descriptor_stat):
                        _unlink_held_private_file(
                            path_authority.parent_descriptor,
                            temporary_name,
                            descriptor,
                            expected_links=descriptor_stat.st_nlink,
                            context="private create-once cleanup temporary",
                        )
                        temporary_present = False
                        os.fsync(path_authority.parent_descriptor)
            os.close(descriptor)


def _ensure_create_once_file(
    path: Path,
    content: bytes,
    *,
    root: Path | None = None,
    authority: _PrivatePathAuthority | None = None,
    expected_parent_identity: tuple[int, int] | None = None,
) -> bool:
    try:
        _write_new_private_file(
            path,
            content,
            root=root,
            authority=authority,
            expected_parent_identity=expected_parent_identity,
        )
    except FileExistsError:
        existing = _read_private_file(
            path,
            root=root,
            authority=authority,
        )
        if existing != content:
            raise CapacityValidationError(
                f"immutable finding occurrence collision at {path}"
            )
        return False
    return True


def _strict_json_line(line: bytes, *, source: str) -> dict[str, Any]:
    if not line.endswith(b"\n") or line == b"\n":
        raise CapacityValidationError(
            f"{source} must contain complete non-empty JSON lines"
        )
    try:
        value = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CapacityValidationError(
            f"invalid JSON line in {source}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise CapacityValidationError(f"{source} JSON lines must be objects")
    if canonical_json_bytes(value) != line:
        raise CapacityValidationError(f"{source} must contain canonical JSON lines")
    return value


class _UnspecifiedPrivateDestination:
    pass


_UNSPECIFIED_PRIVATE_DESTINATION = _UnspecifiedPrivateDestination()


def _replace_private_file(
    path: Path,
    content: bytes,
    *,
    root: Path | None = None,
    authority: _PrivatePathAuthority | None = None,
    expected_existing: (
        _PrivateFileSnapshot | None | _UnspecifiedPrivateDestination
    ) = _UNSPECIFIED_PRIVATE_DESTINATION,
) -> None:
    explicit_root = path.parent if root is None else root
    temporary_name = _temporary_peer(path).name
    write_flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    read_flags = os.O_RDONLY | os.O_NONBLOCK
    if hasattr(os, "O_CLOEXEC"):
        write_flags |= os.O_CLOEXEC
        read_flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        write_flags |= os.O_NOFOLLOW
        read_flags |= os.O_NOFOLLOW
    with _private_parent_authority(
        explicit_root,
        path,
        held_root=authority,
    ) as path_authority:
        _recover_private_temporary_files(
            path.parent,
            root=explicit_root,
            authority=path_authority,
            managed_destination_names=frozenset({path_authority.leaf_name}),
        )

        destination_descriptor: int | None = None
        try:
            destination_pathname = os.stat(
                path_authority.leaf_name,
                dir_fd=path_authority.parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            destination_snapshot = None
        except OSError as error:
            raise CapacityValidationError(
                f"cannot inspect private finding destination {path}: {error}"
            ) from error
        else:
            if stat.S_ISLNK(destination_pathname.st_mode) or not stat.S_ISREG(
                destination_pathname.st_mode
            ):
                raise CapacityValidationError(
                    f"unsafe existing private finding destination: {path}"
                )
            try:
                destination_descriptor = os.open(
                    path_authority.leaf_name,
                    read_flags,
                    dir_fd=path_authority.parent_descriptor,
                )
                destination_before = os.fstat(destination_descriptor)
            except OSError as error:
                if destination_descriptor is not None:
                    os.close(destination_descriptor)
                raise CapacityValidationError(
                    f"cannot hold private finding destination {path}: {error}"
                ) from error
            if (
                stat.S_ISLNK(destination_pathname.st_mode)
                or not stat.S_ISREG(destination_pathname.st_mode)
                or not stat.S_ISREG(destination_before.st_mode)
                or destination_pathname.st_uid != os.geteuid()
                or destination_before.st_uid != os.geteuid()
                or destination_pathname.st_nlink != 1
                or destination_before.st_nlink != 1
                or stat.S_IMODE(destination_pathname.st_mode) != 0o600
                or stat.S_IMODE(destination_before.st_mode) != 0o600
                or _private_path_identity(destination_pathname)
                != _private_path_identity(destination_before)
            ):
                os.close(destination_descriptor)
                destination_descriptor = None
                raise CapacityValidationError(
                    f"unsafe existing private finding destination: {path}"
                )
            try:
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(destination_descriptor, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                destination_after_read = os.fstat(destination_descriptor)
                destination_pathname_after_read = os.stat(
                    path_authority.leaf_name,
                    dir_fd=path_authority.parent_descriptor,
                    follow_symlinks=False,
                )
            except OSError as error:
                os.close(destination_descriptor)
                destination_descriptor = None
                raise CapacityValidationError(
                    f"cannot snapshot private finding destination {path}: {error}"
                ) from error
            destination_snapshot = _PrivateFileSnapshot(
                identity=_private_path_identity(destination_after_read),
                stat_fingerprint=(
                    destination_after_read.st_size,
                    destination_after_read.st_mtime_ns,
                    destination_after_read.st_ctime_ns,
                ),
                content=b"".join(chunks),
            )
            if (
                _private_path_identity(destination_before)
                != destination_snapshot.identity
                or _private_path_identity(destination_pathname_after_read)
                != destination_snapshot.identity
                or (
                    destination_before.st_size,
                    destination_before.st_mtime_ns,
                    destination_before.st_ctime_ns,
                )
                != destination_snapshot.stat_fingerprint
            ):
                os.close(destination_descriptor)
                destination_descriptor = None
                raise CapacityValidationError(
                    f"private finding destination changed while held: {path}"
                )

        if isinstance(
            expected_existing,
            _UnspecifiedPrivateDestination,
        ):
            expected_destination = destination_snapshot
        else:
            expected_destination = expected_existing
            if destination_snapshot != expected_destination:
                if destination_descriptor is not None:
                    os.close(destination_descriptor)
                    destination_descriptor = None
                raise CapacityValidationError(
                    "private finding destination differs from its preflight "
                    f"snapshot: {path}"
                )

        try:
            descriptor = os.open(
                temporary_name,
                write_flags,
                0o600,
                dir_fd=path_authority.parent_descriptor,
            )
        except OSError as error:
            if destination_descriptor is not None:
                os.close(destination_descriptor)
            raise CapacityValidationError(
                f"cannot create private finding temporary file: {error}"
            ) from error

        def temporary_stat(*, links: int) -> os.stat_result:
            try:
                pathname = os.stat(
                    temporary_name,
                    dir_fd=path_authority.parent_descriptor,
                    follow_symlinks=False,
                )
                descriptor_stat = os.fstat(descriptor)
            except OSError as error:
                raise CapacityValidationError(
                    f"private finding replacement temporary changed: {error}"
                ) from error
            if (
                not stat.S_ISREG(pathname.st_mode)
                or not stat.S_ISREG(descriptor_stat.st_mode)
                or pathname.st_uid != os.geteuid()
                or descriptor_stat.st_uid != os.geteuid()
                or stat.S_IMODE(pathname.st_mode) != 0o600
                or stat.S_IMODE(descriptor_stat.st_mode) != 0o600
                or pathname.st_nlink != links
                or descriptor_stat.st_nlink != links
                or _private_path_identity(pathname)
                != _private_path_identity(descriptor_stat)
            ):
                raise CapacityValidationError(
                    "private finding replacement temporary lost its exact "
                    "owner/type/mode/link/descriptor identity"
                )
            return descriptor_stat

        def validate_destination_before_publication() -> None:
            if expected_destination is None:
                try:
                    os.stat(
                        path_authority.leaf_name,
                        dir_fd=path_authority.parent_descriptor,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    return
                except OSError as error:
                    raise CapacityValidationError(
                        "cannot revalidate absent private finding destination "
                        f"{path}: {error}"
                    ) from error
                raise CapacityValidationError(
                    "private finding destination appeared after preflight: "
                    f"{path}"
                )
            if destination_descriptor is None:
                raise CapacityValidationError(
                    f"private finding destination authority was lost: {path}"
                )
            try:
                pathname = os.stat(
                    path_authority.leaf_name,
                    dir_fd=path_authority.parent_descriptor,
                    follow_symlinks=False,
                )
                held = os.fstat(destination_descriptor)
            except OSError as error:
                raise CapacityValidationError(
                    f"private finding destination changed before publication: "
                    f"{path}: {error}"
                ) from error
            held_fingerprint = (
                held.st_size,
                held.st_mtime_ns,
                held.st_ctime_ns,
            )
            if (
                not stat.S_ISREG(pathname.st_mode)
                or not stat.S_ISREG(held.st_mode)
                or pathname.st_uid != os.geteuid()
                or held.st_uid != os.geteuid()
                or pathname.st_nlink != 1
                or held.st_nlink != 1
                or stat.S_IMODE(pathname.st_mode) != 0o600
                or stat.S_IMODE(held.st_mode) != 0o600
                or _private_path_identity(pathname)
                != expected_destination.identity
                or _private_path_identity(held)
                != expected_destination.identity
                or held_fingerprint != expected_destination.stat_fingerprint
            ):
                raise CapacityValidationError(
                    "private finding destination identity changed before "
                    f"publication: {path}"
                )

        temporary_present = True
        try:
            try:
                os.fchmod(descriptor, 0o600)
                offset = 0
                while offset < len(content):
                    written = os.write(descriptor, content[offset:])
                    if written <= 0:
                        raise OSError("private finding write made no progress")
                    offset += written
                os.fsync(descriptor)
            except OSError as error:
                raise CapacityValidationError(
                    f"cannot write private finding file {path}: {error}"
                ) from error

            _validate_held_private_file_content(
                descriptor,
                content,
                context="private replacement temporary file",
            )
            path_authority.revalidate()
            held_temporary = temporary_stat(links=1)
            temporary_identity = _private_path_identity(held_temporary)
            validate_destination_before_publication()
            if expected_destination is None:
                os.link(
                    temporary_name,
                    path_authority.leaf_name,
                    src_dir_fd=path_authority.parent_descriptor,
                    dst_dir_fd=path_authority.parent_descriptor,
                    follow_symlinks=False,
                )
                linked_temporary = temporary_stat(links=2)
                destination = os.stat(
                    path_authority.leaf_name,
                    dir_fd=path_authority.parent_descriptor,
                    follow_symlinks=False,
                )
                if (
                    _private_path_identity(linked_temporary)
                    != temporary_identity
                    or _private_path_identity(destination)
                    != temporary_identity
                ):
                    raise CapacityValidationError(
                        f"new private finding destination is invalid: {path}"
                    )
                _unlink_held_private_file(
                    path_authority.parent_descriptor,
                    temporary_name,
                    descriptor,
                    expected_links=2,
                    context="private replacement temporary file",
                )
                temporary_present = False
            else:
                _renameat2(
                    path_authority.parent_descriptor,
                    temporary_name,
                    path_authority.leaf_name,
                    flags=_RENAME_EXCHANGE,
                )
                temporary_present = False
                assert destination_descriptor is not None
                exchanged_destination = os.stat(
                    temporary_name,
                    dir_fd=path_authority.parent_descriptor,
                    follow_symlinks=False,
                )
                replaced_destination = os.fstat(destination_descriptor)
                replacement_mismatch = (
                    _private_path_identity(exchanged_destination)
                    != expected_destination.identity
                    or _private_path_identity(replaced_destination)
                    != expected_destination.identity
                    or not stat.S_ISREG(replaced_destination.st_mode)
                    or replaced_destination.st_uid != os.geteuid()
                    or stat.S_IMODE(replaced_destination.st_mode) != 0o600
                    or replaced_destination.st_nlink != 1
                    or replaced_destination.st_size
                    != expected_destination.stat_fingerprint[0]
                    or replaced_destination.st_mtime_ns
                    != expected_destination.stat_fingerprint[1]
                )
                content_mismatch: CapacityValidationError | None = None
                if not replacement_mismatch:
                    try:
                        _validate_held_private_file_content(
                            destination_descriptor,
                            expected_destination.content,
                            context="exchanged private finding destination",
                        )
                    except CapacityValidationError as error:
                        content_mismatch = error
                if replacement_mismatch or content_mismatch is not None:
                    _renameat2(
                        path_authority.parent_descriptor,
                        temporary_name,
                        path_authority.leaf_name,
                        flags=_RENAME_EXCHANGE,
                    )
                    temporary_present = True
                    raise CapacityValidationError(
                        "private finding destination identity or bytes changed "
                        "during "
                        f"publication: {path}"
                    ) from content_mismatch
                _unlink_held_private_file(
                    path_authority.parent_descriptor,
                    temporary_name,
                    destination_descriptor,
                    expected_links=1,
                    context="exchanged private finding destination",
                )
            _validate_held_private_file_content(
                descriptor,
                content,
                context="published private replacement file",
            )
            destination = os.stat(
                path_authority.leaf_name,
                dir_fd=path_authority.parent_descriptor,
                follow_symlinks=False,
            )
            if (
                _private_path_identity(destination) != temporary_identity
                or not stat.S_ISREG(destination.st_mode)
                or destination.st_uid != os.geteuid()
                or destination.st_nlink != 1
                or stat.S_IMODE(destination.st_mode) != 0o600
            ):
                raise CapacityValidationError(
                    f"published private finding file identity is invalid: {path}"
                )
            path_authority.revalidate()
            os.fsync(path_authority.parent_descriptor)
            _validate_held_private_file_content(
                descriptor,
                content,
                context="durable private replacement file",
            )
            destination = os.stat(
                path_authority.leaf_name,
                dir_fd=path_authority.parent_descriptor,
                follow_symlinks=False,
            )
            held_temporary = os.fstat(descriptor)
            if (
                _private_path_identity(destination) != temporary_identity
                or _private_path_identity(held_temporary) != temporary_identity
                or not stat.S_ISREG(destination.st_mode)
                or not stat.S_ISREG(held_temporary.st_mode)
                or destination.st_uid != os.geteuid()
                or held_temporary.st_uid != os.geteuid()
                or destination.st_nlink != 1
                or held_temporary.st_nlink != 1
                or stat.S_IMODE(destination.st_mode) != 0o600
                or stat.S_IMODE(held_temporary.st_mode) != 0o600
            ):
                raise CapacityValidationError(
                    f"durable private finding file identity is invalid: {path}"
                )
            path_authority.revalidate()
        except OSError as error:
            raise CapacityValidationError(
                f"cannot publish finding ledger {path}: {error}"
            ) from error
        finally:
            if temporary_present:
                try:
                    pathname = os.stat(
                        temporary_name,
                        dir_fd=path_authority.parent_descriptor,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    temporary_present = False
                else:
                    descriptor_stat = os.fstat(descriptor)
                    if stat.S_ISREG(pathname.st_mode) and _private_path_identity(
                        pathname
                    ) == _private_path_identity(descriptor_stat):
                        _unlink_held_private_file(
                            path_authority.parent_descriptor,
                            temporary_name,
                            descriptor,
                            expected_links=descriptor_stat.st_nlink,
                            context="private replacement cleanup temporary",
                        )
                        temporary_present = False
                        os.fsync(path_authority.parent_descriptor)
            os.close(descriptor)
            if destination_descriptor is not None:
                os.close(destination_descriptor)


def replace_capacity_finding_private_file(
    path: Path,
    content: bytes,
    *,
    root: Path,
    authority: _PrivatePathAuthority | None = None,
    expected_existing: (
        _PrivateFileSnapshot | None | _UnspecifiedPrivateDestination
    ) = _UNSPECIFIED_PRIVATE_DESTINATION,
) -> None:
    """Atomically replace one owner-only file and fsync its parent."""
    _replace_private_file(
        path,
        content,
        root=root,
        authority=authority,
        expected_existing=expected_existing,
    )


def _canonical_jsonl_records(
    content: bytes,
    *,
    source: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    offset = 0
    while offset < len(content):
        newline = content.find(b"\n", offset)
        if newline < 0:
            raise CapacityValidationError(f"{source} ends with an incomplete JSON line")
        raw_line = content[offset : newline + 1]
        records.append(_strict_json_line(raw_line, source=source))
        offset = newline + 1
    return records


def read_capacity_finding_canonical_jsonl(
    path: Path,
    *,
    root: Path,
    authority: _PrivatePathAuthority | None = None,
) -> tuple[dict[str, Any], ...]:
    """Read and validate an owner-only canonical JSONL artifact."""
    return tuple(
        _canonical_jsonl_records(
            _read_private_file(
                path,
                root=root,
                authority=authority,
            ),
            source=str(path),
        )
    )


def read_capacity_finding_manifest(
    path: Path,
    *,
    root: Path,
    authority: _PrivatePathAuthority | None = None,
) -> dict[str, Any]:
    """Read an owner-only run manifest with duplicate-key rejection."""
    return _strict_json_object(
        _read_private_file(
            path,
            root=root,
            authority=authority,
        ),
        source=str(path),
    )


def _records_by_unique_finding_id(
    records: Sequence[Mapping[str, Any]],
    *,
    source: str,
) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for index, raw_record in enumerate(records):
        record = dict(raw_record)
        finding_id = record.get("finding_id")
        if not isinstance(finding_id, str) or not finding_id:
            raise CapacityValidationError(
                f"{source} record {index} requires a non-empty finding_id"
            )
        if finding_id in by_id:
            raise CapacityValidationError(
                f"{source} contains duplicate finding_id {finding_id}"
            )
        by_id[finding_id] = record
    return by_id


def _validate_ingest_lock_identity(
    authority: _PrivatePathAuthority,
    descriptor: int,
) -> None:
    try:
        pathname = os.stat(
            authority.leaf_name,
            dir_fd=authority.parent_descriptor,
            follow_symlinks=False,
        )
        lock_stat = os.fstat(descriptor)
    except OSError as error:
        raise CapacityValidationError(
            f"finding ingest lock identity changed: {error}"
        ) from error
    if (
        stat.S_ISLNK(pathname.st_mode)
        or not stat.S_ISREG(pathname.st_mode)
        or not stat.S_ISREG(lock_stat.st_mode)
        or pathname.st_uid != os.geteuid()
        or lock_stat.st_uid != os.geteuid()
        or pathname.st_nlink != 1
        or lock_stat.st_nlink != 1
        or stat.S_IMODE(pathname.st_mode) != 0o600
        or stat.S_IMODE(lock_stat.st_mode) != 0o600
        or _private_path_identity(pathname) != _private_path_identity(lock_stat)
    ):
        raise CapacityValidationError(
            "finding ingest lock must retain one current-user, single-link, "
            "mode-0600 regular-file identity"
        )


def _open_ingest_lock(
    authority: _PrivatePathAuthority,
    *,
    create: bool = True,
) -> int:
    flags = os.O_RDWR | os.O_NONBLOCK
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    created = False
    if create:
        try:
            descriptor = os.open(
                authority.leaf_name,
                flags | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=authority.parent_descriptor,
            )
            created = True
        except FileExistsError:
            try:
                descriptor = os.open(
                    authority.leaf_name,
                    flags,
                    dir_fd=authority.parent_descriptor,
                )
            except OSError as error:
                raise CapacityValidationError(
                    f"cannot open finding ingest lock: {error}"
                ) from error
        except OSError as error:
            raise CapacityValidationError(
                f"cannot open finding ingest lock: {error}"
            ) from error
    else:
        try:
            descriptor = os.open(
                authority.leaf_name,
                flags,
                dir_fd=authority.parent_descriptor,
            )
        except OSError as error:
            raise CapacityValidationError(
                f"cannot open existing finding ingest lock: {error}"
            ) from error
    try:
        if created:
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
            os.fsync(authority.parent_descriptor)
        _validate_ingest_lock_identity(authority, descriptor)
        authority.revalidate()
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


_CAPACITY_FINDING_V2_MARKER_NAMES = (
    CAPACITY_FINDING_INDEX_NAME,
    CAPACITY_FINDING_SOURCE_DIRECTORY,
    CAPACITY_FINDING_INDEX_DIRECTORY,
    CAPACITY_FINDING_BODY_DIRECTORY,
)


@dataclass(frozen=True, slots=True)
class CapacityFindingRunSelection:
    """One root-locked decision between legacy and finding-v2 run handling."""

    is_capacity_v2: bool
    authority: _PrivatePathAuthority | None


def _private_capacity_v2_state_exists(
    authority: _PrivatePathAuthority,
) -> bool:
    authority.revalidate()
    found = False
    for name in _CAPACITY_FINDING_V2_MARKER_NAMES:
        try:
            os.stat(
                name,
                dir_fd=authority.root_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            continue
        except OSError as error:
            raise CapacityValidationError(
                f"cannot inspect capacity-v2 run marker {name}: {error}"
            ) from error
        found = True
        break
    authority.revalidate()
    return found


def _pathname_capacity_v2_state_exists(run_dir: Path) -> bool:
    return any(
        _path_present(run_dir / name) for name in _CAPACITY_FINDING_V2_MARKER_NAMES
    )


@contextmanager
def capacity_finding_run_selection(
    run_dir: Path,
) -> Iterator[CapacityFindingRunSelection]:
    """Hold one stable root decision across all selected run I/O."""
    candidate = run_dir.expanduser()
    try:
        root_stat = candidate.lstat()
    except FileNotFoundError:
        yield CapacityFindingRunSelection(
            is_capacity_v2=False,
            authority=None,
        )
        return
    except OSError as error:
        raise CapacityValidationError(
            f"cannot inspect issue-discovery run root: {error}"
        ) from error

    private_root = (
        stat.S_ISDIR(root_stat.st_mode)
        and not stat.S_ISLNK(root_stat.st_mode)
        and root_stat.st_uid == os.geteuid()
        and stat.S_IMODE(root_stat.st_mode) == 0o700
    )
    if not private_root:
        if _pathname_capacity_v2_state_exists(candidate):
            raise CapacityValidationError(
                "capacity-v2 state requires a current-user mode-0700 "
                "non-symlink run root"
            )
        yield CapacityFindingRunSelection(
            is_capacity_v2=False,
            authority=None,
        )
        return

    root = _validate_evidence_root(candidate)
    lock_path = root / CAPACITY_FINDING_INGEST_LOCK_NAME
    with _private_parent_authority(root, lock_path) as authority:
        lock_descriptor: int | None = None
        try:
            fcntl.flock(authority.root_descriptor, fcntl.LOCK_EX)
            authority.revalidate()
            is_capacity_v2 = _private_capacity_v2_state_exists(authority)
            if is_capacity_v2:
                lock_descriptor = _open_ingest_lock(
                    authority,
                    create=False,
                )
                fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
                _validate_ingest_lock_identity(authority, lock_descriptor)
            try:
                yield CapacityFindingRunSelection(
                    is_capacity_v2=is_capacity_v2,
                    authority=authority,
                )
            finally:
                if lock_descriptor is not None:
                    _validate_ingest_lock_identity(
                        authority,
                        lock_descriptor,
                    )
                authority.revalidate()
        finally:
            if lock_descriptor is not None:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
                os.close(lock_descriptor)
            fcntl.flock(authority.root_descriptor, fcntl.LOCK_UN)


@contextmanager
def capacity_finding_ingest_lock(
    run_dir: Path,
) -> Iterator[_PrivatePathAuthority]:
    """Hold the validated owner-only lock shared by finding artifact writers."""
    root = _validate_evidence_root(run_dir)
    lock_path = root / CAPACITY_FINDING_INGEST_LOCK_NAME
    with _private_parent_authority(root, lock_path) as authority:
        lock_descriptor: int | None = None
        try:
            # The held run-directory inode is the non-replaceable coordination
            # point for compliant writers; the persistent lock file remains an
            # independently validated audit artifact.
            fcntl.flock(authority.root_descriptor, fcntl.LOCK_EX)
            lock_descriptor = _open_ingest_lock(authority)
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            _validate_ingest_lock_identity(authority, lock_descriptor)
            authority.revalidate()
            try:
                yield authority
            finally:
                _validate_ingest_lock_identity(authority, lock_descriptor)
                authority.revalidate()
        finally:
            if lock_descriptor is not None:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
                os.close(lock_descriptor)
            fcntl.flock(authority.root_descriptor, fcntl.LOCK_UN)


def read_capacity_finding_private_file(
    path: Path,
    *,
    root: Path,
    authority: _PrivatePathAuthority | None = None,
) -> bytes:
    """Read one owner-only artifact through an O_NOFOLLOW descriptor."""
    return _read_private_file(
        path,
        root=root,
        authority=authority,
    )


def snapshot_capacity_finding_private_file(
    path: Path,
    *,
    root: Path,
    authority: _PrivatePathAuthority | None = None,
) -> _PrivateFileSnapshot:
    """Capture exact bytes and inode authority for a later bound replacement."""
    return _read_private_file_snapshot(
        path,
        root=root,
        authority=authority,
    )


def recover_capacity_finding_private_file_publication(
    path: Path,
    *,
    root: Path,
    authority: _PrivatePathAuthority,
) -> None:
    """Recover only the exact interrupted temporary peer for one output."""
    _recover_private_temporary_files(
        path.parent,
        root=root,
        authority=authority,
        managed_destination_names=frozenset({path.name}),
    )
    authority.revalidate()


def snapshot_capacity_finding_replay_authority(
    finding_ids: Iterable[str],
    evidence_paths: Iterable[str],
    *,
    evidence_root: Path,
    authority: _PrivatePathAuthority,
) -> CapacityFindingReplaySnapshot:
    """Bind every immutable input used to derive a v2 issue packet."""
    expected_ids = frozenset(finding_ids)
    if not expected_ids or any(
        not isinstance(finding_id, str)
        or _ARTIFACT_ID_RE.fullmatch(finding_id) is None
        for finding_id in expected_ids
    ):
        raise CapacityValidationError(
            "capacity-finding replay snapshot requires valid finding IDs"
        )
    root = authority.root
    if evidence_root.expanduser().absolute() != root:
        raise CapacityValidationError(
            "replay snapshot evidence_root differs from held run authority"
        )

    run_files = tuple(
        (
            name,
            _read_private_file_snapshot(
                root / name,
                root=root,
                authority=authority,
            ),
        )
        for name in (
            CAPACITY_FINDING_MANIFEST_NAME,
            CAPACITY_FINDING_SOURCE_NAME,
            CAPACITY_FINDING_INDEX_NAME,
            CAPACITY_FINDING_LIFECYCLE_NAME,
        )
    )

    artifact_directories: list[
        tuple[
            str,
            tuple[int, int],
            tuple[tuple[str, _PrivateFileSnapshot], ...],
        ]
    ] = []
    for directory_name, suffix in (
        (CAPACITY_FINDING_SOURCE_DIRECTORY, ".json"),
        (CAPACITY_FINDING_INDEX_DIRECTORY, ".json"),
        (CAPACITY_FINDING_BODY_DIRECTORY, ".md"),
    ):
        artifacts = _preflight_artifact_directory(
            root / directory_name,
            suffix=suffix,
            root=root,
            authority=authority,
        )
        actual_ids = frozenset(artifacts.paths)
        if (
            not artifacts.exists
            or artifacts.identity is None
            or actual_ids != expected_ids
        ):
            missing = sorted(expected_ids - actual_ids)
            unexpected = sorted(actual_ids - expected_ids)
            raise CapacityValidationError(
                "capacity-finding replay snapshot inventory mismatch in "
                f"{directory_name} (missing={missing}, "
                f"unexpected={unexpected})"
            )
        artifact_directories.append(
            (
                directory_name,
                artifacts.identity,
                tuple(sorted(artifacts.snapshots.items())),
            )
        )

    normalized_evidence: dict[str, PurePosixPath] = {}
    for index, raw_path in enumerate(evidence_paths):
        path = _normalized_evidence_path(
            raw_path,
            field_name=f"replay evidence_paths[{index}]",
        )
        normalized_evidence[path.as_posix()] = path
    if not normalized_evidence:
        raise CapacityValidationError(
            "capacity-finding replay snapshot requires immutable evidence"
        )
    evidence_files = tuple(
        (
            path_text,
            _read_evidence_file_snapshot(root, relative_path),
        )
        for path_text, relative_path in sorted(normalized_evidence.items())
    )
    authority.revalidate()
    return CapacityFindingReplaySnapshot(
        run_files=run_files,
        artifact_directories=tuple(artifact_directories),
        evidence_files=evidence_files,
    )


def validate_capacity_finding_replay_snapshot(
    expected: CapacityFindingReplaySnapshot,
    finding_ids: Iterable[str],
    evidence_paths: Iterable[str],
    *,
    evidence_root: Path,
    authority: _PrivatePathAuthority,
) -> None:
    """Reject any replay input drift before issue-packet publication."""
    current = snapshot_capacity_finding_replay_authority(
        finding_ids,
        evidence_paths,
        evidence_root=evidence_root,
        authority=authority,
    )
    if current != expected:
        raise CapacityValidationError(
            "capacity-finding replay authority changed before output"
        )


def validate_capacity_finding_artifact_inventory(
    finding_ids: Iterable[str],
    *,
    evidence_root: Path,
    authority: _PrivatePathAuthority,
) -> None:
    """Validate the exact closed create-once artifact set for packet replay."""
    expected_ids = frozenset(finding_ids)
    if not expected_ids or any(
        not isinstance(finding_id, str)
        or _ARTIFACT_ID_RE.fullmatch(finding_id) is None
        for finding_id in expected_ids
    ):
        raise CapacityValidationError(
            "capacity-finding artifact inventory requires valid finding IDs"
        )
    root = authority.root
    if evidence_root.expanduser().absolute() != root:
        raise CapacityValidationError(
            "artifact inventory evidence_root differs from held run authority"
        )
    for directory_name, suffix in (
        (CAPACITY_FINDING_SOURCE_DIRECTORY, ".json"),
        (CAPACITY_FINDING_INDEX_DIRECTORY, ".json"),
        (CAPACITY_FINDING_BODY_DIRECTORY, ".md"),
    ):
        directory = root / directory_name
        artifacts = _preflight_artifact_directory(
            directory,
            suffix=suffix,
            root=root,
            authority=authority,
        )
        actual_ids = frozenset(artifacts.paths)
        if not artifacts.exists or actual_ids != expected_ids:
            missing = sorted(expected_ids - actual_ids)
            unexpected = sorted(actual_ids - expected_ids)
            raise CapacityValidationError(
                f"capacity-finding artifact inventory mismatch in "
                f"{directory_name} (missing={missing}, "
                f"unexpected={unexpected})"
            )
    authority.revalidate()


def load_capacity_finding_index_artifacts(
    source_path: Path,
    index_path: Path,
    body_path: Path,
    *,
    repo_root: Path,
    evidence_root: Path,
    authority: _PrivatePathAuthority | None = None,
) -> dict[str, Any]:
    """Verify create-once source/index/body files for packet replay."""
    if authority is None:
        root = _validate_evidence_root(evidence_root)
    else:
        authority.revalidate()
        root = authority.root
        if evidence_root.expanduser().absolute() != root:
            raise CapacityValidationError(
                "packet replay evidence_root differs from held run authority"
            )
    for directory in (source_path.parent, index_path.parent, body_path.parent):
        _validate_private_directory(
            directory,
            root=root,
            authority=authority,
        )
        if directory.expanduser().absolute().parent != root:
            raise CapacityValidationError(
                "capacity-finding artifact directories must share evidence_root"
            )
    source_bytes = _read_private_file(
        source_path,
        root=root,
        authority=authority,
    )
    index_bytes = _read_private_file(
        index_path,
        root=root,
        authority=authority,
    )
    body_bytes = _read_private_file(
        body_path,
        root=root,
        authority=authority,
    )
    source = _strict_json_object(source_bytes, source=str(source_path))
    index = _strict_json_object(index_bytes, source=str(index_path))
    if canonical_json_bytes(source) != source_bytes:
        raise CapacityValidationError("capacity-finding source file is not canonical")
    if canonical_json_bytes(index) != index_bytes:
        raise CapacityValidationError("capacity-finding index file is not canonical")
    expected = _validate_replayed_occurrence(
        source,
        index,
        repo_root=repo_root,
        evidence_root=root,
    )
    finding_id = expected["finding_id"]
    if (
        source_path.parent.name != CAPACITY_FINDING_SOURCE_DIRECTORY
        or source_path.name != f"{finding_id}.json"
        or index_path.parent.name != CAPACITY_FINDING_INDEX_DIRECTORY
        or index_path.name != f"{finding_id}.json"
        or body_path.parent.name != CAPACITY_FINDING_BODY_DIRECTORY
        or body_path.name != f"{finding_id}.md"
    ):
        raise CapacityValidationError(
            "capacity-finding artifact paths must be keyed by finding_id"
        )
    body = expected["occurrence_body"]
    assert isinstance(body, str)
    if body_bytes != body.encode("utf-8"):
        raise CapacityValidationError(
            "capacity-finding body bytes do not match the exact index"
        )
    if hashlib.sha256(body_bytes).hexdigest() != expected["occurrence_body_sha256"]:
        raise CapacityValidationError(
            "capacity-finding body digest does not match the exact index"
        )
    return expected


def _validate_replayed_occurrence(
    source: Mapping[str, Any],
    index: Mapping[str, Any],
    *,
    repo_root: Path,
    evidence_root: Path,
) -> dict[str, Any]:
    expected = validate_capacity_finding_index_record(
        index,
        source,
        repo_root=repo_root,
    )
    public_root = _validate_git_root(
        repo_root,
        expected_repository="arkhai-io/simple-compute-market",
    )
    contract_ref = _validate_commit(
        public_root,
        source.get("scm_contract_ref"),
        field_name="capacity finding SCM contract ref",
    )
    _validate_evidence(
        source.get("evidence"),
        evidence_root,
        redaction_rules=_load_pinned_redaction_rules(
            public_root,
            contract_ref,
        ),
    )
    return expected


def _manifest_occurrence(index_record: Mapping[str, Any]) -> dict[str, Any]:
    authority = index_record["observed_authority"]
    assert isinstance(authority, Mapping)
    return {
        "finding_id": index_record["finding_id"],
        "finding_sha256": index_record["finding_sha256"],
        "fingerprint": index_record["fingerprint"],
        "destination_repo": index_record["destination_repo"],
        "classification": index_record["classification"],
        "scenario_id": index_record["scenario_id"],
        "scenario_sha256": index_record["scenario_sha256"],
        "profile_stage_id": index_record["profile_stage_id"],
        "profile_stage_sha256": index_record["profile_stage_sha256"],
        "result_id": index_record["result_id"],
        "result_sha256": index_record["result_sha256"],
        "stage_id": authority["stage_id"],
        "observed_at": authority["observed_at"],
    }


def _common_manifest_authority(
    index_record: Mapping[str, Any],
) -> dict[str, Any]:
    authority = index_record["observed_authority"]
    assert isinstance(authority, Mapping)
    return {
        "run_id": authority["run_id"],
        "working_branch": authority["working_branch"],
        "working_ref": authority["working_ref"],
        "upstream_branch": authority["upstream_branch"],
        "upstream_ref": authority["upstream_ref"],
        "inbound_merge_ref": authority["inbound_merge_ref"],
        "reconciliation_epoch_id": authority["reconciliation_epoch_id"],
    }


def _strict_json_object(content: bytes, *, source: str) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite number {value!r} is not valid")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate object key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise CapacityValidationError(
            f"invalid JSON object at {source}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise CapacityValidationError(f"{source} must be a JSON object")
    return value


_MANIFEST_OCCURRENCE_FIELDS = frozenset(
    {
        "finding_id",
        "finding_sha256",
        "fingerprint",
        "destination_repo",
        "classification",
        "scenario_id",
        "scenario_sha256",
        "profile_stage_id",
        "profile_stage_sha256",
        "result_id",
        "result_sha256",
        "stage_id",
        "observed_at",
    }
)
_COMMON_MANIFEST_AUTHORITY_FIELDS = frozenset(
    {
        "run_id",
        "working_branch",
        "working_ref",
        "upstream_branch",
        "upstream_ref",
        "inbound_merge_ref",
        "reconciliation_epoch_id",
    }
)


@dataclass(frozen=True, slots=True)
class _ManifestPreflight:
    existing_snapshot: _PrivateFileSnapshot | None
    existing_occurrences: dict[str, dict[str, Any]]
    occurrences: dict[str, dict[str, Any]]
    desired_bytes: bytes | None


def validate_capacity_finding_manifest(
    manifest: Mapping[str, Any],
    index_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate the exact closed manifest projection for persisted indexes."""
    value = dict(manifest)
    indexes = _records_by_unique_finding_id(
        index_records,
        source="capacity-finding manifest indexes",
    )
    if not indexes:
        raise CapacityValidationError(
            "capacity-finding manifest validation requires at least one index"
        )
    first_index = indexes[sorted(indexes)[0]]
    common_authority = _common_manifest_authority(first_index)
    if value.get("run_id") != common_authority["run_id"]:
        raise CapacityValidationError(
            "manifest run_id conflicts with capacity finding authority"
        )
    direct_authority_aliases = {
        "working_branch": "working_branch",
        "working_ref": "working_ref",
        "observed_ref": "working_ref",
        "upstream_branch": "upstream_branch",
        "upstream_ref": "upstream_ref",
        "inbound_merge_ref": "inbound_merge_ref",
        "reconciliation_epoch_id": "reconciliation_epoch_id",
    }
    for manifest_field, authority_field in direct_authority_aliases.items():
        if (
            manifest_field in value
            and value[manifest_field] != common_authority[authority_field]
        ):
            raise CapacityValidationError(
                f"manifest {manifest_field} conflicts with finding authority"
            )
    declared_common = value.get("capacity_finding_authority")
    if (
        not isinstance(declared_common, Mapping)
        or set(declared_common) != _COMMON_MANIFEST_AUTHORITY_FIELDS
        or dict(declared_common) != common_authority
    ):
        raise CapacityValidationError(
            "manifest capacity_finding_authority conflicts across occurrences "
            "or is not closed"
        )
    for finding_id, index in indexes.items():
        if _common_manifest_authority(index) != common_authority:
            raise CapacityValidationError(
                f"capacity finding {finding_id} has mixed run/branch/ref authority"
            )
    raw_occurrences = value.get("capacity_findings")
    if not isinstance(raw_occurrences, list):
        raise CapacityValidationError(
            "manifest capacity_findings must be an array of objects"
        )
    occurrences: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_occurrence in raw_occurrences:
        if (
            not isinstance(raw_occurrence, Mapping)
            or set(raw_occurrence) != _MANIFEST_OCCURRENCE_FIELDS
        ):
            raise CapacityValidationError(
                "manifest capacity_findings entries must be exact closed "
                "occurrence projections"
            )
        occurrence = dict(raw_occurrence)
        finding_id = occurrence.get("finding_id")
        if not isinstance(finding_id, str) or finding_id in seen:
            raise CapacityValidationError(
                "manifest capacity_findings has missing or duplicate IDs"
            )
        seen.add(finding_id)
        occurrences.append(occurrence)
    expected_occurrences = [
        _manifest_occurrence(indexes[finding_id]) for finding_id in sorted(indexes)
    ]
    if occurrences != expected_occurrences:
        raise CapacityValidationError(
            "manifest capacity_findings does not exactly project persisted indexes"
        )
    return value


def _preflight_capacity_manifest(
    path: Path,
    index_record: Mapping[str, Any],
    *,
    root: Path,
    authority: _PrivatePathAuthority,
) -> _ManifestPreflight:
    common_authority = _common_manifest_authority(index_record)
    exists = _private_path_present(
        path,
        root=root,
        authority=authority,
    )
    if exists:
        existing_snapshot = _read_private_file_snapshot(
            path,
            root=root,
            authority=authority,
        )
        manifest = _strict_json_object(
            existing_snapshot.content,
            source=str(path),
        )
    else:
        existing_snapshot = None
        manifest = {
            "schema_version": 2,
            "run_id": common_authority["run_id"],
        }

    if manifest.get("run_id") != common_authority["run_id"]:
        raise CapacityValidationError(
            "manifest run_id conflicts with capacity finding authority"
        )
    direct_authority_aliases = {
        "working_branch": "working_branch",
        "working_ref": "working_ref",
        "observed_ref": "working_ref",
        "upstream_branch": "upstream_branch",
        "upstream_ref": "upstream_ref",
        "inbound_merge_ref": "inbound_merge_ref",
        "reconciliation_epoch_id": "reconciliation_epoch_id",
    }
    for manifest_field, authority_field in direct_authority_aliases.items():
        if (
            manifest_field in manifest
            and manifest[manifest_field] != common_authority[authority_field]
        ):
            raise CapacityValidationError(
                f"manifest {manifest_field} conflicts with finding authority"
            )

    changed = (
        not exists
        or existing_snapshot is None
        or canonical_json_bytes(manifest) != existing_snapshot.content
    )
    if "capacity_finding_authority" not in manifest:
        manifest["capacity_finding_authority"] = common_authority
        changed = True
    else:
        existing_common = manifest["capacity_finding_authority"]
        if (
            not isinstance(existing_common, Mapping)
            or set(existing_common) != _COMMON_MANIFEST_AUTHORITY_FIELDS
            or dict(existing_common) != common_authority
        ):
            raise CapacityValidationError(
                "manifest capacity_finding_authority conflicts across occurrences "
                "or is not closed"
            )

    if "capacity_findings" not in manifest:
        raw_occurrences = []
        changed = True
    else:
        raw_occurrences = manifest["capacity_findings"]
    if not isinstance(raw_occurrences, list):
        raise CapacityValidationError(
            "manifest capacity_findings must be an array of objects"
        )
    occurrences_by_id: dict[str, dict[str, Any]] = {}
    for item in raw_occurrences:
        if not isinstance(item, Mapping) or set(item) != _MANIFEST_OCCURRENCE_FIELDS:
            raise CapacityValidationError(
                "manifest capacity_findings entries must be exact closed "
                "occurrence projections"
            )
        occurrence = dict(item)
        finding_id = occurrence.get("finding_id")
        if not isinstance(finding_id, str) or finding_id in occurrences_by_id:
            raise CapacityValidationError(
                "manifest capacity_findings has missing or duplicate IDs"
            )
        occurrences_by_id[finding_id] = occurrence
    existing_ids = [str(occurrence["finding_id"]) for occurrence in raw_occurrences]
    if existing_ids != sorted(existing_ids):
        raise CapacityValidationError(
            "manifest capacity_findings must be sorted by finding_id"
        )
    existing_occurrences = {
        item_id: dict(item) for item_id, item in occurrences_by_id.items()
    }

    occurrence = _manifest_occurrence(index_record)
    finding_id = str(occurrence["finding_id"])
    existing = occurrences_by_id.get(finding_id)
    if existing is not None and existing != occurrence:
        raise CapacityValidationError(
            f"manifest immutable occurrence collision for {finding_id}"
        )
    if existing is None:
        occurrences_by_id[finding_id] = occurrence
        changed = True
    desired_occurrences = [
        occurrences_by_id[item_id] for item_id in sorted(occurrences_by_id)
    ]
    if raw_occurrences != desired_occurrences:
        manifest["capacity_findings"] = desired_occurrences
        changed = True
    elif "capacity_findings" not in manifest:
        manifest["capacity_findings"] = desired_occurrences
        changed = True
    return _ManifestPreflight(
        existing_snapshot=existing_snapshot,
        existing_occurrences=existing_occurrences,
        occurrences=occurrences_by_id,
        desired_bytes=canonical_json_bytes(manifest) if changed else None,
    )


def _detected_lifecycle_event(
    index_record: Mapping[str, Any],
) -> dict[str, Any]:
    authority = index_record["observed_authority"]
    assert isinstance(authority, Mapping)
    return {
        "schema_version": 2,
        "candidate_kind": "capacity-finding-v2",
        "finding_id": index_record["finding_id"],
        "finding_sha256": index_record["finding_sha256"],
        "fingerprint": index_record["fingerprint"],
        "state": "detected",
        "recorded_at": authority["observed_at"],
        "destination_repo": index_record["destination_repo"],
        "classification": index_record["classification"],
        "frontier": index_record["frontier"],
        "scenario_id": index_record["scenario_id"],
        "scenario_sha256": index_record["scenario_sha256"],
        "profile_stage_id": index_record["profile_stage_id"],
        "profile_stage_sha256": index_record["profile_stage_sha256"],
        "result_id": index_record["result_id"],
        "result_sha256": index_record["result_sha256"],
        "scm_contract_ref": index_record["scm_contract_ref"],
        "observed_authority": authority,
        "filing_readiness": index_record["filing_readiness"],
    }


@dataclass(frozen=True, slots=True)
class _ArtifactDirectory:
    exists: bool
    identity: tuple[int, int] | None
    paths: dict[str, Path]
    contents: dict[str, bytes]
    snapshots: dict[str, _PrivateFileSnapshot]


def _preflight_artifact_directory(
    path: Path,
    *,
    suffix: str,
    root: Path,
    authority: _PrivatePathAuthority,
) -> _ArtifactDirectory:
    if not _private_path_present(
        path,
        root=root,
        authority=authority,
    ):
        return _ArtifactDirectory(
            exists=False,
            identity=None,
            paths={},
            contents={},
            snapshots={},
        )
    paths: dict[str, Path] = {}
    contents: dict[str, bytes] = {}
    snapshots: dict[str, _PrivateFileSnapshot] = {}
    with _held_private_directory(
        path,
        root=root,
        authority=authority,
    ) as directory_descriptor:
        directory_identity = _private_path_identity(os.fstat(directory_descriptor))
        try:
            names = sorted(os.listdir(directory_descriptor))
        except OSError as error:
            raise CapacityValidationError(
                f"cannot enumerate private finding directory {path}: {error}"
            ) from error
        for name in names:
            child = path / name
            if not name.endswith(suffix):
                raise CapacityValidationError(
                    f"unexpected private finding artifact in {path}: {name}"
                )
            finding_id = name[: -len(suffix)]
            if not _ARTIFACT_ID_RE.fullmatch(finding_id) or finding_id in paths:
                raise CapacityValidationError(
                    f"invalid or duplicate finding artifact name in {path}: "
                    f"{name}"
                )
            snapshot = _read_private_file_snapshot_at(
                directory_descriptor,
                name,
                display_path=child,
            )
            snapshots[finding_id] = snapshot
            contents[finding_id] = snapshot.content
            paths[finding_id] = child
    return _ArtifactDirectory(
        exists=True,
        identity=directory_identity,
        paths=paths,
        contents=contents,
        snapshots=snapshots,
    )


def _canonical_object_artifacts(
    artifacts: _ArtifactDirectory,
    *,
    label: str,
    root: Path,
    authority: _PrivatePathAuthority,
) -> tuple[dict[str, dict[str, Any]], dict[str, bytes]]:
    values: dict[str, dict[str, Any]] = {}
    contents: dict[str, bytes] = {}
    del root, authority
    for finding_id, path in artifacts.paths.items():
        content = artifacts.contents[finding_id]
        value = _strict_json_object(content, source=str(path))
        if canonical_json_bytes(value) != content:
            raise CapacityValidationError(
                f"{label} create-once file is not canonical: {path}"
            )
        if value.get("finding_id") != finding_id:
            raise CapacityValidationError(
                f"{label} filename does not match finding_id: {path}"
            )
        values[finding_id] = value
        contents[finding_id] = content
    return values, contents


def _existing_ledger(
    path: Path,
    *,
    root: Path,
    authority: _PrivatePathAuthority,
) -> tuple[_PrivateFileSnapshot | None, list[dict[str, Any]]]:
    if not _private_path_present(
        path,
        root=root,
        authority=authority,
    ):
        return None, []
    snapshot = _read_private_file_snapshot(
        path,
        root=root,
        authority=authority,
    )
    return snapshot, _canonical_jsonl_records(
        snapshot.content,
        source=str(path),
    )


def _validate_capacity_lifecycle(
    records: Sequence[Mapping[str, Any]],
    expected_indexes: Mapping[str, Mapping[str, Any]],
) -> set[str]:
    events_by_id: dict[str, list[dict[str, Any]]] = {}
    for raw_event in records:
        event = dict(raw_event)
        finding_id = event.get("finding_id")
        is_capacity_v2 = event.get("candidate_kind") == "capacity-finding-v2"
        if not is_capacity_v2 and finding_id not in expected_indexes:
            # A canonical legacy lifecycle fact is outside the v2 capability.
            continue
        if not isinstance(finding_id, str) or finding_id not in expected_indexes:
            raise CapacityValidationError(
                "capacity-v2 lifecycle contains an unknown finding_id"
            )
        events_by_id.setdefault(finding_id, []).append(event)

    detected_ids: set[str] = set()
    for finding_id, events in events_by_id.items():
        if not events or events[0].get("state") != "detected":
            raise CapacityValidationError(
                f"finding {finding_id} has lifecycle suffix before detection"
            )
        detected = [event for event in events if event.get("state") == "detected"]
        expected = _detected_lifecycle_event(expected_indexes[finding_id])
        if len(detected) != 1 or detected[0] != expected or events[0] != expected:
            raise CapacityValidationError(
                f"detected lifecycle collision for {finding_id}"
            )
        for suffix in events[1:]:
            state = suffix.get("state")
            if not isinstance(state, str) or not state or state == "detected":
                raise CapacityValidationError(
                    f"finding {finding_id} has malformed lifecycle suffix"
                )
        detected_ids.add(finding_id)
    return detected_ids


def validate_capacity_finding_lifecycle(
    records: Sequence[Mapping[str, Any]],
    index_records: Sequence[Mapping[str, Any]],
) -> None:
    """Validate one exact detected prefix for every persisted v2 occurrence."""
    indexes = _records_by_unique_finding_id(
        index_records,
        source="capacity-finding lifecycle indexes",
    )
    if not indexes:
        raise CapacityValidationError(
            "capacity-finding lifecycle validation requires at least one index"
        )
    detected_ids = _validate_capacity_lifecycle(records, indexes)
    missing = sorted(set(indexes) - detected_ids)
    if missing:
        raise CapacityValidationError(
            "capacity-v2 lifecycle is missing exact detected events for: "
            + ", ".join(missing)
        )


@dataclass(frozen=True, slots=True)
class _IngestPreflight:
    source_path: Path
    index_path: Path
    body_path: Path
    source_directory_identity: tuple[int, int] | None
    index_directory_identity: tuple[int, int] | None
    body_directory_identity: tuple[int, int] | None
    create_source_directory: bool
    create_index_directory: bool
    create_body_directory: bool
    create_source_file: bool
    create_index_file: bool
    create_body_file: bool
    source_ledger_path: Path
    source_ledger_existing: _PrivateFileSnapshot | None
    source_ledger_bytes: bytes | None
    index_ledger_path: Path
    index_ledger_existing: _PrivateFileSnapshot | None
    index_ledger_bytes: bytes | None
    manifest_path: Path
    manifest_existing: _PrivateFileSnapshot | None
    manifest_bytes: bytes | None
    lifecycle_path: Path
    lifecycle_existing: _PrivateFileSnapshot | None
    lifecycle_bytes: bytes | None


def _preflight_ingest(
    finding: ValidatedCapacityFinding,
    source: Mapping[str, Any],
    index_record: Mapping[str, Any],
    *,
    repo_root: Path,
    authority: _PrivatePathAuthority,
) -> _IngestPreflight:
    root = finding.evidence_root
    finding_id = finding.finding_id
    expected_source = dict(source)
    expected_index = dict(index_record)
    expected_source_bytes = canonical_json_bytes(expected_source)
    expected_index_bytes = canonical_json_bytes(expected_index)

    source_directory = root / CAPACITY_FINDING_SOURCE_DIRECTORY
    index_directory = root / CAPACITY_FINDING_INDEX_DIRECTORY
    body_directory = root / CAPACITY_FINDING_BODY_DIRECTORY
    source_artifacts = _preflight_artifact_directory(
        source_directory,
        suffix=".json",
        root=root,
        authority=authority,
    )
    index_artifacts = _preflight_artifact_directory(
        index_directory,
        suffix=".json",
        root=root,
        authority=authority,
    )
    body_artifacts = _preflight_artifact_directory(
        body_directory,
        suffix=".md",
        root=root,
        authority=authority,
    )
    source_files, source_file_bytes = _canonical_object_artifacts(
        source_artifacts,
        label="capacity-finding source",
        root=root,
        authority=authority,
    )
    index_files, index_file_bytes = _canonical_object_artifacts(
        index_artifacts,
        label="capacity-finding index",
        root=root,
        authority=authority,
    )
    body_file_bytes = dict(body_artifacts.contents)

    source_ledger_path = root / CAPACITY_FINDING_SOURCE_NAME
    source_ledger_snapshot, source_ledger_records = _existing_ledger(
        source_ledger_path,
        root=root,
        authority=authority,
    )
    source_ledger = _records_by_unique_finding_id(
        source_ledger_records,
        source=str(source_ledger_path),
    )
    index_ledger_path = root / CAPACITY_FINDING_INDEX_NAME
    index_ledger_snapshot, index_ledger_records = _existing_ledger(
        index_ledger_path,
        root=root,
        authority=authority,
    )
    index_ledger = _records_by_unique_finding_id(
        index_ledger_records,
        source=str(index_ledger_path),
    )

    manifest_path = root / CAPACITY_FINDING_MANIFEST_NAME
    manifest = _preflight_capacity_manifest(
        manifest_path,
        expected_index,
        root=root,
        authority=authority,
    )

    lifecycle_path = root / CAPACITY_FINDING_LIFECYCLE_NAME
    lifecycle_snapshot, lifecycle_records = _existing_ledger(
        lifecycle_path,
        root=root,
        authority=authority,
    )

    all_ids = (
        set(source_files)
        | set(index_files)
        | set(body_file_bytes)
        | set(source_ledger)
        | set(index_ledger)
        | set(manifest.occurrences)
        | {finding_id}
    )
    for event in lifecycle_records:
        event_id = event.get("finding_id")
        if event.get("candidate_kind") == "capacity-finding-v2":
            if not isinstance(event_id, str):
                raise CapacityValidationError(
                    "capacity-v2 lifecycle event requires finding_id"
                )
            all_ids.add(event_id)

    expected_indexes: dict[str, dict[str, Any]] = {}
    common_authority = _common_manifest_authority(expected_index)
    for item_id in sorted(all_ids):
        is_current = item_id == finding_id
        ordered_components = (
            ("source file", item_id in source_files),
            ("index file", item_id in index_files),
            ("body file", item_id in body_file_bytes),
            ("source ledger", item_id in source_ledger),
            ("index ledger", item_id in index_ledger),
            ("manifest", item_id in manifest.existing_occurrences),
            (
                "detected lifecycle",
                any(
                    event.get("finding_id") == item_id
                    for event in lifecycle_records
                ),
            ),
        )
        if is_current:
            missing_component: str | None = None
            for component, present in ordered_components:
                if not present:
                    if missing_component is None:
                        missing_component = component
                    continue
                if missing_component is not None:
                    raise CapacityValidationError(
                        f"current capacity finding {item_id} is not a valid "
                        "durable publication prefix "
                        f"({component} exists after missing "
                        f"{missing_component})"
                    )
        elif not all(present for _, present in ordered_components):
            missing = ", ".join(
                name for name, present in ordered_components if not present
            )
            raise CapacityValidationError(
                f"unrelated capacity finding {item_id} is an incomplete or "
                f"malformed durable occurrence (missing {missing})"
            )

        source_value = expected_source if is_current else source_files.get(item_id)
        if source_value is None:
            source_value = source_ledger.get(item_id)
        index_value = expected_index if is_current else index_files.get(item_id)
        if index_value is None:
            index_value = index_ledger.get(item_id)
        if source_value is None or index_value is None:
            raise CapacityValidationError(
                f"capacity finding {item_id} lacks source/index authority"
            )
        source_value = dict(source_value)
        index_value = dict(index_value)
        if source_value.get("finding_id") != item_id:
            raise CapacityValidationError(
                f"capacity finding source identity mismatch for {item_id}"
            )
        if index_value.get("finding_id") != item_id:
            raise CapacityValidationError(
                f"capacity finding index identity mismatch for {item_id}"
            )

        source_bytes = canonical_json_bytes(source_value)
        index_bytes = canonical_json_bytes(index_value)
        if item_id in source_file_bytes and source_file_bytes[item_id] != source_bytes:
            raise CapacityValidationError(
                f"immutable finding occurrence collision at "
                f"{source_artifacts.paths[item_id]}"
            )
        if (
            item_id in source_ledger
            and canonical_json_bytes(source_ledger[item_id]) != source_bytes
        ):
            raise CapacityValidationError(f"source ledger collision for {item_id}")
        if item_id in index_file_bytes and index_file_bytes[item_id] != index_bytes:
            raise CapacityValidationError(
                f"immutable finding occurrence collision at "
                f"{index_artifacts.paths[item_id]}"
            )
        if (
            item_id in index_ledger
            and canonical_json_bytes(index_ledger[item_id]) != index_bytes
        ):
            raise CapacityValidationError(f"index ledger collision for {item_id}")

        verified_index = _validate_replayed_occurrence(
            source_value,
            index_value,
            repo_root=repo_root,
            evidence_root=root,
        )
        if verified_index != index_value:
            raise CapacityValidationError(
                f"capacity-finding index verification drift for {item_id}"
            )
        if _common_manifest_authority(index_value) != common_authority:
            raise CapacityValidationError(
                f"capacity finding {item_id} has mixed run/branch/ref authority"
            )
        expected_body_value = index_value.get("occurrence_body")
        if not isinstance(expected_body_value, str):
            raise CapacityValidationError(
                f"capacity finding {item_id} has no exact occurrence body"
            )
        if item_id in body_file_bytes and body_file_bytes[
            item_id
        ] != expected_body_value.encode("utf-8"):
            raise CapacityValidationError(
                f"immutable finding occurrence collision at "
                f"{body_artifacts.paths[item_id]}"
            )
        if (
            item_id in manifest.existing_occurrences
            and manifest.existing_occurrences[item_id]
            != _manifest_occurrence(index_value)
        ):
            raise CapacityValidationError(
                f"manifest immutable occurrence collision for {item_id}"
            )
        expected_indexes[item_id] = index_value

    detected_ids = _validate_capacity_lifecycle(
        lifecycle_records,
        expected_indexes,
    )
    for item_id in sorted(all_ids - {finding_id}):
        if item_id not in detected_ids:
            raise CapacityValidationError(
                f"unrelated capacity finding {item_id} has no exact detected "
                "lifecycle event"
            )

    create_source_file = finding_id not in source_files
    create_index_file = finding_id not in index_files
    create_body_file = finding_id not in body_file_bytes
    append_source_ledger = finding_id not in source_ledger
    append_index_ledger = finding_id not in index_ledger
    append_lifecycle = finding_id not in detected_ids
    return _IngestPreflight(
        source_path=source_directory / f"{finding_id}.json",
        index_path=index_directory / f"{finding_id}.json",
        body_path=body_directory / f"{finding_id}.md",
        source_directory_identity=source_artifacts.identity,
        index_directory_identity=index_artifacts.identity,
        body_directory_identity=body_artifacts.identity,
        create_source_directory=not source_artifacts.exists,
        create_index_directory=not index_artifacts.exists,
        create_body_directory=not body_artifacts.exists,
        create_source_file=create_source_file,
        create_index_file=create_index_file,
        create_body_file=create_body_file,
        source_ledger_path=source_ledger_path,
        source_ledger_existing=source_ledger_snapshot,
        source_ledger_bytes=(
            (
                source_ledger_snapshot.content
                if source_ledger_snapshot is not None
                else b""
            )
            + expected_source_bytes
            if append_source_ledger
            else None
        ),
        index_ledger_path=index_ledger_path,
        index_ledger_existing=index_ledger_snapshot,
        index_ledger_bytes=(
            (
                index_ledger_snapshot.content
                if index_ledger_snapshot is not None
                else b""
            )
            + expected_index_bytes
            if append_index_ledger
            else None
        ),
        manifest_path=manifest_path,
        manifest_existing=manifest.existing_snapshot,
        manifest_bytes=manifest.desired_bytes,
        lifecycle_path=lifecycle_path,
        lifecycle_existing=lifecycle_snapshot,
        lifecycle_bytes=(
            (
                lifecycle_snapshot.content
                if lifecycle_snapshot is not None
                else b""
            )
            + canonical_json_bytes(_detected_lifecycle_event(expected_index))
            if append_lifecycle
            else None
        ),
    )


def ingest_capacity_finding(
    value: Mapping[str, Any],
    result: ValidatedCapacityResult,
    *,
    authority_repo_root: Path,
    run_dir: Path,
) -> IngestedCapacityFinding:
    """Create or recover one exact finding occurrence under a private run dir."""
    finding = validate_capacity_finding(
        value,
        result,
        authority_repo_root=authority_repo_root,
        evidence_root=run_dir,
    )
    source = require_validated_capacity_finding(finding)
    index_record = capacity_finding_index_record(finding)
    validate_capacity_finding_index_record(
        index_record,
        source,
        repo_root=result.repo_root,
    )
    source_bytes = canonical_json_bytes(source)
    index_bytes = canonical_json_bytes(index_record)
    body = index_record["occurrence_body"]
    assert isinstance(body, str)
    body_bytes = body.encode("utf-8")

    root = finding.evidence_root
    with capacity_finding_ingest_lock(root) as run_authority:
        # Recover only authenticated writer temp peers before the read-only
        # preflight. This closes both pre-publication and post-link crash
        # windows without interpreting or repairing destination content.
        for directory, names, pattern in (
            (
                root,
                frozenset(
                    {
                        CAPACITY_FINDING_SOURCE_NAME,
                        CAPACITY_FINDING_INDEX_NAME,
                        CAPACITY_FINDING_MANIFEST_NAME,
                        CAPACITY_FINDING_LIFECYCLE_NAME,
                    }
                ),
                None,
            ),
            (
                root / CAPACITY_FINDING_SOURCE_DIRECTORY,
                frozenset(),
                _PRIVATE_FINDING_JSON_DESTINATION_RE,
            ),
            (
                root / CAPACITY_FINDING_INDEX_DIRECTORY,
                frozenset(),
                _PRIVATE_FINDING_JSON_DESTINATION_RE,
            ),
            (
                root / CAPACITY_FINDING_BODY_DIRECTORY,
                frozenset(),
                _PRIVATE_FINDING_BODY_DESTINATION_RE,
            ),
        ):
            _recover_private_temporary_files(
                directory,
                root=root,
                authority=run_authority,
                managed_destination_names=names,
                managed_destination_pattern=pattern,
            )

        # No occurrence directory, destination file, ledger, manifest, or
        # lifecycle byte changes before all durable state (including unrelated
        # occurrences) has been authenticated.
        preflight = _preflight_ingest(
            finding,
            source,
            index_record,
            repo_root=result.repo_root,
            authority=run_authority,
        )

        directory_identities: dict[Path, tuple[int, int]] = {}
        for directory, expected_identity in (
            (
                preflight.source_path.parent,
                preflight.source_directory_identity,
            ),
            (
                preflight.index_path.parent,
                preflight.index_directory_identity,
            ),
            (
                preflight.body_path.parent,
                preflight.body_directory_identity,
            ),
        ):
            directory_identities[directory] = _private_directory(
                directory,
                root=root,
                authority=run_authority,
                expected_existing_identity=expected_identity,
            )
        if preflight.create_source_file:
            _write_new_private_file(
                preflight.source_path,
                source_bytes,
                root=root,
                authority=run_authority,
                expected_parent_identity=directory_identities[
                    preflight.source_path.parent
                ],
            )
        if preflight.create_index_file:
            _write_new_private_file(
                preflight.index_path,
                index_bytes,
                root=root,
                authority=run_authority,
                expected_parent_identity=directory_identities[
                    preflight.index_path.parent
                ],
            )
        if preflight.create_body_file:
            _write_new_private_file(
                preflight.body_path,
                body_bytes,
                root=root,
                authority=run_authority,
                expected_parent_identity=directory_identities[
                    preflight.body_path.parent
                ],
            )
        if preflight.source_ledger_bytes is not None:
            _replace_private_file(
                preflight.source_ledger_path,
                preflight.source_ledger_bytes,
                root=root,
                authority=run_authority,
                expected_existing=preflight.source_ledger_existing,
            )
        if preflight.index_ledger_bytes is not None:
            _replace_private_file(
                preflight.index_ledger_path,
                preflight.index_ledger_bytes,
                root=root,
                authority=run_authority,
                expected_existing=preflight.index_ledger_existing,
            )
        if preflight.manifest_bytes is not None:
            _replace_private_file(
                preflight.manifest_path,
                preflight.manifest_bytes,
                root=root,
                authority=run_authority,
                expected_existing=preflight.manifest_existing,
            )
        if preflight.lifecycle_bytes is not None:
            _replace_private_file(
                preflight.lifecycle_path,
                preflight.lifecycle_bytes,
                root=root,
                authority=run_authority,
                expected_existing=preflight.lifecycle_existing,
            )
        postflight = _preflight_ingest(
            finding,
            source,
            index_record,
            repo_root=result.repo_root,
            authority=run_authority,
        )
        if (
            postflight.create_source_directory
            or postflight.create_index_directory
            or postflight.create_body_directory
            or postflight.create_source_file
            or postflight.create_index_file
            or postflight.create_body_file
            or postflight.source_ledger_bytes is not None
            or postflight.index_ledger_bytes is not None
            or postflight.manifest_bytes is not None
            or postflight.lifecycle_bytes is not None
        ):
            raise CapacityValidationError(
                "capacity-finding ingest did not finish as one exact durable "
                "occurrence"
            )
    return IngestedCapacityFinding(
        finding=finding,
        source_path=preflight.source_path,
        index_path=preflight.index_path,
        index_record=index_record,
        appended_source=preflight.create_source_file,
        appended_index=preflight.index_ledger_bytes is not None,
    )
