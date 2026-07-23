## ADDED Requirements

### Requirement: Golden-image configuration compatibility

Golden-image automation MUST emit a validated provisioning profile whose setting names and precedence are consumed directly by the VM provisioning adapter. Root SSH password material MUST be delivered through the provisioning Secret profile and MUST NOT be rendered into a ConfigMap or diagnostic output.

#### Scenario: Generated profile is applied

- **WHEN** an operator generates and applies golden-image configuration through the documented provisioning profile workflow
- **THEN** startup loads the image name, root SSH filename, password, and selected GCS source values without manual key renaming

#### Scenario: Deployment resources render

- **WHEN** Helm renders provisioning with golden-image configuration
- **THEN** secret values are referenced from the Secret-backed profile and do not appear in ConfigMap or redacted diagnostic output

#### Scenario: Obsolete or conflicting GCS key is supplied

- **WHEN** configuration uses an unsupported legacy key or both request and service-default GCS values conflict
- **THEN** validation reports the accepted key/precedence without silently selecting an unused setting
