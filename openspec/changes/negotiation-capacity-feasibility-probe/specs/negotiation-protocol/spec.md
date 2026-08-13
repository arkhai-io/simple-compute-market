## ADDED Requirements

### Requirement: Authoritative capacity verification before agreement

A storefront MUST verify a requested capacity shape against the authoritative site
before agreeing terms for it. The verification MUST consume no capacity, create no
reservation, and leave no state that could exclude another buyer. A shape the site
cannot currently supply MUST be reported distinctly from a shape the seller declines to
sell, so a counterparty can tell whether to change the request or retry later. The
verification's result MUST be treated as a point-in-time answer carrying no guarantee
that the capacity remains available at reservation. Where the site cannot be reached,
the negotiation MUST take an explicit disposition rather than treating an indeterminate
result as either success or failure.

#### Scenario: Requested shape cannot currently be served

- **WHEN** a shape is requested that the site authority cannot currently supply
- **THEN** the negotiation reports it unservable before terms are agreed, distinctly
  from a seller declining to sell that shape

#### Scenario: Seller declines a shape it will not sell

- **WHEN** a shape is one the seller will not sell
- **THEN** it is reported as declined by the seller, and is distinguishable from the
  site being unable to supply it

#### Scenario: Verification consumes nothing

- **WHEN** a requested shape is verified during negotiation
- **THEN** no capacity is reserved or held, and a concurrent buyer's ability to reserve
  that capacity is unaffected

#### Scenario: Two negotiations verify the same scarce capacity

- **WHEN** two negotiations verify a shape that only one of them can ultimately reserve
- **THEN** both may be told it is currently servable, and the reservation remains the
  authoritative decision

#### Scenario: Site authority is unreachable

- **WHEN** the authoritative site cannot be reached during verification
- **THEN** the negotiation applies its explicit disposition for an indeterminate result
  rather than silently passing or silently failing
