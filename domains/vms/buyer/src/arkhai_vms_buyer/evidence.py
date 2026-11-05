"""VM buyer composition owns the evidence root beside its identity profiles."""

from core_buyer.profile_service import profile_store_path
from market_deal_lifecycle_buyer import FileEvidenceStore


def evidence_store() -> FileEvidenceStore:
    return FileEvidenceStore(profile_store_path().parent / "evidence")
