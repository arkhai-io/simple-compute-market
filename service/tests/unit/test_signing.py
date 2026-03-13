"""Unit tests for service.clients.erc8004.signing."""

import time
import pytest

PRIVATE_KEY = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
OWNER_ADDRESS = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"


def test_sign_eip191_returns_hex_string():
    pytest.importorskip("eth_account")
    from service.clients.erc8004.signing import sign_eip191
    sig = sign_eip191(PRIVATE_KEY, "hello world")
    assert sig is not None
    assert isinstance(sig, str)
    assert len(sig) == 130  # 65 bytes, no 0x prefix


def test_sign_eip191_is_recoverable():
    """The signature produced can be recovered back to the expected address."""
    eth_account = pytest.importorskip("eth_account")
    encode_defunct = pytest.importorskip("eth_account.messages").encode_defunct
    from service.clients.erc8004.signing import sign_eip191
    message = "test-recovery"
    sig = sign_eip191(PRIVATE_KEY, message)
    recovered = eth_account.Account.recover_message(encode_defunct(text=message), signature=sig)
    assert recovered.lower() == OWNER_ADDRESS.lower()


def test_sign_eip191_no_eth_account(monkeypatch):
    import service.clients.erc8004.signing as mod
    monkeypatch.setattr(mod, "HAS_ETH_ACCOUNT", False)
    from service.clients.erc8004.signing import sign_eip191
    assert sign_eip191(PRIVATE_KEY, "hello") is None


def test_build_order_auth_has_required_fields():
    pytest.importorskip("eth_account")
    from service.clients.erc8004.signing import build_order_auth
    before = int(time.time())
    auth = build_order_auth(PRIVATE_KEY, "create_order", "agent-id-123")
    after = int(time.time())
    assert "signature" in auth
    assert "timestamp" in auth
    assert before <= auth["timestamp"] <= after
    assert isinstance(auth["signature"], str)
    assert len(auth["signature"]) == 130


def test_build_order_auth_message_format():
    """The message embedded in the signature matches the expected format."""
    eth_account = pytest.importorskip("eth_account")
    encode_defunct = pytest.importorskip("eth_account.messages").encode_defunct
    from service.clients.erc8004.signing import build_order_auth
    auth = build_order_auth(PRIVATE_KEY, "update_order", "order-xyz")
    expected_msg = f"update_order:order-xyz:{auth['timestamp']}"
    recovered = eth_account.Account.recover_message(
        encode_defunct(text=expected_msg), signature=auth["signature"]
    )
    assert recovered.lower() == OWNER_ADDRESS.lower()


def test_build_order_auth_no_eth_account(monkeypatch):
    import service.clients.erc8004.signing as mod
    monkeypatch.setattr(mod, "HAS_ETH_ACCOUNT", False)
    from service.clients.erc8004.signing import build_order_auth
    assert build_order_auth(PRIVATE_KEY, "create_order", "agent-id") == {}


def test_verify_eip191_valid():
    pytest.importorskip("eth_account")
    from service.clients.erc8004.signing import sign_eip191, verify_eip191
    sig = sign_eip191(PRIVATE_KEY, "hello")
    assert verify_eip191("hello", sig, OWNER_ADDRESS) is True


def test_verify_eip191_wrong_address():
    pytest.importorskip("eth_account")
    from service.clients.erc8004.signing import sign_eip191, verify_eip191
    sig = sign_eip191(PRIVATE_KEY, "hello")
    assert verify_eip191("hello", sig, "0x000000000000000000000000000000000000dead") is False


def test_verify_eip191_wrong_message():
    pytest.importorskip("eth_account")
    from service.clients.erc8004.signing import sign_eip191, verify_eip191
    sig = sign_eip191(PRIVATE_KEY, "hello")
    assert verify_eip191("wrong message", sig, OWNER_ADDRESS) is False


def test_verify_eip191_no_eth_account(monkeypatch):
    import service.clients.erc8004.signing as mod
    monkeypatch.setattr(mod, "HAS_ETH_ACCOUNT", False)
    from service.clients.erc8004.signing import verify_eip191
    assert verify_eip191("hello", "0xdeadbeef", OWNER_ADDRESS) is False
