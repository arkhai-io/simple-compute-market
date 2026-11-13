#!/usr/bin/env python3
"""Refuse a second list of release components, and any workflow that could publish.

Two rules, with no exception list.

**One enumeration.** `manifests/release-components.json` is the only list of what
a marketplace release comprises and of the development images its validation
runs. A workflow, a publish target or a lane target that names a declared
distribution, image, development image, the chart or the binary is refused,
naming the file, the target and what it named. A publish target is a Make target
named `push-*`, `publish-*`, `clobber-*` or `load-candidate`, or one whose recipe
runs an uploader. A lane target is one named `test-e2e*`, `build-e2e*` or
`pull-release-images`. Make variables a rule references are read as part of it,
so a list moved into a variable is still found. A target that needs a list reads
the declaration instead (`scripts/release_components.py`).

**Workflow credentials.** A workflow cannot publish without a credential, and
the credentials it can hold are few and written in its file, so the rule judges
what it holds rather than which commands it runs: a list of upload commands
would miss `uv publish`, `twine upload`, `helm push` and every marketplace
action. A workflow is refused when it declares no top-level `permissions:`
(without one it gets the repository's default token, which may write), grants
`id-token`, `packages`, `attestations` or `contents` write access anywhere, or
references a secret other than `GITHUB_TOKEN`. Named publishing steps are
refused as well, so that a refusal can name the step.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from release_components import REPO_ROOT, DeclarationError, ReleaseComponents, load

_SKIPPED_DIRS = {".git", ".venv", "venv", "node_modules", ".dist", "__pycache__",
                 "openspec", "target", ".snapshot"}

_GRANT = re.compile(r"(?<![\w-])(id-token|packages|attestations|contents)\s*:\s*['\"]?write\b")
_WRITE_ALL = re.compile(r"\bpermissions\s*:\s*['\"]?write-all\b")
_SECRET = re.compile(r"\bsecrets\.([A-Za-z_][A-Za-z0-9_]*)|\bsecrets\[\s*['\"]([^'\"]+)['\"]\s*\]")
_INHERITED_SECRETS = re.compile(r"\bsecrets\s*:\s*inherit\b")
_PUBLISHING_STEPS = {
    "pypa/gh-action-pypi-publish": re.compile(r"pypa/gh-action-pypi-publish"),
    "softprops/action-gh-release": re.compile(r"softprops/action-gh-release"),
    "npm publish": re.compile(r"\bnpm\s+publish\b"),
    "docker push": re.compile(r"\bdocker\s+push\b"),
    "gh release create": re.compile(r"\bgh\s+release\s+create\b"),
}
_BUILD_PUSH_ACTION = re.compile(r"docker/build-push-action")
_PUSH_TRUE = re.compile(r"^\s*push\s*:\s*['\"]?true\b", re.MULTILINE)

_UPLOADER = re.compile(
    r"publish_artifacts\.py|push-distributions\.py|\bdocker\s+push\b|\bhelm\s+push\b"
    r"|\bgcloud\s+artifacts\b|\buv\s+publish\b|\btwine\s+upload\b|\bnpm\s+publish\b")
_PUBLISH_TARGET = re.compile(r"^(push|publish|clobber)-|^load-candidate$")
_LANE_TARGET = re.compile(r"^(test-e2e|build-e2e)|^pull-release-images$")
_RULE = re.compile(r"^([^\s#:=][^#:=]*?)\s*:(?![=:])(.*)$")
_VARIABLE = re.compile(
    r"^(?:export\s+|override\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(\+=|\?=|:{1,3}=|=)\s*(.*)$")
_REFERENCE = re.compile(r"\$[({]([A-Za-z_][A-Za-z0-9_]*)[)}]")


@dataclass(frozen=True)
class Rule:
    targets: tuple[str, ...]
    text: str


def _without_comments(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.lstrip().startswith("#")]


def _name_pattern(name: str) -> str:
    """`name` as a whole token, spelled with hyphens or underscores, which a
    version or a variable may follow but a longer name may not."""
    parts = re.split(r"[-_.]+", name)
    return (r"(?<![A-Za-z0-9_.-])" + r"[-_.]".join(map(re.escape, parts))
            + r"(?![A-Za-z0-9_.]|[-_][A-Za-z])")


def _chart_name(root: Path, path: str) -> str | None:
    chart = root / path / "Chart.yaml"
    if not chart.is_file():
        return None
    match = re.search(r"^name:\s*['\"]?([^'\"\s]+)", chart.read_text(encoding="utf-8"),
                      re.MULTILINE)
    return match.group(1) if match else None


def component_patterns(components: ReleaseComponents,
                       chart_name: str | None) -> list[tuple[str, re.Pattern[str]]]:
    """Each declared component, as a label and the pattern that finds it named."""
    patterns: list[tuple[str, str]] = []
    for entry in components.distributions:
        patterns.append((f"distribution {entry.dist}", _name_pattern(entry.dist)))
    for label, images in (("image", components.images),
                          ("development image", components.development_images)):
        for image in images:
            for spelling in sorted({image.name, image.local}):
                # A tag suffix, such as a revision, may follow the name.
                patterns.append((f"{label} {image.name}",
                                 r"arkhai:" + re.escape(spelling) + r"(?![A-Za-z0-9_.])"))
                patterns.append((f"{label} {image.name}",
                                 r"--(?:target|source)[= ]+['\"]?" + re.escape(spelling)
                                 + r"(?![A-Za-z0-9_.-])"))
    chart = f"chart {components.chart.path}"
    patterns.append((chart, r"(?<![A-Za-z0-9_.-])" + re.escape(components.chart.path) + "/"))
    if chart_name:
        patterns.append((chart, _name_pattern(chart_name)))
    for binary in components.binaries:
        patterns.append((f"binary {binary.name}",
                         r"(?<![A-Za-z0-9_./-])" + re.escape(binary.path)
                         + r"(?![A-Za-z0-9_.-])"))
    for package in components.npm or ():
        patterns.append((f"npm package {package.path}",
                         r"(?<![A-Za-z0-9_./-])" + re.escape(package.path)
                         + r"(?![A-Za-z0-9_.-])"))
    return [(label, re.compile(pattern, re.IGNORECASE)) for label, pattern in patterns]


def named_components(text: str, patterns: list[tuple[str, re.Pattern[str]]]) -> list[str]:
    """The labels of every declared component `text` names, in declaration order."""
    found: list[str] = []
    for label, pattern in patterns:
        if label not in found and pattern.search(text):
            found.append(label)
    return found


def makefile_rules(text: str) -> list[Rule]:
    """Each rule of a Makefile, its header and recipe with the values of the
    variables it references written after it."""
    lines = text.replace("\\\n", " ").splitlines()
    variables: dict[str, str] = {}
    for line in lines:
        if line.startswith("\t"):
            continue
        match = _VARIABLE.match(line)
        if match:
            name, operator, value = match.groups()
            variables[name] = (variables.get(name, "") + " " + value
                               if operator == "+=" else value)

    def expanded(body: str) -> str:
        values: list[str] = []
        pending, seen = _REFERENCE.findall(body), set()
        while pending:
            name = pending.pop()
            if name in seen or name not in variables:
                continue
            seen.add(name)
            values.append(variables[name])
            pending.extend(_REFERENCE.findall(variables[name]))
        return "\n".join([body, *values])

    rules: list[Rule] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = None if line.startswith("\t") or _VARIABLE.match(line) else _RULE.match(line)
        index += 1
        if not match:
            continue
        targets = tuple(name for name in match.group(1).split() if not name.startswith("."))
        body = [line]
        while index < len(lines):
            following = lines[index]
            if following.startswith("\t"):
                body.append(following)
            elif following.strip() and not following.lstrip().startswith("#"):
                break
            index += 1
        if targets:
            text_of_rule = "\n".join(_without_comments("\n".join(body)))
            rules.append(Rule(targets, expanded(text_of_rule)))
    return rules


def _kind_of(rule: Rule) -> str | None:
    if any(_PUBLISH_TARGET.search(target) for target in rule.targets):
        return "publish target"
    if _UPLOADER.search(rule.text):
        return "publish target"
    if any(_LANE_TARGET.search(target) for target in rule.targets):
        return "lane target"
    return None


def makefile_problems(label: str, text: str,
                      patterns: list[tuple[str, re.Pattern[str]]]) -> list[str]:
    problems: list[str] = []
    for rule in makefile_rules(text):
        kind = _kind_of(rule)
        if kind is None:
            continue
        for component in named_components(rule.text, patterns):
            problems.append(f"{label}: {kind} {' '.join(rule.targets)} names {component}; "
                            "read it from the declaration instead")
    return problems


def _step_name(lines: list[str], index: int) -> str:
    """The `name:` of the workflow step whose text holds line `index`."""
    indent = len(lines[index]) - len(lines[index].lstrip())
    for start in range(index, -1, -1):
        item = re.match(r"^(\s*)-\s+(.*)$", lines[start])
        if item and (len(item.group(1)) < indent or start == index):
            dash = len(item.group(1))
            block = [item.group(2)]
            for following in lines[start + 1:]:
                if following.strip() and len(following) - len(following.lstrip()) <= dash:
                    break
                block.append(following.strip())
            for entry in block:
                named = re.match(r"^name\s*:\s*['\"]?(.*?)['\"]?\s*$", entry)
                if named:
                    return named.group(1)
            return "(unnamed)"
    return "(unnamed)"


def _step_text(lines: list[str], index: int) -> str:
    """The text of the workflow step whose text holds line `index`."""
    indent = len(lines[index]) - len(lines[index].lstrip())
    for start in range(index, -1, -1):
        item = re.match(r"^(\s*)-\s+", lines[start])
        if item and (len(item.group(1)) < indent or start == index):
            dash = len(item.group(1))
            block = [lines[start]]
            for following in lines[start + 1:]:
                if following.strip() and len(following) - len(following.lstrip()) <= dash:
                    break
                block.append(following)
            return "\n".join(block)
    return lines[index]


def workflow_problems(label: str, text: str,
                      patterns: list[tuple[str, re.Pattern[str]]]) -> list[str]:
    lines = _without_comments(text)
    body = "\n".join(lines)
    problems: list[str] = []
    if not re.search(r"^permissions\s*:", body, re.MULTILINE):
        problems.append(f"{label}: declares no top-level permissions:, so it gets the "
                        "repository's default token, which may write")
    for grant in sorted({match.group(1) for match in _GRANT.finditer(body)}):
        problems.append(f"{label}: grants {grant}: write")
    if _WRITE_ALL.search(body):
        problems.append(f"{label}: grants permissions: write-all")
    secrets = sorted({first or second for first, second in _SECRET.findall(body)}
                     - {"GITHUB_TOKEN"})
    for secret in secrets:
        problems.append(f"{label}: references secret {secret}; only GITHUB_TOKEN is allowed")
    if _INHERITED_SECRETS.search(body):
        problems.append(f"{label}: passes on every secret with secrets: inherit")
    for index, line in enumerate(lines):
        for step, pattern in _PUBLISHING_STEPS.items():
            if pattern.search(line):
                problems.append(f"{label}: step {_step_name(lines, index)!r} publishes "
                                f"with {step}")
        if _BUILD_PUSH_ACTION.search(line) and _PUSH_TRUE.search(_step_text(lines, index)):
            problems.append(f"{label}: step {_step_name(lines, index)!r} publishes with "
                            "docker/build-push-action and push: true")
    for component in named_components(body, patterns):
        problems.append(f"{label}: names {component}; read it from the declaration instead")
    return problems


def _makefiles(root: Path) -> list[Path]:
    found: list[Path] = []
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = sorted(name for name in subdirectories
                                   if name not in _SKIPPED_DIRS)
        for name in sorted(files):
            if name == "Makefile" or name.endswith(".mk"):
                found.append(Path(directory) / name)
    return found


def check(root: Path = REPO_ROOT, components: ReleaseComponents | None = None) -> list[str]:
    """Every refusal for the tree at `root`."""
    components = components or load(root / "manifests" / "release-components.json")
    patterns = component_patterns(components, _chart_name(root, components.chart.path))
    problems: list[str] = []
    workflows = root / ".github" / "workflows"
    if workflows.is_dir():
        for workflow in sorted([*workflows.glob("*.yml"), *workflows.glob("*.yaml")]):
            problems += workflow_problems(str(workflow.relative_to(root)),
                                          workflow.read_text(encoding="utf-8"), patterns)
    for makefile in _makefiles(root):
        problems += makefile_problems(str(makefile.relative_to(root)),
                                      makefile.read_text(encoding="utf-8"), patterns)
    return problems


def main() -> int:
    try:
        problems = check()
    except DeclarationError as error:
        print(f"check-release-components: {error}", file=sys.stderr)
        return 1
    if problems:
        print("check-release-components:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print("OK: the declaration is the only list of release components, "
          "and no workflow can publish.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
