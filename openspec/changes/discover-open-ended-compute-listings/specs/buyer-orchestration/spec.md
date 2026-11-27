## ADDED Requirements

### Requirement: A compute option's class is read from its entitlements

Both compute buyers MUST read a compute option's class from its early-termination entitlements alone: reserved where neither party is entitled, on-demand where the payer alone is, spot where the payer and the payee are, committed spot where the payee alone is. The class MUST NOT be a stored listing or Agreement field and MUST NOT depend on how the option is billed. The class a buyer displays and the class its shorthand selects MUST be the same reading.

#### Scenario: A lease neither party may end early

- **WHEN** a buyer views an option that states no early-termination entitlement
- **THEN** the display says reserved, whether the option is billed once or by the period

#### Scenario: A lease only the seller may end

- **WHEN** a buyer views an option that entitles the payee and not the payer
- **THEN** the display says committed spot, not spot

#### Scenario: The display and the shorthand agree

- **WHEN** a buyer selects by a class and views the option selected
- **THEN** the display names the class the buyer asked for

### Requirement: Compute buyers narrow discovery and purchase by class

Both compute buyers' discovery and purchase commands MUST accept a class shorthand naming reserved, on-demand, spot or committed spot. A class that matches no option MUST leave an empty result: it MUST NOT relax the class, enable a disabled mechanism or permit a substitution after acceptance.

#### Scenario: A listing offers several classes

- **WHEN** a buyer asks for spot on a listing with reserved, on-demand and spot options
- **THEN** only the spot option's identity reaches negotiation

#### Scenario: Asking for spot commits to no term

- **WHEN** a buyer asks for spot on a listing whose only payee-entitled option does not entitle the payer
- **THEN** nothing is selected

#### Scenario: A class is explained without buying

- **WHEN** a buyer names a class in explanation mode
- **THEN** the output shows the predicates the class expanded to and the options that survived them
- **AND** no negotiation, settlement or provider mutation occurs

### Requirement: The buyers share one settlement selection

The VM, bare-metal and API-credit buyers MUST choose a listing's settlement option through one shared selection. The selection MUST carry its choice beside the listing as advertised and MUST NOT narrow or rewrite the options the listing advertises; pricing, negotiation and revalidation MUST read the chosen option from that choice.

#### Scenario: A listing advertises two options

- **WHEN** a buyer's selection chooses one of two options a listing advertises
- **THEN** the listing the buyer holds still carries both options, and negotiation opens from the chosen one

#### Scenario: A bare-metal buyer selects by clause

- **WHEN** a bare-metal buyer names a settlement clause that one hosted option of a listing satisfies
- **THEN** the shared selection chooses that option as it would for a VM buyer, and the purchase proceeds with it
