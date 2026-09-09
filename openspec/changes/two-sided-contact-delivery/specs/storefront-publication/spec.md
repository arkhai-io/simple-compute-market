## MODIFIED Requirements

### Requirement: Synthetic contact publication validates the whole file

The callback-absent requirement below applies to schema version 1. Schema version
2 instead requires the exact new two-sided runtime and policy described below;
all shared synthetic/whole-file validation constraints remain applicable.

The bare-metal `publish-contacts` command and opt-in startup publication SHALL
share one loader for a strict JSON document: schema version 1, one to five offers,
unique explicit listing IDs, bounded synthetic labels, positive GPU/CPU/RAM/disk
dimensions, region, and a configured public contact profile. The file SHALL be at
most 128 KiB. Offers and public profile terms SHALL include
`SYNTHETIC TEST OFFER: no supply, payment, or provisioning.`

The loader SHALL require introduction-only composition with no seller delivery
callback. It SHALL prepare every offer, enforce the contact kit's
[literal privacy guard](../contact-exchange-settlement/spec.md#requirement-literal-configured-contacts-stay-out-of-public-artifacts),
obtain the signed registry filter specification, require `vms.compute/1`, validate
all projected requests against that schema, and check every existing-ID conflict
before creating listing intent or mutating the registry. Runtime database
initialization and authenticated schema reads are not listing publication.

Local artifacts SHALL use the typed `bare_metal.v1` listing, with no access or
physical authority. Discovery SHALL additionally project flat GPU, region, CPU,
RAM, and disk fields for the existing compute schema. Each offer SHALL carry one
rateless contact option and no accepted escrows.

#### Scenario: The last offer is invalid

- **WHEN** the last entry fails public-content, schema, or existing-ID validation
- **THEN** no listing intent or registry mutation is performed for the file
- **AND** a configured-contact leak is refused before registry calls as well

## ADDED Requirements

### Requirement: Policy-eligible publication has a separate version and new IDs

Schema version 2 SHALL contain exactly schema_version, delivery_policy and offers.
It SHALL preserve version-1 ContactOffer fields/bounds, require 1–5 unique IDs
prefixed synthetic-contact-delivery-, and require each referenced configured
profile to match the exact root contact-delivery.v1 policy. Private contact,
route and credentials SHALL remain out of the public file. Version-1 files,
example bytes, IDs and option hashes SHALL remain unchanged. First version-2
publication SHALL require an absent local ID; retry SHALL require the identical
version-2 local immutable intent, never conversion of an old ID.

#### Scenario: Old ID is reused for eligible work

- **WHEN** a version-2 file collides with a version-1 or other pre-existing ID
- **THEN** whole-file preflight rejects before local intent or registry POST

### Requirement: Eligible publication validates private configuration without effects

All version-2 contacts, routes, credential syntax, profiles and resolved runtime
configuration SHALL validate before constructing an outbound client. Full signed
registry-schema and existing-ID validation SHALL precede local intent/POSTs.
Decoded-string leak checks SHALL cover private contact/route/credential values;
diagnostics SHALL use bounded stages without echoing contaminated IDs or values.
Structural preflight SHALL NOT authenticate SMTP or send mail. Default chart
rendering SHALL remain unchanged when deliveryConfigSecret is null; opt-in SHALL
project only an existing Secret name/key into the main runtime container.

#### Scenario: Last offer leaks a private value through JSON escaping

- **WHEN** the final entry includes a private configured value in decoded nested
  keys/strings, including Unicode or escaped controls
- **THEN** the file produces zero local intent and zero registry POSTs
- **AND** no diagnostic repeats that private value or contaminated ID
