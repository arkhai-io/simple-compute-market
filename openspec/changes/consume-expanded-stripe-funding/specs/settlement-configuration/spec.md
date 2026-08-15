## ADDED Requirements

### Requirement: Hosted options use exact funding profiles

The `fiat.stripe.v1` registration MUST admit only the exact funding profiles `card.v1`, `us_bank_transfer.v1`, and `us_ach_debit.v1`. Each hosted publication clause MUST name exactly one profile, lowercase currency, positive minor-unit rate, interaction capability, and typed condition profile. New options MUST NOT contain `payment_method_types`, free-form provider methods, unversioned aliases, or a recovery-only legacy card value.

The funding profile MUST participate in the complete deterministic option identity and in the immutable accepted settlement projection. Equal resource, rate, currency, parties, and condition under different profiles MUST produce distinct option identities.

#### Scenario: Card and ACH have the same rate

- **WHEN** a seller configures `card.v1` and `us_ach_debit.v1` with otherwise identical clauses
- **THEN** publication produces two separately identifiable options whose accepted plans retain their exact profile

#### Scenario: Unsupported funding string is configured

- **WHEN** a clause contains `card`, `sepa_debit`, a Stripe method type, or another unregistered value
- **THEN** typed validation fails before readiness, publication, negotiation, or provider I/O

### Requirement: Hosted profile readiness is independent and exact

Hosted preflight MUST verify the exact signed client/API/schema and payer/profile/authorization capabilities plus authority, seller account, condition resolver, currency, country policy, and profile readiness required by each configured clause. It MUST return one safe result per profile. An unready profile MUST suppress only clauses for that profile, while ready hosted profiles and Alkahest remain available. Accepted operations MUST remain recoverable after a profile becomes unready for new materialization.

#### Scenario: ACH is unready while card is ready

- **WHEN** the authority reports a safe ACH blocker and valid card capability/readiness
- **THEN** publication suppresses ACH options, retains card and Alkahest options, and reports no provider identifier or secret

#### Scenario: Manifest lacks a selected profile

- **WHEN** the verified release does not advertise one configured profile or authorization contract
- **THEN** that profile remains unavailable and no compatible-major or unversioned fallback is used

### Requirement: Buyer hosted compatibility includes local payer readiness

Buyer compatibility for a hosted option MUST require the exact installed profile capability, supported USD/country policy, required interaction ability under the current action policy, and a selected local buyer profile with an active opaque payer binding ready for that authority/environment. Discovery-time checks MUST use only local profile metadata and advertised option data; they MUST perform no hosted mutation. Compatibility MUST be revalidated immediately before negotiation start and exact authorization.

#### Scenario: Buyer selects an ACH interaction mode

- **WHEN** an advertised ACH option survives resource filtering and the selected local profile has an active authority/environment binding plus interaction capability
- **THEN** explicit interactive mode remains compatible without a saved mandate, while saved/off-session mode requires the exact ready instrument and mandate

#### Scenario: Local readiness changes after discovery

- **WHEN** the selected payer binding or instrument readiness becomes revoked before negotiation starts
- **THEN** revalidation fails without accepting terms or switching to another profile

### Requirement: Buyer off-session automation policy is explicitly bounded

Buyer configuration MAY enable off-session authorization only through a typed policy that names the exact authority/environment, funding profile, currency, maximum amount per purchase, maximum aggregate amount over a declared window, and optional seller-principal bounds. Disabled or absent policy MUST require ordinary interactive authorization handling. The policy MUST NOT contain provider IDs, instruments, mandates, action URLs, raw hosted payloads, or blanket seller permission.

Policy evaluation MUST occur only for one accepted obligation and MUST produce a decision to sign that exact authorization or require interaction. It MUST NOT change profile, instrument selection, amount, currency, destination, seller, obligation hash, marketplace operation ID, or expiry.

#### Scenario: Purchase exceeds per-purchase bound

- **WHEN** an accepted obligation exceeds the configured exact profile/currency amount limit
- **THEN** automation refuses to sign and the buyer follows the interactive action policy without selecting another funding option

#### Scenario: Seller is outside the allowlist

- **WHEN** a seller-controlled obligation otherwise matches but its canonical principal is outside optional policy bounds
- **THEN** automation refuses and no hosted funding authorization is created automatically

### Requirement: Hosted consumer configuration pins the expanded release

Enabling any expanded hosted profile MUST pin one exact verified hosted manifest, client wheel, API/schema version, payer-profile contract, funding-authorization contract, funding-profile set, identity capability, and service image identity. Buyer and storefront roles MUST agree on those public pins before publication or authorization. Marketplace schemas MUST reject hosted provider, Customer, PaymentMethod, mandate, webhook, database, migration, and administrator fields.

#### Scenario: Buyer and storefront pins differ

- **WHEN** the buyer expects a different payer/profile capability or client identity from the publishing storefront's verified authority release
- **THEN** compatibility fails before terms acceptance or payer authorization

## MODIFIED Requirements

### Requirement: Recovery uses pinned mechanism identity

Run logs MAY record configuration-schema version, public resolved mechanism set, selected funding profile, safe funding-authorization reference, and source-free fingerprints, but MUST NOT store secrets, stable payer/instrument refs, provider data, or raw actions. Recovery MUST use the accepted plan's canonical mechanism, exact funding profile, obligation, funding authorization, and operation identities rather than current priority, current profile readiness, current automation policy, or another mechanism/profile's readiness.

#### Scenario: Priority changes during a funded obligation

- **WHEN** recovery resumes an obligation after another mechanism becomes first priority
- **THEN** it resumes the originally pinned mechanism, funding profile, authorization, and stable operation identity without fallback

#### Scenario: Profile is disabled during pending funding

- **WHEN** recovery resumes an accepted bank operation after operators disable that profile for new deals
- **THEN** it continues status/reclaim under the accepted profile and never converts the obligation to card or Alkahest
