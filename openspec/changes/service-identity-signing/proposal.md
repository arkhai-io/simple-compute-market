## Why

**Supersedes `add-storefront-principal-authentication`** (2026-08-06). That change
proposed multi-principal shared-secret authentication plus per-record `owner_principal`
ownership, motivated by several storefronts sharing one provisioning authority. That
topology is no longer being pursued, so per-record ownership between principals became
vacuous — with one storefront per authority, "does this principal own this record" is
always true. The defect it found is real and survives; the mechanism does not.

The defect: `storefront_admin_key` is a single shared secret doing two jobs. Its own
settings comment says it "signs the outbound lease-watchdog callback to the storefront,
and gates every inbound request." One secret authenticates both directions, so a
storefront that holds the key to *call* an authority also holds that authority's
*outbound signing* identity — a compromised storefront can forge callbacks that appear
to come from the provisioner. Rotation is impossible without downtime, because exactly
one secret is valid at a time and both sides must flip together.

The repository already has the mechanism to fix this and has never applied it to this
boundary. `kit/identity` is a pluggable identity-scheme registry, and
`core_storefront.auth.verify_signed_identity` already performs replay-resistant
asymmetric request verification — `X-Signature`/`X-Timestamp`, a skew bound, and a
canonical (operation, resource_id, timestamp) message — on every buyer request. Only the
service-to-service boundary still uses a shared secret.

Choosing `eip191` rather than a plain signature scheme is deliberate and separately
justified: pairing each site identity with a wallet is a step toward a trustless
storefront-to-site relationship, and makes site-owner collateral as a registration
prerequisite expressible without a second identity mapping. Verification stays offline —
`Account.recover_message` is pure ecrecover, needing no RPC and no chain configuration.

## What Changes

- Sign requests in both directions with the signer's private key and verify against the
  counterparty's registered identity, replacing the shared secret as the authentication
  primitive. Reuse `verify_signed_identity`'s existing canonicalization and skew
  handling rather than inventing a second signed-request format.
- Give the storefront a site registry of `(site_id, url, identity)`, where `identity` is
  a scheme-tagged `market_identity.Identity`. For `eip191` its `identifier` is the
  lowercase 0x address — **not** a public key, which an address is not derivable back
  into. Populated from configuration initially, but read through a registry interface so
  moving to storage later is a second implementation rather than a rewrite.
- Give the provisioning authority the storefront's identity, one per authority, matching
  the actual one-to-one cardinality of that direction.
- Support overlapping valid identities per counterparty so a key can be rotated without
  a coordinated flip or downtime.
- Retire `storefront_admin_key` as the authentication primitive once both directions are
  signed, following the freeze-then-redirect pattern rather than removing it abruptly.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `physical-provisioning`: an authority authenticates requests by verifying a signature
  against a registered storefront identity, rather than by comparing a shared secret,
  and signs its own outbound calls with material the caller never holds.
- `storefront-publication`: a storefront holds a registry of site identities and verifies
  authority-originated calls against them, rather than trusting a secret it also uses to
  authenticate itself.

## Non-Goals

- Do not add multi-principal shared-secret configuration or per-record
  `owner_principal` ownership. Both were the superseded change's mechanism for a
  topology that is not being pursued.
- Do not support many-to-many storefront-to-authority ownership. The registry is
  one-to-many in the direction that is genuinely many — sites per storefront — and
  one-to-one in the direction that is not.
- Do not implement site-owner collateral, staking, or any on-chain registration
  prerequisite. This change makes them expressible by giving each site a wallet
  identity; it does not build them.
- Do not build storefront-admin site management. Configuration is the initial source;
  the registry interface is what makes admin management a later change rather than a
  rewrite.
- Do not change buyer authentication, which already works this way.
- Do not add a second identity scheme. `eip191` is registered and offline-verifiable
  today.

## Impact

- Affected code: `provisioning/compute/service` (`StorefrontAuthMiddleware` and the
  outbound event sink), `core/storefront` and the VM storefront's site client
  configuration, `kit/identity` if the service-to-service canonicalization needs a
  distinct operation vocabulary, and `kit/site-client`.
- Affected configuration: each service gains a private key in its Secret profile and the
  counterparty's identity in ordinary configuration. Identities are not secret, so the
  sensitive surface shrinks: one secret per service replaces one shared secret per
  relationship held by both sides.
- Affected deployment, including the infrastructure repository: key generation and
  distribution, Secret profiles for private keys, ConfigMap entries for identities.
- Affected tests: middleware and event-sink suites, site-client suites, rotation
  coverage, and deployment render tests.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the site-authority section, which currently
      states that one shared key both gates inbound requests and signs outbound
      callbacks, and that there is no per-storefront identity.
- [x] Existing subsystem specification — `openspec/specs/physical-provisioning/spec.md`
      and `openspec/specs/storefront-publication/spec.md`.
- [ ] New subsystem specification — none.
- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md` — key material placement.

### Knowledge to promote

- Service-to-service calls are authenticated by signature against a registered
  counterparty identity, and no party holds material that lets it sign as another —
  `openspec/specs/physical-provisioning/spec.md`.
- A storefront holds a registry of site identities and verifies authority calls against
  it — `openspec/specs/storefront-publication/spec.md`.
- Why an eip191 identity rather than a bare signing key —
  `openspec/specs/storefront-publication/architecture.md`.

## Dependencies and Related Changes

- Supersedes `add-storefront-principal-authentication`, which is removed rather than
  amended: its mechanism and its motivating topology are both gone, and Git history
  preserves it.
- Unblocks `replace-polling-with-authenticated-push`, which was blocked on a trusted reverse
  channel and can now replace polling with authenticated push.
- `pools-7-storefront-fulfillment-cutover` Section 8's ownership check no longer needs
  this change: with one storefront per authority the check is vacuous. Its
  existence-only check stands.
- Independent of every Goal 1–5 change; touches no capacity, negotiation, settlement, or
  publication behavior.
