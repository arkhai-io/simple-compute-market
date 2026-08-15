## Why

The marketplace can exercise the hosted settlement adapter in-process, but it cannot currently prove that a released private authority composes locally with registry publication, negotiation, VM fulfillment, settlement recovery, and buyer-visible Checkout behavior. A local artifact-driven harness is needed so authorized developers and protected CI can verify that system boundary without open-sourcing the authority or relying on a shared remote development deployment.

## What Changes

- Add an opt-in local Compose profile that joins the released hosted authority API, migration, worker, and durable state to the marketplace network by immutable image and manifest inputs; it never builds or mounts hosted-service source.
- Add marketplace-owned staged E2E scenarios for hosted-only publication, buyer discovery and negotiation, Checkout action, VM fulfillment, collection, eligible reclaim, restart recovery, accepted-mechanism pinning, and coexistence with Alkahest.
- Consume a private, versioned E2E simulator release from `hosted-settlement-service` for deterministic payment, transfer, refund, webhook, outage, idempotency, and clock controls. Test controls remain separate from public buyer/storefront APIs and are unavailable in production service releases.
- Add a protected real-Stripe test-mode lane using the same local marketplace topology, real Checkout, Stripe CLI webhook forwarding, and exact provider-effect assertions. It is optional for local development and never substitutes for hermetic lifecycle evidence.
- Make public/default builds and tests independent of private registry credentials, private hosted artifacts, Stripe credentials, and the sibling source checkout. Missing private inputs produce an explicit opt-in prerequisite failure rather than skipping a selected hosted suite.
- Let private trusted CI check out an exact marketplace commit and invoke the repository-owned E2E target; fork and untrusted pull-request jobs receive no private image, simulator, signing, or Stripe credentials.
- Split the temporary hosted-repository cross-repo smoke into hosted client/service conformance and marketplace-owned adapter/system evidence so no hosted package or lasting hosted test imports a market domain.
- Keep portable non-EVM conditions as the default hosted system path. Local Anvil/EAS conformance is a separate profile rather than a prerequisite for wallet-free Stripe tests.
- Do not publish the private service implementation, simulator implementation, provider secrets, administrator APIs, provider identifiers, raw webhooks, or service source through this repository.
- Do not make hosted settlement required for ordinary marketplace builds, existing Alkahest E2E, or public contributor workflows.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `test-compatibility`: Add artifact-bound, marketplace-owned hermetic and real-provider system evidence for an optional private authority, with explicit staged state, deterministic controls, process restarts, and trusted-CI isolation.
- `deployment-state`: Add an opt-in local hosted-settlement composition that consumes immutable private release artifacts without source/editable dependencies or default public-CI credentials.

## Impact

- Affected code: root and VM Compose overlays, `e2e-tests` staged scenarios/fixtures, hosted adapter test support, marketplace Make targets, release verification scripts, and protected workflow configuration.
- External dependency: private change `add-hosted-settlement-e2e-simulator` must publish a compatible simulator image/control contract before hermetic system tests can pass. `add-hosted-account-identities`, `add-nonchain-marketplace-identities`, and `unify-settlement-mechanism-configuration` must provide the final signer, client, configuration, and CLI contracts before the no-wallet scenario is implemented.
- Deployment: local/E2E only. Production hosted deployment topology and marketplace production activation do not change.
- Packaging: the marketplace consumes signed wheels, manifests, schemas, and digest-pinned images; it gains no editable sibling source or hosted service implementation dependency.
- Contributor workflow: default public checks remain unchanged. Authorized developers opt into private artifact acquisition; protected CI runs the private lanes without exposing credentials to untrusted code.

## Supersession disposition

Marketplace implementation checkpoint `c128b902` preserves the ordinary hosted-release composition, marketplace lifecycle, protected Stripe driver/evidence, and simulator consumer work created under this change. Hosted producer checkpoints `f46ca41` and `d4fd002` preserve the separately released simulator implementation and documentation.

The hermetic Compose acceptance matrix did not complete and this change claims no accepted simulator system evidence. `replace-hosted-simulator-with-stripe-test-e2e` supersedes the simulator strategy: deterministic Arkhai recovery moves to provider-port integration in hosted producer change `replace-e2e-simulator-with-scripted-provider-tests`, while hosted financial system acceptance uses Stripe test mode through the ordinary production release. Completed implementation and real-Stripe evidence remain recorded here; no remaining task should validate or release the simulator.

The delta specs and permanent-document promotion statements in this change are
retained as proposal history only and MUST NOT be applied as current simulator
capabilities. Current evidence ownership, production-only composition,
protected prerequisites, run identity, sanitization, and failure attribution
are promoted by the replacement into
`openspec/specs/{test-compatibility,deployment-state}/{spec,architecture}.md`,
`docs/development/{ARCHITECTURE,TESTING,DEPLOYMENT_AND_CONFIG}.md`, and
`e2e-tests/tests/e2e/roles/README.md`. The only concrete acceptance still
credited to this change is the completed work and real Stripe evidence recorded
above; unchecked simulator acceptance and closeout remain incomplete by
design.
