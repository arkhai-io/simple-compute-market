"""VM provision-term construction."""

from service.schemas import ProvisionTerms


def make_vm_provision_terms(
    *,
    duration_seconds: int,
    ssh_public_key: str,
) -> ProvisionTerms:
    return ProvisionTerms(
        duration_seconds=int(duration_seconds),
        ssh_public_key=ssh_public_key,
    )
