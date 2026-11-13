#!/usr/bin/env python3
"""Refuse a second list of release components, and any workflow that could publish.

Four rules, with no exception list. Each runs on its own (`--rule enumeration`,
`--rule credentials`, `--rule market-binary`, `--rule revision`); with no
`--rule`, every one runs.

**One enumeration.** This rule holds `manifests/release-components.json` to being
the only list of what a marketplace release comprises and of the development
images its validation runs. A workflow, a publish target or a lane target that names a declared
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
refused as well, so that a refusal can name the step. This rule reads no
declaration.

**The market binary's project.** The release's `market` binary is built from a
locked project whose `[project].dependencies` list what it bundles. That list
is held equal, by normalised distribution name, to the buyer CLI and the buyer
domains `scripts/market_binary.py` derives from the declaration: a list held
equal to the declaration by a check is not a second list. A missing
distribution is named with the project that registers it, and an extra one as
neither. Only `dependencies` is compared; the build's own tools sit in a
dependency group.

**Nine-character revisions.** Every revision tag a build writes and every
version a push stores is `git rev-parse --short=9`, and a release's bill of
materials names each image by its `<name>-<rev9>` tag. Git's default
abbreviation grows with the repository, so a Makefile abbreviating a revision
with a bare `--short`, or any other length, is refused.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from market_binary import DOMAIN_GROUP, PROJECT, TARGET, binary, inputs
from release_components import (
    DECLARATION_PATH,
    REPO_ROOT,
    DeclarationError,
    ReleaseComponents,
    chart_field,
    load,
    normalise_distribution,
)

_SKIPPED_DIRS = {".git", ".venv", "venv", "node_modules", ".dist", "__pycache__",
                 "openspec", "target", ".snapshot"}

_GRANT = re.compile(r"(?<![\w-])(id-token|packages|attestations|contents)\s*:\s*['\"]?write\b")
_WRITE_ALL = re.compile(r"\bpermissions\s*:\s*['\"]?write-all\b")
# Context and secret names are case-insensitive in an Actions expression.
_SECRETS_CONTEXT = re.compile(r"(?<![\w.-])secrets\b", re.IGNORECASE)
_NAMED_SECRET = re.compile(r"\s*(?:\.\s*([A-Za-z_][A-Za-z0-9_-]*)|\[\s*['\"]([^'\"]+)['\"]\s*\])")
_INHERITED_SECRETS = re.compile(r"\bsecrets\s*:\s*inherit\b")
_PUBLISHING_STEPS = {
    "pypa/gh-action-pypi-publish": re.compile(r"pypa/gh-action-pypi-publish"),
    "softprops/action-gh-release": re.compile(r"softprops/action-gh-release"),
    "npm publish": re.compile(r"\bnpm\s+publish\b"),
    "docker push": re.compile(r"\bdocker\s+push\b"),
    "gh release create": re.compile(r"\bgh\s+release\s+create\b"),
}
_BUILD_PUSH_ACTION = re.compile(r"docker/build-push-action")
# Any `push:` but a literal false may push, such as an expression true on some events.
_PUSH = re.compile(r"^\s*push\s*:\s*(?!['\"]?false['\"]?\s*$)(\S.*?)\s*$", re.MULTILINE)

_UPLOADER = re.compile(
    r"publish_artifacts\.py|\bdocker\s+push\b|\bhelm\s+push\b"
    r"|\bgcloud\s+artifacts\b|\buv\s+publish\b|\btwine\s+upload\b|\bnpm\s+publish\b")
_PUBLISH_TARGET = re.compile(r"^(push|publish|clobber)-|^load-candidate$")
_LANE_TARGET = re.compile(r"^(test-e2e|build-e2e)|^pull-release-images$")
_RULE = re.compile(r"^([^\s#:=][^#:=]*?)\s*:(?![=:])(.*)$")
_VARIABLE = re.compile(
    r"^(?:export\s+|override\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(\+=|\?=|:{1,3}=|=)\s*(.*)$")
_REFERENCE = re.compile(r"\$[({]([A-Za-z_][A-Za-z0-9_]*)[)}]")
_REV_PARSE = re.compile(r"\bgit\s+rev-parse\b[^\n;&|)]*")
_SHORT = re.compile(r"--short(?:=\S*)?")
REVISION_LENGTH = 9


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
    return chart_field(chart.read_text(encoding="utf-8"), "name")


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


def _expressions(text: str) -> list[str]:
    """The body of every `${{ … }}` in `text`, the only place a workflow reads the
    secrets context. A `}}` inside one of the expression's single-quoted strings
    does not end it."""
    found: list[str] = []
    start = text.find("${{")
    while start != -1:
        index, quoted = start + 3, False
        while index < len(text):
            if text[index] == "'":
                quoted = not quoted
            elif not quoted and text.startswith("}}", index):
                break
            index += 1
        found.append(text[start + 3:index])
        start = text.find("${{", index)
    return found


def _secret_references(text: str) -> tuple[set[str], bool]:
    """The secrets a workflow's expressions name, upper-cased, and whether one
    reads the secrets context without naming a secret, as `toJSON(secrets)` and
    `secrets[matrix.name]` do: such a read can reach any secret.

    It reads the workflow's raw text. A line beginning with `#` inside a block
    scalar is not a comment, and Actions substitutes expressions in it."""
    names: set[str] = set()
    unnamed = False
    for expression in _expressions(text):
        for match in _SECRETS_CONTEXT.finditer(expression):
            named = _NAMED_SECRET.match(expression, match.end())
            if named:
                names.add((named.group(1) or named.group(2)).upper())
            else:
                unnamed = True
    return names, unnamed


def workflow_credential_problems(label: str, text: str) -> list[str]:
    """The workflow-credential rule's refusals of one workflow."""
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
    named, unnamed = _secret_references(text)
    for secret in sorted(named - {"GITHUB_TOKEN"}):
        problems.append(f"{label}: references secret {secret}; only GITHUB_TOKEN is allowed")
    if unnamed:
        problems.append(f"{label}: reads the secrets context without naming a secret; "
                        "only GITHUB_TOKEN is allowed")
    if _INHERITED_SECRETS.search(body):
        problems.append(f"{label}: passes on every secret with secrets: inherit")
    for index, line in enumerate(lines):
        for step, pattern in _PUBLISHING_STEPS.items():
            if pattern.search(line):
                problems.append(f"{label}: step {_step_name(lines, index)!r} publishes "
                                f"with {step}")
        push = (_PUSH.search(_step_text(lines, index))
                if _BUILD_PUSH_ACTION.search(line) else None)
        if push:
            problems.append(f"{label}: step {_step_name(lines, index)!r} publishes with "
                            f"docker/build-push-action and push: {push.group(1)}")
    return problems


def workflow_enumeration_problems(label: str, text: str,
                                  patterns: list[tuple[str, re.Pattern[str]]]) -> list[str]:
    """The single-enumeration rule's refusals of one workflow."""
    body = "\n".join(_without_comments(text))
    return [f"{label}: names {component}; read it from the declaration instead"
            for component in named_components(body, patterns)]


def _makefiles(root: Path) -> list[Path]:
    found: list[Path] = []
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = sorted(name for name in subdirectories
                                   if name not in _SKIPPED_DIRS)
        for name in sorted(files):
            if name == "Makefile" or name.endswith(".mk"):
                found.append(Path(directory) / name)
    return found


def _workflows(root: Path) -> list[Path]:
    workflows = root / ".github" / "workflows"
    if not workflows.is_dir():
        return []
    return sorted([*workflows.glob("*.yml"), *workflows.glob("*.yaml")])


def check_credentials(root: Path = REPO_ROOT) -> list[str]:
    """The workflow-credential rule's refusals for the tree at `root`. It reads
    no declaration."""
    problems: list[str] = []
    for workflow in _workflows(root):
        problems += workflow_credential_problems(str(workflow.relative_to(root)),
                                                 workflow.read_text(encoding="utf-8"))
    return problems


_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def check_market_binary(root: Path = REPO_ROOT,
                        components: ReleaseComponents | None = None,
                        target: str = TARGET, project: str = PROJECT) -> list[str]:
    """The market-binary rule's refusals: the binary's project at `project`
    must depend on exactly the buyer CLI and the buyer domains the declaration
    gives the binary `target` builds."""
    components = components or load(root / DECLARATION_PATH)
    entry = binary(components, target)
    found = inputs(components, root, entry.name)
    expected = {normalise_distribution(found.cli.distribution.dist):
                (found.cli.distribution, f"defines the `{entry.name}` console script")}
    for domain in found.domains:
        expected[normalise_distribution(domain.distribution.dist)] = (
            domain.distribution, f"registers a {DOMAIN_GROUP} entry point")

    label = f"{project}/pyproject.toml"
    try:
        document = tomllib.loads((root / project / "pyproject.toml").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"{label} does not exist; the {entry.name} binary is built from it"]
    except tomllib.TOMLDecodeError as error:
        return [f"{label} is not valid TOML: {error}"]
    dependencies = (document.get("project") or {}).get("dependencies") or []
    if not isinstance(dependencies, list):
        return [f"{label}: [project].dependencies is not a list"]

    problems: list[str] = []
    named: dict[str, str] = {}
    for requirement in dependencies:
        match = _REQUIREMENT_NAME.match(requirement) if isinstance(requirement, str) else None
        if not match:
            problems.append(f"{label}: {requirement!r} is not a requirement")
            continue
        named.setdefault(normalise_distribution(match.group(1)), match.group(1))
    for name, (distribution, why) in expected.items():
        if name not in named:
            problems.append(f"{label}: does not depend on {distribution.dist}, which "
                            f"{distribution.path} {why}")
    for name, spelled in named.items():
        if name not in expected:
            problems.append(f"{label}: depends on {spelled}, which is neither the buyer "
                            "CLI nor a declared buyer domain")
    return problems


def revision_problems(label: str, text: str) -> list[str]:
    """The revision rule's refusals of one Makefile: each `git rev-parse` that
    abbreviates with anything but `--short=9`."""
    wanted = f"--short={REVISION_LENGTH}"
    problems: list[str] = []
    for line in _without_comments(text.replace("\\\n", " ")):
        for call in _REV_PARSE.finditer(line):
            for short in _SHORT.finditer(call.group(0)):
                if short.group(0) != wanted:
                    problems.append(f"{label}: abbreviates a revision with {short.group(0)}; "
                                    f"use git rev-parse {wanted}")
    return problems


def check_revision(root: Path = REPO_ROOT) -> list[str]:
    """The revision rule's refusals for the tree at `root`. It reads no
    declaration."""
    problems: list[str] = []
    for makefile in _makefiles(root):
        problems += revision_problems(str(makefile.relative_to(root)),
                                      makefile.read_text(encoding="utf-8"))
    return problems


def check_enumeration(root: Path = REPO_ROOT,
                      components: ReleaseComponents | None = None) -> list[str]:
    """The single-enumeration rule's refusals for the tree at `root`."""
    components = components or load(root / DECLARATION_PATH)
    patterns = component_patterns(components, _chart_name(root, components.chart.path))
    problems: list[str] = []
    for workflow in _workflows(root):
        problems += workflow_enumeration_problems(str(workflow.relative_to(root)),
                                                  workflow.read_text(encoding="utf-8"),
                                                  patterns)
    for makefile in _makefiles(root):
        problems += makefile_problems(str(makefile.relative_to(root)),
                                      makefile.read_text(encoding="utf-8"), patterns)
    return problems


# Each rule, by the name `--rule` takes, and what its passing establishes.
RULES = {
    "enumeration": "the declaration is the only list of release components",
    "credentials": "no workflow can publish",
    "market-binary": "the market binary's project bundles exactly the buyer CLI and the "
                     "declared buyer domains",
    "revision": "every Makefile abbreviates a revision to nine characters",
}


def check(root: Path = REPO_ROOT, components: ReleaseComponents | None = None,
          rules: tuple[str, ...] = tuple(RULES)) -> list[str]:
    """Every refusal the named rules make for the tree at `root`."""
    problems: list[str] = []
    if "enumeration" in rules:
        problems += check_enumeration(root, components)
    if "credentials" in rules:
        problems += check_credentials(root)
    if "market-binary" in rules:
        problems += check_market_binary(root, components)
    if "revision" in rules:
        problems += check_revision(root)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rule", action="append", choices=sorted(RULES), dest="rules",
                        help="run only this rule; repeat it for several (default: every rule)")
    rules = tuple(parser.parse_args(argv).rules or RULES)
    try:
        problems = check(rules=rules)
    except DeclarationError as error:
        print(f"check-release-components: {error}", file=sys.stderr)
        return 1
    if problems:
        print("check-release-components:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print("OK: " + "; ".join(RULES[rule] for rule in RULES if rule in rules) + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
