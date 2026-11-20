---
tags: [repository, configuration]
---

# Introduction delivery configuration

How each side's operator configures where revealed introductions are delivered, as
this repository's instance of
[`configuration.md`](../../../docs/guidance/engineering/configuration.md). The
contacts an introduction carries are
[`contact-exchange-settlement`'s](../contact-exchange-settlement/configuration.md).

## Introduction delivery

`[Delivery]` sends each revealed introduction to destinations the side's own
operator configured; the seller's side carries the buyer's contact, the buyer's
side the seller's. `enabled` names sink instances; an instance's table names the
installed sink it uses with `sink`, and a table naming none uses the sink of its own
name, so `[Delivery.file]` keeps its meaning.

```toml
[Delivery]
enabled = ["west-hook", "east-mail", "audit"]

[Delivery.west-hook]
sink = "webhook"
sign = true                         # signed with the storefront's marketplace signer

[Delivery.east-mail]
sink = "smtp"
host = "mail.east-seller.example"
sender = "storefront@example.com"
recipients = ["sales@east-seller.example"]

[Delivery.audit]
sink = "file"
path = "/var/log/introductions.jsonl"

[Delivery.origins]                  # seller side only
dc-west = ["west-hook", "audit"]
dc-east = ["east-mail", "audit"]
```

A storefront with more than one origin must route: with sinks enabled and no
`[Delivery.origins]`, it refuses to start, since broadcasting every reveal to every
destination would hand one seller's buyers' contacts to another. Every routed name
must be enabled, every enabled instance routed, and every origin the table names
must be one of the storefront's sites; a site the table does not name receives no
seller-side delivery. A buyer may not route. With
`sign = true` a webhook request carries a v2 marketplace signature its receiver
verifies against the storefront principal. The installable `apprise` sink
(`arkhai-kit-delivery-apprise`, in both storefront images) reaches any service an
Apprise URL names. Credentials — a webhook's `url` and `headers`, an SMTP
`password`, Apprise `urls` — are secret settings: they belong in the secrets overlay,
and the Helm values schema refuses them in an agent's `config`.

Operators re-deliver a revealed introduction to its origin's instances with
`market-storefront settlement contact redeliver --obligation-ref …` on VM and the
bare-metal storefront's `redeliver-introduction` command. Delivery and re-delivery
are specified in [introduction delivery](spec.md).

The VM and bare-metal end-to-end lanes each run a Mailpit as the seller's mail sink.
Each lane's storefront configuration (`domains/vms/storefront/storefront.bob.lane.toml`,
`domains/bare_metal/storefront/storefront.dev.toml`) enables one SMTP instance,
`[Delivery.seller-mail]`, sending to the `mailpit` host on port 1025 and addressed
to the seller contact its `[Settlement.contact]` reveals; the bare-metal lane adds
the service in `compose.bare-metal-local.yml`, which its storefront waits on until
healthy. The introduction scenarios read the mail back through the lane's
`MAILPIT.API_URL` (`e2e-tests/config/config-docker.yml`). Every address in them is a
development value on a reserved domain.
