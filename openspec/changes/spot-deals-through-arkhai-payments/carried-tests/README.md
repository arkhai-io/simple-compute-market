# Carried storefront tests for recurring options

These tests drive recurring options through the served VM and bare-metal
storefronts. They cannot run in the storefront suites today. No installed payment
mechanism has a recurring encoder, term timing or billing projection, so each test
runs over a `recurring_world` module that puts fixtures at those composition
ports. `docs/development/TESTING.md`, "Integration Tests", allows a mock only at
the external I/O boundary, so a fixture at a composition port is a mock inside the
codebase. The owner chose to keep these tests out of the suites until the
functionality exists, so `negotiate-open-ended-compute-terms` moved them here.

This change installs the recurring mechanism. Once its code implements those ports,
it puts the cases back into the storefront suites they came from. It replaces each
world's fixtures with the installed mechanism's helper, term timing and billing
projection, and keeps only the pieces a deployment supplies: the servicing
declaration, and a pool's delivery deadline where a test still needs one. Each
file here names its original module. That module's helpers are repeated here as
they stood.

Each door also keeps a test at the lowest level that proves it without a fixture
port. Those tests stay where they are; they are listed beside each case below.

## `vms/` and `bare_metal/`

Each directory holds its storefront's `recurring_world.py` as it was and the cases
that used it. The VM world stands fixtures at the recurring encoder
(`rate_preset_helpers`), term timing (`rate_term_projections`) and billing
projection (`project_billing`), and a placeholder for the payments seller stage at
acceptance. The bare-metal world stands fixtures at the encoder and term timing.
Both inject the servicing declaration, the pool's delivery deadline and the penalty
multiple.

| Case | Storefronts | What it proves | Lowest-level test that remains |
|---|---|---|---|
| `test_one_listing_offers_reserved_on_demand_and_spot_on_its_capacity_identity` | VM, bare metal (`test_publication_loop.py`, `test_http_publication_rates.py`) | Declaring rate servicing adds on-demand and spot options to the listing a pool already publishes. Listing, shape and bounds stay the same; each option has its own ID and derives its class, never storing it. | `kit/settlement-runtime/tests/unit/test_rate_publication.py` (`test_a_declared_preset_is_encoded_with_the_selected_declaration`, `test_a_recurring_clause_is_derived_through_its_helper_and_never_the_registry`) |
| `test_publication_omits_recurring_options_whose_treatments_are_undeclared` | VM, bare metal | A narrower declaration omits each recurring option, with its `rate_servicing_undeclared` diagnostic, and keeps the listing's other options. | `test_rate_publication.py` (`test_an_undeclared_treatment_or_setup_omits_the_recurring_candidate`, `test_a_built_rate_option_the_servicing_declaration_withholds_is_omitted`); `test_rate_servicing.py` |
| `test_an_on_demand_option_stating_no_penalty_publishes_the_configured_multiple` | VM, bare metal | On-demand with no stated penalty publishes the configured multiple of its period price; spot publishes none. | `test_rate_publication.py` (`test_on_demand_with_no_stated_penalty_takes_the_default_multiple_of_its_period_price`, `test_a_configured_multiple_replaces_the_default`, `test_spot_carries_no_default_penalty`) |
| `test_a_clause_s_deadline_publishes_where_the_pool_supplies_none` | VM, bare metal | With no pool deadline, once and recurring payment options publish their clause's deadline, and each one lacking it is reported as a default buyer's refusal. | The once half stays in the storefront suites as `test_a_once_payment_option_publishes_its_clause_s_deadline_where_the_pool_supplies_none`. The restored case replaces it. Recurring half: `test_rate_publication.py` (`test_a_recurring_option_publishes_the_pool_s_deadline_else_its_clause_s`, `test_a_recurring_option_with_neither_deadline_publishes_with_its_diagnostic`) |
| `test_a_cached_recurring_selection_whose_treatment_is_withdrawn_is_refused` | VM, bare metal (`test_publication_loop.py`, `test_http_negotiation.py`) | A recurring option selected after its treatment's declaration is withdrawn is answered with the signed 409 asking for a refetch, and no negotiation is written. | Each storefront's `test_selected_rate_servicing.py` (VM `tests/unit/`, bare metal `tests/`). It drives the real negotiation runtime over a listing record seeded with a rate option, and shows the refusal and that nothing is kept. Only publishing the option first and the HTTP answer need the carried case. The declaration's check alone: `test_rate_servicing.py` |
| `test_an_omitted_horizon_is_accepted_at_the_default_bound_the_buyer_checks` | VM (`test_buyer_selection_negotiation.py`) | The served storefront resolves an omitted horizon to the default bound and signs it, and the buyer's accepted-horizon check admits it. | `kit/settlement-runtime/tests/unit/test_horizon.py` (`test_an_omitted_recurring_horizon_binds_the_earliest_bound_at_a_whole_second_start`, `test_the_buyer_accepts_the_default_bound_for_an_omitted_horizon`) |
| `test_a_buyer_that_named_no_duration_verifies_the_accepted_pricing` | VM | A shape-priced recurring acceptance whose buyer named no duration passes the buyer's pricing verification. | `domains/vms/buyer/tests/test_per_period_acceptance.py` (`test_accepted_per_period_money_matches_one_signed_period_quote`, whose Agreement's provision terms name no duration) |
| `test_a_horizon_leaving_no_runway_is_refused_naming_the_minimum_that_passes` | VM, bare metal | A horizon one second short of approval window, deadline and one period is refused before anything is written, and the refusal names that minimum. VM also shows the minimum is accepted. | `test_horizon.py` (`test_the_horizon_leaves_no_runway`) |
