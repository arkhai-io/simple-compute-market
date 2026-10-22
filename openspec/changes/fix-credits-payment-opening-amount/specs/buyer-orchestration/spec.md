## ADDED Requirements

### Requirement: Negotiation opens from the selected advertised option

When a domain's buyer hook selects a settlement option, buyer orchestration MUST resolve that selection to the option the listing advertises before negotiating, and MUST give that option's rate and acceptance contract to the negotiation policy and to settlement revalidation. A selection that resolves to no advertised option MUST end that candidate's attempt before revalidation and without contacting its seller.

#### Scenario: A listing advertises differently priced options

- **WHEN** a buyer selects a listing's payment option and the listing also advertises an escrow option at another rate
- **THEN** negotiation opens with the payment option's mechanism and option ID, at an amount derived from the payment option's rate

#### Scenario: A selection names nothing the listing advertises

- **WHEN** a hook's selection names a mechanism or option ID absent from the listing's advertised options
- **THEN** the candidate's attempt exits as `unadvertised_settlement_selection`, and no negotiation is opened with its seller

### Requirement: The match cap counts candidates the buyer can settle with

A buy command's limit on the matches it tries MUST count only candidates with a usable settlement choice: a candidate with none MUST NOT take one of the tries.

#### Scenario: Some discovered listings cannot be settled with

- **WHEN** a buyer limits a purchase to N matches and some earlier discovered listings advertise no option the buyer can use
- **THEN** the buyer negotiates with up to N listings that do, and no unusable listing takes one of the N tries

### Requirement: Credit purchases stop selecting at the match cap

`market credits buy` MUST choose settlement for discovered listings in discovery order and stop once its match limit's worth of usable candidates is found, so no buyer is prompted, and no settlement prerequisite is read, for a listing past the limit.

#### Scenario: More usable listings are discovered than the limit

- **WHEN** a credit buyer limits a purchase to N matches and more than N discovered listings have a usable settlement choice
- **THEN** selection evaluates no listing after the Nth usable one
