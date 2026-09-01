## Context

The filter specification identifies the listing vocabulary, while registry authority settings identify the response signer. Neither surface carries the registry's public URL, display name, operator identity, or access posture. Clients therefore need a separate, manually synchronized trust bundle before they can inspect the registry.

The existing version 2 marketplace envelope already authenticates registry responses. The descriptor needs that proof of possession, but it does not need another online signing protocol.

## Goals / Non-Goals

**Goals:** publish one portable descriptor body; bind it to the active authority signer; prevent configuration drift between schema, access gate, and manifest; keep the endpoint available before read-key acquisition.

**Non-Goals:** third-party endorsement, directory curation, authority rotation, read-key issuance, or a new signature implementation.

## Decisions

### Publish a well-known descriptor through the existing signed exchange

The route is `GET /.well-known/arkhai/registry-descriptor.json`. The caller signs the request as `registry.descriptor.read` over resource `registry-descriptor`. The registry signs the response through the same version 2 response contract as authenticated discovery.

The route does not require a read API key. A key-gated registry must disclose its acquisition pointer before a caller possesses that key. Marketplace request authentication and replay classification still apply.

### Keep the descriptor body portable

The JSON body uses stable camel-case field names:

```json
{
  "access": {"posture": "public"},
  "authority": {
    "name": "registry-a",
    "principals": [{"scheme": "ed25519", "identifier": "..."}]
  },
  "baseUrl": "https://registry.example",
  "displayName": "Example Compute Registry",
  "operatorIdentity": "Example Operator",
  "schema": {"id": "vms.compute", "version": "1"}
}
```

The shared core carrier validates this shape without importing identity-kit or role packages. The registry client converts descriptor principals to identity-kit values only at its trust boundary.

### Derive facts that already have an authority

The registry builds the descriptor once at startup:

- `authority.name` comes from the stable registry authority ID.
- `authority.principals[0]` comes from the loaded signer.
- `schema` comes from the active filter specification.
- `access.posture` comes from the read-key gate.

The operator configures `baseUrl`, `displayName`, and `operatorIdentity`. A key-gated registry must also configure `access.acquisitionPointer`; a public registry rejects that pointer. Startup fails if the descriptor cannot be built, so the endpoint cannot advertise stale or contradictory facts.

### Separate possession from endorsement

The signed response proves that the principal named in the body possesses the active registry credential. It does not establish that the operator or URL is trustworthy. A client may use the descriptor for explicit trust-on-first-use, or it may require a separately trusted directory or operator signature before importing the pin.

Offline tooling may sign the descriptor body for curation. That artifact lifecycle is independent from the online request-response signature and is not implemented by the registry process.

## Risks / Trade-offs

- **A proxy URL differs from the service URL.** The public base URL is explicit operator configuration; the service does not infer it from request headers.
- **Access policy and descriptor drift.** The posture is derived from the live read gate, and startup validates the acquisition-pointer rule.
- **Schema changes without descriptor changes.** The descriptor reads the same cached filter specification used by listing validation and discovery.
- **A self-signed descriptor is mistaken for endorsement.** Permanent documentation states that the proof establishes possession only.

## Validation

- Core carrier tests cover exact wire aliases, principal formats, unique pins, URL schemes, and public/key-gated access invariants.
- Registry integration tests use the typed client to prove the well-known route, signed response verification, replay behavior, and read-key independence.
- Helm render tests prove public fields reach ordinary configuration and signer material remains Secret-mounted.
- Strict OpenSpec validation and comment-hygiene checks run before closeout.

## Permanent Documentation Promotion

| Accepted decision | Permanent location |
|---|---|
| Registry descriptors use one strict portable body and the existing signed response exchange | `openspec/specs/registry-discovery/{spec,architecture}.md` |
| Descriptor facts are derived from their existing authorities where possible | `openspec/specs/registry-discovery/spec.md`; `docs/development/ARCHITECTURE.md` |
| Public descriptor configuration remains separate from signer credentials | `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Self-signature proves possession but not third-party endorsement | `openspec/specs/registry-discovery/architecture.md` |
