# Design: add skill extension points

Status: design phase. Not planned. The direction under "Starting direction" came
from the owner's discussion that opened the lesser goal, and design confirms or
revises it. Everything under "Open questions" is undecided.

## Context

- **Skill layout.** Each `change-*` skill is one `SKILL.md` under
  `.agents/skills/<name>/`, with no supporting files. Claude Code and Codex load
  it through a relative symlink in `.claude/skills/` and `.codex/skills/`.
  `scripts/check_agent_skills.py` enforces one source per skill, under
  "Harness-neutral agent skills" in `openspec/specs/change-workflow/spec.md`.
- **Repository-specific material in the skills.** A search for this repository's
  terms (Helm, end-to-end pipeline, namespace, capacity, CI dispatch, packaging)
  finds about sixty matches in `change-validate` and seventeen in
  `change-archive-cleanup`. The other skills have a few or none. That search
  undercounts: skills also cite this repository's documents and make targets,
  which the capability contract and the guidance layering handle.
- **The closeout parts.** `openspec/README.md`'s "Plan closeout requirements"
  lists eleven parts: comment hygiene, import placement, documentation
  compliance, narrative compression, roadmap currency, campaign index currency,
  packaging, end-to-end pipeline, promotion, documentation citations, and
  archival. The owner's view is that several are company engineering concerns,
  some are workflow concerns, and a few are this repository's.

## Starting direction

- **Named extension points are the only form of per-repository variation.** Full
  overrides and free-form addenda are rejected.
- **Addenda may add or narrow.** Removing a baseline obligation is an explicit,
  visible deviation.
- **A check verifies that every addendum targets a declared slot.**
- **The skill reads its addenda when it runs,** at paths the configuration names.
  The engine does not compose the skill's prompt.
- **Protecting guidance from a hostile addendum is deferred** until untrusted
  parties supply addenda. When it comes, canaries and licence terms are the
  favoured controls, with light pattern matching on what leaves; no LLM-based
  filtering.

## Open questions

- **Slot granularity and vocabulary.** Whether slots follow a skill's sections
  (one per numbered step of closeout, say) or a smaller set of named concerns
  (`closeout-parts`, `validation-parts`, `validation-diagnosis`,
  `cleanup-teardown`). Fewer, broader slots are easier to keep stable. Slot names
  are public surface, so renaming one is breaking.
- **The addendum's form.** One Markdown file per slot, one file per skill with a
  section per slot, or entries in the configuration file itself. Files are easier
  to review and diff; entries keep everything in one place.
- **How a skill finds its addenda.** By reading the configuration and the files it
  names, or by asking the engine for a slot's resolved content. The engine
  command is one seam where reading could later be logged or filtered, without
  the engine composing prompts.
- **Telling narrowing from removal.** Whether a deviation is a section in the
  addendum, an entry in the configuration, or both. Whether the check can tell an
  addendum that removes an obligation from one that narrows it, or only that a
  deviation is declared. A check on wording would be brittle. A declared
  deviation is reviewable.
- **Reviews and addenda.** A reviewer judging a closeout or a validation should
  read the same addenda the step obeyed. Whether `change-review` declares slots of
  its own, or reads the addenda of the step under review, is open.
- **Where validation's slot ends and the capability contract begins.** If
  validation becomes a profile of capabilities, its addendum might carry only
  diagnosis notes and evidence rules. If it stays a sequence the skill drives,
  the addendum might carry the sequence. This is settled with
  `add-workflow-capability-contract`'s design.
- **The orchestrator.** `change-orchestrate` relays and routes and holds almost
  no repository material. Whether it needs slots at all is open.
- **The first slot inventory.** Which slots this repository's material actually
  needs. Only those should be created, not slots added speculatively in case
  another repository wants them.
