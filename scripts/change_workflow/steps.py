"""The step table: each step's skill, the permission rules an unattended run of it
is held to, and the models it runs on.

The table is `.claude/change-steps.toml`, the workflow's policy. Each step's rules
are its own plus `common`'s, and each row names its models in priority order,
each with its harness and effort. The loader refuses a row the policy forbids: a
model the workflow never runs on, two models of one vendor, Codex, pi, or a bb
thread on any step but the review, or an OpenAI model on pi through any provider
but `openai-codex`.

Contract: openspec/specs/change-workflow/spec.md, "Unattended runs are held to
their step's permissions".
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from change_workflow.common import ROOT, STEPS, Entry, StepError

STEP_TABLE = ROOT / ".claude" / "change-steps.toml"
HARNESSES = ("claude", "codex", "pi", "bb")
# Harnesses that run the review alone. Codex holds it to read-only by its sandbox;
# pi and a bb thread only by the review's prompt, which suffices for a step whose
# only output is its final message, and for no step that commits or relocks.
REVIEW_ONLY = ("codex", "pi", "bb")
# What a bb provider runs on, as a vendor: an outage or a usage limit of one takes
# down every model it serves.
_BB_PROVIDERS = {"codex": "openai", "claude-code": "anthropic"}
# pi's providers by the account they bill: `openai-codex` is the ChatGPT
# subscription Codex also uses, and the API providers are other accounts.
_PI_PROVIDERS = {"openai-codex": "openai", "anthropic": "anthropic"}
# Models the workflow never runs on, whatever a row says.
_FORBIDDEN_MODEL = re.compile(r"fable|astra", re.I)


@dataclass(frozen=True)
class Model:
    """One model a step may run on: its harness, its name, and its effort."""

    harness: str
    model: str
    effort: str | None = None

    def entry(self) -> Entry:
        """The model as a log line records it."""
        return {"harness": self.harness, "model": self.model,
                **({"effort": self.effort} if self.effort else {})}

    @property
    def vendor(self) -> str:
        """The account the model runs on, which one outage or usage limit takes down.

        Codex and pi's `openai-codex` provider share one OpenAI subscription, and
        Claude Code and pi's `anthropic` provider one Anthropic account. A pi model
        is `<provider>/<model>`, and a bb thread's `<bb provider>/<its model>`.
        """
        if self.harness == "codex":
            return "openai"
        if self.harness == "claude":
            return "anthropic"
        provider, _, rest = self.model.partition("/")
        if self.harness == "bb":
            if provider == "pi":
                return Model("pi", rest).vendor
            return _BB_PROVIDERS.get(provider, provider)
        return _PI_PROVIDERS.get(provider, provider)


@dataclass(frozen=True)
class StepRules:
    """A step's skill, the permission rules an unattended run of it is held to, and
    the models it runs on, in priority order."""

    skill: str
    allow: tuple[str, ...]
    deny: tuple[str, ...]
    models: tuple[Model, ...] = ()
    # The step whose last session this step resumes, rather than starting fresh.
    resume_from: str | None = None


def pi_provider_problem(model: Model) -> str | None:
    """Why `model` runs an OpenAI model on pi outside the subscription, or None."""
    pi_model = (model.model if model.harness == "pi"
                else model.model.partition("/")[2] if model.harness == "bb"
                and model.model.startswith("pi/") else None)
    if pi_model and pi_model.partition("/")[0] == "openai":
        return (f"names {model.model}, an OpenAI model on pi's per-token openai provider; "
                "use openai-codex/…, the subscription")
    return None


def load_steps(path: Path = STEP_TABLE) -> dict[str, StepRules]:
    """Each step's rules, `common`'s added to its own, and its models."""
    try:
        table = tomllib.loads(path.read_text("utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise StepError(f"cannot read the step table {path}: {exc}") from exc
    if unknown := set(table) - {"common", "steps"}:
        raise StepError(f"{path} has unknown tables: {', '.join(sorted(unknown))}")
    common = table.get("common", {})
    if set(common) - {"allow", "deny"}:
        raise StepError(f"{path}'s common row takes only allow and deny")
    steps = {}
    for name, row in table.get("steps", {}).items():
        if name not in STEPS:
            raise StepError(f"{path} names an unknown step {name!r}")
        if ("skill" not in row or "models" not in row
                or set(row) - {"skill", "models", "allow", "deny", "resume_from"}):
            raise StepError(f"{path}'s {name} row needs a skill and models, and takes only "
                            "skill, models, allow, deny, and resume_from")
        steps[name] = StepRules(
            skill=row["skill"],
            allow=(*_rules(path, common, "allow"), *_rules(path, row, "allow")),
            deny=(*_rules(path, common, "deny"), *_rules(path, row, "deny")),
            models=_models(path, name, row["models"]),
            resume_from=row.get("resume_from"))
    for name, rules in steps.items():
        if rules.resume_from is not None and rules.resume_from not in steps:
            raise StepError(f"{path}'s {name} row resumes {rules.resume_from!r}, which has "
                            "no row")
    return steps


def _rules(path: Path, row: dict[str, Any], key: str) -> tuple[str, ...]:
    # A string here would be spread into characters, silently dropping its rule.
    rules = row.get(key, [])
    if not isinstance(rules, list) or not all(isinstance(rule, str) and rule for rule in rules):
        raise StepError(f"{path}: {key} must be a list of rules")
    return tuple(rules)


def _models(path: Path, name: str, entries: Any) -> tuple[Model, ...]:
    """A row's models, refusing what the policy forbids.

    A harness is one vendor's, so two entries of one harness are two models of one
    vendor: an outage or a usage limit takes both down, and the second is no
    fallback. Codex, pi, and bb threads run only the review: Codex's writing
    sandbox cannot refuse a commit or a relock, and pi and bb hold a run to its
    limits only by its prompt. An OpenAI model on pi runs through `openai-codex`,
    the subscription, never an API account billed per token.
    """
    row = f"{path}'s {name} row"
    if not isinstance(entries, list) or not entries:
        raise StepError(f"{row} needs models, a list of one or more models")
    models = []
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) - {"harness", "model", "effort"}
                or not isinstance(entry.get("model"), str) or not entry["model"]):
            raise StepError(f"{row} has a model entry without a model, or with a key other "
                            f"than harness, model, and effort: {entry!r}")
        if entry.get("harness") not in HARNESSES:
            raise StepError(f"{row} names harness {entry.get('harness')!r}; expected one of "
                            + ", ".join(HARNESSES))
        effort = entry.get("effort")
        if effort is not None and not (isinstance(effort, str) and effort):
            raise StepError(f"{row} gives {entry['model']} an effort that is not a name")
        if _FORBIDDEN_MODEL.search(entry["model"]):
            raise StepError(f"{row} names {entry['model']}, a model the workflow never runs on")
        if entry["harness"] in REVIEW_ONLY and name != "review":
            shown = {"codex": "Codex", "bb": "A bb thread"}.get(entry["harness"],
                                                                entry["harness"])
            raise StepError(f"{row} names a {entry['harness']} model; {shown} runs only "
                            "the review")
        model = Model(entry["harness"], entry["model"], effort)
        if entry["harness"] in ("pi", "bb") and "/" not in entry["model"]:
            raise StepError(f"{row} names {entry['harness']} model {entry['model']!r}; "
                            "expected <provider>/<model>")
        if problem := pi_provider_problem(model):
            raise StepError(f"{row} {problem}")
        models.append(model)
    vendors = [model.vendor for model in models]
    if len(set(vendors)) != len(vendors):
        raise StepError(f"{row} names two models of one vendor, which an outage or a usage "
                        "limit takes down together")
    return tuple(models)
