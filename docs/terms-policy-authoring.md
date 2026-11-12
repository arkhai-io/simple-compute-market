# Writing a terms policy

A compute buyer and a compute storefront each run one **terms policy**: the party's own rule for which settlement options it will not take, or will not publish. The market ships the policies that reproduce its defaults. To decide differently, write a Python package, install it beside the buyer CLI or the storefront, and name it in configuration.

This covers the VM and bare-metal domains. API credits has no lifecycle rights to weigh and consults no terms policy.

## What a policy decides, and what it cannot

A policy declines, and a buyer's may order what it accepts. A buyer policy returns the reasons it refuses an option and the order it prefers the rest in; a seller policy returns the reasons it withholds an option from publication or refuses a buyer's selection of one, and reports. Neither has an answer that accepts something the rest of the system would refuse, and neither can change an option. These run whatever a policy returns:

- decoding and validation of the option's lifecycle terms against what the installed mechanism and the dispute authority support;
- acceptance of the option's dispute authority, configured with `[[Dispute]]` and `use_registry_dispute_authorities`;
- mechanism compatibility and what the composition can service;
- the accepted Agreement matching the selected option, re-derivation of the payment mandate from it, and verification of receipts, signatures and registry pins.

A buyer policy that raises while refusing refuses the option, and one that raises while ordering fails the command. A seller policy that raises fails publication, and one that raises at selection refuses the selection.

A policy implements any of its role's methods. The packaged `default` answers for the ones it leaves out, so a seller policy that only refuses certain buyers is one method.

## The buyer protocol

```python
from market_settlement_runtime.terms_policy import (
    BuyerTermsOffer, BuyerTermsPolicy, BuyerTermsPreference,
)

class BuyerTermsPolicy(Protocol):
    def refusals(self, offer: BuyerTermsOffer) -> Sequence[str]: ...

class BuyerTermsPreference(Protocol):
    def prefer(self, offers: Sequence[BuyerTermsOffer]) -> Sequence[BuyerTermsOffer]: ...
```

`BuyerTermsOffer` carries:

| Field | Meaning |
|---|---|
| `option` | the `SettlementOption` as advertised or accepted |
| `lifecycle` | its decoded `LifecycleTerms`, or `None` when it states none |
| `has_adapter` | whether the option's mechanism has a lifecycle adapter; without one the option makes no delivery promise |
| `registry_url` | the registry the listing came from, empty when unknown |
| `listing` | the listing advertising the option, empty at payment approval |

From `refusals`, return an empty sequence to accept. It is asked when options are selected, and again about the accepted Agreement's option before a recurring payment is approved, where `registry_url` and `listing` are empty. When it refuses every option it is offered and nothing is selectable, the command prints its reasons.

`prefer` receives one listing's options that passed the buyer's settlement clauses, its refusals and every other check, in the default order: mechanism priority from `[Settlement].priority`, then dispute-authority preference, then option identity. Return them most preferred first; the buyer selects the first. An offer left out is not refused and follows the returned ones. Each offer's price is `offer.option.price` and its terms `offer.lifecycle`.

A preference orders the options of one listing, not listings. Which listing is tried first is the aggregation policy's, and across listings the highest-priority mechanism any of them selected still wins, so a preference for an option of a lower-priority mechanism can lose its listing to another. The bare-metal buyer buys one option named by `--option-id` and consults no preference.

## The seller protocol

```python
from market_settlement_runtime.terms_policy import (
    SellerTermsAdmission, SellerTermsOffer, SellerTermsPolicy, SellerTermsReview,
    SellerTermsSelection,
)

class SellerTermsPolicy(Protocol):
    def default_penalty_periods(self) -> int: ...
    def review(self, offer: SellerTermsOffer) -> SellerTermsReview: ...

class SellerTermsAdmission(Protocol):
    def admit(self, selection: SellerTermsSelection) -> Sequence[str]: ...
```

`default_penalty_periods` is the premature-stop penalty of an on-demand recurring preset whose publication clause names none, in periods of the quoted amount. It is read once at startup and must be a non-negative integer.

`review` sees each option after the storefront has derived and validated it and before it is published. `SellerTermsReview.refusals` withhold the option, each reported as a `seller_terms_policy_refusal` publication diagnostic; `diagnostics` are `(code, detail)` pairs reported without withholding. A policy does not rewrite an option: what a listing offers is stated in its publication clauses.

`admit` is asked when a buyer selects an advertised option, in every round the storefront would otherwise counter or accept. `SellerTermsSelection` carries:

| Field | Meaning |
|---|---|
| `option` | the listing's own copy of the selected `SettlementOption`; `None` when the buyer opened with an escrow proposal, which selects an accepted escrow contract |
| `lifecycle` | its decoded `LifecycleTerms`, or `None` |
| `buyer` | the buyer's marketplace identity, as the storefront authenticated the request |
| `listing` | the listing record |
| `at` | the time, in UTC |

Return an empty sequence to admit. It is asked last: about a selection the listing offers, that the storefront can service, and that the round's other guards let through, and everything after the round's decision still runs. Reasons refuse the selection, and **are sent to the buyer**: an opening is answered 409 `offer_unfulfillable` and a later round `reject`, each with the reason `seller_terms_policy_refusal: <your reasons>`. Write nothing in a reason you would not tell the buyer.

The policy does not set the price; price rounds belong to the negotiation policy chain.

## Packaging

An entry point names a **factory**: a callable taking the policy's settings as a mapping and returning the policy.

```toml
[project]
name = "my-terms-policies"
version = "0.1.0"
dependencies = ["arkhai-kit-settlement-runtime"]

[project.entry-points."market.buyer_terms_policies"]
example = "terms_policies:example_buyer"

[project.entry-points."market.seller_terms_policies"]
example = "terms_policies:example_seller"
```

[`kit/settlement-runtime/examples/terms_policies.py`](../kit/settlement-runtime/examples/terms_policies.py) is that module. Its buyer takes an option with no delivery deadline but holds the on-demand penalty to a floor, which neither packaged policy does, and can prefer spot options; its seller publishes only options that promise a deadline and refuses the buyers its settings list. The kit's unit tests load both through these entry-point values.

Install the package into the environment the buyer CLI or the storefront runs in.

## Selecting a policy

At the root of the buyer's configuration file or the storefront's, before any table header for the short form:

```toml
terms_policy = "example"
```

or, to pass settings, a table whose `name` selects the policy and whose other keys reach its factory, with their names lower-cased:

```toml
[terms_policy]
name = "example"
minimum_penalty = 5000
```

The bare-metal buyer reads the key at the root of the file `BARE_METAL_BUYER_CONFIG` selects, beside `[bare_metal]`.

Absent, the policy is `default`. Only the selected policy is imported. A name nothing installed provides, a name two distributions provide, a factory that fails or rejects its settings, and a result that is not a policy of the role each stop the command or the storefront's startup with the policy's name; nothing falls back to `default`.

## The packaged policies

| Role | Name | Decision |
|---|---|---|
| buyer | `default` | For a mechanism with a lifecycle adapter, refuses an option with no delivery deadline, an on-demand option with no positive premature-stop penalty, and a payee stop or term end that does not return the final partial period |
| buyer | `permissive` | Refuses nothing |
| buyer | both | Keep a listing's options in the default order |
| seller | `default` | 24 penalty periods; withholds nothing; reports each buyer `default` refusal of an option as a `default_buyer_refusal` diagnostic; admits every selection |

`--allow-unprotected-terms` on `market buy`, `market negotiate` and `market bare-metal buy` is shorthand for selecting `permissive` for that run. It is refused when configuration selects any policy other than `default` or `permissive`: the flag does not replace a policy you installed.
