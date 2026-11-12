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

A terms policy MUST only be able to decline: a buyer policy returns refusals for an offered option, at selection and again for the accepted Agreement's option at payment approval; a seller policy returns refusals and diagnostics for a derived option before publication, and the default penalty periods. Term validation, dispute-authority acceptance, mechanism compatibility and servicing declarations, the accepted Agreement matching the selected option, exact mandate re-derivation, and receipt, signature and pin verification MUST run whatever the policy returns. A seller policy's refusal withholds the option with a `seller_terms_policy_refusal` diagnostic.

#### Scenario: A permissive buyer meets an unaccepted authority

- **WHEN** the buyer's policy refuses nothing and an option names a dispute authority the buyer has not accepted
- **THEN** the option is refused for its authority

#### Scenario: A seller policy withholds an option

- **WHEN** a storefront's policy returns a refusal for one derived option of a listing
- **THEN** that option is not published and a `seller_terms_policy_refusal` diagnostic names it
- **AND** the listing's other options are published
