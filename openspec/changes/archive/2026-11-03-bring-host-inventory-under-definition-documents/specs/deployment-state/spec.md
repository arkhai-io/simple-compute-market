## ADDED Requirements

### Requirement: The provisioning chart renders a host definitions document

The provisioning chart MUST render a non-empty `definitions.hosts` value verbatim into its ConfigMap, mount it read-only at `/app/config/host-definitions.yaml`, and set `host_definitions_path` to that path in the rendered profile; an empty value MUST render no document, mount, or path. The values schema MUST refuse `host_definitions_path`, `inventory_path`, and `inventory_ini` under `config`, and `host-definitions.yaml` as a `configFiles` name. It MUST refuse `relay_definitions_path` under `config` as it refuses the pool and capacity paths, since the chart derives every definition document's path from its `definitions` value. The chart's values MUST NOT state `inventory_path`. A change to the document MUST change the ConfigMap checksum the deployment carries, so a release that edits it rolls the pod.

#### Scenario: A release supplies host definitions

- **WHEN** a release sets `definitions.hosts` to a host definitions document
- **THEN** the document renders into the ConfigMap, mounts at `/app/config/host-definitions.yaml`, and the rendered profile sets `host_definitions_path` to that path

#### Scenario: A release supplies no host definitions

- **WHEN** `definitions.hosts` is empty
- **THEN** no host document renders or mounts, and the rendered profile sets no `host_definitions_path`

#### Scenario: A release states the path or a retired inventory setting

- **WHEN** a release sets `config.host_definitions_path`, `config.inventory_path`, or `config.inventory_ini`
- **THEN** rendering fails naming the refused key

#### Scenario: A release states the relay definitions path

- **WHEN** a release sets `config.relay_definitions_path`
- **THEN** rendering fails naming the refused key

#### Scenario: A release edits its host definitions

- **WHEN** a release changes `definitions.hosts`
- **THEN** the deployment's ConfigMap checksum changes, and the pod is replaced
