## 1. Resolve the configuration contract

- [ ] 1.1 Trace every generated, declared, loaded, and adapter/Ansible-consumed golden SSH/GCS/image key and record ownership/precedence in `design.md`.
- [ ] 1.2 Decide request field versus service default ownership for GCS bucket/path and remove or migrate dead setting names.
- [ ] 1.3 Define generated public/secret profile schemas and validation/redaction behavior.

## 2. Implement generation and consumption

- [ ] 2.1 Emit consumed `golden_root_ssh_filename`, `golden_root_ssh_password`, `golden_image_name`, and accepted GCS keys from IaC automation.
- [ ] 2.2 Update provisioning settings/adapter injection and add bounded actionable legacy-key diagnostics.
- [ ] 2.3 Wire secret fragment through the existing provisioning Secret profile and non-secret values through the appropriate config path.

## 3. Verify and document

- [ ] 3.1 Add generated-key, Dynaconf precedence, adapter input, conflicting-key, and missing-secret tests.
- [ ] 3.2 Add Helm render/redaction/mount tests proving passwords never enter ConfigMaps/logs.
- [ ] 3.3 Replace obsolete IaC injection guidance with current generate/apply/rotate workflow and run a round-trip validation.
- [x] 3.4 **Withdrawn** 2026-10-14: closeout does this — 4.9 writes the architecture companion and the promotion record, 4.10 validates, and the archive in 4.11 writes the `physical-provisioning` spec its delta covers. As first planned: Promote the contract to `physical-provisioning` spec/architecture, record promotion in `design.md`, and run strict validation before archive.
- [ ] 3.5 **Comment hygiene and import placement, before the pre-closeout review.** Run `make check-comment-hygiene` and read the comments this change added for any that narrate the review or migration that introduced them; move each import the change added to module level unless a verified circular import or a recorded lazy-load reason keeps it local. Closeout only confirms both.

## 4. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 4.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read the comments this change added for any that narrate the review or migration that introduced them. Do not edit code here: anything to rewrite returns the change to implementation.
- [ ] 4.2 **Import placement — confirm.** Check the imports this change added for any still local without a recorded reason. One that should move returns the change to implementation.
- [ ] 4.3 **Documentation compliance.** Re-check this change's accepted decisions against `openspec/README.md`'s placement rules, and the permanent documents against the code they describe. Durable conceptual rationale for the `physical-provisioning` contract sits in its companion `architecture.md` rather than only in `design.md`.
- [ ] 4.4 **Narrative compression.** Compress completed-task notes to final behavior, material validation evidence, unresolved or deferred work, and permanent-documentation destinations, moving durable rationale into `design.md` first.
- [ ] 4.5 **Roadmap currency.** Update the affected goal's current state and gap mapping in `docs/development/ROADMAP.md`, or record that no goal is affected. This change belongs to no campaign, so it most likely owes the roadmap nothing; confirm that and record the disposition explicitly.
- [ ] 4.6 **Campaign index currency.** Update this change's row, and its campaign's dependency graph, in `openspec/changes/README.md`, or record that both are unchanged. Other rows' `Depends on` are left alone: archive cleanup releases dependents after the closeout gate.
- [ ] 4.7 **Packaging.** Run `make check-packaging` and resolve every failure it reports (a failure needing a code or lock change returns the change to implementation).
- [ ] 4.8 **End-to-end pipeline.** Record the passing run the latest validation names, its result, and the scenarios that exercise this change, or an explicit blocker naming its cause and the change that owns it, with the validations it gates treated as unrun.
- [ ] 4.9 **Promotion.** Write the permanent documents this change owes — `openspec/specs/physical-provisioning/architecture.md` (the golden-image configuration contract's ownership, precedence, and secret delivery rationale) and the generate/apply/rotate operator guidance that replaces the obsolete IaC injection guidance (3.3) — and add a design-promotion record mapping every accepted decision to its exact permanent heading; verify no production source references this change's directory. A `spec.md` the deltas cover (`openspec/specs/physical-provisioning/spec.md`) is written by the archive in 4.11, not by hand; the record names it all the same.
- [ ] 4.10 **Documentation citations.** After promotion, run `make check-doc-citations CHANGE=fix-golden-image-config` and resolve every match, then `openspec validate fix-golden-image-config --strict`.
- [ ] 4.11 **Archival.** Last, once every other part is checked: `openspec archive fix-golden-image-config -y` merges the deltas into `openspec/specs/` and moves the change under `openspec/changes/archive/`; point the index row at the archived directory, and run `openspec validate --specs --strict`.
