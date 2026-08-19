## Context

See proposal.md — Why. The shape of the existing harness is what constrains the
approach:

- `require_release_identity` is the first statement of `driver.run()`. It builds
  a `ReleaseIdentity` from twenty-odd pinned values, several read out of the
  generated compose env, and rejects `observed_marketplace_commit !=
  marketplace_commit`. That single comparison is what makes a branch untestable.
- `prepare-hosted-compose` runs `gh attestation verify` against
  `arkhai-io/simple-compute-market` before rendering a compose environment, so
  the stack cannot even start without a CI-minted attestation.
- The safety gates already live in the same module but are independent
  functions: `require_test_secret`, `require_connected_account`,
  `require_ready_account`, `require_loopback_webhook`,
  `verify_loopback_webhook_endpoint`. Nothing about them depends on release
  identity — they are fused only by call order.
- `StripeTestEvidence` carries `IdentityEvidence`, which embeds marketplace and
  hosted release identity. Evidence is signed and schema-identified, so adding a
  field is a schema change, not a free annotation.
- The credential broker returns provider credentials, an account ref, an
  authority environment map, eight identity credentials, and two registry API
  keys, with a one-hour expiry. Only its *shape* matters to the harness; nothing
  in the body depends on it being a service.

## Goals / Non-Goals

**Goals:**

- Make the failure that is currently blocking bare metal reproducible on a
  laptop, on a branch, without a release.
- Keep protected evidence exactly as strong as it is today, and make its
  strength legible in the artifact rather than implied by provenance.
- Leave one code path through the body, so a development run exercises the same
  code a protected run does.

**Non-Goals:**

- Any relaxation available to a protected run. Modes are not a spectrum; there
  are two, and only one qualifies.
- Deciding the broker's authentication model. This design fixes its payload
  shape and defers everything else.

## Decisions

### Safety gates are unconditional; provenance gates classify

The division is by what a gate protects, not by how expensive it is to satisfy.
A gate that prevents harm — charging a live card, leaking a credential,
accepting a webhook from off-box — runs in every mode, because a development run
touches the same real Stripe test account and the same real network. A gate that
establishes provenance decides what the resulting artifact may be *cited for*.

This is why the split is safe: nothing that could cause damage becomes optional.
The only thing a development run loses is the right to be called evidence.

Alternative rejected: a single `--skip-gates` escape hatch. It would put both
kinds behind one switch, and the first person in a hurry would skip both.

### Release mode is a property of the evidence, not of the invocation

`--release-mode` selects which gates must pass, but the evidence records what was
actually proven. The recorded mode is derived from whether provenance binding
succeeded, not copied from the flag — so no combination of arguments can produce
an artifact that claims attestation it does not have. A protected invocation
whose binding fails still fails closed; it does not silently downgrade.

`StripeTestEvidence` gains `release_mode`, and the schema identity bumps. A
consumer that has not been updated fails on the schema rather than misreading an
older-shaped document.

### `ReleaseIdentity` keeps one type, with a development constructor

Development runs build the same `ReleaseIdentity` from observed local values —
the working tree's actual commit, the locally built image digest, the staged
manifest hash — rather than a parallel type or a bag of `None`s. Downstream code,
including evidence assembly, stays identical, and a reader of a development
report still sees exactly what was running; it simply is not attested.

The observed-equals-trusted comparison moves into the attested constructor. That
comparison is the whole reason a branch cannot be tested, and it is meaningless
for a run that does not claim to be a release.

### Compose preparation splits at the attestation, not before it

`prepare-hosted-compose` keeps its attested path unchanged, including
`gh attestation verify`. The local path renders the same compose environment from
locally available inputs. The rendering logic is shared; only the source of the
marketplace identity differs. A local stack therefore differs from a released one
in provenance only, which is what makes a development reproduction of a protected
failure worth anything.

### Local credential assembly is built to the broker's response shape

The assembler reads operator-supplied provider credentials and generates the
identity credentials the scenario needs, emitting the same keys the broker
returns. Two consequences: the body cannot tell the difference, and implementing
the broker later means serving that payload rather than redesigning the seam.

Generated identity material is ephemeral and local. The assembler never writes
provider credentials into the repository, and the existing evidence redaction
applies unchanged.

## Risks / Trade-offs

- **A development run is mistaken for qualifying evidence.** → The mode is
  recorded in the artifact, derived rather than declared, and required to be
  checked by whoever cites it; the schema bump makes an unaware consumer fail
  rather than misread.
- **Two compose paths drift.** → They share the rendering; only the marketplace
  identity source differs, and the attested path is unchanged so CI keeps
  proving it.
- **Local runs touch a real Stripe test account.** → Unchanged from today, and
  the safety gates that make that acceptable now apply in every mode rather than
  only the protected one.
- **The blocked qualification tasks stay blocked.** This change does not produce
  the evidence they need; it makes the work that has to precede that evidence
  possible. That is a deliberate limit, not an oversight.

## Migration Plan

Additive and reversible. CI keeps calling the attested path with the same
arguments and gets the same behaviour plus one evidence field. No deployment,
persistence, or wire change. Rollback is reverting the mode argument; the
attested path never depended on it.

## Open Questions

- Whether the credential broker, when built, should serve development runs too
  or remain protected-only. Deferrable: the payload shape is fixed here, and
  either answer consumes it unchanged.
