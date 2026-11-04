"""Dispute interfaces and buyer-side kit boundaries over fixture trees."""

import pytest

from test_architecture import Tree


RULES = """
[[disputes]]
name = "mediation"
kit = "kit-mediation"
tokens = ["mediation.v1"]
[kit_areas]
foundation = ["kit/base"]
buyer = ["kit/lifecycle-buyer"]
[kind_allowlists.dispute]
layers = ["core"]
kinds = ["contracts"]
areas = ["foundation"]
enforce = true
"""


def tree_with_dispute(tmp_path, *, source=""):
    tree = Tree(tmp_path, RULES)
    tree.project("kit/base", "kit-base")
    tree.project("kit/wire-contracts", "kit-wire-contracts")
    tree.project("kit/mediation", "kit-mediation",
                 deps=["kit-base", "kit-wire-contracts"],
                 modules={"adapter.py": "import kit_base\nimport kit_wire_contracts\n" + source})
    return tree


def test_dispute_kit_and_its_composition_have_interface_scope(tmp_path):
    tree = tree_with_dispute(tmp_path, source='INTERFACE = "mediation.v1"\n')
    tree.project("domains/dom/storefront", "dom-storefront", deps=["kit-mediation"],
                 modules={"app.py": "import kit_mediation\n"})

    model = tree.model()
    assert model.projects["kit-mediation"].kind == "dispute"
    assert model.projects["kit-mediation"].scope == {"mediation"}
    assert "mediation" in model.projects["dom-storefront"].scope
    assert tree.keys() == set()


def test_dispute_interface_tokens_are_not_neutral_vocabulary(tmp_path):
    tree = tree_with_dispute(tmp_path)
    tree.project("kit/neutral", "kit-neutral", modules={"a.py": 'INTERFACE = "mediation.v1"\n'})

    assert ("vocabulary", "kit-neutral", "mediation.v1") in tree.keys()


def test_dispute_kit_cannot_name_a_payment_mechanism(tmp_path):
    tree = tree_with_dispute(tmp_path, source='PAYMENT = "mech.v1"\n')

    assert ("vocabulary", "kit-mediation", "mech.v1") in tree.keys()


def test_a_kit_cannot_hold_both_scopes(tmp_path):
    tree = tree_with_dispute(tmp_path)
    tree.write_rules('[[mechanisms]]\nname = "other"\nkit = "kit-mediation"\ntokens = ["other.v1"]\n')

    assert ("layer_scope", "kit-mediation", "kit") in tree.keys()


def test_dispute_kit_cannot_depend_on_an_authority(tmp_path):
    tree = Tree(tmp_path, RULES)
    tree.project("kit/site", "kit-site")
    tree.project("kit/mediation", "kit-mediation", deps=["kit-site"],
                 modules={"a.py": "import kit_site\n"})

    assert ("kind_allowlist", "kit-mediation", "kit-site") in tree.keys()


def test_buyer_kit_foundation_and_contracts_are_consumed_by_buyer(tmp_path):
    tree = tree_with_dispute(tmp_path)
    tree.project("kit/lifecycle-buyer", "kit-lifecycle-buyer", deps=["kit-base", "kit-wire-contracts"],
                 modules={"a.py": "import kit_base\nimport kit_wire_contracts\n"})
    tree.project("domains/dom/buyer", "dom-buyer", deps=["kit-lifecycle-buyer"],
                 modules={"a.py": "import kit_lifecycle_buyer\n"})

    assert tree.keys() == set()


@pytest.mark.parametrize("target", ["site", "wire-client", "mediation"])
def test_buyer_kit_cannot_depend_on_a_nonfoundation_kit(tmp_path, target):
    tree = tree_with_dispute(tmp_path)
    if target != "mediation":
        tree.project(f"kit/{target}", f"kit-{target}")
    tree.project("kit/lifecycle-buyer", "kit-lifecycle-buyer", deps=[f"kit-{target}"],
                 modules={"a.py": f"import kit_{target.replace('-', '_')}\n"})

    assert ("kit_area", "kit-lifecycle-buyer", f"kit-{target}") in tree.keys()


@pytest.mark.parametrize("path", ["kit/site", "kit/storefront", "domains/dom/storefront"])
def test_nonbuyers_cannot_consume_a_buyer_kit(tmp_path, path):
    tree = tree_with_dispute(tmp_path)
    tree.project("kit/lifecycle-buyer", "kit-lifecycle-buyer")
    tree.project(path, "consumer", deps=["kit-lifecycle-buyer"],
                 modules={"a.py": "import kit_lifecycle_buyer\n"})

    assert ("kit_area", "consumer", "kit-lifecycle-buyer") in tree.keys()
