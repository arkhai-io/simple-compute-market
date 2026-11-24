# Explicit contact delivery

## Why

A canonical native seller can accept an introduction but lacks the signed review,
finalization, outcome, cancellation and delivery-status operations needed for a
buyer to authorize two-sided contact delivery. Its native unbacked publication
already owns the stable listing identities and separates nonbinding asking rates
from settlement prices.

## Scope

Add an opt-in delivery policy over the existing contact mechanism, signed request
and response transport, SQLite introduction store, settlement runtime, delivery
kit, and storefront lifecycle controller. Preserve ordinary introduction starts,
retention and redaction. Keep native publication and price representation intact.

No payments, provisioning, new listing namespace, implicit recipient consent,
translation between settlement-option generations or delivery to counterparty
controlled destinations is introduced.

## Status

Source milestone for review. Installed-wheel, lock, package-version, complete
repository and hosted qualification remain required before integration. No
runtime configuration or deployment is part of this milestone.
