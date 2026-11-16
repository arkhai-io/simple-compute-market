---
tags: [repository, configuration]
---

# Site configuration in a storefront

How a storefront is given the sites whose capacity it publishes, and how it trusts
each, as this repository's instance of
[`configuration.md`](../../../docs/guidance/engineering/configuration.md).

## A site's authority URL is an origin

Each `[capacity.sites]` URL is parsed by the
WHATWG URL standard (pydantic's `AnyHttpUrl`) and must have an `http` or `https`
scheme and no credentials, path other than `/`, query, or fragment; an ASCII control
character anywhere in the value is refused before parsing, since the standard would
drop it rather than refuse it. The site's clients are given the normalized origin
(scheme and host lowercased, an international host as punycode, a default port
omitted, no trailing `/`). A refusal names the site's key and never echoes the URL.
The check is the storefront's at startup, not the chart's values schema; a host the
standard accepts but nothing resolves fails at the first poll.

## Each site is trusted through its service peer

Every configured site is bound to
exactly one `[Identity.service_peers.<peer>]` (`role = "service"`, `site_id`, and
`principals`). The storefront seeds the peer into its durable identity state when the
server starts, and the durable state then owns its principals: the site's responses
and callbacks are verified against the peer's active principals, and they rotate
through the storefront's identity routes with bounded overlap, reaching verification
as the rotation commits. Configuration must keep covering them: startup refuses
configuration that no longer names a seeded peer's durable primary and every
principal active in an overlap, so a restart after a rotation needs configuration
naming the replacement. The service-role read of system status is accepted from any
configured site's peer. There is no storefront-wide provisioning trust set; VM refuses
a configuration stating `[provisioning.identity]`. The bare-metal storefront's
administrators stay in configuration, so its identity routes refuse to rotate one.
