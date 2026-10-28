"""A staged scenario's stages and state, read from source.

Every staged scenario family's source check reads its modules through these, so
a scenario module is checked without its lane's settings or services. A shared
stage is a class with ``test_`` methods that is not named ``Test*``; a domain
declares it by subclassing it with an empty body, so the body that runs is the
shared one.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


def tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def classes(module: ast.Module) -> list[ast.ClassDef]:
    return [node for node in module.body if isinstance(node, ast.ClassDef)]


def class_named(module: ast.Module, name: str) -> ast.ClassDef:
    (found,) = [node for node in classes(module) if node.name == name]
    return found


def fields(node: ast.ClassDef) -> set[str]:
    return {
        item.target.id
        for item in node.body
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
    }


def base_names(node: ast.ClassDef) -> list[str]:
    return [base.id for base in node.bases if isinstance(base, ast.Name)]


def is_stage(node: ast.ClassDef) -> bool:
    return any(
        isinstance(item, ast.FunctionDef) and item.name.startswith("test_")
        for item in node.body
    )


@dataclass
class StateUse:
    written: set[str]
    read: set[str]
    required: set[str]


def state_use(nodes: list[ast.AST], *, state: str) -> StateUse:
    """Which fields of the fixture named ``state`` the nodes -- stage classes or
    their tests -- write, read, and require.

    ``read`` holds plain attribute reads; ``required`` the fields named to
    ``require_state``.
    """
    use = StateUse(set(), set(), set())
    for node in nodes:
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Attribute)
                and isinstance(sub.value, ast.Name)
                and sub.value.id == state
            ):
                (use.written if isinstance(sub.ctx, ast.Store) else use.read).add(sub.attr)
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Name)
                and sub.func.id == "require_state"
                and sub.args
                and isinstance(sub.args[0], ast.Name)
                and sub.args[0].id == state
            ):
                for arg in sub.args[1:]:
                    assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), (
                        f"require_state names a field with a non-literal at line {arg.lineno}"
                    )
                    use.required.add(arg.value)
    return use


def domain_stages(scenario: Path) -> list[ast.ClassDef]:
    """The stages a domain's scenario module declares, in run order."""
    return [node for node in classes(tree(scenario)) if node.name.startswith("Test")]


def running_stages(
    scenario: Path, shared: list[ast.ClassDef]
) -> list[tuple[str, ast.ClassDef]]:
    """The domain's stages in run order, each with the body that runs.

    A subclass of a shared stage runs the shared body; a domain's own stage
    runs its own.
    """
    by_name = {node.name: node for node in shared}
    stages = []
    for node in domain_stages(scenario):
        bases = [name for name in base_names(node) if name in by_name]
        stages.append((node.name, by_name[bases[0]] if bases else node))
    return stages


def run_order(
    scenario: Path, shared: list[ast.ClassDef], *, state: str
) -> list[tuple[str, StateUse]]:
    """The domain's stages in run order, each with its body's use of ``state``."""
    return [
        (name, state_use([body], state=state))
        for name, body in running_stages(scenario, shared)
    ]
