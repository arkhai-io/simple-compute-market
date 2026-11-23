# The change workflow's convenience targets, each calling the engine's command.
#
# A repository's Makefile includes this file after setting its own values; every
# default here is `?=`, so a value set before the include stands. These targets
# and variables carry no compatibility promise: the engine's promise is its
# command, `scripts/change-workflow`, and renaming a target or a variable here
# changes no public interface of the engine. See
# openspec/specs/change-workflow/spec.md.
#
# With UNATTENDED=1, a step's target runs it through the command's wrapper: a
# headless session inside the step's sandbox, which lets it write only the step's
# scope — or unconfined, with a warning, where the sandbox cannot run — ending with
# an outcome logged to the change's workflow log. Without it, the
# target opens an interactive session, unconfined, under the owner's own settings.
# WRITE holds paths the owner grants for that one unattended run, several separated
# by `;`; each reaches the command as its own `--write`, single-quoted so the shell
# passes a path's spaces and quotes as they are (a `$` is make's own, written `$$`).

CHANGE_WORKFLOW ?= scripts/change-workflow

WRITE ?=
# The branch a review reads the change against (REVIEW_BASE), and the branch the
# merge before closeout brings in (FROM), for one run: unset, each is the branch the
# change lands on, as its clone recorded it, and with none recorded the merge, and
# every review but the design's, are refused, naming them.
REVIEW_BASE ?=
# The review's models are the workflow configuration's. Unset by default; given,
# they are the owner's choice for one run, outside the models' policy:
# REVIEW_MODEL replaces the whole list, a claude- model running on Claude and any
# other on Codex, and the record says so. The orchestrating session never sets them.
REVIEW_MODEL ?=
REVIEW_EFFORT ?=

# Named apart from the engine's unattended-run marker, CHANGE_WORKFLOW_UNATTENDED: a
# makefile assignment overrides the environment variable of its name in every
# recipe, so a variable of that name would erase the marker in every recipe an
# unattended run starts, and with it the engine's hook table.
CHANGE_WORKFLOW_HEADLESS = $(filter 1,$(UNATTENDED))
CHANGE_WORKFLOW_GRANTS = $(if $(strip $(WRITE)), --write '$(subst ;,' --write ',$(subst ','\'',$(WRITE)))')
# How a step's target ends its command: unattended, with the paths granted for the
# run, or nothing for an interactive session, which no sandbox confines.
CHANGE_WORKFLOW_RUN = $(if $(CHANGE_WORKFLOW_HEADLESS), --unattended$(CHANGE_WORKFLOW_GRANTS))
CHANGE_WORKFLOW_ARGUMENTS = $(if $(strip $(ARGUMENTS)), --arguments '$(subst ','\'',$(ARGUMENTS))')

.PHONY: design plan implement review triage validate merge closeout archive-cleanup orchestrate
.PHONY: change-next change-clone change-clone-remove round-view round-done round-view-closed
.PHONY: change-watch change-cost change-history check-change-index check-tasks
.PHONY: check-agent-skills check-change-workflow-config check-review check-push-ready push-branch change-graph

design: ## Open a Claude Code design session for an OpenSpec change; unattended, ARGUMENTS follows the change in the skill's invocation, as the owner's direction to the design (CHANGE=<change> [UNATTENDED=1 [ARGUMENTS=<text>] [WRITE='<path>;<path>']])
	@$(CHANGE_WORKFLOW) start design "$(CHANGE)"$(if $(CHANGE_WORKFLOW_HEADLESS),$(CHANGE_WORKFLOW_ARGUMENTS))$(CHANGE_WORKFLOW_RUN)

plan: ## Open a Claude Code planning session for an OpenSpec change; unattended, it resumes the design session, and ARGUMENTS follows the change in the skill's invocation, as the owner's direction to the plan (CHANGE=<change> [UNATTENDED=1 [FRESH=1] [ARGUMENTS=<text>] [WRITE='<path>;<path>']])
	@$(CHANGE_WORKFLOW) start plan "$(CHANGE)"$(if $(CHANGE_WORKFLOW_HEADLESS),$(if $(filter 1,$(FRESH)), --fresh)$(CHANGE_WORKFLOW_ARGUMENTS))$(CHANGE_WORKFLOW_RUN)

implement: ## Open a fresh Claude Code session implementing an OpenSpec change; unattended, ARGUMENTS follows the change in the skill's invocation, as a merge's conflicts to resolve or the owner's direction to the sections, and SESSION_ID continues that implementation session instead (CHANGE=<change> [SECTION=<n>] [SECTIONS=<n-m>] [UNATTENDED=1 [ARGUMENTS=<text>] [SESSION_ID=<id>] [WRITE='<path>;<path>']])
	@$(CHANGE_WORKFLOW) start implement "$(CHANGE)"$(if $(strip $(SECTIONS)$(SECTION)), --sections "$(or $(strip $(SECTIONS)),$(strip $(SECTION)))")$(if $(CHANGE_WORKFLOW_HEADLESS),$(CHANGE_WORKFLOW_ARGUMENTS)$(if $(strip $(SESSION_ID)), --session '$(subst ','\'',$(strip $(SESSION_ID)))'))$(CHANGE_WORKFLOW_RUN)

review: ## Review an OpenSpec change read-only, in Codex or, when Codex is unavailable, on Claude; ARGUMENTS is the owner's direction to the review, where to look harder (CHANGE=<change> KIND=design|implementation|pre-closeout|closeout|merge [ARGUMENTS=<text>] [REVIEW_BASE=<branch>] [REVIEW_MODEL=<any model id, claude-… on Claude; the owner's choice>] [REVIEW_EFFORT=<effort>] [FRESH=1] [UNVALIDATED=1])
	@$(CHANGE_WORKFLOW) review "$(CHANGE)" --kind "$(KIND)" $(if $(strip $(REVIEW_BASE)),--base "$(REVIEW_BASE)") $(if $(strip $(REVIEW_MODEL)),--model "$(REVIEW_MODEL)") $(if $(strip $(REVIEW_EFFORT)),--effort "$(REVIEW_EFFORT)") $(if $(strip $(FRESH)),--fresh) $(if $(filter 1,$(UNVALIDATED)),--unvalidated)$(CHANGE_WORKFLOW_ARGUMENTS)

triage: ## Open a fresh Claude Code session triaging an OpenSpec change's untriaged reviews, validation, and the owner's notes (CHANGE=<change> [UNATTENDED=1 [WRITE='<path>;<path>']])
	@$(CHANGE_WORKFLOW) start triage "$(CHANGE)"$(CHANGE_WORKFLOW_RUN)

validate: ## Open a Claude Code session validating the commit at HEAD for an OpenSpec change; ARGUMENTS follows the change in the skill's invocation (CHANGE=<change> [ARGUMENTS=<text>] [UNATTENDED=1 [WRITE='<path>;<path>']])
	@$(CHANGE_WORKFLOW) start validate "$(CHANGE)"$(CHANGE_WORKFLOW_ARGUMENTS)$(CHANGE_WORKFLOW_RUN)

merge: ## Open a fresh Claude Code session merging the branch an OpenSpec change lands on into its branch once its pre-closeout review is triaged, or again after its archive, resolving the conflicts and repairing what that branch's changes broke; ARGUMENTS follows the branch in the skill's invocation, as the owner's direction to the merge (CHANGE=<change> [FROM=<branch>, default the branch the change lands on] [ARGUMENTS=<text>] [UNATTENDED=1 [WRITE='<path>;<path>']])
	@$(CHANGE_WORKFLOW) start merge "$(CHANGE)"$(if $(strip $(FROM)$(ARGUMENTS)), --arguments '$(subst ','\'',$(strip $(if $(strip $(FROM)),from $(strip $(FROM))) $(ARGUMENTS)))')$(CHANGE_WORKFLOW_RUN)

closeout: ## Open a fresh Claude Code session closing out an OpenSpec change, archiving it last; resumes one archived but not committed (CHANGE=<change> [UNATTENDED=1 [WRITE='<path>;<path>']])
	@$(CHANGE_WORKFLOW) start closeout "$(CHANGE)"$(CHANGE_WORKFLOW_RUN)

archive-cleanup: ## Open a fresh Claude Code session cleaning up an archived OpenSpec change once its closeout review's triage has advanced it, or again after a merge after its archive (CHANGE=<change> [UNATTENDED=1 [WRITE='<path>;<path>']])
	@$(CHANGE_WORKFLOW) start archive-cleanup "$(CHANGE)"$(CHANGE_WORKFLOW_RUN)

orchestrate: ## Open the orchestrating Claude Code session for one OpenSpec change, on the model and effort the workflow configuration's models.orchestrator names (CHANGE=<change>)
	@$(CHANGE_WORKFLOW) start orchestrate "$(CHANGE)"

change-next: ## Print the next step of an OpenSpec change as the orchestrator computes it, in plain form: the step, its reason, and for a waiting run its seq and what it asks (CHANGE=<change>)
	@$(CHANGE_WORKFLOW) find "$(CHANGE)" >/dev/null
	@$(CHANGE_WORKFLOW) next "$(CHANGE)" --plain

change-clone: ## Create a change's own clone beside the owner's workspace, or finish one left incomplete, and start its bootstrap in the background; run in the workspace (CHANGE=<change> [BRANCH=feat/<change>] [FROM=<the branch it lands on; the workspace's checked-out branch>])
	@$(CHANGE_WORKFLOW) clone "$(CHANGE)" $(if $(strip $(BRANCH)),--branch "$(BRANCH)") $(if $(strip $(FROM)),--from "$(FROM)")

change-clone-remove: ## Delete a merged change's clone, copying its history into the workspace first; refuses, deleting nothing, while the clone holds anything else; run in the workspace (CHANGE=<change> [BASE=<the branch it landed on, for a clone that recorded none>])
	@$(CHANGE_WORKFLOW) clone-remove "$(CHANGE)"$(if $(strip $(BASE)), --base "$(BASE)")

round-view: ## Show an implementation round as uncommitted changes for the owner's reading: in the owner's workspace, on the branch fetched from the change's clone, or in place for a change with no clone; run again to follow the clone's new commits (CHANGE=<change> [BASE=<commit>])
	@$(CHANGE_WORKFLOW) round-view "$(CHANGE)" $(if $(BASE),--base "$(BASE)")

round-done: ## Return the branch to the round's commit after round-view, carrying commits made during the view onto it and keeping other edits uncommitted, then return the workspace to where it was
	@$(CHANGE_WORKFLOW) round-done

round-view-closed: ## Fail while a round view is open: the branch then points at the round's base, not its commit
	@$(CHANGE_WORKFLOW) check round-view

change-watch: ## Follow the progress of an OpenSpec change's steps as they run, moving to each new step's progress file as it starts; Ctrl+C stops (CHANGE=<change>)
	@$(CHANGE_WORKFLOW) watch "$(CHANGE)"

change-cost: ## Report what an OpenSpec change's unattended runs cost, by step and by round, with partial dollars as a range and the cache misses with their gaps (CHANGE=<change>)
	@$(CHANGE_WORKFLOW) find "$(CHANGE)" >/dev/null
	@$(CHANGE_WORKFLOW) cost "$(CHANGE)"

change-history: ## Copy an archived change's records and the validation evidence they name from its clone into the owner's workspace, extending files that grew and refusing any that differ; run in the clone (CHANGE=<change>)
	@$(CHANGE_WORKFLOW) history "$(CHANGE)"

check-change-index: ## Fail if the change index has a malformed row, an unresolved change link, an unknown status, a dependency it does not list or that is archived, or an active change directory without exactly one row
	@$(CHANGE_WORKFLOW) check index

check-tasks: ## Fail if a task of a change's task list sits under another section's heading — a heading is missing or the task misplaced — or its closeout section, titled Closeout, is missing, repeated, or not its last (CHANGE=<change>)
	@$(CHANGE_WORKFLOW) check tasks "$(CHANGE)"

check-agent-skills: ## Fail if a committed agent skill is not loaded from its one source under .agents/skills, or an installed engine's skills are not its version's
	@$(CHANGE_WORKFLOW) check skills

check-change-workflow-config: ## Fail, naming each field, unless the workflow configuration and the guides it names pass the configuration's check
	@$(CHANGE_WORKFLOW) check config

check-review: ## Fail if the review on standard input would be refused publishing, printing each problem the format check finds (KIND=design|implementation|pre-closeout|closeout|merge CHANGE=<change>)
	@$(CHANGE_WORKFLOW) check review "$(KIND)" "$(CHANGE)"

check-push-ready: round-view-closed ## Fail unless HEAD is a clean, attached change branch that may be pushed to its own name
	@$(CHANGE_WORKFLOW) check push

push-branch: ## Push exactly HEAD, unforced, to the current branch's own name once it may be pushed and no round view is open
	@$(CHANGE_WORKFLOW) push

change-graph: ## Report where the workflow's graph diagram departs from the graph — each box and edge to add, change, or remove — to redraw it from; fails while it does
	@$(CHANGE_WORKFLOW) check graph

# The hooks around each step's session. Each is a command the workflow configuration
# declares, `before-<step>` or `after-<step>` under `[hooks]`, and none has a default:
# an absent or empty one runs nothing, and the engine probes for no target, so a
# declared target that is missing fails as any command does. A `before-` hook runs
# after the engine's own action before that step, and its failure prevents nothing;
# an `after-` hook runs after a finished session, and its failure resumes it once.
# Each is given `{inputs}`, the run's inputs directory, and a review's and a
# triage's `{kind}`. A repository that writes a hook as a target of its own Makefile
# writes it there, under the name below, and declares the command that runs it:
#
# before-design:
# after-design:
# before-review:
# after-review:
# before-triage:
# after-triage:
# before-plan:
# after-plan:
# before-implement:
# after-implement:
# before-validate:
# after-validate:
# before-merge:
# after-merge:
# before-closeout:
# after-closeout:
# before-archive-cleanup:
# after-archive-cleanup:
