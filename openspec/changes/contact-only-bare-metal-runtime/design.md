# Design

## Decisions

- Introduction-only composition follows the enabled mechanism set rather than a
  new deployment flag. Physical composition still requires trusted sites.
- Unbacked provenance is one constrained alternative: no site, pool, or Physical
  Resource, represented by SQL NULL with immutable listing/thread parity. Domain
  admission, not shared core, decides which offers qualify.
- Amountless negotiation carries absent prices and a complete advertised rateless
  option. Shared core does not identify the mechanism or substitute zero.
- File publication validates the whole input before listing intent and registry
  mutations. Signed schema retrieval precedes schema validation. Each listing's
  immutable public intent commits separately, before the first remote upsert.
  Stable IDs support bounded retries without reopening or withdrawing omitted IDs.
- Acceptance commits only the accepted plan and pending obligation bookkeeping
  together. Explicit buyer start captures contacts and drives completion; party
  reads do neither. Old unregistered references remain unresolved without backfill.
- The contact kit and loader share decoded-string literal protection. It is not
  general data-loss prevention or detection of transformed/unconfigured data.
- General recipient-side delivery remains optional. Only synthetic file
  publication requires no seller delivery callback.

## Alternatives rejected

Fake sites would grant authority the seller does not possess. Parallel
bare-metal-only persistence would duplicate the common immutable binding contract.
Independently optional provenance fields would admit partial physical authority;
site absence instead discriminates a constrained unbacked alternative.

Serialized-JSON matching can miss literal contact values whose representation is
escaped. Recursive decoded-string matching covers that case without introducing
normalization or a general privacy classifier.

## Validation and qualification boundary

The source-level semantic seams are recorded in the owning specifications. Local
checks exercise seller HTTP and SQLite with signed buyer clients, plus an
independent registry process. The registry integration uses its own locked source
environment, not an installed registry wheel. Installed seller/contact-kit checks
cover the pending and privacy corrections; they do not qualify an OCI image.

The bare-metal factory and chart retain their actual environment-and-file inputs,
not the other storefront's profile loader. The chart references existing public
offer and private credential/configuration objects. The non-pushing image-build
CI gate exists but is not evidence that an image has run or been released.
Installed-image dependency provenance, release inputs, and live publication and
introduction verification remain separate open tasks. No local fixture proves
physical delivery, encrypted storage, or an activated deployment.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Unbacked alternative, nullable immutable thread parity, transactional migration | [Market composition spec](../../specs/market-composition/spec.md#requirement-unbacked-storefront-provenance), [architecture](../../specs/market-composition/architecture.md#frozen-storefront-registry-and-executable-ownership) |
| Shared accepted-plan/local-bookkeeping transaction, no lifecycle callback effects | [Market composition spec](../../specs/market-composition/spec.md#requirement-accepted-plan-bookkeeping-shares-the-commit-transaction), [architecture](../../specs/market-composition/architecture.md#accepted-plan-persistence) |
| Generic absent money and full selected-option forwarding | [Buyer orchestration spec](../../specs/buyer-orchestration/spec.md#requirement-amountless-buyer-negotiation-is-explicit), [architecture](../../specs/buyer-orchestration/architecture.md#absent-monetary-inputs) |
| Whole-file validation, typed/flat projection, stable local intent and bounded signed retry | [Storefront publication spec](../../specs/storefront-publication/spec.md#requirement-synthetic-contact-publication-validates-the-whole-file), [architecture](../../specs/storefront-publication/architecture.md#synthetic-contact-file-publication) |
| Introduction-only startup/admission, pending reads, explicit capture and party isolation | [Contact exchange spec](../../specs/contact-exchange-settlement/spec.md), [architecture](../../specs/contact-exchange-settlement/architecture.md#acceptance-and-capture) |
| Literal decoded-string privacy protection and limits | [Contact exchange spec](../../specs/contact-exchange-settlement/spec.md#requirement-literal-configured-contacts-stay-out-of-public-artifacts), [architecture](../../specs/contact-exchange-settlement/architecture.md#privacy-boundary) |
| Capacity applicability and optional recipient delivery remain distinct | [Repository architecture](../../../docs/development/ARCHITECTURE.md#settlement-configuration) |
| Runtime-only versus startup publication, environment/chart inputs and retained state | [Deployment/configuration](../../../docs/development/DEPLOYMENT_AND_CONFIG.md#bare-metal-introduction-only-configuration) |
| Goal 6 current state and image/live gap ownership | [Roadmap](../../../docs/development/ROADMAP.md#goal-6--make-the-settlement-mechanism-a-composed-choice) |
| Locally implemented/promoted status, no physical-qualification dependency | [Campaign index](../README.md#roadmap-goal--make-the-settlement-mechanism-a-composed-choice) |
| Contact capability and companion discoverability | [Capability index](../../specs/README.md#capabilities) |

The publication, buyer, and contact specifications own the promoted requirements;
the original combined delta remains change history, not an additional permanent
owner. Cross-domain contact composition and retention automation remain unowned
Goal 6 gaps. Image/live qualification remains open in this change.
