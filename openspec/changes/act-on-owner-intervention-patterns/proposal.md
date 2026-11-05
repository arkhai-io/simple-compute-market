## Why

The owner's recorded responses to agents say two things the workflow does not yet act
on.

**Most of triage asks the owner what the owner always answers the same way.** Triage
brings every finding to the owner one message at a time and waits for a disposition on
each. It then asks whether the accepted fixes merit another review round. Triage
records hold 478 findings from the changes triaged between 2026-10-14 and 2026-11-03.
For 313 of them, the orchestrated triage's full presentation survives in the workflow
log.

- **Most findings are accepted as proposed.** That is 79% of all findings.
- **One class is almost never corrected.** In this class the triage agent agrees with
  the finding and proposes one edit or fix. It lays out no alternatives and names
  nothing that would change its recommendation. The finding comes from a review, not
  from a validation record or the owner's own notes. Of the 313 presented findings,
  108 were in this class: 102 accepted as proposed, 5 accepted with added context, and
  1 overridden.
- **Advance recommendations are accepted.** The agent recommended advancing at 56
  gates and the owner agreed at 55. It recommended another round at 20 and the owner
  agreed at 18, so disagreement concentrates there.
- **Interventions come early.** They cluster in the first findings of a round, which
  are the most severe and the ones carrying real choices. They fall away after the
  second finding.

**The owner's corrections show where the guidance is wrong, missing or unenforced.**
The intervention ledgers hold 506 corrections. 232 of them rest on judgement that no
written rule supplied, and 150 concern the change's direction. Of the 63 review
findings that cite a written rule, the owner accepted 52 as proposed. So the
corrections show three things:

- **Guidance that is false.** It sends agents to GitHub Issues for intake, which the
  owner does not use, and to glossary files, a vocabulary skill and ADRs that do not
  exist — all from an external skill template none of whose skills is installed.
- **Rules the owner applies repeatedly that nobody wrote down.** For example: no
  guard code for a case nobody can describe; amend a rule or comply, never keep a
  private exception; prefer an existing open-source library; when a validation may
  be waived.
- **Written rules that nothing enforces.** Reviews keep catching the same breaches.

Some of the owner's working preferences also live only in an agent's private memory
between sessions, where no other agent or person sees them.

`design.md` gives the method, every table, and the settled decisions.

## What Changes

### Triage accepts uncontested findings by default

- **A stated rule classifies each finding at triage time** (D3). A finding is accepted
  by default when it comes from a review, is not `blocking`, the agent agrees and
  proposes one edit or fix, neither the reviewer nor the agent lays out an
  alternative and the agent names nothing that would change its recommendation, and
  its fix touches no interface, migration, scope or validation environment. Every
  other finding is discussed as today, one per message.
- **Reviewers state alternatives on every finding** (D17), in a required
  `Alternatives:` field that may say `none` with a reason, so the rule's
  no-alternative condition gets an independent reading.
- **Default-accepted findings are reported, not asked** (D1). One table — label,
  severity, the finding in one line, outcome — rides on the triage's last question
  when it asks one, before any fix, and otherwise goes in its final report. Each is
  recorded in the triage file as accepted by default, with the classification that
  admitted it (D18).
- **Advancing is the default exit** (D2). A recommendation of another round is still
  argued and asked. A triage with nothing to discuss and an advancing recommendation
  asks nothing.
- **The owner can interrupt a running step** (D15). A `stop` command signals a running
  step so it is logged `stopped` with its session; the orchestrating session records
  the interrupt and then resumes, reruns or redirects on the owner's word.
- **The owner can revisit afterwards** (D16). On the owner's direction, the finished
  triage session is resumed with the owner's words, after any step started since is
  stopped; it amends the fix in a new commit, logs the correction, and names its exit
  again. A revisit is a ledger entry marked `revisits default acceptance:` (D19).
- **Guidance reviews measure it** (D20, D21). A new interactive skill,
  `guidance-review`, reads every change's records since the last review, reports
  default acceptances, revisits and a sample audit of classifications against the
  rule's measured baseline, clusters the owner's corrections, and lists candidate
  guidance edits for the owner to pick.
- **Steps recommend waivers** (D22). A step meeting a waivable guard recommends a
  waiver when a written criterion holds; only the owner waives, and recommendations
  and their acceptance are counted.

### The guidance says what the owner actually does

- **Deferred work** (D5). The issue-tracker and triage-label documents and sections
  are deleted; `AGENTS.md` says where deferred work goes instead. The issue-discovery
  harness's own filing is unchanged.
- **Defects found during a change** (D6). `openspec/README.md` states the owner's
  preference: a small, understood defect is fixed in the change that found it; a large
  or vague one gets its own change or an unowned gap. The review, triage, design and
  implementation skills align to it; implementation fixes such a defect and records it
  as outside the plan.
- **Vocabulary** (D11). `docs/agents/domain.md` names where terms live — product terms
  in `ARCHITECTURE.md`, subsystem terms in each specification, workflow terms in a new
  `Terms` section of `change-workflow`'s specification — and states the rule for new
  terms. The ADR guidance is dropped (D23).
- **Three rules the owner applies are written down** (D8–D10): no speculative guard
  code; amend a rule or comply; prefer an existing open-source library.
- **Working preferences move from agent memory** (D12): notes and follow-up proposals
  across changes; stating bookkeeping in a design discussion rather than asking it; a
  skill restates guidance only briefly, with a citation, and never stricter than its
  source.
- **Seven written rules get checks** (D24): permanent destinations for decisions,
  history wording in added comments, one version bump per changed package, private
  keys and provider-format credentials, through gitleaks, a maintained secret scanner,
  with four of its default rules off because they misfire on the repository's own
  fixtures and code (D26, D27), reasons for function-local imports, the capability index, whose missing `contact-exchange-settlement` row is
  added, and one lock revision across every `uv.lock`. Agents on different uv releases
  have been rewriting each other's locks. So the uv minimum rises to the release that
  writes the repository's lock revision, the repository's relock and environment
  refresh commands check it, the revision check catches a lock a plain `uv run`
  rewrites, and the locks still at the older revision are relocked.
- **A full-rule secret audit, run by hand** (D29). `make audit-secrets` reports what
  every gitleaks rule finds in the tracked tree, gating nothing, and is run before an
  official build ships. Its first run found a golden-image root password in the VM
  IaC README, which is replaced with placeholders (D25).

### Not changed, by the owner's decision

- **No narrowest-fix rule** (D7). The owner's scope growth comes from deliberately
  unifying the VM and bare-metal domains, which the architecture already favours.
- **The rule for stored-state migrations stays as written** (D13).
- **Promoting principles stays as it is** (D14).

### Out of scope

- **Folding revisits into the workflow graph** (D4), proposed by a guidance review if
  revisits become frequent.
- **Adopting ADRs** (D23), not proposed.
- **Skills citing guidance instead of restating it**, an open question in
  `layer-engineering-guidance`.
- **The design discussion's presentation.** It already presents consequence and
  convention decisions together for confirmation.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `change-workflow`: default acceptance and its report in triage, the advancing
  default, reviewers' alternatives, the owner's interrupt of a running step, revisiting
  a default acceptance, the ledger's marking of revisits and recommended waivers,
  waiver recommendations, guidance reviews, and the checks a change's closing checks
  run.

## Impact

- **Specification.** `openspec/specs/change-workflow/spec.md` modifies "Phases and
  owner touchpoints", "Review records", "Triage of every finding", "Intervention
  ledger", and "Discussion steps stay conversations with the owner"; adds "The owner
  interrupts a running step", "The owner revisits a default acceptance", "Waivers are
  recommended and the owner's to take", "Guidance reviews", and "A change's closing
  checks enforce written rules"; and gains a `## Terms` section at closeout.
  `openspec/specs/change-workflow/architecture.md` changes "What the workflow is for",
  "The owner is interrupted only for judgement", "The orchestrator relays and routes",
  "Reviews are files", and "Triage".
- **Tooling.**
  - `scripts/run_change_step.py` and `scripts/change_workflow/` (`cli.py`,
    `wrapper.py`, `running.py`, `log.py`): the `stop` command, the `--resumes`
    direction, and resuming a finished triage under it.
  - `scripts/change_workflow/review.py`: the `Alternatives` field.
  - `scripts/check_change.py` and new check scripts under `scripts/`: destinations,
    history wording, version bumps, local imports, the capability index.
  - Private keys: a pinned gitleaks beside `scripts/check_public_content.py`, in
    `scripts/hooks/pre-commit`, `scripts/hooks/pre-push`, the guarded push
    (`scripts/check_push_ready.py`), `make check-public-content`, and
    `.github/workflows/public-content.yml`, its commit scans reading merge patches; a
    new `.gitleaks.toml`, the gate, extending a new `scripts/gitleaks-audit.toml`, the
    audit, which replaces the default private-key rule with one that cannot join two
    key blocks; the gate also turns off `generic-api-key`, `jwt` and
    `curl-auth-header`. `scripts/check_secrets.py --audit` and `make audit-secrets`:
    the audit.
  - `domains/vms/provisioning/iac/README.md`: the root password and key filename
    replaced with placeholders.
  - `scripts/check_locks.py`: one lock revision. `scripts/check_uv_version.py`: the
    raised minimum. `scripts/uv_project.py`: `lock` and `reinit` check the uv version.
    `.github/workflows/tests.yml` and `e2e.yml`: the uv they install. The `uv.lock`
    files still at the older revision: relocked.
  - `scripts/change_next_step.py`: a resumed triage's later outcome governs; no new
    node or exit.
- **Skills.**
  - `.agents/skills/change-triage/SKILL.md`: the rule, the classification, the table,
    the advancing default, revisits, waiver recommendations, and the defect outcome.
  - `.agents/skills/change-orchestrate/SKILL.md`: relaying the table, interrupting a
    step, and routing a revisit.
  - `.agents/skills/change-review/SKILL.md`: the `Alternatives` field and the scope and
    consistency lenses.
  - `.agents/skills/change-implement/SKILL.md`: a found defect.
  - `.agents/skills/change-design/SKILL.md`: decisions under `### D<n>` headings, the
    splitting question, stating bookkeeping, and waiver recommendations after a return.
  - `.agents/skills/change-validate/SKILL.md` and
    `.agents/skills/change-archive-cleanup/SKILL.md`: waiver recommendations.
  - `.agents/skills/guidance-review/SKILL.md`: new, linked from `.claude/skills/` and
    `.codex/skills/`.
- **Guidance.**
  - `AGENTS.md`: "Deferred work" replacing "Issue tracker" and "Triage labels"; "Domain
    docs" without ADRs; a rule for work that conflicts with a written rule.
  - `docs/agents/issue-tracker.md` and `docs/agents/triage-labels.md`: deleted.
  - `docs/agents/domain.md`: rewritten.
  - `docs/agents/change-workflow.md`: the table, default acceptance, interrupts,
    revisits, "Waivers", notes and proposals across changes, and skills restating
    guidance.
  - `openspec/README.md`: defects found during a change, and the scope-creep sentence.
  - `docs/development/ARCHITECTURE.md`: the guard-code and library rules, and, under
    "Public repository content checks", gitleaks, its installation, the repository's
    key rule and why it replaces the default, the three default rules the gate turns
    off and why, the audit, and the two things the gate cannot see: an edit beneath an
    existing key header, and a random credential in no provider's format.
  - `docs/development/RELEASING.md`, "Cutting a release": run `make audit-secrets`
    and read its findings before an official build ships.
  - `openspec/specs/README.md`: the `contact-exchange-settlement` row.
  - `docs/development/BUILD_AND_PACKAGING.md`: the raised uv minimum, the lock-revision
    check, and drift in both directions.
- **Coordination.**
  - `layer-engineering-guidance` restructures the guidance by layer. This change lands
    first, and that change inherits these edits in its design review. Its design gains
    the open question on skills citing instead of restating.
  - `align-package-paths-with-layers` has an open point on `domain.md`'s platform
    context, which this change's rewrite dissolves; its design reverifies once this
    change lands.
  - `extract-change-workflow-repository` moves the skills, the workflow specification
    and the guidance to a separate repository, and `add-skill-extension-points`
    restructures the skills into slots. Neither has started, and whichever lands second
    carries the other's edit.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1, the table and when it reaches the owner: `openspec/specs/change-workflow/spec.md`
  ("Triage of every finding"), and `docs/agents/change-workflow.md`.
- D2, the advancing default: `openspec/specs/change-workflow/spec.md` ("Phases and
  owner touchpoints"), and `architecture.md`, "The owner is interrupted only for
  judgement".
- D3, the default-acceptance rule: `openspec/specs/change-workflow/spec.md`; why the
  class is accepted by default, and the evidence in summary with Rule E's baseline:
  `openspec/specs/change-workflow/architecture.md`, "Triage".
- D4, revisits outside the graph: `openspec/specs/change-workflow/architecture.md`,
  "Triage".
- D5, deferred work: `AGENTS.md`.
- D6, defects found during a change: `openspec/README.md`.
- D7: no permanent destination — a decision not to add a rule.
- D8, no speculative guard code: `docs/development/ARCHITECTURE.md`.
- D9, amend a rule or comply: `AGENTS.md`.
- D10, prefer an existing library: `docs/development/ARCHITECTURE.md`.
- D11, where the vocabulary lives and the rule for new terms: `docs/agents/domain.md`;
  the workflow's terms: `openspec/specs/change-workflow/spec.md`, "Terms".
- D12, the promoted preferences: `docs/agents/change-workflow.md` ("Skills", and notes
  and proposals across changes) and `.agents/skills/change-design/SKILL.md`.
- D13: no permanent destination — the existing rule stays as written.
- D14, the one promoted principle, that the owner can always reach a running step:
  `openspec/specs/change-workflow/architecture.md`, "The orchestrator relays and
  routes".
- D15, interrupting a running step: `openspec/specs/change-workflow/spec.md`,
  `architecture.md` ("The orchestrator relays and routes"), and
  `docs/agents/change-workflow.md`.
- D16, revisiting a default acceptance: `openspec/specs/change-workflow/spec.md`,
  `architecture.md` ("Triage"), and `docs/agents/change-workflow.md`.
- D17, reviewers' alternatives: `openspec/specs/change-workflow/spec.md` ("Review
  records") and `architecture.md`, "Reviews are files".
- D18, the classification record: `openspec/specs/change-workflow/spec.md` ("Triage of
  every finding").
- D19, the revisit marker: `openspec/specs/change-workflow/spec.md` ("Intervention
  ledger") and `docs/agents/change-workflow.md`, "The ledger".
- D20, guidance reviews: `openspec/specs/change-workflow/spec.md` ("Guidance reviews")
  and `architecture.md`, "Triage".
- D21, how the revisit rate is read: `openspec/specs/change-workflow/architecture.md`,
  "Triage".
- D22, waiver recommendations and their criteria: `openspec/specs/change-workflow/spec.md`
  and `docs/agents/change-workflow.md`, "Waivers".
- D23: no permanent destination — guidance is removed.
- D24, the seven checks: `openspec/specs/change-workflow/spec.md` ("A change's closing
  checks enforce written rules"), `docs/agents/change-workflow.md`; for the private-key
  check, `docs/development/ARCHITECTURE.md`, "Public repository content checks"; and,
  for the lock revision and the uv minimum, `docs/development/BUILD_AND_PACKAGING.md`.
- D25: no permanent destination — a defect fixed in place.
- D26, the gate's rules and what it leaves to review and the audit:
  `docs/development/ARCHITECTURE.md`, "Public repository content checks", and the
  comments of `.gitleaks.toml`.
- D27, what the gate refuses and passes: `openspec/specs/change-workflow/spec.md`
  ("A change's closing checks enforce written rules").
- D28, the tree test as the guard on a gitleaks upgrade:
  `docs/development/ARCHITECTURE.md`, "Public repository content checks".
- D29, the audit: `openspec/specs/change-workflow/spec.md` ("A change's closing checks
  enforce written rules"), `docs/development/ARCHITECTURE.md`, "Public repository
  content checks", and `docs/development/RELEASING.md`, "Cutting a release".
- D30: no permanent destination — the change's own cadence.
