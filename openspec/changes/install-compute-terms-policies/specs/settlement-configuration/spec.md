## ADDED Requirements

### Requirement: A terms policy is installed and selected by name

A compute buyer and a compute storefront MUST each resolve one terms policy by name: the buyer from the `market.buyer_terms_policies` entry-point group, the storefront from `market.seller_terms_policies`. The root `terms_policy` configuration key selects it, as a name or as a table whose `name` selects and whose other keys are passed to the policy as its settings; absent, the name is `default`. Only the selected policy is loaded. A name no installed distribution provides, a name two distributions provide, an export that is not a policy of the role, and a policy that fails to load or rejects its settings MUST each refuse the command or startup, naming the policy; none falls back to `default`.

#### Scenario: A third-party buyer policy is selected

- **WHEN** an installed distribution registers `cautious` in `market.buyer_terms_policies` and the buyer's configuration states `terms_policy = "cautious"`
- **THEN** the buyer's option selection and payment approval ask that policy

#### Scenario: The selected policy is not installed

- **WHEN** configuration names a terms policy no installed distribution provides
- **THEN** the command or startup fails naming it and the installed policies
- **AND** no option is selected or published under another policy

### Requirement: The packaged terms policies are today's decisions

The settlement runtime MUST ship the buyer policies `default` and `permissive` and the seller policy `default`. Buyer `default` refuses, for a mechanism with a lifecycle adapter, an option with no delivery deadline, an on-demand option with no positive premature-stop penalty, and a payee stop or term end that does not return the final partial period. Buyer `permissive` refuses nothing. Seller `default` gives an on-demand recurring preset whose clause names no penalty a penalty of 24 periods, withholds no derived option, and reports the buyer `default` refusals of each as diagnostics. `--allow-unprotected-terms` MUST select `permissive` for that run and MUST be refused when configuration selects any other non-default policy.

#### Scenario: No configuration

- **WHEN** neither `terms_policy` nor the flag is given
- **THEN** the buyer refuses an Arkhai payments compute option with no delivery deadline, naming the default buyer's refusal

#### Scenario: The flag with an installed policy

- **WHEN** configuration selects a third-party buyer policy and the command passes `--allow-unprotected-terms`
- **THEN** the command is refused before any option is selected

### Requirement: A terms policy declines and waives nothing else

A terms policy MUST only be able to decline or order: a buyer policy returns refusals for an offered option, at selection and again for the accepted Agreement's option at payment approval; a seller policy returns refusals and diagnostics for a derived option before publication, and the default penalty periods. A policy MAY implement any of its role's methods, and the packaged `default` answers for the rest. Term validation, dispute-authority acceptance, mechanism compatibility and servicing declarations, the accepted Agreement matching the selected option, exact mandate re-derivation, and receipt, signature and pin verification MUST run whatever the policy returns. A seller policy's refusal withholds the option with a `seller_terms_policy_refusal` diagnostic.

#### Scenario: A permissive buyer meets an unaccepted authority

- **WHEN** the buyer's policy refuses nothing and an option names a dispute authority the buyer has not accepted
- **THEN** the option is refused for its authority

#### Scenario: A seller policy withholds an option

- **WHEN** a storefront's policy returns a refusal for one derived option of a listing
- **THEN** that option is not published and a `seller_terms_policy_refusal` diagnostic names it
- **AND** the listing's other options are published

### Requirement: A seller's terms policy admits each selection last

When a buyer selects an advertised option, a compute storefront MUST ask its terms policy before deciding the round, giving it the listing's own copy of the selected option with its decoded terms, the authenticated buyer's identity, the listing, and the time. The policy MUST be asked only about a selection every other check of the round has let through, MUST NOT be able to alter the option, and its admission MUST NOT skip any later check. A refusal MUST reach the buyer on the existing refusal path with the reason `seller_terms_policy_refusal:` followed by the policy's reasons: a 409 `offer_unfulfillable` at an opening, a `reject` at a continuation. A policy that fails MUST refuse without sending its failure to the buyer. The packaged `default` admits every selection.

#### Scenario: A seller refuses one buyer

- **WHEN** a storefront's policy returns a reason for a selection by one buyer identity
- **THEN** that buyer's opening is answered 409 `offer_unfulfillable` with reason `seller_terms_policy_refusal:` and the policy's reason
- **AND** another buyer's selection of the same option is accepted

#### Scenario: A selection another check refuses

- **WHEN** a buyer selects an option the listing does not offer
- **THEN** the opening is refused for that and the policy is not asked

### Requirement: A buyer's terms policy may order a listing's acceptable options

A compute buyer MUST hand each listing's options that survive its clauses, compatibility and refusals to its terms policy's preference, in the order mechanism priority, dispute-authority preference and option identity give, and MUST select the first option of the returned order. An option the preference leaves out MUST keep its place after the returned ones; a preference MUST NOT be able to refuse or introduce an option. The packaged policies MUST return the order they are given. Ordering across listings is unchanged.

#### Scenario: A policy prefers another option

- **WHEN** a listing advertises two acceptable options and the buyer's policy returns the second first
- **THEN** the buyer selects the second option

#### Scenario: No preference installed

- **WHEN** the buyer's policy is `default`
- **THEN** the buyer selects the option it selected before preferences existed

### Requirement: A buyer is told when its terms policy refused everything

When a compute buyer finds nothing to select and its terms policy refused at least one option while none was admitted, the command MUST print each refused option with the policy's reasons at normal verbosity.

#### Scenario: The default policy refuses the only option

- **WHEN** `market buy` matches one listing whose only option has no delivery deadline, under the `default` policy
- **THEN** the command reports that the terms policy refused the option, naming the default buyer's refusal
