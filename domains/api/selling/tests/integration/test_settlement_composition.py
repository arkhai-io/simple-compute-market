"""The library's settlement composition, assembled over real SQLite from what a storefront passes."""

from __future__ import annotations

import pytest
from arkhai_api.evidence import ExpectedIssuanceEvidenceV1, IssuanceEvidenceError
from market_core import SettlementStageTable
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_settlement_runtime import MechanismRegistration
from market_storefront_kit.dispute_configuration import RegistryDisputePolicy
from pydantic import BaseModel, ConfigDict

from arkhai_api_selling.evidence_store import IssuanceEvidenceRepository, IssuanceEvidenceService
from arkhai_api_selling.settlement_composition import build_selling_settlement_composition
from tests.bundles import BUYER, CLAIMANT, DOMAIN, EXAMPLE, ISSUER, create_tables

# Deterministic development key; never use it on a public network.
OTHER = Ed25519Signer(bytes(range(4, 36)))
COMMITTED_AT = 1_700_000_000
_EXPECTED_FIELDS = (
    "condition_anchor", "obligation_ref", "fulfillment_id", "grant_id", "service", "resource_id",
    "quantity", "key_mode", "key_id", "owner", "buyer", "claimant", "issuer", "request_digest",
)


class _Section(BaseModel):
    enabled: bool = False


class _PublicationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Stage:
    """A seller stage that records what the builder asks of it and refuses a configuration when told to."""

    def __init__(self, refusal: str | None = None) -> None:
        self.validated: list = []
        self.clients_built = 0
        self._refusal = refusal

    def registration(self) -> MechanismRegistration:
        return MechanismRegistration(
            mechanism_id="example.v1", config_key="example", config_model=_Section,
            roles=frozenset({"seller"}), preflight=lambda *_a, **_k: None, client_factory=None,
            option_builder=lambda *_a, **_k: {}, buyer_compatibility=lambda *_a, **_k: True,
            clause_fields=(), publication_input_model=_PublicationInput,
            publication_input_validator=lambda *_a, **_k: None,
        )

    def validate_configuration(self, settlement_config):
        self.validated.append(settlement_config)
        if self._refusal:
            raise ValueError(self._refusal)

    def client(self, _resources):
        self.clients_built += 1
        return "example-client"

    def servicing(self, _settlement_config):
        return "example-servicing"


STAGED = {"priority": ["example.v1"], "example": {"enabled": True}}


def _compose(db_path, resources=None, *, stages=None, configuration=None, **options):
    return build_selling_settlement_composition(
        contributions=EXAMPLE,
        stages=SettlementStageTable({} if stages is None else stages),
        domain=DOMAIN,
        database_path=str(db_path),
        settlement_configuration={} if configuration is None else configuration,
        resources={"chains": {}} if resources is None else resources,
        signer=ISSUER,
        credits_client=object(),
        failure_policy=None,
        worker_id="example-storefront:test",
        servicing_interval_seconds=60,
        on_event=lambda _event, _fields: None,
        **options,
    )


def _body(service, signer):
    return service.body(
        condition_anchor="condition:1",
        obligation_ref="obligation:1",
        fulfillment_id="example-fulfillment.v1:" + "a" * 64,
        grant_id="example-fulfillment.v1:" + "a" * 64,
        service="alpha",
        resource_id="quota-a",
        quantity=5,
        key_mode="new",
        key_id="ak_public",
        owner=BUYER,
        buyer=BUYER,
        claimant=CLAIMANT,
        issuer=signer.identity,
        committed_at_unix=COMMITTED_AT,
        request_digest="sha256:" + "b" * 64,
    )


def _expected(body):
    return ExpectedIssuanceEvidenceV1(
        **{name: getattr(body, name) for name in _EXPECTED_FIELDS},
        funding_expiration_unix=COMMITTED_AT + 3600,
    )


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "storefront.db"
    create_tables(path)
    return path


def test_a_composition_without_a_dispute_policy_offers_no_dispute_authority(db_path):
    resources = {"chains": {}}
    composition = _compose(db_path, resources)

    assert composition.local_principal == ISSUER.identity
    assert composition.contributions is EXAMPLE and composition.domain is DOMAIN
    assert composition.mechanism_clients == {} and composition.servicing == {}
    assert composition.mechanism_resources is resources
    assert composition.disputes.for_publication() == RegistryDisputePolicy.from_document({}).for_publication()
    assert composition.dispute_interfaces == frozenset()


def test_a_composition_with_a_dispute_policy_carries_it_and_its_interfaces(db_path):
    disputes = RegistryDisputePolicy.from_document({})

    composition = _compose(db_path, disputes=disputes, dispute_interfaces=frozenset({"example.mediation.v1"}))

    assert composition.disputes is disputes
    assert composition.dispute_interfaces == frozenset({"example.mediation.v1"})


def test_the_evidence_service_trusts_only_the_signer_passed(db_path):
    composition = _compose(db_path)
    own = _body(composition.evidence_service, ISSUER)
    published = composition.evidence_service.publish(own)
    other = IssuanceEvidenceService(
        IssuanceEvidenceRepository(str(db_path), EXAMPLE),
        contributions=EXAMPLE,
        signer=OTHER,
        trusted_issuers=TrustedIdentitySet(identities=(OTHER.identity,)),
    )
    another_fulfillment = "example-fulfillment.v1:" + "c" * 64
    foreign_body = _body(other, OTHER).model_copy(
        update={"fulfillment_id": another_fulfillment, "grant_id": another_fulfillment}
    )
    foreign = other.publish(foreign_body)

    assert composition.evidence_service.resolve_verified(
        published.evidence_digest, expected=_expected(own)
    ) == published.evidence
    with pytest.raises(IssuanceEvidenceError, match="issuer is not trusted"):
        composition.evidence_service.resolve_verified(foreign.evidence_digest, expected=_expected(foreign_body))


def test_each_stage_validates_the_resolved_configuration_before_its_client_is_built(db_path):
    stage = _Stage()

    composition = _compose(db_path, stages={"example.v1": stage}, configuration=STAGED)

    assert stage.validated == [composition.settlement_config]
    assert composition.settlement_config.priority == ("example.v1",)
    assert composition.mechanism_clients == {"example.v1": "example-client"}
    assert composition.servicing == {"example.v1": "example-servicing"}


def test_a_configuration_a_stage_refuses_builds_nothing(db_path):
    stage = _Stage(refusal="contradicts itself")

    with pytest.raises(ValueError, match="contradicts itself"):
        _compose(db_path, stages={"example.v1": stage}, configuration=STAGED)
    assert stage.clients_built == 0
