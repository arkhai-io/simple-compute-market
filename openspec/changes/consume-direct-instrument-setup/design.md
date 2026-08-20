## Context

See proposal.md — Why. Three facts about the current code shape the approach.

`ReleaseIdentity` already carries a `hosted_contract` — release version, API version,
schema version, funding profiles, capabilities — read from the bound release's own
conformance artifact and hash-verified against it. `build-hosted-producer-locally` put
it there. Nothing downstream of the gate consumes it yet.

The ephemeral config renderers in the hosted harness already rewrite most of what a
consumer asserts about the authority: identity, environment, manifest digest, base URL,
funding profile, authority principals. They do it by counted substitution against a
checked-in template and refuse to render when a count is wrong. The three contract pins
are the ones they skip.

`hosted-buyer.toml` already establishes the idiom for a pin the renderer owns: a
non-activating placeholder plus a comment saying the run replaces it from the verified
manifest. Its `expected_manifest_digest` is sixty-four zeros.

## Goals / Non-Goals

**Goals:**

- One source for what a run asserts about the hosted authority, on both sides of the
  stack, reached without re-reading or re-verifying the release artifact.
- A committed consumer template that cannot be used unrendered.
- Direct setup verification reachable only through the pinned client's own interface.
- The bank-funded saved-instrument path chosen by what the bound release declares, with
  the interactive path left exactly as it is for releases that declare nothing.

**Non-Goals:**

- Teaching the marketplace what a microdeposit is. The evidence is opaque to everything
  between the payer and the authority.
- Any change to how the authority verifies the evidence. That is producer behavior and
  ships in 0.3.0 already.
- Making the protected lane runnable before 0.3.0 is published.

## Decisions

### D1. The contract reaches the renderers as a value, not as a second read

The config renderers take the contract from `ReleaseIdentity.hosted_contract`, passed in
at construction alongside the manifest digest they already receive. They do not open the
conformance artifact themselves.

*Alternative considered:* let each renderer read and verify the artifact. Rejected — two
readers of the same file can disagree, and the disagreement would surface as a rendered
config rather than as a gate refusal. The gate already read it, verified its hash, and
refused a mismatch; everything downstream should be reading that decision, not redoing it.

### D2. The committed template carries pins that cannot activate

`expected_api_version`, `expected_schema_version`, and `required_capabilities` stay
present in `hosted-storefront.toml` and `hosted-buyer.toml`, as values no real release
can satisfy, with the comment the manifest-digest placeholder already carries.

The capability placeholder must fail closed rather than fail open: an empty
`required_capabilities` list requires nothing and would let an unrendered template pass.
The placeholder is therefore a single capability no release declares, not an empty list.

*Alternative considered:* delete the keys from the template and have the renderer insert
them. Rejected — the committed file stops being a schema-valid config, so nothing can
validate it, and a missing key is easier to reintroduce silently than a placeholder that
visibly names itself.

Rendering keeps the existing discipline: a substitution whose count is not exactly what
the renderer expects refuses to render at all.

### D3. Naming which release you bind is not the defect

`HOSTED_RELEASE_TRUST` continues to name one trust config. Choosing which release a
build binds is a real choice and belongs in the build. What gets derived from it are the
things that merely follow: the client wheel filename, the OpenAPI, conformance, and
migration artifact filenames, all of which are `<name>-v<version>` for the version the
trust config states. This is the provenance-versus-contract split from the previous
change applied to the build: state what you chose, derive what follows.

### D4. Verification goes through the pinned client or not at all

The facade calls the client's `verify_payer_setup` with the client's own request model.
Where the pinned client does not expose it, the operation is reported as unavailable
under the bound release.

*Alternative considered:* keep the client at `==0.2.1` and hand-build the verification
request — construct the body, canonicalize it, sign it, verify the response. Rejected,
and now refused by spec: it would duplicate hosted canonicalization, signing, and
response verification in the consumer, which is the one thing the hosted client exists
to prevent. It would also drift silently the first time the authority changed a header.

*Alternative considered:* a range pin plus capability probing by attribute. Rejected —
the consumer requirement is that it pins one exact client wheel, and a range makes the
installed contract unobservable from configuration.

So the pin moves to `==0.3.0`. This is a sequencing consequence, not a policy change:
you cannot consume a capability without depending on the release that declares it.

### D5. Capability gating reuses the prerequisite path, not a new one

`require_hosted_capabilities` and the per-scenario capability map added by the previous
change are where direct setup is declared as a prerequisite of a bank-funded
saved-instrument lane. A bound release that lacks it produces the same
unavailable-prerequisite refusal as any other missing capability, before any provider
mutation — not a failure inside the setup stage.

### D6. Which evidence the lane submits

Stripe test mode exposes fixed microdeposit verification values, so the lane submits the
documented test-mode evidence rather than reading it back from the provider or from the
authority. This keeps the existing rule that every provider assertion derives from the
selected profile's supported test-mode behavior, and keeps the harness from acquiring a
provider-introspection path it does not otherwise have.

The exact values are confirmed against a live authority during implementation rather
than asserted from documentation; a value the authority rejects is reported as an
unavailable prerequisite, not worked around.

## Risks / Trade-offs

- **The protected lane cannot exercise this until 0.3.0 publishes.** → Nothing about the
  protected lane changes: it requires a signed manifest and refuses without one, exactly
  as today. The block is recorded in the proposal rather than routed around, and the
  development lane runs the same code path end to end in the meantime.

- **The 0.3.0 client wheel is not on any index.** → It is resolved from the local
  wheelhouse by path, which is how `0.2.1` resolves today; the wheel is copied from the
  bound release directory. No new resolution mechanism is introduced. The failure mode
  if it is missing is a lock error at build time, not a runtime surprise.

- **Bumping the client changes the marketplace's recorded consumer identity.** → That is
  what the field records, and protected evidence keeps recording it separately from the
  hosted side. No evidence shape changes.

- **A placeholder pin that fails open would silently weaken every unrendered run.** →
  Addressed by D2's choice of an unsatisfiable capability over an empty list, and by a
  test that asserts the committed templates cannot satisfy any real release.

- **Test-mode microdeposit values are provider-owned and could change.** → The lane
  reports a rejected submission as an unavailable prerequisite rather than retrying or
  substituting another path, so a provider change surfaces as an explicit unavailable
  external prerequisite, which the evidence requirement already demands.

## Migration Plan

The consumer templates and the build stop naming `0.2.1` in the same change that moves
the client pin, so there is no window in which a rendered config and an installed client
disagree. Rollback is reverting the pin and the affected lockfiles; the rendering change
is inert against a 0.2.1 authority, because a bound 0.2.1 release renders exactly the
values the template used to state.
