## MODIFIED Requirements

### Requirement: Stable publisher-chosen listing identity
Every publication MUST carry a non-empty publisher-chosen `listing_id` inside the signed canonical body. The registry MUST retain that value unchanged as the listing resource identity; a repeated publication by the same publisher MAY update the existing listing, while another publisher MUST NOT claim it. Publisher credential rotation MUST preserve publisher and listing identifiers.

#### Scenario: Publisher republishes a known listing
- **WHEN** the owning publisher publishes a changed schema-valid body with an existing `listing_id`
- **THEN** the registry updates the listing under the same listing and publisher identifiers rather than allocating a replacement

#### Scenario: Another publisher reuses a listing identifier
- **WHEN** a different publisher submits an otherwise valid publication carrying an existing `listing_id`
- **THEN** the registry rejects the ownership conflict

## REMOVED Requirements

### Requirement: Publisher identity migration preserves ownership

**Reason**: The conversion it governs (`016_marketplace_principal_auth`) precedes the registry's v0.3.0 floor, `018_listing_resource_column`: every database the registry adopts has already run it, and the registry refuses any database at an earlier revision as unsupported, so the conversion is deleted with the revisions its baseline replaced.

**Migration**: An operator holding a registry database from before the marketplace v0.3.0 release starts the registry from a fresh database.
