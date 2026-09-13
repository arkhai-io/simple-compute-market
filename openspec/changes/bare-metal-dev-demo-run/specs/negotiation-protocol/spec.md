## ADDED Requirements

### Requirement: Physical terms of an exact selection come from the seller's own trusted state

When an exactly selected option provisions a physical resource, the domain MUST
derive every physical term — machine, host, site, pool, resource and access
method — from the seller's trusted listing and its listing binding, and MUST NOT
accept one from the request. An option that advertises the physical facts inline
MUST additionally be held to them and to the binding they were published from. An
option that advertises none MUST still be composed against that trusted state
rather than accepted as a non-provisioning agreement.

Where nothing in the option pins the obligation's expiry, the selection's expiry
MUST be refused once it has passed.

An accepted plan's physical service terms are compared whole by the counterparty
that reconstructs them, so the envelope a domain emits for an option carrying
advertised physical facts MUST remain exactly the envelope that reconstruction
builds.

#### Scenario: A selection carries no advertised physical facts

- **WHEN** a buyer exactly selects an option whose parameters describe only its
  settlement terms on a listing that leases a machine
- **THEN** the accepted terms and the physical service terms are composed from the
  trusted listing and binding, and the deal provisions that machine

#### Scenario: A request names a physical identity

- **WHEN** a negotiation request's provision payload carries a machine, host, site,
  pool or resource identity
- **THEN** the request is rejected and no negotiation, obligation or capacity
  record is written
