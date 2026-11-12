# Writing a terms policy

A compute buyer and a compute storefront each run one **terms policy**: the party's own rule for which settlement options it will not take, or will not publish. The market ships the policies that reproduce its defaults. To decide differently, write a Python package, install it beside the buyer CLI or the storefront, and name it in configuration.

This covers the VM and bare-metal domains. API credits has no lifecycle rights to weigh and consults no terms policy.

## What a policy decides, and what it cannot

A policy declines. A buyer policy returns the reasons it refuses an option; a seller policy returns the reasons it withholds one, and reports. Neither has an answer that accepts something the rest of the system would refuse. These run whatever a policy returns:

- decoding and validation of the option's lifecycle terms against what the installed mechanism and the dispute authority support;
- acceptance of the option's dispute authority, configured with `[[Dispute]]` and `use_registry_dispute_authorities`;
- mechanism compatibility and what the composition can service;
- the accepted Agreement matching the selected option, re-derivation of the payment mandate from it, and verification of receipts, signatures and registry pins.

A buyer policy that raises refuses the option. A seller policy that raises fails publication.

## The buyer protocol

```python
from market_settlement_runtime.terms_policy import BuyerTermsOffer, BuyerTermsPolicy

class BuyerTermsPolicy(Protocol):
    def refusals(self, offer: BuyerTermsOffer) -> Sequence[str]: ...
```

`BuyerTermsOffer` carries:

| Field | Meaning |
|---|---|
| `option` | the `SettlementOption` as advertised or accepted |
| `lifecycle` | its decoded `LifecycleTerms`, or `None` when it states none |
| `has_adapter` | whether the option's mechanism has a lifecycle adapter; without one the option makes no delivery promise |
| `registry_url` | the registry the listing came from, empty when unknown |

Return an empty sequence to accept. The policy is asked when options are selected, and again about the accepted Agreement's option before a recurring payment is approved, where `registry_url` is empty.

## The seller protocol

```python
from market_settlement_runtime.terms_policy import (
    SellerTermsOffer, SellerTermsPolicy, SellerTermsReview,
)

class SellerTermsPolicy(Protocol):
    def default_penalty_periods(self) -> int: ...
    def review(self, offer: SellerTermsOffer) -> SellerTermsReview: ...
```

`default_penalty_periods` is the premature-stop penalty of an on-demand recurring preset whose publication clause names none, in periods of the quoted amount. It is read once at startup and must be a non-negative integer.

`review` sees each option after the storefront has derived and validated it and before it is published. `SellerTermsReview.refusals` withhold the option, each reported as a `seller_terms_policy_refusal` publication diagnostic; `diagnostics` are `(code, detail)` pairs reported without withholding. A policy does not rewrite an option: what a listing offers is stated in its publication clauses.

A seller makes no terms decision during negotiation. A buyer selects an advertised option by its identity and cannot counter its lifecycle terms; price rounds belong to the negotiation policy chain.

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

[`kit/settlement-runtime/examples/terms_policies.py`](../kit/settlement-runtime/examples/terms_policies.py) is that module. Its buyer takes an option with no delivery deadline but holds the on-demand penalty to a floor, which neither packaged policy does; its seller publishes only options that promise a deadline. The kit's unit tests load both through these entry-point values.

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
| seller | `default` | 24 penalty periods; withholds nothing; reports each buyer `default` refusal of an option as a `default_buyer_refusal` diagnostic |

`--allow-unprotected-terms` on `market buy`, `market negotiate` and `market bare-metal buy` is shorthand for selecting `permissive` for that run. It is refused when configuration selects any policy other than `default` or `permissive`: the flag does not replace a policy you installed.
