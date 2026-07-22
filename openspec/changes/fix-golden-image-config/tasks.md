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
