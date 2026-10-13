#!/usr/bin/env python3
"""Report the package architecture of the whole tree, with no exception applied.

Writes Markdown: every project's classification, then every finding of every
rule grouped by rule. A finding a table already classifies carries that
classification — the exception row's owner, or the runtime reason the
declaring package gives — so the report reads as the audited state of the tree rather
than only its failures. `make check-architecture` is the gate; this is the
full view behind it.

Usage: architecture_report.py [--root DIR] [--out PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import architecture  # noqa: E402


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def report(model: architecture.Model) -> str:
    rules = model.rules
    lines = ["# Package architecture report", "",
             "Every rule over every project, with no exception row applied.", "",
             "## Classification", "",
             "| Project | Path | Layer | Kind | Scope | Plugin | Source |", "|---|---|---|---|---|---|---|"]
    for project in sorted(model.projects.values(), key=lambda p: p.path):
        source = f"override ({project.override.get('owner')})" if project.override else (
            "path" if project.reading else "unclassified")
        scope = ", ".join(sorted(project.scope)) or "—"
        lines.append(f"| `{project.name}` | `{project.path}` | {project.layer or '—'} | "
                     f"{project.kind or '—'} | {scope} | {'yes' if project.plugin else ''} | {source} |")

    exceptions = {}
    for row in rules.exceptions:
        project = row["project"] if row.get("rule") == "cycle" else architecture.normalize(row["project"])
        exceptions[(row.get("rule"), project, row["target"])] = row
    declarations = {
        (project.name, architecture.normalize(dist)): reason
        for project in model.projects.values()
        for dist, reason in project.settings.get("runtime-dependencies", {}).items()
    }
    found = architecture.problems(model, architecture.RULES, strict=True)
    lines += ["", "## Findings", ""]
    if not found:
        lines.append("None.")
    for rule in architecture.RULES:
        of_rule = sorted((f for f in found if f.rule == rule), key=lambda f: (f.project, f.target))
        if not of_rule:
            continue
        lines += [f"### {rule}", "", "| Site | Project | Target | Finding | Classification |",
                  "|---|---|---|---|---|"]
        for finding in of_rule:
            site = finding.sites[0] if finding.sites else None
            where = f"`{site.file}:{site.line}`" + (f" ({site.context})" if site.context != "module" else "") \
                if site else ""
            if len(finding.sites) > 1:
                where += f" +{len(finding.sites) - 1}"
            row = exceptions.get(finding.key)
            classification = ""
            if row:
                classification = f"defect, owned by `{row.get('owner')}`"
            elif finding.rule == "unused_declaration" and (finding.project, finding.target) in declarations:
                classification = f"accepted: {declarations[(finding.project, finding.target)]}"
            elif finding.severity == "warn":
                classification = "warning"
            lines.append(f"| {where} | `{finding.project}` | `{finding.target}` | "
                         f"{_cell(finding.message)} | {classification} |")
        lines.append("")
    if declarations:
        lines += ["## Declarations without an import", "", "| Project | Dependency | Reason |", "|---|---|---|"]
        lines += [f"| `{project}` | `{dist}` | {_cell(reason)} |"
                  for (project, dist), reason in sorted(declarations.items())]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=architecture.ROOT)
    parser.add_argument("--out", type=Path, help="write here instead of standard output")
    args = parser.parse_args(argv)
    text = report(architecture.build(args.root))
    if args.out:
        args.out.write_text(text, "utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
