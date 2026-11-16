---
tags: [repository, configuration]
---

# Contact-exchange configuration

How a storefront composing `contact-exchange.v1` is given its seller's contacts and
how long it keeps revealed ones, as this repository's instance of
[`configuration.md`](../../../docs/guidance/engineering/configuration.md). Where a
revealed introduction is delivered is
[`introduction-delivery`'s](../introduction-delivery/configuration.md).

## Contact-exchange contacts

A storefront composing `contact-exchange.v1` (bare metal and VM) configures it in
the peer `[Settlement.contact]` table: its `profiles`, the public terms an
introduction option advertises, and the seller's contact in exactly one of two
forms.

```toml
# One storefront, one origin site: the single form.
[Settlement.contact]
enabled = true
contact_payload = { email = "sales@bob.example" }

# One storefront, several seller sites: a contact per origin.
[Settlement.contact.origins.dc-west]
contact_payload = { email = "ops@west-seller.example" }

[Settlement.contact.origins.dc-east]
contact_payload = { email = "sales@east-seller.example" }
```

An origin is the site a listing's durable binding records; the storefront reads
its configured sites (`[capacity.sites]`, on VM and bare metal alike) as the
known origins. The storefront refuses to start when both forms
are set, when the single form is set while more than one site is configured, or
when an `origins` key names no configured site. A site without an entry is legal:
its listings publish no introduction option, and a reveal for an accepted deal whose
origin has lost its entry is refused with `seller_contact_unavailable` before
anything is stored. The contact is never substituted from another origin.

Contacts are ordinary configuration, marked `never_published` rather than secret:
they may sit in the public configuration (the Helm ConfigMap included) and still
never appear in a listing, an option, readiness, or an obligation. Readiness stays
storefront-wide: the mechanism is unready only with no profiles or no contact in
either form.

## Contact-exchange retention

Two seller-only settings in `[Settlement.contact]` bound how long revealed contacts
are kept:

| Setting | Default | Meaning |
|---|---|---|
| `retention_seconds` | `2592000` (30 days) | How long both contact payloads of a revealed introduction are kept, counted from the reveal. A positive integer, or `"indefinite"` for no deletion. Zero and negative values are refused, so a typo cannot delete introductions moments after reveal. |
| `retention_sweep_interval_seconds` | `3600` | How often the retention sweep runs. Positive. |

The window is current policy, not a term of any deal: a storefront restarted with a
shorter window deletes, on its next sweep, every introduction already past the new
window, including those revealed under the longer one. The window is published to
buyers; deletion and disclosure behaviour are specified in
[contact-exchange settlement](spec.md).
