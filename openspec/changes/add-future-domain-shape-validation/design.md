# Design

## Grounding

Audited against `origin/dev` at `e91767a3b074b20168bbcb87a8418d8287e5f8a6`.

### The product's domain contract

Three domains declare a `MarketDomainContract`:

| Domain | Identity source |
|---|---|
| `domains/vms` | `DomainIdentity(VM_PROVISION_KIND)` |
| `domains/bare_metal` | `DomainIdentity(BARE_METAL_SCHEMA_KIND)` |
| `domains/apicredits` | `DomainIdentity(API_CREDITS_SCHEMA_KIND)` |

Each contract carries an identity, a contract version, immutable codecs, a
declared capability set, and capability-specific factories. `DomainCapability`
enumerates `BUYER`, `STOREFRONT`, `PUBLICATION`, `SETTLEMENT`, `FULFILLMENT`,
`COMPUTE_PROVISIONING`, and `NEGOTIATION`; the VM contract declares
`PUBLICATION`.

Two consequences. Fixtures for bare metal and API credits can use real
identities and real declared capabilities, so the compatibility claim is about
the product. And the product already has a capability-declaration mechanism, so
the harness does not need its own — it reads what a domain declares rather than
maintaining a parallel list that drifts.

## Decisions

### The seam is proved by an adapter the core has never heard of

One fake adapter, arbitrarily named, carrying an opaque namespaced payload
through the runtime and back. It requires no core edit, and the generic path
contains no branch on its identity.

Rejected: proving genericity by adding a second real domain adapter. It would
demonstrate the same property and cost far more, and it would leave a real
adapter for a domain nobody asked the harness to cover — support that then has
to be maintained, or withdrawn later at a cost.

Rejected: asserting genericity by code review. It is true on the day it is
reviewed. The failure mode is a concrete-domain branch added later for a good
local reason, and only a test notices that.

### Payloads are opaque to the runtime

The generic runtime moves a domain payload without interpreting it. It may check
that a payload is well-formed against its declared namespace; it may not read a
field and behave differently.

The line worth holding: the moment the runtime reads a domain field, adding a
domain means editing the runtime, and the property this change exists to
establish is gone. A domain-shaped decision belongs in that domain's adapter or
oracle.

### Fixtures for real domains use real identities

Bare metal and API credits fixtures use `BARE_METAL_SCHEMA_KIND` and
`API_CREDITS_SCHEMA_KIND` and the capabilities those domains actually declare.

Rejected: invented identities that resemble the real ones. A fixture with a
plausible-but-wrong identity tests the harness against a fiction, and it stays
green when the real identity changes — which is precisely the compatibility
signal wanted.

### Fixtures for domains that do not exist are capped by schema

Inference and optional-provider shapes have no product referent. There is
nothing for such a fixture to be right or wrong about, and elaborating one is
speculative design with the appearance of progress. The abandoned branch is the
worked example: 25 schemas and a profile registry for a harness that had never
run.

So exactly one such fixture is admitted, for one purpose — proving the seam
accepts a namespace the core has never seen — and the schema caps it: an
identity, a namespace, and an opaque payload. No capability declarations, no
actor roles, no expected outcomes, no oracles. A fixture that would carry those
fails validation.

Capping by schema rather than by review comment is the point. "Keep it minimal"
is an instruction; a schema that rejects the elaborate version is a control.

Rejected: omitting non-existent-domain fixtures entirely. Then the seam is only
proved against namespaces the core already knows, which is the weaker claim and
the one that would have been true of the archival branch as well.

### Zero-effect is asserted on effects, not on exceptions

A test that attempts to execute a disabled fixture asserts that no process
started, no file was written, no connection opened, and no state changed. Not
that an exception was raised.

The distinction is not pedantic. An implementation that begins executing and
then fails raises exactly the same exception as one that refuses up front, and
only the effect assertions tell them apart. The failure this guards against is a
disabled fixture that half-runs.

### Incompatible product change fails clearly, and "clearly" is specified

A simulated deprecated or renamed product target produces a failure naming the
target, the domain, and the fixture that referenced it — not a generic
resolution error.

The reason to specify this rather than leave it to good practice: a harness that
fails vaguely against a product change trains its operators to treat harness
failures as noise, and after that it stops being a signal at all.

## Open questions

### Does the onboarding proof need a second fake domain?

The feature-onboarding proof runs the intake workflow against an arbitrary
fixture. One fake adapter demonstrates that adding a domain needs no core edit.
Whether the *workflow* is genuinely repeatable is a slightly different claim, and
it is better evidenced by doing it twice.

Provisional: one fake adapter, and the onboarding proof reuses it rather than
introducing a second. Revisit if the first onboarding turns out to have required
an undocumented step, which is the thing a second run would reveal.

### Where do domain oracles live when the domain has no adapter?

A disabled fixture has no oracle, which is consistent while it stays disabled.
When bare metal or API credits eventually gets an adapter, its oracle is
domain-specific and the question is whether it lives with the harness's adapter
or with the product domain.

Not resolved here, and not urgent — but worth deciding before the second adapter
exists rather than after, because the first answer becomes the precedent.
