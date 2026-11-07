## Why

A registry publishes its listing schema but not the operator-authored facts that identify the registry itself. A client must receive the public URL, authority name, authority principal, and schema identity through a separate configuration channel. This prevents a registry from supplying the complete descriptor used for discovery and curation.

## What Changes

- Define one strict registry-descriptor carrier for the public URL, display name, operator identity, authority trust pins, schema identity, and access posture.
- Serve that descriptor at `/.well-known/arkhai/registry-descriptor.json` through the existing authenticated request and signed registry-response contract.
- Derive the authority principal from the active signer, derive schema identity from the active filter specification, and derive access posture from the read gate.
- Require operators to configure only facts that the service cannot derive: the public base URL, display name, operator identity, and an acquisition pointer when reads are key-gated.
- Add the descriptor method to both registry clients and render the public operator fields through Compose and Helm.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `registry-discovery`: A registry publishes a strict, authority-authenticated self-description that clients and directory operators can import.
- `deployment-state`: Registry deployments keep operator-authored public descriptor fields separate from signer credentials.

## Non-Goals

- Do not make a self-signed descriptor an endorsement by a third party.
- Do not add a second runtime signature protocol; directory or release tooling may separately sign the descriptor body.
- Do not publish read keys, signer credentials, provider data, or private deployment coordinates.
- Do not implement registry-authority rotation in this change.

## Impact

- Affected code: the core carrier package, registry service, and registry client.
- Affected configuration: registry Compose and Helm values gain public descriptor fields.
- Affected documentation: registry discovery, deployment configuration, and the repository architecture.

## Permanent documentation impact

- [ ] `openspec/specs/registry-discovery/{spec,architecture}.md` — descriptor behavior and trust boundary.
- [ ] `docs/development/ARCHITECTURE.md` — descriptor ownership in the discovery flow.
- [ ] `docs/development/DEPLOYMENT_AND_CONFIG.md` — public descriptor configuration and secret separation.

## Related issue

- GitHub issue #175.
