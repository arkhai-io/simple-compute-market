## MODIFIED Requirements

### Requirement: Arkhai payment request and receipt authentication

Headless calls to the Arkhai payments service MUST authenticate with WorkOS user-scoped API keys issued for the caller's Arkhai account. Arkhai payment receipts MUST use the service's Ed25519 `arkhai.payments.receipt.v1` signature framing and be verified through the identity kit. A receipt MUST verify only when its signed `livemode` equals the verifying role's configured `livemode`: a test-mode receipt never proves a live payment, and a live receipt never satisfies a test deployment. Marketplace registry, storefront, and negotiation request authentication MUST remain on their existing contracts and MUST NOT become a cross-repository source dependency.

#### Scenario: Arkhai payment request is authenticated

- **WHEN** a buyer or seller kit calls the Arkhai payments service
- **THEN** the request uses the owner's WorkOS user-scoped API credential, and the caller verifies a returned receipt with the published signature contract rather than copying marketplace request-signing code

#### Scenario: A receipt from the other mode proves nothing

- **WHEN** a buyer or seller stage receives a correctly signed receipt for the accepted mandate whose signed `livemode` differs from the stage's configured `livemode`
- **THEN** the receipt does not verify, the stage produces no verified settlement evidence, and delivery or issuance stays blocked
