---
tags: [workflow]
---

# The working model

What a change's work must produce in each phase: what a discussion reads and
records, what a plan holds, and when an implementation is complete. The phases
themselves, and the steps and exits between them, are the workflow's
([Phases, triage, and archival](../../../openspec/specs/change-workflow/README.md#phases-triage-and-archival)).

## Discuss

- Read the repository's root guidance and architecture, the permanent
  specifications the change touches, and the active change, and audit the proposed
  delta against current code and focused evidence, before proposing a design.
- Record alternatives, unresolved questions, and proposed decisions in
  `openspec/changes/<change>/design.md`, and identify the change's permanent
  documentation impact.
- Update `proposal.md` when the intended scope, impact, or acceptance boundary
  changes.
- Do not treat an active change document as permanent architecture.

## Plan

Create or amend the implementation plan only once the design is ready.

- Preserve existing completed tasks. Amend or append tasks rather than replacing
  implementation history.
- Name the files to touch and why.
- Identify the permanent documentation destination for every accepted material
  design decision.
- Include focused validation and relevant integration suites.
- Name evidence only a push produces — a CI workflow's run, which a change branch's
  push does not trigger — on its own line of the section's verification task, beside
  its end-to-end scenarios: `Owed by validation:`, the workflow, the job, and what
  the job must show. It gates no task (`change-workflow`'s CW-5h8e).
- End the plan with the closeout task: the workflow's parts, in their order, with the
  repository's own parts at the position the list gives them
  ([Closeout](closeout.md)). Do not defer it to a later review round. Promotion
  happens at closeout, after the code's last review, to reduce file churn.

## Implement

Implementation is not complete when code merely passes tests. It is complete when:

- the planned code and tests are implemented, and satisfy the change's
  specification;
- existing completed tasks remain preserved, corrections appended or amended;
- every accepted material decision has been classified as permanent, temporary,
  superseded, or rejected, and the change's design-promotion record names where each
  permanent one goes ([The design-promotion record](changes.md#the-design-promotion-record));
- production code holds no reference to the change, its tasks, or its documents
  ([Change references](change-references.md));
- the checks the plan names — focused, integration, and the repository's own — have
  been run and their validation evidence recorded, or any unrun check is disclosed.

Closeout then writes the permanent documents the record names, so that accepted
subsystem behaviour is in its `spec.md`, rationale that does not fit normative
scenarios is in its companion, and cross-system knowledge is in the repository's
cross-system documents, each describing the current system rather than announcing
completion; and archives the change, which synchronizes its verified delta into the
specifications. The closeout review then reads the archived change.

## Asking the owner

Ask the owner questions in prose, in the chat, with each option and your
recommendation written out. Do not use a multiple-choice selector, even where a
skill names one: a list of buttons invites picking an option over thinking the
problem through and writing the answer that fits it.

## Deferred work

Deferred work is recorded in the open change that owns its area, in a new change,
or as an unowned gap in the change index or the repository's roadmap
([The capability index and the roadmap](openspec-documentation.md#the-capability-index-and-the-roadmap)).
