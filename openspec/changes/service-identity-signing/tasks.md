# Implementation Tasks

## 1. Registry and identity configuration

- [ ] 1.1 Re-verify `design.md`'s Context, particularly that `storefront_admin_key` is
      still dual-purpose and that `Eip191Verifier` still compares the recovered value to
      `identity.identifier`.
- [ ] 1.2 Define the site registry as an interface returning `(site_id, url, identity)`,
      config-backed initially. Consumers must not read configuration directly —
      `design.md` records that as what turns admin management into a rewrite.
- [ ] 1.3 Store the identity as `market_identity.Identity`, not a scheme-specific field.
      For `eip191` the identifier is the lowercase 0x **address**, which is a hash of the
      public key and not the key itself; a field named for a public key would be wrong.
- [ ] 1.4 Give the authority the storefront's identity, singular — that direction is
      one-to-one.
- [ ] 1.5 Focused tests: registry resolves by site; an identity registered for one site
      does not authenticate another; a non-default scheme's identifier form round-trips.

## 2. Sign storefront-to-authority calls

- [ ] 2.1 Check whether `verify_signed_identity`'s (operation, resource_id, timestamp)
      canonicalization transfers to every service call, including projection polling and
      capacity-release callbacks, which may have no natural `resource_id`. If it does
      not, extend the canonicalization once rather than forking a second signed-request
      format.
- [ ] 2.2 Sign outbound storefront calls; verify them at the authority against the
      registered storefront identity.
- [ ] 2.3 Keep the shared key accepted throughout, so this section is independently
      deployable.
- [ ] 2.4 Focused tests: valid signature accepted; wrong identity rejected; replay
      outside the skew bound rejected; verification performs no network call.

## 3. Sign authority-to-storefront calls

- [ ] 3.1 Sign outbound authority calls with the authority's own material; verify at the
      storefront against the site registry.
- [ ] 3.2 Confirm the authority no longer signs with material any caller holds — the
      specific defect this change exists to close.
- [ ] 3.3 Focused tests: a compromised storefront credential cannot produce a call the
      storefront accepts as authority-originated; an unregistered site's call is
      rejected.

## 4. Rotation

- [ ] 4.1 Accept a set of valid identities per counterparty rather than one.
- [ ] 4.2 Prove the three-step rotation: introduce, adopt, retire — each independently
      deployable, with no instant where both sides must change together.
- [ ] 4.3 Focused tests: both identities accepted during overlap; retired identity
      rejected.

## 5. Freeze the shared key

The behavioral boundary. After this, an unsigned caller is refused.

- [ ] 5.1 Stop accepting `storefront_admin_key` as an authentication primitive; do not
      delete the setting in this change.
- [ ] 5.2 Document that rollback past this section is a coordinated redeploy of both
      services rather than a code revert, which is why the freeze is separate from
      Sections 2 and 3.

## 6. Deployment and infrastructure

- [ ] 6.1 Private keys through each service's Secret profile; identities through ordinary
      configuration. Identities are not secret, so the sensitive surface shrinks rather
      than grows.
- [ ] 6.2 Record key placement rules in `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- [ ] 6.3 Coordinate key generation and distribution with the infrastructure repository.
      This change cannot land operationally without it.
- [ ] 6.4 Deployment render tests for both directions and for the rotation overlap.

## 7. Validation

- [ ] 7.1 Run the provisioning middleware and event-sink suites, storefront site-client
      suites, `kit/identity` suites, and deployment render tests. Disclose any suite not
      run.
- [ ] 7.2 Measure per-request verification cost. ecrecover is local and cheap but not
      free, and it now runs on every inter-service call including projection polls —
      which is an independent argument for replacing polling with push.
- [ ] 7.3 Run `openspec validate --all --strict` against the baseline current at
      implementation time.

## 8. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 8.1 **Comment hygiene.** Run `make check-comment-hygiene`. Read
      `settings.toml`'s `storefront_admin_key` comment and `middleware/auth.py`'s
      docstring directly; both describe the dual-purpose shared secret this change
      replaces.
- [ ] 8.2 **Import placement.** Review imports this change adds; the provisioning service
      gains a `kit/identity` dependency.
- [ ] 8.3 **Documentation compliance.** Confirm the signing rules landed in
      `physical-provisioning` and `storefront-publication`, the eip191 rationale in
      `storefront-publication/architecture.md`, key placement in
      `DEPLOYMENT_AND_CONFIG.md`, and that `ARCHITECTURE.md`'s site-authority section no
      longer says one shared key does both jobs.
- [ ] 8.4 **Narrative compression.** Compress completed-task notes to final behavior,
      validation evidence, and promotion destinations.
- [ ] 8.5 **Roadmap currency.** Record the disposition; this change closes no roadmap
      goal's gap on its own.
- [ ] 8.6 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Service calls are authenticated by counterparty signature; no party holds material letting it sign as another; verification is local and replay-bounded | `openspec/specs/physical-provisioning/spec.md` — "Service calls are authenticated by counterparty signature" |
| Counterparty identities rotate through overlapping acceptance | `openspec/specs/physical-provisioning/spec.md` — "Counterparty identities rotate without coordinated downtime" |
| Storefronts hold a registry of site identities, in scheme-tagged form, reached through an interface | `openspec/specs/storefront-publication/spec.md` — "Storefronts hold a registry of site identities" |
| Why an eip191 identity rather than a bare signing key | `openspec/specs/storefront-publication/architecture.md` |
| The dual-purpose key and what replaces it | `docs/development/ARCHITECTURE.md`, site authority |
| Private key placement versus non-secret identity configuration | `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Why an address is not a public key, and why the registry holds an `Identity` | This change's `design.md` |
