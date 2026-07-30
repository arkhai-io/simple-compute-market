## Why

Golden-image automation emits key names that do not match provisioning settings, GCS fields have no coherent consumer/default contract, and current guidance targets an obsolete base64 injection path. Helm has a provisioning Secret profile but does not carry the required golden-image values and would expose passwords if placed in the ConfigMap.

## What Changes

- Define one generated Dynaconf profile contract for golden image name, root SSH key filename/password, and selected GCS source fields.
- Decide whether GCS bucket/path remain request/Ansible inputs or become consumed service defaults; remove dead names.
- Deliver secret values through the existing provisioning Secret profile, never the ConfigMap.
- Replace obsolete injection guidance with current generated-profile-to-Secret workflow.
- Add generation, Dynaconf, adapter, Helm render/redaction, and operator round-trip tests.
- State: **Relevant operator/runtime compatibility fix; independently implementation-ready.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `physical-provisioning`: Golden-image automation and provisioning consume one validated configuration/secret contract.

## Dependencies and Related Changes

- Uses current provisioning profile loading but does not depend on `deduplicate-dynaconf-bootstrap`.

## Non-Goals

- Do not put SSH passwords in ConfigMaps, command logs, or generated public artifacts.
- Do not retain unused GCS setting names solely for compatibility without a bounded migration.
- Do not redesign image building or storage providers.

## Impact

Touches VM IaC generation, provisioning settings/adapter input, Helm Secret/value templates, operator documentation, and focused config/render tests.
