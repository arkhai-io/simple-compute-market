"""Check installed schema bytes, models and producer signing vectors."""

from market_arkhai_mediation.contract import publication, validate, vectors, wire
from market_arkhai_mediation.fixtures import sign_record
from market_arkhai_mediation.models import SignedRecordEntry
from market_arkhai_mediation.records import record_message, verify_record

metadata = publication()
assert metadata["published"] and "delivery_end" not in metadata["capabilities"]
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
print("published mediation bytes, models and all eight record vectors verified")
