# Implementation Tasks

## 1. Shared identity contract

- [ ] 1.1 Pin the released `arkhai-kit-identity` artifact and require
      `arkhai.market-request-signature.v2`, the matching response protocol,
      strict scheme-tagged principals, and exact capability checks.
- [ ] 1.2 Remove service-local canonicalization, EIP-191-only assumptions,
      private-key/address derivation, caller-selected expected identities, and
      legacy version 1 or shared-key fallback.
- [ ] 1.3 Add focused contract tests for Ed25519/EIP-191 parity, every bound
      request and response field, malformed proofs, cross-role/principal replay,
      stale timestamps, and exact sync/async bytes.

## 2. Registry and authority configuration

- [ ] 2.1 Define the site registry as an interface returning
      `(site_id, url, principal)`, config-backed initially, with consumers
      independent of the backing source.
- [ ] 2.2 Give each storefront site an exact scheme-tagged authority principal
      and give each authority its one configured storefront principal.
- [ ] 2.3 Inject signer/verifier protocols at composition roots; keep public
      principals in ordinary configuration and private signer material in
      Secret-backed inputs.
- [ ] 2.4 Prove wallet-free Ed25519 profiles render and run without chain, RPC,
      EAS, wallet, or EVM private-key configuration.

## 3. Storefront-to-authority authentication

- [ ] 3.1 Sign outbound storefront requests over role, principal, method,
      semantic operation and resource, request ID, timestamp, and canonical
      body; verify them before authority route dispatch.
- [ ] 3.2 Persist replay reservations by principal and request identity so
      exact retries may recover the stored result while changed reuse fails
      closed.
- [ ] 3.3 Sign authority mutation responses and require clients to verify the
      configured authority, request identity, status, timestamp, and body
      before accepting an acknowledgement.
- [ ] 3.4 Cover every service route, including projection, capacity release,
      provisioning lifecycle, and seller/listing lifecycle operations.

## 4. Authority-to-storefront authentication

- [ ] 4.1 Sign every authority-originated storefront request with the
      authority's injected signer and verify it against the site registry
      before route dispatch.
- [ ] 4.2 Sign storefront mutation responses and require authority clients to
      verify the configured storefront principal and all bound response fields.
- [ ] 4.3 Prove a principal registered for one site cannot authenticate another
      site, a compromised storefront cannot sign as an authority, and unsigned
      or wrong-authority acknowledgements fail closed.

## 5. Rotation and disablement

- [ ] 5.1 Require active-principal and replacement-principal proofs over one
      bounded rotation statement and persist the overlap atomically.
- [ ] 5.2 Accept both principals only during overlap; retire the old principal
      on expiry or explicit retirement and reject it thereafter.
- [ ] 5.3 Keep operator disablement distinct from rotation and prove disablement
      revokes authority without transferring it.

## 6. Deployment cutover

- [ ] 6.1 Render scheme-tagged public principals and Secret-injected signer
      credentials for both peers, with exact startup validation.
- [ ] 6.2 Remove `storefront_admin_key`, legacy signature configuration,
      address/private-key aliases, and mixed-generation deployment paths.
- [ ] 6.3 Add deployment and package checks for exact identity-kit version and
      protocol capabilities, dual-scheme profiles, public/private separation,
      and rejection of stale artifacts.

## 7. Validation

- [ ] 7.1 Run focused identity, provisioning middleware/event-sink,
      storefront/site-client, domain composition, migration, replay, rotation,
      and deployment-render suites.
- [ ] 7.2 Exercise an end-to-end Ed25519 service flow and an explicit EIP-191
      flow, including signed acknowledgements and a changed-replay rejection.
- [ ] 7.3 Run strict OpenSpec validation against the baseline current at
      implementation time and disclose any suite not run.

## 8. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 8.1 **Comment hygiene.** Run `make check-comment-hygiene`; remove comments
      and docstrings describing shared-key, version 1, address-derived, or
      migration-only behavior.
- [ ] 8.2 **Import placement.** Review every touched package against the
      documented dependency layers; service and domain packages consume
      identity protocols without importing signer implementations upward.
- [ ] 8.3 **Documentation compliance.** Promote version 2 request/response,
      replay, registry, rotation, dual-scheme, and credential-placement
      decisions to the owning permanent specifications and architecture docs.
- [ ] 8.4 **Narrative compression.** Compress completed-task notes to final
      behavior, validation evidence, and promotion destinations.
- [ ] 8.5 **Roadmap currency.** Record the final roadmap disposition.
- [ ] 8.6 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Service peers use the shared body-bound version 2 request and response contracts with exact configured principals | `openspec/specs/marketplace-identity/{spec,architecture}.md`; `openspec/specs/physical-provisioning/spec.md` |
| Request identities are durably reserved and exact retries are distinct from changed replay | `openspec/specs/marketplace-identity/spec.md`; `openspec/specs/physical-provisioning/spec.md` |
| Ed25519 is wallet-free by default and EIP-191 remains explicit under one scheme-tagged protocol | `openspec/specs/marketplace-identity/{spec,architecture}.md`; `docs/development/ARCHITECTURE.md` |
| Storefronts resolve exact site authority principals through an interface and verify signed acknowledgements | `openspec/specs/storefront-publication/{spec,architecture}.md` |
| Counterparty rotation requires dual proof and bounded overlap; disablement never transfers authority | `openspec/specs/{marketplace-identity,physical-provisioning,storefront-publication}/spec.md` |
| Public principals and private signer credentials have separate deployment ownership | `docs/development/DEPLOYMENT_AND_CONFIG.md` |
