## Context

IaC emits `root_ssh_*`, `gcs_bucket_url`, `gcs_image_path`, and `golden_image_name`; provisioning declares `golden_root_ssh_*`, `golden_image_name`, `golden_gcs_bucket`, and `golden_gcs_project`. Only some are consumed, while runtime jobs use other GCS names. Helm mounts a provisioning Secret profile but golden values are absent; old docs describe a pre-extraction injection mechanism.

## Goals / Non-Goals

**Goals:** one consumed generated profile; Secret-safe transfer; coherent GCS ownership; tested operator workflow.

**Non-Goals:** image-builder redesign or secret storage in ConfigMap/logs.

## Decisions

- Generated profile uses provisioning-consumed `golden_root_ssh_filename`, `golden_root_ssh_password`, and `golden_image_name`.
- Before implementation, trace GCS bucket/path ownership. If service defaults are required, define and consume explicit bucket/path settings; otherwise keep them request/Ansible fields and remove dead service declarations. `golden_gcs_project` is not retained without a consumer.
- Split generated non-secret and secret fragments or provide a redacting conversion command; apply secrets to the pre-existing provisioning Secret profile.
- Never print secret values in Helm render diagnostics or operational commands.
- Update the VM IaC guide to current Helm/Dynaconf profile workflow.

## Risks / Trade-offs

- **[Renamed keys break existing generated files]** → Support one bounded validation/migration message and regenerate from source.
- **[GCS defaults conflict with request values]** → Define explicit precedence and test both paths.
- **[Secret leaks during transfer]** → Redact output, use restrictive files/Secret input, and add render/log scans.

## Permanent Documentation Promotion

The validated config/secret contract belongs in `physical-provisioning` spec/architecture; operator generation/application procedure belongs in VM provisioning IaC documentation.
