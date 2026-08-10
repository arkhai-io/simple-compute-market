"""The VM domain's declared negotiation policy sources.

The domain decides which of its own policies are worth loading. The torch
strategy is the interesting case: it is offered only when the chain being
composed names it, so a storefront that never negotiates with reinforcement
learning does not import torch to find that out.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from domains.vms.negotiation.policy_sources import (
    RL_POLICY_NAMES,
    VM_DEFAULT_SELLER_CHAIN,
    VM_SELLER_POLICIES,
    TorchStrategySource,
    vm_policy_sources,
)
from market_policy import (
    CatalogueSource,
    InlineSource,
    NegotiationPolicyRequest,
    PolicyRole,
    negotiation_catalogue_builder,
    scalar_escrow_policies,
)


def _request(*, role=PolicyRole.STOREFRONT, requested=VM_DEFAULT_SELLER_CHAIN):
    return NegotiationPolicyRequest(role=role, requested_policies=frozenset(requested))


def test_the_guards_are_always_offered_to_a_storefront() -> None:
    sources = vm_policy_sources(_request())

    assert len(sources) == 1
    assert isinstance(sources[0], InlineSource)
    assert set(sources[0].load()) == set(VM_SELLER_POLICIES)


def test_the_domain_offers_no_buyer_side_policies() -> None:
    assert vm_policy_sources(_request(role=PolicyRole.BUYER)) == ()


def test_every_source_satisfies_the_protocol() -> None:
    for source in vm_policy_sources(_request(requested=["rl"])):
        assert isinstance(source, CatalogueSource)


def test_the_torch_source_is_withheld_when_no_chain_asks_for_it() -> None:
    sources = vm_policy_sources(_request())

    assert not any(isinstance(s, TorchStrategySource) for s in sources)


@pytest.mark.parametrize("rl_name", sorted(RL_POLICY_NAMES))
def test_the_torch_source_is_offered_for_each_rl_alias(rl_name: str) -> None:
    sources = vm_policy_sources(_request(requested=["escrow_shape_guard", rl_name]))

    assert any(isinstance(s, TorchStrategySource) for s in sources)


def test_composing_the_default_surface_does_not_import_the_strategy_module() -> None:
    """Withholding the source must avoid the import, not merely the name.

    Asserts the property this design actually has. Torch is imported lazily
    inside the strategy's forward passes, so composing the RL source does not
    pull torch into the process either way; what composition avoids is the
    strategy module and its dependency graph.

    Run in a subprocess because an unrelated test in this process may already
    have imported the module, which would make an in-process check vacuous.
    """
    strategy = "domains.vms.negotiation.rl.torch_arkhai_strategy"
    program = (
        "import sys;"
        "from market_policy import (negotiation_catalogue_builder,"
        " scalar_escrow_policies, NegotiationPolicyRequest, PolicyRole);"
        "from domains.vms.negotiation.policy_sources import"
        " vm_policy_sources, VM_DEFAULT_SELLER_CHAIN, RL_POLICY_NAMES;"
        "import os;"
        "wanted = frozenset([os.environ['REQUESTED']]) if os.environ['REQUESTED']"
        " else frozenset(VM_DEFAULT_SELLER_CHAIN);"
        "r=NegotiationPolicyRequest(role=PolicyRole.STOREFRONT,"
        " requested_policies=wanted);"
        "b=negotiation_catalogue_builder().add_loader(scalar_escrow_policies());"
        "b.add_loaders(vm_policy_sources(r));"
        "c=b.build();"
        "assert c.names();"
        f"print({strategy!r} in sys.modules)"
    )

    # pytest's `pythonpath` setting applies to this process, not to a bare
    # subprocess, so the parent's resolved sys.path is handed over explicitly.
    base = dict(os.environ)
    base["PYTHONPATH"] = os.pathsep.join(
        [path for path in sys.path if path] + [base.get("PYTHONPATH", "")]
    ).strip(os.pathsep)

    def _imports_strategy(requested: str) -> bool:
        result = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            check=True,
            env={**base, "REQUESTED": requested},
        )
        return result.stdout.strip() == "True"

    # The control case matters: without it this test could pass because the
    # module is never importable in this environment for some other reason.
    assert _imports_strategy("rl") is True
    assert _imports_strategy("") is False


def test_an_rl_chain_fails_loudly_when_the_strategy_cannot_load(monkeypatch) -> None:
    """A silent substitute would negotiate under a strategy nobody chose."""

    def _unavailable():
        raise ModuleNotFoundError("No module named 'torch'")

    monkeypatch.setattr(TorchStrategySource, "load", lambda self: _unavailable())

    builder = negotiation_catalogue_builder().add_loaders(
        vm_policy_sources(_request(requested=["rl"]))
    )

    with pytest.raises(Exception) as caught:
        builder.build()

    assert "vm-torch-strategy" in str(caught.value)


def test_the_default_chain_interleaves_domain_and_kit_policies() -> None:
    domain_owned = set(VM_SELLER_POLICIES)
    chained = set(VM_DEFAULT_SELLER_CHAIN)

    assert domain_owned <= chained
    assert chained - domain_owned, "the chain must also draw on the policy kit"


def test_the_default_chain_resolves_against_a_composed_catalogue() -> None:
    catalogue = (
        negotiation_catalogue_builder()
        .add_loader(scalar_escrow_policies())
        .add_loaders(vm_policy_sources(_request()))
        .build()
    )

    resolved = catalogue.resolve(list(VM_DEFAULT_SELLER_CHAIN))

    assert len(resolved) == len(VM_DEFAULT_SELLER_CHAIN)
    assert catalogue.provenance("round_zero_opening_guard").startswith("vm-domain")
    assert catalogue.provenance("bisection").startswith("kit-scalar-escrow")


@pytest.mark.torch
def test_the_torch_source_offers_every_alias_under_one_middleware() -> None:
    """Requires the [rl] extra; marked so the default suite does not need torch."""
    offered = TorchStrategySource().load()

    assert set(offered) == set(RL_POLICY_NAMES)
    assert len(set(offered.values())) == 1


def test_the_strategy_is_offered_to_a_buyer_but_the_guards_are_not() -> None:
    """A buyer resolving an inventory guard would name a policy it does not own.

    The strategy is different: both sides of a negotiation may run it, and the
    buyer previously reached it through a registrar hook installed by import
    side effect.
    """
    buyer = vm_policy_sources(_request(role=PolicyRole.BUYER, requested=["rl"]))
    offered = {name for source in buyer for name in source.load()}

    assert offered == set(RL_POLICY_NAMES)
    assert not offered & set(VM_SELLER_POLICIES)


def test_a_buyer_asking_for_no_rl_receives_nothing_from_this_domain() -> None:
    assert vm_policy_sources(_request(role=PolicyRole.BUYER)) == ()
