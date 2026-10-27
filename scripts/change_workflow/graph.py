"""The workflow's graph: one table of its nodes, the exits each node's step may take,
the join an exit waits on, and the guards on each exit with the step that satisfies
each.

A node is a step, qualified by the kind of review where routing tells kinds apart:
a design review has other exits than a closeout review, and so has the triage of
each. An exit names the node it leads to, and is taken only once every guard on it
holds; an unmet guard names its remedy — a node whose step satisfies it, or the
owner where no step can — and some name the owner when their remedy has run and
could not satisfy them, as a validation of `HEAD` that failed. A join is the set of
records an exit waits for: the round's triage waits for its sections, the owner's
reading, its validation, and its implementation review, each supplied by a step of
its own.

`scripts/change_next_step.py` interprets the table: it reads where the change
stands and which exit its last step chose from the change's files and log, and
follows that exit through its guards. A guard is checked against the readings that
computation supplies (`Readings`), so the table holds no state of its own. A
*held* guard is not checked as its exit is taken: the computation holds a whole
stretch of the workflow on it. A dependency gating planning, implementation, or
closeout holds every step from that phase on, before the change is read; a clone's
bootstrap holds every step that needs the environment, the round's own
implementation included, and every step while it has not started or has failed.

`make change-graph` prints the table as a Mermaid diagram (`mermaid`), the diagram
the change-workflow architecture shows. A durable change to the workflow is a
change to this table, made as an OpenSpec change. See
openspec/specs/change-workflow/architecture.md, "Routing is code, with the model as
backstop".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence

from change_workflow.records import is_documentation, is_record

Result = dict[str, Any]
# What the reading of where the change stands hands a guard: the review whose
# triage chose the exit, and what the round's reading of it found.
Context = Mapping[str, Any]

OWNER = "owner"
# The remedy of a guard no step satisfies by running: the computation holds the
# step it would name until the condition changes by itself.
WAIT = "wait"
PHASES = ("design", "planning", "implementation", "closeout")

# What each exit is taken on, as the diagram labels it; a triage's `## Next`
# token chooses among them.
ADVANCE = "advance"
ANOTHER_ROUND = "another round"
RETURN = "a return"


@dataclass(frozen=True)
class Node:
    """A step, with the kind of review it is or triages where it has one."""

    step: str
    kind: str | None = None

    @property
    def label(self) -> str:
        """The node as diagrams and documents write it, `review:pre-closeout`; never
        parsed."""
        return f"{self.step}:{self.kind}" if self.kind else self.step

    def result(self, reason: str, **extra: Any) -> Result:
        """The computation's result naming this node's step. A review names its kind;
        a triage names none, since it triages whatever records await it."""
        kind = {"kind": self.kind} if self.kind and self.step == "review" else {}
        return {"step": self.step, **kind, "reason": reason, **extra}


class Readings(Protocol):
    """What the guards read of the change, supplied by the next-step computation. A
    review is that computation's record of one, read for its file and its triage
    file's names."""

    def validated(self, why: str,
                  exempt: Callable[[str], bool] = is_record) -> Result | None: ...

    def fixed_since(self, review: Any, exempt: Callable[[str], bool] = is_record) -> bool: ...

    def changed_outside_documentation(self, review: Any) -> str | None: ...

    def return_confirmed(self, review: Any) -> bool: ...


Check = Callable[[Readings, Context], "Result | None"]


@dataclass(frozen=True)
class Guard:
    """A condition on an exit: what must hold, the step that makes it hold, and what
    follows when that step has run and it still does not."""

    condition: str
    remedy: Node | str
    otherwise: str | None = None
    # None for a held guard, which the computation holds its stretch of the workflow
    # on; otherwise the check, None when the guard holds and the result naming its
    # remedy when it does not.
    check: Check | None = None

    @property
    def held(self) -> bool:
        return self.check is None


@dataclass(frozen=True)
class Join:
    """The records an exit waits for, each with the node whose step supplies it."""

    waits_for: tuple[tuple[str, Node], ...]


@dataclass(frozen=True)
class Exit:
    target: Node
    guards: tuple[Guard, ...] = ()
    when: str | None = None
    join: Join | None = None


@dataclass(frozen=True)
class Declaration:
    """A node of the table: its exits, the phases the change is in while its step
    runs, and the step a run of it is logged as, None for a step the log does not
    record."""

    node: Node
    exits: tuple[Exit, ...]
    phases: tuple[str, ...]
    runs: str | None


DESIGN = Node("design")
DESIGN_REVIEW = Node("review", "design")
DESIGN_TRIAGE = Node("triage", "design")
PLAN = Node("plan")
# The plan's next round, recorded as it starts; each of its sessions implements
# sections, and the round's in progress while one is unchecked.
ROUND = Node("round")
ROUND_VIEW = Node("round-view")
VALIDATE = Node("validate")
IMPLEMENTATION_REVIEW = Node("review", "implementation")
IMPLEMENTATION_TRIAGE = Node("triage", "implementation")
PRE_CLOSEOUT_REVIEW = Node("review", "pre-closeout")
PRE_CLOSEOUT_TRIAGE = Node("triage", "pre-closeout")
CLOSEOUT = Node("closeout")
CLOSEOUT_REVIEW = Node("review", "closeout")
CLOSEOUT_TRIAGE = Node("triage", "closeout")
ARCHIVE_CLEANUP = Node("archive-cleanup")


def owner(reason: str, **extra: Any) -> Result:
    return {"step": OWNER, "reason": reason, **extra}


# The guards' checks. Each reads only what `Readings` and the context supply.

def _return_confirmed(readings: Readings, context: Context) -> Result | None:
    review = context["review"]
    if readings.return_confirmed(review):
        return None
    return owner(f"{review.triage.name} records a return the owner has not confirmed: "
                 "resume its triage if it stopped before proposing the return, or decide "
                 "what the triage records")


def _validated(why: str, exempt: Callable[[str], bool] = is_record) -> Check:
    return lambda readings, _: readings.validated(why, exempt)


def _fix_validated(exempt: Callable[[str], bool]) -> Check:
    """A fix the triage accepted, once committed since its review read `HEAD`,
    validated before the review runs again; with no fix, the same commit is
    reviewed again whatever its validation said."""
    def check(readings: Readings, context: Context) -> Result | None:
        review = context["review"]
        if not readings.fixed_since(review, exempt):
            return None
        return readings.validated(f"{review.triage.name} records another round, and the "
                                  "fix committed since needs validating", exempt)
    return check


def _fix_read(_: Readings, context: Context) -> Result | None:
    """The owner reads a repeat pass's fix before it is validated and reviewed, in a
    change worked in this checkout, since the view moves the branch the fix's
    validation and review would run on. In a clone the reading runs beside them
    and holds neither."""
    if not context["unread"] or context["in_clone"]:
        return None
    return {"step": ROUND_VIEW.step, **context["base"],
            "reason": f"{context['review'].triage.name} records another round over a fix; "
                      "the owner reads the fix"}


def _correction_validated(readings: Readings, context: Context) -> Result | None:
    """Measured from the commit the first closeout review read, the archive: a code
    fix an earlier round of closeout reviews committed is still unvalidated when
    the latest review read it."""
    first = context["first"]
    if not (changed := readings.changed_outside_documentation(first)):
        return None
    return readings.validated(f"HEAD changes {changed} since {first.path.name} reviewed the "
                              "archive, so it is validated before archive cleanup")


VALIDATION_FAILED = "failed or inconclusive: owner"

PLANNING_RELEASED = Guard("a dependency gating planning released", OWNER)
IMPLEMENTATION_RELEASED = Guard("a dependency gating implementation released", OWNER)
CLOSEOUT_RELEASED = Guard("a dependency gating closeout released", OWNER)
BOOTSTRAPPED = Guard("in a clone, the bootstrap finished", WAIT, "failed: owner")
RETURN_CONFIRMED = Guard("the owner's confirmation", OWNER, check=_return_confirmed)
HEAD_VALIDATED = Guard("HEAD validated, records exempt", VALIDATE, VALIDATION_FAILED,
                       _validated("a pre-closeout review needs a passing validation of HEAD"))
ROUND_FIX_VALIDATED = Guard("the fix commit validated, records exempt", VALIDATE,
                            VALIDATION_FAILED,
                            _validated("the round's fixes need validating"))
REPEAT_FIX_READ = Guard("a fix committed since the review read", ROUND_VIEW, check=_fix_read)
REPEAT_FIX_VALIDATED = Guard("a fix committed since the review validated", VALIDATE,
                             VALIDATION_FAILED, _fix_validated(is_record))
CLOSEOUT_VALIDATED = Guard("HEAD validated, openspec/ and docs/ exempt", VALIDATE,
                           VALIDATION_FAILED,
                           _validated("closeout needs a passing validation of HEAD",
                                      is_documentation))
DOCUMENTED_FIX_VALIDATED = Guard("a fix outside openspec/ and docs/ validated", VALIDATE,
                                 VALIDATION_FAILED, _fix_validated(is_documentation))
CORRECTION_VALIDATED = Guard("a path outside openspec/ and docs/ changed since the first "
                             "closeout review: HEAD validated", VALIDATE, VALIDATION_FAILED,
                             _correction_validated)

ROUND_JOIN = Join((("the round's sections checked", ROUND),
                   ("the owner's reading", ROUND_VIEW),
                   ("its validation", VALIDATE),
                   ("its implementation review", IMPLEMENTATION_REVIEW)))
TO_ROUND_TRIAGE = Exit(IMPLEMENTATION_TRIAGE, join=ROUND_JOIN)


def _declare(node: Node, phases: tuple[str, ...], *exits: Exit,
             runs: str | None = None) -> Declaration:
    return Declaration(node, exits, phases, runs or node.step)


_STEPS = (
    _declare(DESIGN, ("design",), Exit(DESIGN_REVIEW)),
    _declare(DESIGN_REVIEW, ("design",), Exit(DESIGN_TRIAGE)),
    _declare(DESIGN_TRIAGE, ("design",),
             Exit(PLAN, (PLANNING_RELEASED,), ADVANCE),
             Exit(DESIGN_REVIEW, when=ANOTHER_ROUND),
             Exit(DESIGN, (RETURN_CONFIRMED,), RETURN)),
    _declare(PLAN, ("planning",),
             Exit(ROUND, (IMPLEMENTATION_RELEASED,)),
             Exit(PRE_CLOSEOUT_REVIEW, (HEAD_VALIDATED,), "nothing to implement")),
    _declare(ROUND, ("implementation",),
             Exit(IMPLEMENTATION_TRIAGE, (BOOTSTRAPPED,), join=ROUND_JOIN),
             runs="implement"),
    _declare(IMPLEMENTATION_REVIEW, ("implementation",), TO_ROUND_TRIAGE),
    _declare(IMPLEMENTATION_TRIAGE, ("implementation",),
             Exit(ROUND, (ROUND_FIX_VALIDATED,), ADVANCE),
             Exit(ROUND, (ROUND_FIX_VALIDATED,), "sections out of the plan's order"),
             Exit(PRE_CLOSEOUT_REVIEW, (ROUND_FIX_VALIDATED,), "advance, after the last round"),
             Exit(IMPLEMENTATION_REVIEW, (REPEAT_FIX_READ, REPEAT_FIX_VALIDATED),
                  ANOTHER_ROUND),
             Exit(PLAN, (RETURN_CONFIRMED,), RETURN),
             Exit(DESIGN, (RETURN_CONFIRMED,), RETURN)),
    _declare(PRE_CLOSEOUT_REVIEW, ("implementation",), Exit(PRE_CLOSEOUT_TRIAGE)),
    _declare(PRE_CLOSEOUT_TRIAGE, ("implementation",),
             Exit(CLOSEOUT, (CLOSEOUT_RELEASED, CLOSEOUT_VALIDATED), ADVANCE),
             Exit(PRE_CLOSEOUT_REVIEW, (DOCUMENTED_FIX_VALIDATED,), ANOTHER_ROUND),
             Exit(PLAN, (RETURN_CONFIRMED,), RETURN),
             Exit(DESIGN, (RETURN_CONFIRMED,), RETURN)),
    _declare(CLOSEOUT, ("closeout",), Exit(CLOSEOUT_REVIEW)),
    _declare(CLOSEOUT_REVIEW, ("closeout",), Exit(CLOSEOUT_TRIAGE)),
    # An archived change has no earlier phase, so a closeout triage has no return.
    _declare(CLOSEOUT_TRIAGE, ("closeout",),
             Exit(ARCHIVE_CLEANUP, (CORRECTION_VALIDATED,), ADVANCE),
             Exit(CLOSEOUT_REVIEW, when=ANOTHER_ROUND)),
    # The change is done once archive cleanup has run.
    _declare(ARCHIVE_CLEANUP, ("closeout",)),
)


def _remedying(remedy: Node, phases: tuple[str, ...], runs: str | None) -> Declaration:
    """A node whose step is a join's member or a guard's remedy. Its exits are each
    join it supplies, and each exit whose guard it remedies, with that exit's guards,
    which are checked again once it has run: the computation names the exit's target
    only when they hold."""
    found: dict[tuple[Node, str | None], Exit] = {}
    for declaration in _STEPS:
        for exit_ in declaration.exits:
            if exit_.join and remedy in (node for _, node in exit_.join.waits_for):
                found.setdefault((exit_.target, None), Exit(exit_.target, join=exit_.join))
            elif any(guard.remedy == remedy for guard in exit_.guards):
                found.setdefault((exit_.target, exit_.when), exit_)
    return Declaration(remedy, tuple(found.values()), phases, runs)


TABLE: tuple[Declaration, ...] = _STEPS + (
    _remedying(ROUND_VIEW, ("implementation",), None),
    _remedying(VALIDATE, ("implementation", "closeout"), VALIDATE.step),
)
NODES: dict[Node, Declaration] = {declaration.node: declaration for declaration in TABLE}


def exits(source: Node, *, target: Node | None = None, when: str | None = None) -> list[Exit]:
    """The exits of `source` to `target`, or taken on `when`, in the table's order."""
    return [exit_ for exit_ in NODES[source].exits
            if (target is None or exit_.target == target)
            and (when is None or exit_.when == when)]


def phase_steps(phase: str) -> tuple[str, ...]:
    """The steps whose runs the log records while the change is in `phase`."""
    return tuple(dict.fromkeys(declaration.runs for declaration in TABLE
                               if phase in declaration.phases and declaration.runs))


def review_phase(kind: str) -> str | None:
    """The phase a review of `kind` runs in; None for a kind the table has no review
    of."""
    declaration = NODES.get(Node("review", kind))
    return declaration.phases[0] if declaration else None


# The diagram: the table drawn as a Mermaid flowchart, which the change-workflow
# architecture shows and a test holds to this rendering.

def _id(node: Node) -> str:
    return node.label.replace(":", "_").replace("-", "_")


def _remedy(remedy: Node | str) -> str:
    return remedy.label if isinstance(remedy, Node) else remedy


def _guard(guard: Guard) -> str:
    otherwise = f", {guard.otherwise}" if guard.otherwise else ""
    held = " (held)" if guard.held else ""
    return f"{guard.condition} ⇒ {_remedy(guard.remedy)}{otherwise}{held}"


def mermaid(table: Sequence[Declaration] = TABLE) -> str:
    """The table as a Mermaid flowchart: a box for each node, an edge for each exit
    labelled with what it is taken on and each guard with its remedy, and a hexagon
    for each join, which the exits waiting on it enter, labelled with the record
    their node supplies. The same table always renders the same text."""
    lines = ["flowchart TD"]
    lines += [f'    {_id(d.node)}["{d.node.label}"]' for d in table]
    joins = {exit_.join: exit_.target for d in table for exit_ in d.exits if exit_.join}
    lines += [f'    join_{_id(target)}{{{{"join"}}}}' for target in joins.values()]
    for declaration in table:
        for exit_ in declaration.exits:
            supplies = [what for what, node in exit_.join.waits_for
                        if node == declaration.node] if exit_.join else []
            label = "<br/>".join([*supplies, *([exit_.when] if exit_.when else []),
                                  *map(_guard, exit_.guards)])
            arrow = f'-->|"{label}"|' if label else "-->"
            target = f"join_{_id(exit_.target)}" if exit_.join else _id(exit_.target)
            lines.append(f"    {_id(declaration.node)} {arrow} {target}")
    lines += [f"    join_{_id(target)} --> {_id(target)}" for target in joins.values()]
    return "\n".join(lines) + "\n"


def main() -> int:
    print(mermaid(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
