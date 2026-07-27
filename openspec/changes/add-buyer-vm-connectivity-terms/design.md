## Context

Today, VM connectivity for hosts without a public IP is entirely
storefront-operator configuration: `frp_server_addr`, `frp_domain`, and
`frp_dashboard_password` in `market_storefront/settings.toml`, applied
uniformly to every fulfillment regardless of buyer. `AnsiblePreparedJobParameters`
already carries these three fields through to the Ansible playbook — the gap
is entirely upstream of that: nothing between the buyer and the fulfillment
request currently has a place for buyer-supplied values, and nothing
validates them before a deal is accepted.

`openspec/specs/negotiation-protocol/spec.md`'s "Versioned domain provision
envelope" requirement already establishes the mechanism this needs: buyers
transmit a domain-owned payload when opening negotiation ("VM buyer opens
negotiation" scenario), and — per `ARCHITECTURE.md`'s "Discovery and
negotiation" flow — "Seller policy evaluates listing data, captured side
inputs, and the message history" before terms are agreed. Connectivity terms
are a natural fit for that existing payload and that existing validation
point; this is not a new protocol mechanism, it's a new field validated by
the mechanism that already exists.

## Goals / Non-Goals

**Goals:**
- Let a buyer specify their own FRP relay (server, domain, dashboard
  credential) as part of a deal's negotiated terms.
- Validate buyer-supplied connectivity terms before a deal is accepted, not
  after — a bad configuration should be a negotiation-time rejection, not a
  fulfillment-time failure discovered after the buyer has already committed.
- Preserve today's storefront-configured default unchanged for buyers who
  supply no connectivity terms of their own.

**Non-Goals:**
- Redesigning the connectivity mechanism itself (still FRP).
- Any change to `pools-7-storefront-fulfillment-cutover`'s scope; that
  change only needs to leave a `connectivity` field shape this one can
  populate from a second source.

## Open Questions

### What does "valid" mean for a buyer-supplied FRP server, and who checks it?

A syntactic check (well-formed address/domain) is cheap and clearly seller
policy's job. Whether to also *reach* the buyer's claimed FRP server during
negotiation (an active connectivity check, not just shape validation) is a
real design question: it catches a broken buyer configuration earlier, but
it also means the storefront process makes an outbound network call to a
buyer-controlled address as part of ordinary negotiation traffic — see the
security consideration immediately below, which applies to this question
directly.

### Security: buyer-specified outbound relay target is an SSRF-adjacent surface

This is the one genuinely new risk this change introduces and needs explicit
resolution before implementation, not just before merge. If a buyer can name
an arbitrary `frp_server_addr`, two different components may end up
initiating outbound connections to a buyer-controlled network location:

- The **provisioned VM** connecting out to the buyer's FRP server — this is
  probably fine and is the whole point (the buyer's own VM reaching the
  buyer's own relay), but it does mean seller-operated compute infrastructure
  is running a process configured to phone home to an address the buyer
  chose, and that configuration should be treated as untrusted input by
  whatever prepares it (already true in principle — `_validate_extra_vars`
  exists for a related reason — but this is a new instance of it).
- The **storefront process itself**, if the "reach the buyer's FRP server
  during negotiation" active-check option above is chosen — this is the more
  serious case. A storefront making outbound requests to an address supplied
  in an unauthenticated or lightly-authenticated buyer message is a
  textbook SSRF shape (internal network probing, cloud metadata endpoint
  access, etc.) unless deliberately constrained (e.g. an allowlist of
  permitted address shapes, egress-restricted network path for this specific
  check, or simply not doing an active check and relying on syntactic
  validation plus the VM's own connection attempt failing loudly and safely
  if the address is bad).

Resolve this before implementation begins, not as a follow-up hardening
pass. If active validation is wanted, its network path needs its own
explicit design, not an incidental `httpx.get()` from wherever negotiation
policy happens to run.

### Where does the negotiated value live relative to the storefront-configured default?

Options: negotiated terms always override the storefront default when
present (buyer's choice wins); the storefront can mark listings as
"seller-managed-connectivity-only," refusing buyer-supplied terms
per-listing; or some other precedence rule. Not resolved here.

### Does this belong on `ComputeResource`/settlement encoding directly, or in a separate side-channel?

`encode_compute_lease` already encodes `compute_resource`/`token_resource`
terms into `order_bytes`. Whether connectivity terms belong in that same
encoded structure (durable, on-chain-adjacent, replayable) or a separate,
storefront-side-only negotiated-terms record (not encoded into the
settlement claim itself) is an open modeling question with different
implications for buyer-visible commitment strength.

## Risks / Trade-offs

- **[Buyer-supplied credential handling]** — `frp_dashboard_password` is a
  credential. If buyer-specified, it needs the same handling discipline as
  any other buyer-supplied secret passed through to a domain adapter (not
  logged, not persisted beyond what's operationally necessary). Not
  specific to this change's mechanism, but worth restating given a new
  credential-shaped field is being added to a negotiated-terms payload for
  the first time in this domain.
- **[Precedent for future per-deal domain-specific terms]** — this is the
  first VM-domain field added to the negotiation provision envelope
  specifically for buyer infrastructure preference rather than resource
  sizing. If it goes well, expect requests for similar buyer-specified
  fields elsewhere; worth watching whether the envelope's validation
  pattern scales past one field.
