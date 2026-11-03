# Design: add workflow harness adapters

Status: design phase. Not planned. The direction under "Starting direction" came
from the owner's discussion that opened the lesser goal, and design confirms or
revises it. Everything under "Open questions" is undecided.

## Context

- **Harness code.** The harness-specific code is spread over several modules:
  - `scripts/change_workflow/harness.py` builds the headless Claude Code command
    (`claude -p`, with the step's rules and schema) and the Codex review commands
    (`codex exec --sandbox read-only`, and `codex exec resume` with the sandbox
    set through configuration). It also recognizes each harness's
    unavailable-model and usage-limit messages.
  - `stream.py` reads Claude Code's event stream.
  - `subagents.py` reads Claude Code subagent transcripts for denials.
  - `cost.py` records a Claude run's dollars, turns, and tokens, and a Codex
    review's tokens.
- **Model policy.** Each row of `.claude/change-steps.toml` lists its step's models
  in priority order, each with a harness and an effort. The review row lists Codex
  first, then Claude; every other row lists one Claude model. The table refuses a
  row with two models of one vendor, and a waiting run resumes only on the model
  it ran on. The rationale is in "Models are policy, with no same-vendor fallback"
  in `openspec/specs/change-workflow/architecture.md`.
- **Codex's sandbox modes** include read-only and workspace-write. Those match two
  of the profiles `sandbox-unattended-workflow-steps` proposes.

## Starting direction

- **Build the adapter interface regardless of how many harnesses use it.** It
  makes harness support one module's concern.
- **Target Claude Code, Codex, and at least one harness serving open models**
  through a provider such as Venice.
- **Codex for implementation** is an immediate use: it balances usage limits
  across plans.
- **Harnesses without skill loading are deferred.** The workflow does not render
  prompts.

## Open questions

- **Which open-model harness.** The candidates are harnesses that load agent skills
  and accept an OpenAI-compatible provider. Whether a candidate supports skills
  today, can enforce a sandbox profile, reports structured events, and can resume
  a session is checked in design, not assumed here.
- **Profiles a harness cannot enforce.** If a harness offers no workspace-write
  sandbox, it can run only read-only steps, unless a container provides the
  sandbox around it. Whether the engine refuses such a pairing when it loads the
  step table, or falls back to the next model, is open.
- **The vendor of an open model.** The rule against a same-vendor fallback exists
  because one outage or limit takes both models down. For an open model served
  through a provider, the shared point of failure is the provider, not the model's
  author. Whether "vendor" means the provider for such rows is open.
- **Cost across harnesses.** Claude Code reports dollars; Codex reports tokens; an
  open-model provider may report either. Whether cost is normalized to dollars
  from a price table, or reported in each harness's own unit, decides what
  `make change-cost` can compare.
- **Event streams and refusals.** The wrapper relies on Claude Code's structured
  events for progress, questions, and denials. A harness with plainer output, like
  Codex's review output today, which is condensed into progress, may not surface
  a question or a refusal in a form the wrapper can act on. What the interface
  requires of a harness for writing steps, compared with reviews, is open.
- **Questions and resumption.** An unattended step that needs the owner waits and
  is resumed with the answer. Whether each harness can resume a session with a new
  message, and how, decides whether it can run steps that ask questions.
- **Subagents.** Claude Code steps use subagents, whose denials are read from
  their transcripts. Whether other harnesses have an equivalent, and whether a
  step's skill may assume one, is open.
- **Where adapters live.** Inside the engine only, or as a public interface a
  repository or a third party could supply. Supplying one from outside makes the
  interface public surface.
