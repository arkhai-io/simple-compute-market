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

`scripts/change_next_step.py` interprets the table: it reads the exit the last
step's outcome named, or the owner's direction, from the change's log, checks it
against the exits the table declares, and follows it through its guards. A guard is
checked against the readings that computation supplies (`Readings`), so the table
holds no state of its own. A
*held* guard is not checked as its exit is taken: the computation holds a whole
stretch of the workflow on it. A dependency gating planning, implementation, or
closeout holds every step from that phase on, before the change is read; a clone's
bootstrap holds every step that needs the environment, the round's own
implementation included, and every step while it has not started or has failed.

A step's exit, an owner's direction, and the computation's result name a node the
same way, as a target: an object naming its step, with `kind` for a review and for a
triage the kind of review it triages, `sections` for an implementation out of the
plan's order, and for a validation the `target` it is for (`node_of`). Its label,
`review:pre-closeout`, is drawn in diagrams and documents and never parsed.

A node may also have entry guards: conditions on entering it at all, by a step's
exit or by the owner's direction, which checks no exit guard. An unwaivable one
refuses every entry while it is not met (`entry_refusal`); a waivable one takes the
owner's direction as its override.

The change-workflow architecture shows the table as a diagram laid out by hand,
held to the table's boxes and edges (`drawing`); `make change-graph` prints it as a
Mermaid flowchart (`mermaid`) for whoever redraws it. A durable change to the
workflow is a change to this table, made as an OpenSpec change. See
openspec/specs/change-workflow/architecture.md, "Routing is code, with the model as
backstop".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence

from change_workflow.common import StepError
from change_workflow.records import is_documentation, is_record

Result = dict[str, Any]
# What the reading of where the change stands hands a guard: the run whose outcome
# named the exit, the review a triage's outcome named, and what the round's reading
# of it found.
Context = Mapping[str, Any]

OWNER = "owner"
# The remedy of a guard no step satisfies by running: the computation holds the
# step it would name until the condition changes by itself.
WAIT = "wait"
PHASES = ("design", "planning", "implementation", "closeout")

# What each exit is taken on, as the diagram labels it. A step's outcome names the
# exit's target; where a node has two exits to one target, the target's sections say
# which (`OUT_OF_ORDER`).
ADVANCE = "advance"
ANOTHER_ROUND = "another round"
RETURN = "a return"
OUT_OF_ORDER = "sections out of the plan's order"


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
        """The computation's result naming this node's step: a review with its kind,
        a triage with the kind of review it triages."""
        kind = {"kind": self.kind} if self.kind else {}
        return {"step": self.step, **kind, "reason": reason, **extra}


class Readings(Protocol):
    """What the guards read of the change, supplied by the next-step computation. A
    review is that computation's record of one, read for its file and its triage
    file's names; a run is a line of the workflow log."""

    def validated(self, why: str,
                  exempt: Callable[[str], bool] = is_record) -> Result | None: ...

    def fixed_since(self, review: Any, exempt: Callable[[str], bool] = is_record) -> bool: ...

    def changed_outside_documentation(self, review: Any) -> str | None: ...

    def return_confirmed(self, run: Mapping[str, Any]) -> bool: ...


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
class Standing:
    """What the entry guards read of the change: whether it is archived, and the
    kinds of review awaiting triage."""

    archived: bool
    awaiting: frozenset[str]


# Why an entry guard is not met for an entry to `target`, the entry a direction
# when `directed`; None when it is met.
EntryCheck = Callable[[Standing, Mapping[str, Any], bool], "str | None"]


@dataclass(frozen=True)
class EntryGuard:
    """A condition on entering a node, by a step's exit or the owner's direction,
    without which its step cannot, or should not, carry out its work.

    An unwaivable guard refuses every entry while it is not met. A waivable one
    takes the owner's direction as its override, and on a step's exit is met first
    by the exit guard that remedies it, so nothing here checks it: the step's own
    entry check reads it (`check` None).
    """

    condition: str
    waivable: bool = False
    check: EntryCheck | None = None


@dataclass(frozen=True)
class Declaration:
    """A node of the table: its exits, the phases the change is in while its step
    runs, the step a run of it is logged as, None for a step the log does not
    record, and its entry guards."""

    node: Node
    exits: tuple[Exit, ...]
    phases: tuple[str, ...]
    runs: str | None
    entry: tuple[EntryGuard, ...] = ()


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
# The change is done: no step runs, and nothing leads on.
DONE = Node("done")


def owner(reason: str, **extra: Any) -> Result:
    return {"step": OWNER, "reason": reason, **extra}


# The guards' checks. Each reads only what `Readings` and the context supply.

def _return_confirmed(readings: Readings, context: Context) -> Result | None:
    run = context["run"]
    if readings.return_confirmed(run):
        return None
    return owner(f"the {run.get('step')} run at seq {run.get('seq')} proposed a return the "
                 "owner has not confirmed: the owner confirms it by a decision that resolves "
                 "the run and directs the step returned to, or decides what follows")


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

# The entry guards. The archive is the boundary no entry crosses: an archived change
# is not returned to an earlier phase, since its deltas are merged into the
# specifications, and a change not archived is not taken past it, since the closeout
# review reads the archive and archive cleanup would mark `archived` a change whose
# deltas were never merged.

def _archived(standing: Standing, _: Mapping[str, Any], __: bool) -> str | None:
    return None if standing.archived else "the change is not archived"


def _not_archived(standing: Standing, _: Mapping[str, Any], __: bool) -> str | None:
    return "the change is archived" if standing.archived else None


def _awaits_triage(standing: Standing, target: Mapping[str, Any], _: bool) -> str | None:
    kind = target["kind"]
    return None if kind in standing.awaiting else (f"no {kind} review, and no validation "
                                                   "after it, awaits triage")


def _carries_target(_: Standing, target: Mapping[str, Any], __: bool) -> str | None:
    try:
        node_of(target)
    except TargetError as exc:
        return str(exc)
    return None


def _never_directed(_: Standing, __: Mapping[str, Any], directed: bool) -> str | None:
    return "the change is done only once archive cleanup has run" if directed else None


NOT_ARCHIVED = EntryGuard("the change is not archived", check=_not_archived)
ARCHIVED = EntryGuard("the change is archived", check=_archived)
AWAITS_TRIAGE = EntryGuard("a review of its kind, or a validation after it, awaits triage",
                           check=_awaits_triage)
CARRIES_TARGET = EntryGuard("it carries a target that is a node", check=_carries_target)
NEVER_DIRECTED = EntryGuard("reached only by archive cleanup's exit", check=_never_directed)
# The review checks it itself as it starts (`change_workflow.review`), taking the
# owner's direction to it, or `--unvalidated`, as the override.
REVIEW_VALIDATED = EntryGuard("the latest validation passed for HEAD, or for an ancestor it "
                              "differs from only in records, or after a pre-closeout triage "
                              "only in openspec/ and docs/", waivable=True)

ROUND_JOIN = Join((("the round's sections checked", ROUND),
                   ("the owner's reading", ROUND_VIEW),
                   ("its validation", VALIDATE),
                   ("its implementation review", IMPLEMENTATION_REVIEW)))
TO_ROUND_TRIAGE = Exit(IMPLEMENTATION_TRIAGE, join=ROUND_JOIN)


def _declare(node: Node, phases: tuple[str, ...], *exits: Exit, runs: str | None = None,
             entry: tuple[EntryGuard, ...] = ()) -> Declaration:
    return Declaration(node, exits, phases, runs or node.step, entry)


_STEPS = (
    _declare(DESIGN, ("design",), Exit(DESIGN_REVIEW), entry=(NOT_ARCHIVED,)),
    _declare(DESIGN_REVIEW, ("design",), Exit(DESIGN_TRIAGE)),
    _declare(DESIGN_TRIAGE, ("design",),
             Exit(PLAN, (PLANNING_RELEASED,), ADVANCE),
             Exit(DESIGN_REVIEW, when=ANOTHER_ROUND),
             Exit(DESIGN, (RETURN_CONFIRMED,), RETURN), entry=(AWAITS_TRIAGE,)),
    _declare(PLAN, ("planning",),
             Exit(ROUND, (IMPLEMENTATION_RELEASED,)),
             Exit(PRE_CLOSEOUT_REVIEW, (HEAD_VALIDATED,), "nothing to implement"),
             entry=(NOT_ARCHIVED,)),
    _declare(ROUND, ("implementation",),
             Exit(IMPLEMENTATION_TRIAGE, (BOOTSTRAPPED,), join=ROUND_JOIN),
             runs="implement", entry=(NOT_ARCHIVED,)),
    _declare(IMPLEMENTATION_REVIEW, ("implementation",), TO_ROUND_TRIAGE),
    _declare(IMPLEMENTATION_TRIAGE, ("implementation",),
             Exit(ROUND, (ROUND_FIX_VALIDATED,), ADVANCE),
             Exit(ROUND, (ROUND_FIX_VALIDATED,), OUT_OF_ORDER),
             Exit(PRE_CLOSEOUT_REVIEW, (ROUND_FIX_VALIDATED,), "advance, after the last round"),
             Exit(IMPLEMENTATION_REVIEW, (REPEAT_FIX_READ, REPEAT_FIX_VALIDATED),
                  ANOTHER_ROUND),
             Exit(PLAN, (RETURN_CONFIRMED,), RETURN),
             Exit(DESIGN, (RETURN_CONFIRMED,), RETURN), entry=(AWAITS_TRIAGE,)),
    _declare(PRE_CLOSEOUT_REVIEW, ("implementation",), Exit(PRE_CLOSEOUT_TRIAGE),
             entry=(REVIEW_VALIDATED,)),
    _declare(PRE_CLOSEOUT_TRIAGE, ("implementation",),
             Exit(CLOSEOUT, (CLOSEOUT_RELEASED, CLOSEOUT_VALIDATED), ADVANCE),
             Exit(PRE_CLOSEOUT_REVIEW, (DOCUMENTED_FIX_VALIDATED,), ANOTHER_ROUND),
             Exit(PLAN, (RETURN_CONFIRMED,), RETURN),
             Exit(DESIGN, (RETURN_CONFIRMED,), RETURN), entry=(AWAITS_TRIAGE,)),
    # Closeout has no archive guard: it is the step that archives.
    _declare(CLOSEOUT, ("closeout",), Exit(CLOSEOUT_REVIEW)),
    _declare(CLOSEOUT_REVIEW, ("closeout",), Exit(CLOSEOUT_TRIAGE), entry=(ARCHIVED,)),
    # An archived change has no earlier phase, so a closeout triage has no return.
    _declare(CLOSEOUT_TRIAGE, ("closeout",),
             Exit(ARCHIVE_CLEANUP, (CORRECTION_VALIDATED,), ADVANCE),
             Exit(CLOSEOUT_REVIEW, when=ANOTHER_ROUND), entry=(ARCHIVED, AWAITS_TRIAGE)),
    _declare(ARCHIVE_CLEANUP, ("closeout",), Exit(DONE), entry=(ARCHIVED,)),
    Declaration(DONE, (), ("closeout",), None, (NEVER_DIRECTED,)),
)


def _remedying(remedy: Node, phases: tuple[str, ...], runs: str | None,
               entry: tuple[EntryGuard, ...] = ()) -> Declaration:
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
    return Declaration(remedy, tuple(found.values()), phases, runs, entry)


TABLE: tuple[Declaration, ...] = _STEPS + (
    _remedying(ROUND_VIEW, ("implementation",), None),
    # A validation names the target it is for, whose own entry guards are checked
    # on the validation's exit: a round's validation starts before the review its
    # target triages is published.
    _remedying(VALIDATE, ("implementation", "closeout"), VALIDATE.step, (CARRIES_TARGET,)),
)
NODES: dict[Node, Declaration] = {declaration.node: declaration for declaration in TABLE}
# The steps whose nodes are told apart by the kind of review they are or triage.
_KINDED = {node.step for node in NODES if node.kind}


class TargetError(StepError):
    """A target names no node of the table."""


def section_ids(sessions: Any) -> bool:
    """Whether `sessions` is a list of sessions, each a non-empty list of section ids,
    each a positive whole number or a name."""
    return (isinstance(sessions, list) and bool(sessions)
            and all(isinstance(session, list) and session
                    and all((isinstance(section, int) and not isinstance(section, bool))
                            or (isinstance(section, str) and section)
                            for section in session)
                    for session in sessions))


def node_of(target: Any) -> Node:
    """The node `target` names, or `TargetError` saying why it names none.

    A review or a triage is a node only with its kind: without one, or with an
    empty or unknown one, it is refused rather than read as any review. An
    implementation names its sections, which it takes out of the plan's order, and is
    the round that implements them. A validation names the target it is for, itself
    a node and not another validation.
    """
    if not isinstance(target, Mapping) or not isinstance(target.get("step"), str):
        raise TargetError(f"a target is an object naming its step; got {target!r}")
    step = target["step"]
    if unknown := sorted(set(target) - {"step", "kind", "sections", "target"}):
        raise TargetError(f"a target names its step, kind, sections, or target, not "
                          f"{', '.join(unknown)}")
    if "kind" in target and step not in _KINDED:
        raise TargetError(f"only a review or a triage names a kind, not {step!r}")
    if "sections" in target and step != "implement":
        raise TargetError(f"only an implementation names sections, not {step!r}")
    if "target" in target and step != VALIDATE.step:
        raise TargetError(f"only a validation names a target, not {step!r}")
    if step in _KINDED:
        kind = target.get("kind")
        if not isinstance(kind, str) or not kind:
            raise TargetError(f"a {step} is a node only with the kind of review it "
                              f"{'is' if step == 'review' else 'triages'}; got "
                              f"{target!r}")
        node = Node(step, kind)
        if node not in NODES:
            raise TargetError(f"{node.label} is no node: {kind!r} is not a kind of review")
        return node
    if step == "implement":
        if not section_ids(target.get("sections")):
            raise TargetError("an implementation names its sessions, each a non-empty list "
                              f"of sections; got {target.get('sections')!r}")
        return ROUND
    if step == VALIDATE.step:
        if "target" not in target:
            raise TargetError("a validation names the target it is for")
        if node_of(target["target"]) == VALIDATE:
            raise TargetError("a validation is for a target other than another validation")
        return VALIDATE
    if Node(step) not in NODES:
        raise TargetError(f"{step!r} is no node of the workflow graph")
    return Node(step)


def entry_refusal(target: Mapping[str, Any], standing: Standing, *,
                  directed: bool) -> str | None:
    """Why an entry to `target` — the owner's direction when `directed`, else a
    step's exit — is refused: the first unwaivable entry guard not met of a node it
    names, the target and, for a validation, the target nested in it. None when
    every one is met.

    A waivable guard refuses nothing here: a direction is its override, and on a
    step's exit the exit guard that remedies it is met first. A validation is
    checked for its nested target only when directed: the computation names a
    validation before the review its target triages may be published, and checks
    the target's guards on the validation's exit.
    """
    try:
        node = node_of(target)
    except TargetError:
        # A validation without a target that is a node is refused by its own entry
        # guard, which says so; any other target that names no node is no entry.
        if not (isinstance(target, Mapping) and target.get("step") == VALIDATE.step):
            raise
        node = VALIDATE
    for guard in NODES[node].entry:
        if not guard.waivable and guard.check and (why := guard.check(standing, target,
                                                                      directed)):
            return f"{node.label}'s entry guard ({guard.condition}) is not met: {why}"
    if node == VALIDATE and directed:
        return entry_refusal(target["target"], standing, directed=directed)
    return None


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


# The diagram. The change-workflow architecture shows a drawing laid out by hand,
# `docs/development/diagrams/change-workflow-graph.drawio` with its SVG export,
# which a test holds to the table's boxes and edges (`drawing`), whatever its
# layout. `make change-graph` prints the table as a Mermaid flowchart (`mermaid`),
# for whoever redraws it.

def _id(node: Node) -> str:
    return node.label.replace(":", "_").replace("-", "_")


def _remedy(remedy: Node | str) -> str:
    return remedy.label if isinstance(remedy, Node) else remedy


def guard_text(guard: Guard) -> str:
    """A guard as the diagrams write it: its condition, its remedy, and what follows
    when the remedy has run and it still does not hold."""
    otherwise = f", {guard.otherwise}" if guard.otherwise else ""
    held = " (held)" if guard.held else ""
    return f"{guard.condition} ⇒ {_remedy(guard.remedy)}{otherwise}{held}"


@dataclass(frozen=True)
class Edge:
    """An exit as a diagram draws it: from a box to a box or a join, labelled with
    the record its node supplies a join, what it is taken on, and its guards."""

    source: str
    target: str
    supplies: tuple[str, ...]
    when: str | None
    guards: tuple[Guard, ...]

    @property
    def pieces(self) -> tuple[str, ...]:
        return (*self.supplies, *([self.when] if self.when else []),
                *map(guard_text, self.guards))


def drawing(table: Sequence[Declaration] = TABLE) -> tuple[dict[str, tuple[str, ...]],
                                                             list[Edge]]:
    """What any diagram of the table draws: a box for each node, by id, holding its
    label and its entry guards, and one for each join; and an edge for each exit,
    entering the join it waits on, then one from each join to its target."""
    boxes = {_id(d.node): (d.node.label, *(f"entry: {guard.condition}"
                                           + (" (waivable)" if guard.waivable else "")
                                           for guard in d.entry)) for d in table}
    joins = {exit_.join: exit_.target for d in table for exit_ in d.exits if exit_.join}
    boxes.update({f"join_{_id(target)}": ("join",) for target in joins.values()})
    edges = [Edge(_id(d.node), f"join_{_id(exit_.target)}" if exit_.join else _id(exit_.target),
                  tuple(what for what, node in exit_.join.waits_for if node == d.node)
                  if exit_.join else (), exit_.when, exit_.guards)
             for d in table for exit_ in d.exits]
    edges += [Edge(f"join_{_id(target)}", _id(target), (), None, ())
              for target in joins.values()]
    return boxes, edges


def mermaid(table: Sequence[Declaration] = TABLE) -> str:
    """The table as a Mermaid flowchart: a box for each node with its entry guards,
    an edge for each exit labelled with what it is taken on and each guard with its
    remedy, and a hexagon for each join, which the exits waiting on it enter,
    labelled with the record their node supplies. The same table always renders the
    same text."""
    boxes, edges = drawing(table)
    lines = ["flowchart TD"]
    lines += [f'    {id_}{{{{"join"}}}}' if id_.startswith("join_")
              else f'    {id_}["{"<br/>".join(text)}"]' for id_, text in boxes.items()]
    for edge in edges:
        label = "<br/>".join(edge.pieces)
        arrow = f'-->|"{label}"|' if label else "-->"
        lines.append(f"    {edge.source} {arrow} {edge.target}")
    return "\n".join(lines) + "\n"


def main() -> int:
    print(mermaid(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
