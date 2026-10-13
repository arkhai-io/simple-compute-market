"""The repository's package architecture, read from the tree.

Every project outside the tooling paths is classified by layer, kind, and scope
from its path and name, and its dependencies are every import statement under
``src/`` and every internal distribution its ``pyproject.toml`` declares. The
rules of ``docs/development/ARCHITECTURE.md`` ("Package and dependency layers")
are evaluated over that graph against the tables in
``docs/development/ARCHITECTURE.toml``.

Scope is read from the path and never inferred from imports: a check that
derived a package's permission from its imports would authorize every edge by
the act of adding it. The one exception is a composition's mechanisms, which
are whatever mechanisms the packages it composes know.

Every import node is an edge, at module level, inside a function, under
``TYPE_CHECKING``, or behind ``try``. The context is recorded so a reader can
see where an edge is, and no rule consults it.

Standard library only, so the checks run with a plain ``python3`` and no
project environment. Third-party imports are mapped to nothing: an import root
is internal only when some project ships it as ``src/<package>``.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import tomllib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES_FILE = Path("docs/development/ARCHITECTURE.toml")
SKIPPED_DIRS = {".venv", "node_modules", "openspec", ".git", ".dist", "build", "__pycache__"}

#: Which check script answers for which rules. Exception expiry runs in the
#: script that owns the rule a row names; override expiry runs with layers,
#: because an override changes classification.
GROUPS = {
    "layers": ("configuration", "unclassified", "layer", "cycle", "layer_scope", "override_expiry"),
    "scope": ("scope", "vocabulary"),
    "dependencies": ("undeclared_import", "unused_declaration", "declaration_expiry"),
    "kinds": ("kind_budget", "external_budget", "plugin_in_degree"),
}
RULES = tuple(rule for rules in GROUPS.values() for rule in rules)

_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
#: The keys a package's own ``[tool.arkhai.architecture]`` table may hold. They
#: narrow or annotate the package; none classifies it, so nothing a package
#: declares about itself can widen what its path grants.
PACKAGE_KEYS = frozenset({"allowed-dependencies", "import-roots", "runtime-dependencies"})
_STDLIB = frozenset(sys.stdlib_module_names) | {"__future__"}


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


# --------------------------------------------------------------------------
# Rules file
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Rules:
    layers: tuple[str, ...]
    kind_words: frozenset[str]
    role_words: frozenset[str]
    skip: tuple[str, ...]
    families: dict[str, dict]
    domains: dict[str, dict]
    mechanisms: dict[str, dict]
    plugin_groups: dict[str, str | None]
    budgets: dict[str, dict]
    vocabulary_fail_layers: frozenset[str]
    overrides: tuple[dict, ...]
    exceptions: tuple[dict, ...]
    plugin_group_rows: tuple[dict, ...] = ()

    def element_kind(self, element: str) -> str:
        if element in self.families:
            return "family"
        if element in self.domains:
            return "domain"
        return "mechanism"

    def mechanism_of_kit(self, distribution: str) -> str | None:
        for name, mechanism in self.mechanisms.items():
            if normalize(mechanism["kit"]) == distribution:
                return name
        return None


def load_rules(root: Path) -> Rules:
    data = tomllib.loads((root / RULES_FILE).read_text("utf-8"))
    conventions = data.get("conventions", {})
    return Rules(
        layers=tuple(data["layers"]["order"]),
        kind_words=frozenset(conventions.get("kind_words", ())),
        role_words=frozenset(conventions.get("role_words", ())),
        skip=tuple(conventions.get("skip", ())),
        families={row["name"]: row for row in data.get("families", ())},
        domains={row["name"]: row for row in data.get("domains", ())},
        mechanisms={row["name"]: row for row in data.get("mechanisms", ())},
        plugin_groups={
            row["name"]: normalize(row["owner"]) if row.get("owner") else None
            for row in data.get("plugin_groups", ())
        },
        budgets=data.get("budgets", {}),
        vocabulary_fail_layers=frozenset(data.get("vocabulary", {}).get("fail_layers", ())),
        overrides=tuple(data.get("overrides", ())),
        exceptions=tuple(data.get("exceptions", ())),
        plugin_group_rows=tuple(data.get("plugin_groups", ())),
    )


# --------------------------------------------------------------------------
# Projects and classification
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Reading:
    layer: str
    kind: str
    scope: frozenset[str]


@dataclass
class Project:
    name: str
    path: str
    package: str
    declared: dict[str, tuple[str, int]]  # internal distribution -> (extra or "", line)
    entry_groups: frozenset[str]
    reading: Reading | None
    # Every declared distribution, internal or third-party, with its line.
    declared_all: dict[str, tuple[str, int]] = field(default_factory=dict)
    # The package's own [tool.arkhai.architecture] table.
    settings: dict = field(default_factory=dict)
    # A project whose wheel target is not one package under src/ cannot be
    # read; it is reported rather than skipped.
    malformed: bool = False
    override: dict | None = None
    plugin: bool = False
    layer: str = ""
    kind: str = ""
    scope: frozenset[str] = frozenset()
    # The scope its path or override grants, before a composition's widening.
    own_scope: frozenset[str] = frozenset()

    @property
    def pyproject(self) -> str:
        return f"{self.path}/pyproject.toml"


def _kind_of(segment: str, rules: Rules, roles: bool) -> str:
    words = rules.kind_words | (rules.role_words if roles else frozenset())
    word = segment if segment in words else segment.rsplit("-", 1)[-1] if "-" in segment else ""
    if word not in words:
        return "library"
    return "executable" if word in rules.role_words else word


def read_path(path: str, distribution: str, rules: Rules) -> Reading | None:
    """Layer, kind, and scope as the path and name state them, or None."""
    parts = path.split("/")
    if parts[0] == "core" and len(parts) <= 2:
        return Reading("core", "library", frozenset())
    if parts[0] == "kit" and len(parts) == 2:
        mechanism = rules.mechanism_of_kit(distribution)
        return Reading("kit", _kind_of(parts[1], rules, roles=False),
                       frozenset({mechanism} if mechanism else ()))
    if parts[0] == "roles" and len(parts) == 2:
        return Reading("composition", "executable", frozenset())
    if parts[0] != "domains" or len(parts) < 2:
        return None
    directory = "/".join(parts[:2])
    scope: set[str] = set()
    for name, family in rules.families.items():
        if family["directory"] == directory:
            scope.add(name)
    for name, domain in rules.domains.items():
        if domain["directory"] == directory:
            scope.add(name)
            if domain.get("family"):
                scope.add(domain["family"])
    if not scope:
        return None
    last = parts[-1]
    kind = _kind_of(last, rules, roles=True) if len(parts) > 2 else "library"
    for name in rules.mechanisms:
        if last == name or last.endswith(f"-{name}") or f"-{name}-" in last:
            scope.add(name)
    layer = "composition" if kind == "executable" else "specialization"
    return Reading(layer, kind, frozenset(scope))


def _declared(project: dict, text: str) -> dict[str, tuple[str, int]]:
    requirements = [(req, "") for req in project.get("dependencies", ())]
    for extra, reqs in project.get("optional-dependencies", {}).items():
        requirements += [(req, extra) for req in reqs]
    declared: dict[str, tuple[str, int]] = {}
    lines = text.splitlines()
    for requirement, extra in requirements:
        match = _REQUIREMENT_NAME.match(requirement)
        if not match:
            continue
        name = normalize(match.group(1))
        line = next((i for i, row in enumerate(lines, 1) if requirement in row), 1)
        declared.setdefault(name, (extra, line))
    return declared


def discover(root: Path, rules: Rules) -> dict[str, Project]:
    projects: dict[str, Project] = {}
    for pyproject in sorted(root.rglob("pyproject.toml")):
        relative = pyproject.parent.relative_to(root)
        parts = relative.parts
        if not parts or SKIPPED_DIRS & set(parts):
            continue
        if any(relative.as_posix() == s or relative.as_posix().startswith(f"{s}/") for s in rules.skip):
            continue
        text = pyproject.read_text("utf-8")
        data = tomllib.loads(text)
        if "project" not in data or data.get("tool", {}).get("uv", {}).get("package") is False:
            continue
        packages = data.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {}).get(
            "wheel", {}).get("packages", [])
        name = normalize(data["project"].get("name", relative.as_posix()))
        malformed = len(packages) != 1
        declared = _declared(data["project"], text)
        projects[name] = Project(
            name=name,
            path=relative.as_posix(),
            package="" if malformed else packages[0].rsplit("/", 1)[-1],
            declared=declared,
            entry_groups=frozenset(data["project"].get("entry-points", {})),
            reading=None if malformed else read_path(relative.as_posix(), name, rules),
            declared_all={dist: where for dist, where in declared.items() if dist != name},
            settings=data.get("tool", {}).get("arkhai", {}).get("architecture", {}),
            malformed=malformed,
        )
    internal = set(projects)
    for project in projects.values():
        project.declared = {
            dist: where for dist, where in project.declared.items()
            if dist in internal and dist != project.name
        }
    return projects


def _classify(projects: dict[str, Project], rules: Rules, edges: list[Edge]) -> None:
    overrides = {normalize(row["project"]): row for row in rules.overrides}
    for project in projects.values():
        row = overrides.get(project.name)
        project.override = row
        if project.malformed:
            continue
        if row:
            project.layer, project.kind = row["layer"], row["kind"]
            project.scope = frozenset(row.get("scope", ()))
        elif project.reading:
            project.layer, project.kind = project.reading.layer, project.reading.kind
            project.scope = project.reading.scope
        project.own_scope = project.scope
        project.plugin = any(
            group in rules.plugin_groups and rules.plugin_groups[group] != project.name
            for group in project.entry_groups
        )
    # A composition composes its family's domains when it lives at the
    # family, and whatever mechanisms the packages it depends on know. A
    # composition may depend on another, so the mechanisms are a fixed point.
    targets: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        targets[edge.source].add(edge.target)
    compositions = [p for p in projects.values() if p.layer == "composition"]
    for project in compositions:
        if any(e in rules.domains for e in project.scope):
            continue
        for family in [e for e in project.scope if e in rules.families]:
            project.scope |= {name for name, d in rules.domains.items() if d.get("family") == family}
    changed = True
    while changed:
        changed = False
        for project in compositions:
            mechanisms = {e for t in targets[project.name] for e in projects[t].scope if e in rules.mechanisms}
            if not mechanisms <= project.scope:
                project.scope |= mechanisms
                changed = True


# --------------------------------------------------------------------------
# Edges
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Site:
    file: str
    line: int
    context: str


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    site: Site
    declared: bool  # True for a pyproject declaration, False for an import


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")


class _Imports(ast.NodeVisitor):
    def __init__(self) -> None:
        self.contexts: list[str] = []
        self.found: list[tuple[str, int, str]] = []
        self.literals: list[tuple[str, int, str]] = []
        self.docstrings: set[int] = set()

    def _scope(self, node: ast.AST, context: str | None) -> None:
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            self.docstrings.add(id(body[0].value))
        if context:
            self.contexts.append(context)
        self.generic_visit(node)
        if context:
            self.contexts.pop()

    def visit_Module(self, node: ast.Module) -> None:
        self._scope(node, None)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope(node, None)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope(node, "function")

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_If(self, node: ast.If) -> None:
        if not _is_type_checking(node.test):
            self.generic_visit(node)
            return
        self.contexts.append("type-checking")
        for child in node.body:
            self.visit(child)
        self.contexts.pop()
        for child in node.orelse:
            self.visit(child)

    def visit_Try(self, node: ast.Try) -> None:
        self.contexts.append("try")
        self.generic_visit(node)
        self.contexts.pop()

    visit_TryStar = visit_Try

    def _context(self) -> str:
        return self.contexts[-1] if self.contexts else "module"

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.found.append((alias.name, node.lineno, self._context()))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # A relative import stays inside the importing package.
        if node.level == 0 and node.module:
            self.found.append((node.module, node.lineno, self._context()))

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and id(node) not in self.docstrings:
            self.literals.append((node.value, node.lineno, self._context()))


@dataclass
class Model:
    root: Path
    rules: Rules
    projects: dict[str, Project]
    edges: list[Edge]
    # project -> (import root, site) for every root outside the standard
    # library and the project's own package, internal or third-party.
    externals: dict[str, list[tuple[str, Site]]]
    literals: dict[str, list[tuple[str, Site]]]   # project -> (string literal, site)


def build(root: Path = ROOT) -> Model:
    rules = load_rules(root)
    projects = discover(root, rules)
    owner = {project.package: project.name for project in projects.values()}
    edges: list[Edge] = []
    externals: dict[str, list[tuple[str, Site]]] = defaultdict(list)
    literals: dict[str, list[tuple[str, Site]]] = defaultdict(list)
    for project in projects.values():
        for dist, (extra, line) in project.declared.items():
            context = f"declaration [{extra}]" if extra else "declaration"
            edges.append(Edge(project.name, dist, Site(project.pyproject, line, context), True))
        if project.malformed:
            continue
        source_root = root / project.path / "src" / project.package
        for module in sorted(source_root.rglob("*.py")):
            relative = module.relative_to(root).as_posix()
            visitor = _Imports()
            visitor.visit(ast.parse(module.read_text("utf-8"), filename=relative))
            for name, line, context in visitor.found:
                top = name.split(".", 1)[0]
                site = Site(relative, line, context)
                if owner.get(top) == project.name or top in _STDLIB:
                    continue
                externals[project.name].append((top, site))
                if top in owner:
                    edges.append(Edge(project.name, owner[top], site, False))
            for value, line, context in visitor.literals:
                literals[project.name].append((value, Site(relative, line, context)))
    _classify(projects, rules, edges)
    return Model(root, rules, projects, edges, dict(externals), dict(literals))


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------


@dataclass
class Finding:
    rule: str
    project: str
    target: str
    message: str
    sites: list[Site] = field(default_factory=list)
    severity: str = "fail"
    excused_by: dict | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.rule, self.project, self.target)

    def render(self) -> str:
        where = ""
        if self.sites:
            first = self.sites[0]
            where = f"{first.file}:{first.line}: "
            if first.context != "module":
                where += f"({first.context}) "
            if len(self.sites) > 1:
                where += f"(+{len(self.sites) - 1} more) "
        return f"{where}[{self.rule}] {self.project}: {self.message}"


def _grouped(edges: list[Edge]) -> dict[tuple[str, str], list[Edge]]:
    grouped: dict[tuple[str, str], list[Edge]] = defaultdict(list)
    for edge in edges:
        grouped[(edge.source, edge.target)].append(edge)
    for pair in grouped.values():
        # Report an import site before a declaration: it is the one to change.
        pair.sort(key=lambda e: (e.declared, e.site.file, e.site.line))
    return grouped


def _sites(edges: list[Edge]) -> list[Site]:
    return [edge.site for edge in edges]


def unclassified(model: Model) -> list[Finding]:
    return [
        Finding("unclassified", p.name, p.path,
                f"{p.path} does not build exactly one package under src/, so the check cannot read it"
                if p.malformed else f"{p.path} yields no layer, kind, or scope and has no override row",
                [Site(p.pyproject, 1, "module")])
        for p in model.projects.values() if not p.layer
    ]


def layer(model: Model) -> list[Finding]:
    order = {name: i for i, name in enumerate(model.rules.layers)}
    findings = []
    for (source, target), edges in _grouped(model.edges).items():
        s, t = model.projects[source], model.projects[target]
        if s.layer and t.layer and order[t.layer] > order[s.layer]:
            findings.append(Finding("layer", source, target,
                                    f"a {s.layer} depends on {target}, a {t.layer}", _sites(edges)))
    return findings


def cycle(model: Model) -> list[Finding]:
    graph: dict[str, set[str]] = defaultdict(set)
    for edge in model.edges:
        s, t = model.projects[edge.source], model.projects[edge.target]
        if s.layer and s.layer == t.layer:
            graph[edge.source].add(edge.target)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def connect(node: str) -> None:
        index[node] = low[node] = len(index)
        stack.append(node)
        on_stack.add(node)
        for nxt in sorted(graph[node]):
            if nxt not in index:
                connect(nxt)
                low[node] = min(low[node], low[nxt])
            elif nxt in on_stack:
                low[node] = min(low[node], index[nxt])
        if low[node] == index[node]:
            component = []
            while True:
                member = stack.pop()
                on_stack.discard(member)
                component.append(member)
                if member == node:
                    break
            if len(component) > 1:
                components.append(sorted(component))

    for node in sorted(graph):
        if node not in index:
            connect(node)
    return [
        Finding("cycle", members[0], " -> ".join(members),
                f"the {model.projects[members[0]].layer} packages {', '.join(members)} depend on each other",
                [Site(model.projects[m].pyproject, 1, "module") for m in members])
        for members in components
    ]


def layer_scope(model: Model) -> list[Finding]:
    rules = model.rules
    findings = []
    for p in model.projects.values():
        if not p.layer:
            continue
        problem = None
        if p.layer == "core" and p.scope:
            problem = f"a core package knows {', '.join(sorted(p.scope))}"
        elif p.layer == "kit":
            own = rules.mechanism_of_kit(p.name)
            extra = p.scope - ({own} if own else set())
            if extra:
                problem = f"a kit knows {', '.join(sorted(extra))}, and only a mechanism's own kit may know it"
        elif p.layer == "specialization" and not any(rules.element_kind(e) != "mechanism" for e in p.scope):
            problem = "a specialization knows no family or domain"
        if problem:
            findings.append(Finding("layer_scope", p.name, p.layer, problem,
                                    [Site(p.pyproject, 1, "module")]))
    return findings


def scope(model: Model) -> list[Finding]:
    findings = []
    for (source, target), edges in _grouped(model.edges).items():
        s, t = model.projects[source], model.projects[target]
        # What a composition composes is not knowledge its dependents gain;
        # depending on a composition is the layer rule's finding.
        missing = t.own_scope - s.scope
        if s.layer and t.layer and missing:
            findings.append(Finding(
                "scope", source, target,
                f"depends on {target}, which knows {', '.join(sorted(missing))} outside its scope "
                f"{{{', '.join(sorted(s.scope))}}}", _sites(edges)))
    return findings


def vocabulary(model: Model) -> list[Finding]:
    rules = model.rules
    tokens: dict[str, str] = {}
    for table in (rules.families, rules.domains, rules.mechanisms):
        for name, row in table.items():
            for token in row.get("tokens", ()):
                tokens[token] = name
    findings: dict[tuple[str, str], Finding] = {}
    for name, literals in model.literals.items():
        p = model.projects[name]
        if not p.layer:
            continue
        for value, site in literals:
            element = tokens.get(value)
            if element is None or element in p.scope:
                continue
            key = (name, value)
            if key not in findings:
                severity = "fail" if p.layer in rules.vocabulary_fail_layers else "warn"
                findings[key] = Finding(
                    "vocabulary", name, value,
                    f"names {value!r}, the identity of {element}, outside its scope", [], severity)
            findings[key].sites.append(site)
    return list(findings.values())


def undeclared_import(model: Model) -> list[Finding]:
    findings = []
    for (source, target), edges in _grouped([e for e in model.edges if not e.declared]).items():
        if target not in model.projects[source].declared:
            findings.append(Finding("undeclared_import", source, target,
                                    f"imports {target}, which its pyproject.toml does not declare",
                                    _sites(edges)))
    return findings


def _declaration_rows(model: Model) -> dict[tuple[str, str], str]:
    """Each package's runtime-dependency reasons, keyed by (package, dependency)."""
    return {
        (p.name, normalize(dist)): reason
        for p in model.projects.values()
        for dist, reason in p.settings.get("runtime-dependencies", {}).items()
    }


def unused_declaration(model: Model) -> list[Finding]:
    imported = {(e.source, e.target) for e in model.edges if not e.declared}
    rows = _declaration_rows(model)
    findings = []
    for p in model.projects.values():
        for dist, (extra, line) in sorted(p.declared.items()):
            # Declaring a plugin without importing it is how a host installs
            # one, so the reason needs no row.
            if (p.name, dist) in imported or (p.name, dist) in rows or model.projects[dist].plugin:
                continue
            context = f"declaration [{extra}]" if extra else "declaration"
            findings.append(Finding(
                "unused_declaration", p.name, dist,
                f"declares {dist} without importing it, and its runtime-dependencies give no reason",
                [Site(p.pyproject, line, context)], "warn"))
    return findings


def declaration_expiry(model: Model) -> list[Finding]:
    imported = {(e.source, e.target) for e in model.edges if not e.declared}
    findings = []
    for (project, dist), _reason in _declaration_rows(model).items():
        p = model.projects[project]
        if dist not in p.declared:
            problem = f"gives a runtime reason for {dist}, which it does not declare as an internal dependency"
        elif (project, dist) in imported:
            problem = f"gives a runtime reason for {dist}, which it now imports"
        else:
            continue
        findings.append(Finding("declaration_expiry", project, dist, problem,
                                [Site(p.pyproject, 1, "module")]))
    return findings


def _within_budget(model: Model, source: Project, target: Project, budget: dict) -> bool:
    if target.layer in budget.get("layers", ()) or target.kind in budget.get("kinds", ()):
        return True
    if target.name in {normalize(d) for d in budget.get("distributions", ())}:
        return True
    if budget.get("family_vocabulary"):
        vocabularies = {normalize(f["vocabulary"]) for n, f in model.rules.families.items()
                        if n in source.scope and f.get("vocabulary")}
        return target.name in vocabularies
    return False


def kind_budget(model: Model) -> list[Finding]:
    findings = []
    for (source, target), edges in _grouped(model.edges).items():
        s, t = model.projects[source], model.projects[target]
        budget = model.rules.budgets.get(s.kind)
        if budget is None or _within_budget(model, s, t, budget):
            continue
        findings.append(Finding(
            "kind_budget", source, target,
            f"is a {s.kind} package and depends on {target}, outside its kind's budget",
            _sites(edges), "fail" if budget.get("enforce") else "warn"))
    return findings


def external_budget(model: Model) -> list[Finding]:
    """A package with ``allowed-dependencies`` declares and imports only those.

    The list names distributions, internal or third-party. A declaration is
    checked by name. An internal import root maps to its distribution through
    the tree; a third-party root to the distribution of the same normalized
    name, or through ``import-roots`` where the two are named differently.
    """
    owner = {p.package: p.name for p in model.projects.values() if p.package}
    findings: dict[tuple[str, str], Finding] = {}

    def breach(p: Project, dist: str, site: Site, how: str) -> None:
        key = (p.name, dist)
        if key not in findings:
            findings[key] = Finding("external_budget", p.name, dist,
                                    f"{how} {dist}, which its allowed-dependencies do not list")
        findings[key].sites.append(site)

    for p in model.projects.values():
        if "allowed-dependencies" not in p.settings:
            continue
        allowed = {normalize(d) for d in p.settings["allowed-dependencies"]}
        aliases = {root: normalize(dist) for root, dist in p.settings.get("import-roots", {}).items()}
        for dist, (extra, line) in sorted(p.declared_all.items()):
            if dist not in allowed:
                context = f"declaration [{extra}]" if extra else "declaration"
                breach(p, dist, Site(p.pyproject, line, context), "declares")
        for root, site in model.externals.get(p.name, ()):
            dist = owner.get(root) or aliases.get(root) or normalize(root)
            if dist not in allowed:
                breach(p, dist, site, "imports")
    return list(findings.values())


def _owner_problem(model: Model, owner: str | None) -> str | None:
    changes = model.root / "openspec" / "changes"
    if not owner:
        return "names no owning change"
    if owner == "archive" or not (changes / owner).is_dir():
        return f"names {owner!r}, which is not an unarchived change under openspec/changes/"
    return None


def configuration(model: Model) -> list[Finding]:
    """The rules file and the package tables refer only to things that exist."""
    rules = model.rules
    site = [Site(RULES_FILE.as_posix(), 1, "module")]
    problems: list[tuple[str, str, str]] = []  # (project or table, target, message)
    elements = set(rules.families) | set(rules.domains) | set(rules.mechanisms)

    def unique(rows, key, table):
        seen = set()
        for row in rows:
            k = key(row)
            if k in seen:
                problems.append((table, str(k), f"has a duplicate {table} row for {k}"))
            seen.add(k)

    unique(rules.exceptions, lambda r: (r.get("rule"), r.get("project"), r.get("target")), "exception")
    unique(rules.overrides, lambda r: normalize(r.get("project", "")), "override")
    unique(rules.plugin_group_rows, lambda r: r.get("name"), "plugin-group")
    for name, family in rules.families.items():
        vocabulary = family.get("vocabulary")
        if vocabulary and normalize(vocabulary) not in model.projects:
            problems.append(("family", name, f"family {name} names vocabulary {vocabulary}, which is not a project"))
    for name, domain in rules.domains.items():
        if domain.get("family") and domain["family"] not in rules.families:
            problems.append(("domain", name, f"domain {name} names family {domain['family']}, which is not one"))
    for name, mechanism in rules.mechanisms.items():
        if normalize(mechanism["kit"]) not in model.projects:
            problems.append(("mechanism", name, f"mechanism {name} names kit {mechanism['kit']}, which is not a project"))
    for group, owner in rules.plugin_groups.items():
        if owner and owner not in model.projects:
            problems.append(("plugin-group", group, f"plugin group {group} names owner {owner}, which is not a project"))
    for kind, budget in rules.budgets.items():
        for dist in budget.get("distributions", ()):
            if normalize(dist) not in model.projects:
                problems.append(("budget", f"{kind}:{dist}", f"the {kind} budget names {dist}, which is not a project"))
    for row in rules.overrides:
        project = normalize(row.get("project", ""))
        for element in row.get("scope", ()):
            if element not in elements:
                problems.append((project, f"scope:{element}", f"its override row grants {element}, which is no family, domain, or mechanism"))
        if (why := _owner_problem(model, row.get("owner"))):
            problems.append((project, "owner", f"its override row {why}"))
    for row in rules.exceptions:
        if (why := _owner_problem(model, row.get("owner"))):
            problems.append((normalize(row.get("project", "")), f"owner:{row.get('rule')}:{row.get('target')}",
                             f"its exception row for {row.get('rule')} on {row.get('target')} {why}"))
    findings = [Finding("configuration", project, target, message, list(site))
                for project, target, message in problems]
    for p in model.projects.values():
        for key in sorted(set(p.settings) - PACKAGE_KEYS):
            findings.append(Finding("configuration", p.name, key,
                                    f"its [tool.arkhai.architecture] table has {key!r}, which a package may not declare",
                                    [Site(p.pyproject, 1, "module")]))
    return findings


def plugin_in_degree(model: Model) -> list[Finding]:
    return [
        Finding("plugin_in_degree", source, target,
                f"imports {target}, a plugin; a host declares a plugin and never imports it",
                _sites(edges))
        for (source, target), edges in _grouped([e for e in model.edges if not e.declared]).items()
        if model.projects[target].plugin
    ]


def override_expiry(model: Model) -> list[Finding]:
    findings = []
    for row in model.rules.overrides:
        name = normalize(row["project"])
        p = model.projects.get(name)
        site = [Site(RULES_FILE.as_posix(), 1, "module")]
        if p is None:
            findings.append(Finding("override_expiry", name, "override",
                                    "has an override row but is not a project", site))
            continue
        granted = frozenset(row.get("scope", ()))
        reading = p.reading
        if reading and (reading.layer, reading.kind, reading.scope) == (row["layer"], row["kind"], granted):
            findings.append(Finding("override_expiry", name, "override",
                                    f"{p.path} now classifies as its override row says; delete the row "
                                    f"(owned by {row.get('owner')})", site))
            continue
        # A mechanism granted beyond the path is knowledge the project must
        # use; a family or domain granted is where it belongs, whatever it uses.
        path_scope = reading.scope if reading else frozenset()
        used = {e for edge in model.edges if edge.source == name for e in model.projects[edge.target].scope}
        for mechanism in sorted(e for e in granted - path_scope if e in model.rules.mechanisms):
            if mechanism not in used:
                findings.append(Finding(
                    "override_expiry", name, f"grant:{mechanism}",
                    f"its override row grants {mechanism}, which none of its dependencies knows "
                    f"(owned by {row.get('owner')})", site))
    return findings


CHECKS = {
    "configuration": configuration,
    "unclassified": unclassified,
    "layer": layer,
    "cycle": cycle,
    "layer_scope": layer_scope,
    "scope": scope,
    "vocabulary": vocabulary,
    "undeclared_import": undeclared_import,
    "unused_declaration": unused_declaration,
    "declaration_expiry": declaration_expiry,
    "kind_budget": kind_budget,
    "external_budget": external_budget,
    "plugin_in_degree": plugin_in_degree,
    "override_expiry": override_expiry,
}


def exception_expiry(model: Model, found: list[Finding], rules: tuple[str, ...]) -> list[Finding]:
    """A row excusing nothing: its edge is gone, or no longer breaks its rule."""
    keys = {f.key for f in found}
    expired = []
    for row in model.rules.exceptions:
        rule = row.get("rule", "")
        if rule not in rules:
            continue
        key = (rule, normalize(row["project"]) if rule != "cycle" else row["project"], row["target"])
        if key not in keys:
            expired.append(Finding(
                "exception_expiry", key[1], f"{rule}:{row['target']}",
                f"its exception row for {rule} on {row['target']} excuses no finding; delete it "
                f"(owned by {row.get('owner')})", [Site(RULES_FILE.as_posix(), 1, "module")]))
    return expired


def problems(model: Model, rules: tuple[str, ...] = RULES, strict: bool = False) -> list[Finding]:
    """Every finding of ``rules``, with exceptions applied unless ``strict``."""
    found = [finding for rule in rules if rule in CHECKS for finding in CHECKS[rule](model)]
    if strict:
        return found
    rows = {}
    for row in model.rules.exceptions:
        key_project = row["project"] if row.get("rule") == "cycle" else normalize(row["project"])
        rows[(row.get("rule"), key_project, row["target"])] = row
    for finding in found:
        finding.excused_by = rows.get(finding.key)
    return found + exception_expiry(model, found, rules)


def owned_rows(model: Model, change: str, rules: tuple[str, ...] = RULES) -> list[str]:
    rows = [f"exception: {r['rule']} {r['project']} -> {r['target']}"
            for r in model.rules.exceptions if r.get("owner") == change and r.get("rule") in rules]
    if "override_expiry" in rules:
        rows += [f"override: {r['project']}" for r in model.rules.overrides if r.get("owner") == change]
    return rows


# --------------------------------------------------------------------------
# Command line, shared by the check scripts
# --------------------------------------------------------------------------


def main(group: str, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"Check the {group} rules of the package architecture.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--strict", action="store_true", help="apply no exception row")
    parser.add_argument("--change", help="list the rows this change owns; fail while any remains")
    args = parser.parse_args(argv)
    model = build(args.root)
    rules = GROUPS[group]
    if args.change:
        rows = owned_rows(model, args.change, rules)
        for row in rows:
            print(f"{args.change} owns {row}")
        return 1 if rows else 0
    found = problems(model, rules, strict=args.strict)
    failures = [f for f in found if f.severity == "fail" and not f.excused_by]
    warnings = [f for f in found if f.severity == "warn" and not f.excused_by]
    for finding in failures:
        print(finding.render())
    for finding in warnings:
        print(f"warning: {finding.render()}")
    if failures:
        print(f"FAIL: {len(failures)} {group} finding(s). See docs/development/ARCHITECTURE.md, "
              "\"Package and dependency layers\".")
        return 1
    print(f"OK: the {group} rules hold" + (f" ({len(warnings)} warning(s))." if warnings else "."))
    return 0
