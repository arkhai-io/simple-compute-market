## 1. Helm composition

- [ ] 1.1 Alias the registry subchart as an optional API-credits registry.
- [ ] 1.2 Make signer identity and filter-spec selection instance-local.
- [ ] 1.3 Add independent API-credits identity, descriptor, auth, persistence,
      Service, and image values.

## 2. Image and evidence

- [ ] 2.1 Package both repository-owned filter specifications in the registry
      image at stable paths.
- [ ] 2.2 Add a dual-registry fixture and render assertions for schema identity,
      names, Services, PVCs, Secret references, and descriptor URLs.
- [ ] 2.3 Prove the disabled alias preserves compute-only output.

## 3. Permanent promotion

- [ ] 3.1 Promote the topology and rationale to the deployment-state spec and
      architecture.
- [ ] 3.2 Update permanent architecture and deployment/configuration guidance.
- [ ] 3.3 Run targeted Helm checks, repository quality gates, strict OpenSpec
      validation, and archive the completed change.
