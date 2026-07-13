## ADDED Requirements

### Requirement: Compute capability composition proof

VM and bare-metal storefront compositions MUST obtain their market semantics from the common market-domain contract and their optional execution behavior from the common compute-provisioning contract, without making compute provisioning universal to other domains.

#### Scenario: Current compute domains are composed

- **WHEN** VM and bare-metal storefronts are configured against the extracted compute provisioner
- **THEN** each uses its own deterministic market hooks and executor payloads behind the two shared contracts

#### Scenario: API-credit domain is composed in the same repository

- **WHEN** API-credit buyer/storefront contract tests run without compute provisioning configured
- **THEN** its market-domain behavior remains complete and no compute client or executor adapter is required
