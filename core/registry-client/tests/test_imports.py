from registry_client import RegistryClient, RegistryClientError, SyncRegistryClient


def test_public_client_imports() -> None:
    assert RegistryClient is not None
    assert SyncRegistryClient is not None
    assert RegistryClientError is not None
