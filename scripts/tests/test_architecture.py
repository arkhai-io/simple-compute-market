"""The package architecture rules, over synthetic trees."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SCRIPTS))
_SPEC = importlib.util.spec_from_file_location("architecture", _SCRIPTS / "architecture.py")
assert _SPEC and _SPEC.loader
architecture = importlib.util.module_from_spec(_SPEC)
sys.modules["architecture"] = architecture
_SPEC.loader.exec_module(architecture)

RULES_HEAD = """
version = 1
[layers]
order = ["core", "kit", "specialization", "composition"]
[conventions]
kind_words = ["contracts", "client"]
role_words = ["storefront", "buyer", "service", "app"]
skip = ["tools"]
[[families]]
name = "fam"
directory = "domains/fam"
vocabulary = "fam-vocab"
tokens = []
[[domains]]
name = "dom"
directory = "domains/dom"
family = "fam"
tokens = ["dom.v1"]
[[domains]]
name = "sib"
directory = "domains/sib"
family = "fam"
tokens = ["sib.v1"]
[[domains]]
name = "solo"
directory = "domains/solo"
tokens = []
[[mechanisms]]
name = "mech"
kit = "kit-mech"
tokens = ["mech.v1"]
[[plugin_groups]]
name = "host.plugins"
[[plugin_groups]]
name = "host.sinks"
owner = "kit-sinks"
[kind_allowlists.contracts]
layers = ["core"]
distributions = []
family_vocabulary = true
enforce = true
[kind_allowlists.client]
layers = ["core"]
kinds = ["contracts"]
distributions = []
enforce = true
[vocabulary]
fail_layers = ["core", "kit"]
"""


GRAPH_RULES = tuple(rule for rule in architecture.RULES if rule != "configuration")


class Tree:
    """A repository of synthetic projects under ``tmp_path``."""

    def __init__(self, root: Path, rules: str = "") -> None:
        self.root = root
        self.rules = rules
        self.write_rules()

    def write_rules(self, extra: str = "", *, changes: bool = True) -> None:
        """Write the rules file; with ``changes``, create every owner's change directory."""
        self.rules += extra
        path = self.root / "docs" / "development" / "ARCHITECTURE.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(RULES_HEAD + self.rules, "utf-8")
        if changes:
            for owner in re.findall(r'owner = "([^"]+)"', self.rules):
                if owner != "archive":
                    (self.root / "openspec" / "changes" / owner).mkdir(parents=True, exist_ok=True)

    def project(self, path: str, name: str, *, deps=(), extras=None, entry_points=None,
                modules=None, package: str | None = None, settings: str = "") -> None:
        package = package or name.replace("-", "_")
        project = self.root / path
        (project / "src" / package).mkdir(parents=True)
        body = [f'[project]\nname = "{name}"\nversion = "0.1.0"',
                "dependencies = [" + ", ".join(f'"{d}"' for d in deps) + "]"]
        if extras:
            body.append("[project.optional-dependencies]")
            body += [f'{k} = [' + ", ".join(f'"{d}"' for d in v) + "]" for k, v in extras.items()]
        for group, entries in (entry_points or {}).items():
            body.append(f'[project.entry-points."{group}"]')
            body += [f'{k} = "{v}"' for k, v in entries.items()]
        body.append(f'[tool.hatch.build.targets.wheel]\npackages = ["src/{package}"]')
        if settings:
            body.append(settings)
        (project / "pyproject.toml").write_text("\n".join(body) + "\n", "utf-8")
        (project / "src" / package / "__init__.py").write_text("", "utf-8")
        for module, source in (modules or {}).items():
            (project / "src" / package / module).write_text(source, "utf-8")

    def findings(self, rules=None, strict: bool = False):
        # The configuration rule needs every project the rules file names; the
        # graph tests build only the projects they exercise.
        rules = rules or GRAPH_RULES
        model = architecture.build(self.root)
        return [f for f in architecture.problems(model, rules, strict) if not f.excused_by]

    def keys(self, rules=None, strict: bool = False):
        return {f.key for f in self.findings(rules, strict)}

    def model(self):
        return architecture.build(self.root)


def _tree(tmp_path: Path) -> Tree:
    tree = Tree(tmp_path)
    tree.project("core", "core-carrier")
    tree.project("kit/base", "kit-base", deps=["core-carrier"], modules={"a.py": "import core_carrier\n"})
    return tree


# ------------------------------------------------------------------ reading


def test_a_conforming_tree_has_no_findings(tmp_path):
    tree = _tree(tmp_path)
    tree.project("domains/fam", "fam-vocab", deps=["kit-base"], modules={"a.py": "import kit_base\n"})
    tree.project("domains/dom/storefront", "dom-storefront", deps=["fam-vocab"],
                 modules={"a.py": "import fam_vocab\n"})

    assert tree.findings() == []


def test_a_suffix_is_a_kind_only_when_it_is_a_kind_word(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/capability-shape", "kit-shape")
    tree.project("kit/site-client", "kit-site-client")
    tree.project("kit/pool-contracts", "kit-pool-contracts")
    projects = tree.model().projects

    assert projects["kit-shape"].kind == "library"
    assert projects["kit-site-client"].kind == "client"
    assert projects["kit-pool-contracts"].kind == "contracts"


def test_role_words_make_executables_under_domains_but_not_under_kit(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/storefront", "kit-storefront")
    tree.project("domains/solo/sample-app", "solo-sample-app")
    tree.project("domains/dom/buyer", "dom-buyer")
    projects = tree.model().projects

    assert (projects["kit-storefront"].layer, projects["kit-storefront"].kind) == ("kit", "library")
    assert (projects["solo-sample-app"].layer, projects["solo-sample-app"].kind) == ("composition", "executable")
    assert projects["dom-buyer"].layer == "composition"


def test_scope_roots_and_nested_paths_are_libraries_in_their_scope(tmp_path):
    tree = _tree(tmp_path)
    tree.project("domains/fam", "fam-vocab")
    tree.project("domains/dom/domain", "dom-vocab")
    tree.project("domains/solo/middleware/python", "solo-middleware")
    projects = tree.model().projects

    assert (projects["fam-vocab"].layer, projects["fam-vocab"].scope) == ("specialization", {"fam"})
    assert projects["dom-vocab"].scope == {"fam", "dom"}
    assert (projects["solo-middleware"].kind, projects["solo-middleware"].scope) == ("library", {"solo"})


def test_a_domain_without_a_family_implies_nothing(tmp_path):
    tree = _tree(tmp_path)
    tree.project("domains/solo", "solo-domain")

    assert tree.model().projects["solo-domain"].scope == {"solo"}


def test_a_mechanism_in_a_name_widens_scope(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/mech", "kit-mech")
    tree.project("domains/dom/settlement-mech", "dom-settlement-mech", deps=["kit-mech"],
                 modules={"a.py": "import kit_mech\n"})

    assert tree.model().projects["dom-settlement-mech"].scope == {"fam", "dom", "mech"}
    assert tree.findings() == []


def test_a_skipped_path_is_not_a_project(tmp_path):
    tree = _tree(tmp_path)
    tree.project("tools/thing", "thing", deps=["dom-anything"])

    assert "thing" not in tree.model().projects


def test_an_unread_path_is_a_finding_until_overridden(tmp_path):
    tree = _tree(tmp_path)
    tree.project("provisioning/fam", "fam-kit")

    assert ("unclassified", "fam-kit", "provisioning/fam") in tree.keys()

    tree.write_rules('[[overrides]]\nproject = "fam-kit"\nlayer = "specialization"\nkind = "library"\n'
                     'scope = ["fam"]\nowner = "move-it"\n')
    assert tree.findings() == []


# ------------------------------------------------------------------ edges


def test_every_import_context_is_an_edge(tmp_path):
    tree = _tree(tmp_path)
    tree.project("domains/dom/storefront", "dom-storefront")
    for context, source in {
        "module": "import dom_storefront\n",
        "function": "def f():\n    import dom_storefront\n",
        "type-checking": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import dom_storefront\n",
        "try": "try:\n    from dom_storefront import x\nexcept ImportError:\n    pass\n",
    }.items():
        tree.project(f"kit/k-{context}", f"kit-{context}", modules={"a.py": source})
        found = [f for f in tree.findings() if f.rule == "layer" and f.project == f"kit-{context}"]
        assert found and found[0].sites[0].context == context


def test_a_relative_import_stays_inside_its_package(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/rel", "kit-rel", modules={"a.py": "from . import b\nfrom .b import c\n", "b.py": ""})

    assert tree.findings() == []


def test_an_optional_extra_is_a_declaration(tmp_path):
    tree = _tree(tmp_path)
    tree.project("domains/sib", "sib-vocab")
    tree.project("domains/dom/storefront", "dom-storefront", extras={"all": ["sib-vocab"]})

    found = [f for f in tree.findings() if f.rule == "scope"]
    assert found and found[0].sites[0].context == "declaration [all]"


# ------------------------------------------------------------------ rules


def test_layer_fails_on_an_upward_dependency(tmp_path):
    tree = _tree(tmp_path)
    tree.project("domains/dom/storefront", "dom-storefront")
    tree.project("kit/up", "kit-up", deps=["dom-storefront"], modules={"a.py": "import dom_storefront\n"})

    assert ("layer", "kit-up", "dom-storefront") in tree.keys()


def test_cycle_fails_inside_a_layer(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/a", "kit-a", deps=["kit-b"], modules={"m.py": "import kit_b\n"})
    tree.project("kit/b", "kit-b", deps=["kit-a"], modules={"m.py": "import kit_a\n"})

    assert ("cycle", "kit-a", "kit-a -> kit-b") in tree.keys()


def test_scope_fails_on_a_sibling_domain_even_when_only_declared(tmp_path):
    tree = _tree(tmp_path)
    tree.project("domains/sib/storefront", "sib-storefront")
    tree.project("domains/dom/storefront", "dom-storefront", deps=["sib-storefront"])

    assert ("scope", "dom-storefront", "sib-storefront") in tree.keys()


def test_scope_fails_when_a_family_depends_on_its_domain(tmp_path):
    tree = _tree(tmp_path)
    tree.project("domains/dom", "dom-vocab")
    tree.project("domains/fam", "fam-vocab", deps=["dom-vocab"], modules={"a.py": "import dom_vocab\n"})

    assert ("scope", "fam-vocab", "dom-vocab") in tree.keys()


def test_scope_fails_when_a_neutral_kit_imports_a_mechanism_kit(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/mech", "kit-mech")
    tree.project("kit/policy", "kit-policy", deps=["kit-mech"], modules={"a.py": "import kit_mech\n"})

    assert ("scope", "kit-policy", "kit-mech") in tree.keys()


def test_a_composition_composes_the_mechanisms_it_depends_on(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/mech", "kit-mech")
    tree.project("domains/dom/storefront", "dom-storefront", deps=["kit-mech"],
                 modules={"a.py": "import kit_mech\nX = 'mech.v1'\n"})

    assert tree.findings() == []


def test_a_family_composition_composes_its_family_domains(tmp_path):
    tree = _tree(tmp_path)
    tree.project("domains/dom/adapter", "dom-adapter")
    tree.project("domains/sib/adapter", "sib-adapter")
    tree.project("domains/fam/provisioning-service", "fam-service", deps=["dom-adapter", "sib-adapter"],
                 modules={"a.py": "import dom_adapter, sib_adapter\n"})

    assert tree.findings() == []


def test_layer_scope_fails_on_a_kit_granted_a_family(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/pools", "kit-pools")
    tree.write_rules('[[overrides]]\nproject = "kit-pools"\nlayer = "kit"\nkind = "library"\n'
                     'scope = ["fam"]\nowner = "x"\n')

    assert ("layer_scope", "kit-pools", "kit") in tree.keys()


def test_undeclared_import_fails_and_a_declaration_passes(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/b", "kit-b", modules={"a.py": "import core_carrier\n"})

    assert ("undeclared_import", "kit-b", "core-carrier") in tree.keys()


def test_unused_declaration_warns_until_a_row_gives_the_reason(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/b", "kit-b", deps=["core-carrier"])
    found = {f.key: f for f in tree.findings()}

    assert found[("unused_declaration", "kit-b", "core-carrier")].severity == "warn"

    tree.project("kit/c", "kit-c", deps=["core-carrier"],
                 settings='[tool.arkhai.architecture.runtime-dependencies]\ncore-carrier = "a driver"')
    assert ("unused_declaration", "kit-c", "core-carrier") not in tree.keys()


def test_a_runtime_reason_expires_once_the_dependency_is_imported(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/c", "kit-c", deps=["core-carrier"], modules={"a.py": "import core_carrier\n"},
                 settings='[tool.arkhai.architecture.runtime-dependencies]\ncore-carrier = "x"')

    assert ("declaration_expiry", "kit-c", "core-carrier") in tree.keys()


def test_kind_allowlist_holds_contracts_and_clients(tmp_path):
    tree = _tree(tmp_path)
    tree.project("domains/fam", "fam-vocab")
    tree.project("domains/fam/jobs-contracts", "fam-contracts", deps=["fam-vocab", "kit-base"],
                 modules={"a.py": "import fam_vocab, kit_base\n"})
    tree.project("domains/fam/jobs-client", "fam-client", deps=["fam-contracts", "core-carrier", "fam-vocab"],
                 modules={"a.py": "import fam_contracts, core_carrier, fam_vocab\n"})
    keys = tree.keys()

    assert ("kind_allowlist", "fam-contracts", "kit-base") in keys
    assert ("kind_allowlist", "fam-contracts", "fam-vocab") not in keys
    assert ("kind_allowlist", "fam-client", "fam-vocab") in keys
    assert {k for k in keys if k[0] == "kind_allowlist"} == {
        ("kind_allowlist", "fam-contracts", "kit-base"), ("kind_allowlist", "fam-client", "fam-vocab")}


def _package_allowlist(*dists: str, extra: str = "") -> str:
    return ("[tool.arkhai.architecture]\nallowed-dependencies = ["
            + ", ".join(f'"{d}"' for d in dists) + "]\n" + extra)


def test_package_allowlist_allows_only_the_listed_imports(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/light", "kit-light", deps=["pydantic"],
                 modules={"a.py": "import json\nimport pydantic\nimport httpx\n"},
                 settings=_package_allowlist("pydantic"))

    assert {k for k in tree.keys() if k[0] == "package_allowlist"} == {("package_allowlist", "kit-light", "httpx")}


def test_package_allowlist_holds_declarations_without_an_import(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/light", "kit-light", deps=["pydantic>=2", "sqlalchemy>=2"],
                 modules={"a.py": "import pydantic\n"}, settings=_package_allowlist("pydantic"))
    found = {f.key: f for f in tree.findings()}

    assert set(k for k in found if k[0] == "package_allowlist") == {("package_allowlist", "kit-light", "sqlalchemy")}
    assert found[("package_allowlist", "kit-light", "sqlalchemy")].sites[0].context == "declaration"


def test_package_allowlist_matches_a_root_by_normalized_name_or_alias(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/light", "kit-light", deps=["eth-account", "PyYAML"],
                 modules={"a.py": "import eth_account\nimport yaml\n"},
                 settings=_package_allowlist("eth-account", "pyyaml", extra='[tool.arkhai.architecture.import-roots]\nyaml = "PyYAML"\n'))

    assert not {k for k in tree.keys() if k[0] == "package_allowlist"}


def test_a_plugin_is_declared_and_never_imported(tmp_path):
    tree = _tree(tmp_path)
    tree.project("domains/dom/buyer", "dom-buyer", entry_points={"host.plugins": {"dom": "dom_buyer:x"}})
    tree.project("domains/dom/storefront", "dom-storefront", deps=["dom-buyer"])
    assert tree.model().projects["dom-buyer"].plugin
    assert tree.findings() == []

    tree.project("domains/dom/host-service", "dom-host", deps=["dom-buyer"], modules={"a.py": "import dom_buyer\n"})
    assert ("plugin_in_degree", "dom-host", "dom-buyer") in tree.keys()


def test_a_group_owner_registering_its_own_members_is_not_a_plugin(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/sinks", "kit-sinks", entry_points={"host.sinks": {"file": "kit_sinks:f"}})
    tree.project("kit/sinks-extra", "kit-sinks-extra", entry_points={"host.sinks": {"x": "kit_sinks_extra:x"}})
    tree.project("kit/sinks-user", "kit-sinks-user", deps=["kit-sinks"], modules={"a.py": "import kit_sinks\n"})
    projects = tree.model().projects

    assert not projects["kit-sinks"].plugin
    assert projects["kit-sinks-extra"].plugin
    assert (projects["kit-sinks-extra"].layer, projects["kit-sinks-extra"].kind) == ("kit", "library")
    assert tree.findings() == []


def test_an_unlisted_entry_point_group_confers_nothing(tmp_path):
    tree = _tree(tmp_path)
    tree.project("domains/dom", "dom-vocab", entry_points={"host.domains": {"dom": "dom_vocab:D"}})
    tree.project("domains/dom/buyer", "dom-buyer", deps=["dom-vocab"], modules={"a.py": "import dom_vocab\n"})

    assert not tree.model().projects["dom-vocab"].plugin
    assert tree.findings() == []


def test_vocabulary_fails_in_kit_and_warns_in_a_composition(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/cfg", "kit-cfg", modules={"a.py": "KNOWN = {'mech.v1'}\n"})
    tree.project("domains/dom/storefront", "dom-storefront", modules={"a.py": "OTHER = 'sib.v1'\n"})
    tree.project("kit/doc", "kit-doc", modules={"a.py": '"""Settles through mech.v1."""\nDOC = 1\n'})
    found = {f.key: f.severity for f in tree.findings()}

    assert found[("vocabulary", "kit-cfg", "mech.v1")] == "fail"
    assert found[("vocabulary", "dom-storefront", "sib.v1")] == "warn"
    assert ("vocabulary", "kit-doc", "mech.v1") not in found


# ------------------------------------------------------------------ tables


def test_an_exception_excuses_only_the_rule_it_names(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/mech", "kit-mech")
    tree.project("kit/policy", "kit-policy", modules={"a.py": "import kit_mech\n"})
    tree.write_rules('[[exceptions]]\nrule = "scope"\nproject = "kit-policy"\ntarget = "kit-mech"\n'
                     'owner = "move-it"\nsince = 2026-01-01\n')
    keys = tree.keys()

    assert ("scope", "kit-policy", "kit-mech") not in keys
    assert ("undeclared_import", "kit-policy", "kit-mech") in keys
    assert ("scope", "kit-policy", "kit-mech") in tree.keys(strict=True)


def test_an_exception_expires_when_its_edge_is_gone(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/mech", "kit-mech")
    tree.project("kit/policy", "kit-policy")
    tree.write_rules('[[exceptions]]\nrule = "scope"\nproject = "kit-policy"\ntarget = "kit-mech"\n'
                     'owner = "move-it"\nsince = 2026-01-01\n')

    assert ("exception_expiry", "kit-policy", "scope:kit-mech") in tree.keys()


def test_an_exception_expires_when_its_edge_no_longer_breaks_the_rule(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/plain", "kit-plain")
    tree.project("kit/policy", "kit-policy", deps=["kit-plain"], modules={"a.py": "import kit_plain\n"})
    tree.write_rules('[[exceptions]]\nrule = "scope"\nproject = "kit-policy"\ntarget = "kit-plain"\n'
                     'owner = "move-it"\nsince = 2026-01-01\n')

    assert ("exception_expiry", "kit-policy", "scope:kit-plain") in tree.keys()


def test_an_override_expires_once_the_path_conforms(tmp_path):
    tree = _tree(tmp_path)
    tree.project("domains/fam/provisioning", "fam-kit")
    tree.write_rules('[[overrides]]\nproject = "fam-kit"\nlayer = "specialization"\nkind = "library"\n'
                     'scope = ["fam"]\nowner = "move-it"\n')

    assert ("override_expiry", "fam-kit", "override") in tree.keys()


def test_an_override_expires_once_a_granted_mechanism_goes_unused(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/mech", "kit-mech")
    tree.project("domains/dom/settlement", "dom-settlement")
    grant = ('[[overrides]]\nproject = "dom-settlement"\nlayer = "specialization"\nkind = "library"\n'
             'scope = ["fam", "dom", "mech"]\nowner = "rename-it"\n')
    tree.write_rules(grant)

    assert ("override_expiry", "dom-settlement", "grant:mech") in tree.keys()


def test_an_override_granting_a_family_needs_no_use(tmp_path):
    tree = _tree(tmp_path)
    tree.project("provisioning/fam/contracts", "fam-contracts", deps=["core-carrier"],
                 modules={"a.py": "import core_carrier\n"})
    tree.write_rules('[[overrides]]\nproject = "fam-contracts"\nlayer = "specialization"\nkind = "contracts"\n'
                     'scope = ["fam"]\nowner = "move-it"\n')

    assert tree.findings() == []


def test_owned_rows_lists_a_changes_exceptions_and_overrides(tmp_path):
    tree = _tree(tmp_path)
    tree.project("provisioning/fam", "fam-kit")
    tree.write_rules('[[overrides]]\nproject = "fam-kit"\nlayer = "specialization"\nkind = "library"\n'
                     'scope = ["fam"]\nowner = "move-it"\n'
                     '[[exceptions]]\nrule = "layer"\nproject = "kit-base"\ntarget = "x"\nowner = "move-it"\n')
    model = tree.model()

    assert architecture.owned_rows(model, "move-it") == ["exception: layer kit-base -> x", "override: fam-kit"]
    assert architecture.owned_rows(model, "other") == []


def test_a_package_allowlist_lists_internal_distributions_too(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/shape", "kit-shape", deps=["kit-base"], modules={"a.py": "import kit_base\n"},
                 settings=_package_allowlist())

    assert ("package_allowlist", "kit-shape", "kit-base") in tree.keys()


# ------------------------------------------------------------------ retired per-package tests
#
# Each case is the violation a per-package boundary test used to catch, named
# for that test, so the repository check is shown to fail where it did.


def _retired_case_tree(tmp_path: Path) -> Tree:
    tree = _tree(tmp_path)
    tree.project("kit/mech", "kit-mech")
    tree.project("kit/plain", "kit-plain")
    tree.project("domains/fam", "fam-vocab")
    tree.project("domains/dom", "dom-vocab")
    tree.project("domains/sib", "sib-vocab")
    tree.project("domains/dom/storefront", "dom-storefront")
    tree.project("domains/sib/storefront", "sib-storefront",
                 entry_points={"host.plugins": {"sib": "sib_storefront:x"}})
    tree.project("domains/dom/provisioning-adapter", "dom-adapter")
    tree.project("domains/sib/provisioning-adapter", "sib-adapter")
    tree.project("domains/dom/provisioning/client", "dom-operator-client")
    tree.project("domains/fam/provisioning-service", "fam-service")
    tree.project("roles/storefront", "role-storefront")
    return tree


RETIRED_CASES = {
    # kit identity, settlement runtime, capability shape and pricing, pool
    # contracts and client, contact exchange, compute vocabulary, provisioning
    # contracts and client: an import outside the package's allowlist.
    "allowlist": ("kit/light", "kit-light", "import kit_plain\nimport fastapi\n",
                  [("package_allowlist", "kit-light", "kit-plain"), ("package_allowlist", "kit-light", "fastapi")]),
    # core carrier purity: a carrier importing anything internal.
    "carrier purity": ("core/extra", "core-extra", "import kit_plain\n", [("layer", "core-extra", "kit-plain")]),
    # core domain boundaries: a core role importing a concrete domain.
    "core role and a domain": ("roles/buyer", "role-buyer", "import dom_storefront\n",
                               [("scope", "role-buyer", "dom-storefront")]),
    # VM storefront architecture: a kit importing a domain or a role.
    "kit and a role": ("kit/up", "kit-up", "import role_storefront\nimport dom_vocab\n",
                       [("layer", "kit-up", "role-storefront"), ("layer", "kit-up", "dom-vocab")]),
    # fulfillment and site: a kit importing a family kit or an adapter.
    "kit and a family kit": ("kit/sched", "kit-sched", "import dom_adapter\n", [("layer", "kit-sched", "dom-adapter")]),
    # bare-metal domain and storefront: a domain importing its sibling.
    "sibling domain": ("domains/dom/negotiation", "dom-negotiation", "import sib_vocab\n",
                       [("scope", "dom-negotiation", "sib-vocab")]),
    # bare-metal storefront: core or kit importing a domain storefront.
    "kit and a contribution": ("kit/pub", "kit-pub", "import sib_storefront\n",
                               [("layer", "kit-pub", "sib-storefront"), ("plugin_in_degree", "kit-pub", "sib-storefront")]),
    # provisioning service: an adapter importing its service or its sibling.
    "adapter and service": ("domains/dom/provisioning-extra", "dom-extra", "import fam_service\nimport sib_adapter\n",
                            [("layer", "dom-extra", "fam-service"), ("scope", "dom-extra", "sib-adapter")]),
    # provisioning service: a family module importing a domain's operator client.
    "family and a domain client": ("domains/fam/jobs", "fam-jobs", "import dom_operator_client\n",
                                   [("scope", "fam-jobs", "dom-operator-client")]),
    # settlement runtime: a mechanism-neutral kit importing a mechanism kit.
    "neutral kit and a mechanism": ("kit/neutral", "kit-neutral", "import kit_mech\n",
                                    [("scope", "kit-neutral", "kit-mech")]),
}


@pytest.mark.parametrize("case", sorted(RETIRED_CASES))
def test_the_check_fails_where_a_retired_boundary_test_did(tmp_path, case):
    tree = _retired_case_tree(tmp_path)
    path, name, source, expected = RETIRED_CASES[case]
    tree.project(path, name, modules={"a.py": source}, settings=_package_allowlist("pydantic") if name == "kit-light" else "")

    keys = tree.keys()

    assert set(expected) <= keys, sorted(keys)


# ------------------------------------------------------------------ fail closed and configuration


def test_a_project_without_one_wheel_package_fails_closed(tmp_path):
    tree = _tree(tmp_path)
    project = tmp_path / "kit" / "odd"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text('[project]\nname = "kit-odd"\nversion = "0.1.0"\n', "utf-8")

    found = {f.key: f for f in tree.findings()}

    assert "cannot read it" in found[("unclassified", "kit-odd", "kit/odd")].message


def test_a_virtual_project_is_not_a_package(tmp_path):
    tree = _tree(tmp_path)
    project = tmp_path / "domains" / "dom" / "iac"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text('[project]\nname = "dom-iac"\nversion = "0.1.0"\n'
                                            '[tool.uv]\npackage = false\n', "utf-8")

    assert "dom-iac" not in tree.model().projects


def _configured(tmp_path: Path) -> Tree:
    """A tree holding every project the shared rules file names."""
    tree = _tree(tmp_path)
    tree.project("domains/fam", "fam-vocab")
    tree.project("kit/mech", "kit-mech")
    tree.project("kit/sinks", "kit-sinks")
    return tree


def _configuration(tree: Tree) -> set[tuple[str, str, str]]:
    return tree.keys(rules=("configuration",))


def test_a_complete_configuration_passes(tmp_path):
    assert _configuration(_configured(tmp_path)) == set()


def test_configuration_fails_on_a_name_that_resolves_to_nothing(tmp_path):
    tree = _tree(tmp_path)

    keys = _configuration(tree)

    assert ("configuration", "family", "fam") in keys
    assert ("configuration", "mechanism", "mech") in keys
    assert ("configuration", "plugin-group", "host.sinks") in keys


def test_configuration_fails_on_duplicate_rows(tmp_path):
    tree = _configured(tmp_path)
    row = '[[exceptions]]\nrule = "layer"\nproject = "kit-base"\ntarget = "x"\nowner = "fix-it"\n'
    tree.write_rules(row + row)

    assert any(k[0] == "configuration" and k[1] == "exception" for k in _configuration(tree))


def test_configuration_fails_on_an_owner_that_is_not_an_open_change(tmp_path):
    tree = _configured(tmp_path)
    tree.write_rules('[[exceptions]]\nrule = "layer"\nproject = "kit-base"\ntarget = "x"\nowner = "gone"\n',
                     changes=False)
    (tmp_path / "openspec" / "changes" / "archive" / "2026-01-01-gone").mkdir(parents=True)

    assert ("configuration", "kit-base", "owner:layer:x") in _configuration(tree)


def test_configuration_fails_on_an_override_granting_an_unknown_element(tmp_path):
    tree = _configured(tmp_path)
    tree.write_rules('[[overrides]]\nproject = "kit-base"\nlayer = "kit"\nkind = "library"\n'
                     'scope = ["nowhere"]\nowner = "move-it"\n')

    assert ("configuration", "kit-base", "scope:nowhere") in _configuration(tree)


def test_a_package_table_may_not_classify_its_package(tmp_path):
    tree = _configured(tmp_path)
    tree.project("kit/self", "kit-self", settings='[tool.arkhai.architecture]\nscope = ["dom"]\n')

    assert ("configuration", "kit-self", "scope") in _configuration(tree)


def test_package_allowlist_requires_an_imported_third_party_distribution_be_declared(tmp_path):
    tree = _tree(tmp_path)
    tree.project("kit/light", "kit-light", modules={"a.py": "import sqlalchemy\n"},
                 settings=_package_allowlist("sqlalchemy"))
    found = {f.key: f for f in tree.findings()}

    assert "does not declare" in found[("package_allowlist", "kit-light", "sqlalchemy")].message


def test_a_wheel_naming_a_missing_package_fails_closed(tmp_path):
    tree = _tree(tmp_path)
    project = tmp_path / "kit" / "odd"
    (project / "src" / "odd").mkdir(parents=True)
    (project / "src" / "odd" / "a.py").write_text("import anything_at_all\n", "utf-8")
    (project / "pyproject.toml").write_text(
        '[project]\nname = "kit-odd"\nversion = "0.1.0"\n'
        '[tool.hatch.build.targets.wheel]\npackages = ["src/nonexistent"]\n', "utf-8")

    assert ("unclassified", "kit-odd", "kit/odd") in tree.keys()


def test_configuration_refuses_an_archived_change_named_by_its_path(tmp_path):
    tree = _configured(tmp_path)
    (tmp_path / "openspec" / "changes" / "archive" / "2026-10-01-gone").mkdir(parents=True)
    tree.write_rules('[[exceptions]]\nrule = "layer"\nproject = "kit-base"\ntarget = "x"\n'
                     'owner = "archive/2026-10-01-gone"\n', changes=False)

    assert ("configuration", "kit-base", "owner:layer:x") in _configuration(tree)


def test_configuration_finds_duplicates_under_different_spellings(tmp_path):
    tree = _configured(tmp_path)
    tree.write_rules('[[exceptions]]\nrule = "layer"\nproject = "kit-base"\ntarget = "x"\nowner = "fix-it"\n'
                     '[[exceptions]]\nrule = "layer"\nproject = "Kit_Base"\ntarget = "x"\nowner = "fix-it"\n')

    assert any(k[0] == "configuration" and k[1] == "exception" for k in _configuration(tree))


def test_configuration_refuses_an_exception_for_an_unknown_rule(tmp_path):
    tree = _configured(tmp_path)
    tree.write_rules('[[exceptions]]\nrule = "layr"\nproject = "kit-base"\ntarget = "x"\nowner = "fix-it"\n')

    assert ("configuration", "kit-base", "rule:layr") in _configuration(tree)
