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
- [ ] 3.4 Promote the contract to `physical-provisioning` spec/architecture, record promotion in `design.md`, and run strict validation before archive.

## 4. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 4.1 **Comment hygiene.** Run `make check-comment-hygiene`, then direct-read the comments and docstrings this change touches for the fuzzier provenance-narration rule the target cannot catch mechanically.
- [ ] 4.2 **Import placement.** Review every import this change adds or touches and move it to module level where safe; retain a local import only against an observed circular import or a documented lazy-load reason, verified against the real suite.
- [ ] 4.3 **Documentation compliance.** Re-check this change's accepted decisions against `openspec/README.md`'s placement rules. It carries delta specs for `physical-provisioning`; confirm each landed in the owning `openspec/specs/<capability>/spec.md`, and that durable conceptual rationale sits in the companion `architecture.md` rather than only in `design.md`.
- [ ] 4.4 **Narrative compression.** Compress completed-task notes to final behavior, material validation evidence, unresolved or deferred work, and permanent-documentation destinations, moving durable rationale into `design.md` first.
- [ ] 4.5 **Roadmap currency.** This change belongs to no campaign, so it most likely owes `docs/development/ROADMAP.md` nothing. Confirm that and record the disposition explicitly rather than omitting the step.
- [ ] 4.6 **Campaign index currency.** Update this change's row, and its campaign's dependency graph, in `openspec/changes/README.md` to match its state at completion, or record the disposition here if its status and campaign placement are both unchanged.
- [ ] 4.7 **Promotion.** Add a design-promotion record, mapping every accepted decision to its exact permanent heading, and verify no production source references `openspec/changes/fix-golden-image-config`.
