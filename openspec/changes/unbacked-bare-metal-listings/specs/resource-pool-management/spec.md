## ADDED Requirements

### Requirement: The backing delegate decides delivery terms

A listing's delivery terms are the fields that commit the marketplace to delivering
something, such as a host identity or access methods: a capacity-backed listing stands
behind them and nothing stands behind them on an unbacked one. A domain MUST name its
own delivery terms, and whether they are carried MUST be the backing delegate's
decision through two operations:

- carrying delivery terms, where a publication view or payload is built: the
  capacity-backed delegate passes the terms through and the unbacked delegate carries
  none of them;
- constraining delivery terms, where a listing model validates: the capacity-backed
  delegate requires every term present and non-empty and the unbacked delegate
  requires every term absent.

No delivery term MAY be given a default value, because a default would publish a
commitment nothing stands behind.

#### Scenario: An unbacked view is built

- **WHEN** a domain builds a publication view for a resource in an unbacked pool and
  passes its delivery terms to the pool's backing delegate
- **THEN** the view carries none of those terms, whatever the declaration names

#### Scenario: A backed listing is validated without its terms

- **WHEN** a capacity-backed listing omits one of its domain's delivery terms, or
  carries it empty
- **THEN** its validation refuses it

#### Scenario: An unbacked listing is validated with a term

- **WHEN** an unbacked listing carries one of its domain's delivery terms
- **THEN** its validation refuses it
