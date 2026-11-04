"""Check installed schema bytes, models and producer signing vectors."""

from market_identity import Identity
from market_arkhai_mediation.claims import claim_message, sign_claim, verify_claim
from market_arkhai_mediation.contract import publication, validate, vectors, wire
from market_arkhai_mediation.fixtures import market_signer, sign_record
from market_arkhai_mediation.models import DeliveryEndClaim, SignedDeliveryEndClaim, SignedRecordEntry
from market_arkhai_mediation.records import record_message, verify_record

metadata = publication()
assert metadata["published"] and "delivery_end" in metadata["capabilities"]
data = vectors()
validate("Description", data["description"])
validate("Filing", data["filing"]["request"])
validate("FilingAnswer", data["filing"]["answer"])
validate("Append", data["append"]["request"])
validate("RecordPage", data["read"]["page"])
for vector in data["records"]:
    value = vector["signed"]
    signed = SignedRecordEntry.model_validate(value)
    assert wire(signed) == value
    assert record_message(value["entry"]).hex() == vector["message"]
    assert wire(sign_record(value["entry"])) == value
    verify_record(
        signed, record_key=data["keys"]["record_key"],
        agreement=value["entry"]["agreement"], transaction=value["entry"]["transaction"],
        sequence=value["entry"]["sequence"],
    )
for vector in data["delivery_end_claims"]:
    value = vector["signed"]
    signed = SignedDeliveryEndClaim.model_validate(value)
    seller = Identity.model_validate(value["signer"])
    claim = DeliveryEndClaim.model_validate(value["claim"])
    assert wire(signed) == value
    assert claim_message(agreement=value["agreement"], claim=claim, signer=seller).hex() == vector["message"]
    assert verify_claim(signed, agreement=value["agreement"], seller=seller, claim=claim)
    assert wire(sign_claim(agreement=value["agreement"], claim=claim, signer=market_signer(value["signer"]["scheme"]))) == value
validate("RespondentAfter", data["respondent"]["request"])
validate("RespondentPage", data["respondent"]["page"])
validate("RespondentPage", data["respondent"]["after_answer"])
validate("Append", data["delivery_end"]["append"])
print("published mediation bytes, record vectors and both claim signature schemes verified")
