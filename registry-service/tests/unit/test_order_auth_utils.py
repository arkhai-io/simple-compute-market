"""Unit tests for verify_order_signature and _verify_eip191_signature in utils.py."""

import time
import pytest


OWNER_PRIVATE_KEY = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
OWNER_ADDRESS = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"
OTHER_PRIVATE_KEY = "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6"


@pytest.fixture(scope="module")
def eth_account():
    return pytest.importorskip("eth_account")


@pytest.fixture(scope="module")
def encode_defunct():
    return pytest.importorskip("eth_account.messages").encode_defunct


def _make_sig(eth_account, encode_defunct, private_key: str, message: str) -> str:
    msg_hash = encode_defunct(text=message)
    return eth_account.Account.sign_message(msg_hash, private_key).signature.hex()


# --- verify_order_signature ---

def test_verify_order_signature_valid_create(eth_account, encode_defunct):
    from src.api.utils import verify_order_signature
    ts = int(time.time())
    sig = _make_sig(eth_account, encode_defunct, OWNER_PRIVATE_KEY, f"create_order:agent-1:{ts}")
    assert verify_order_signature("create_order", "agent-1", ts, sig, OWNER_ADDRESS) is True


def test_verify_order_signature_valid_update(eth_account, encode_defunct):
    from src.api.utils import verify_order_signature
    ts = int(time.time())
    sig = _make_sig(eth_account, encode_defunct, OWNER_PRIVATE_KEY, f"update_order:order-42:{ts}")
    assert verify_order_signature("update_order", "order-42", ts, sig, OWNER_ADDRESS) is True


def test_verify_order_signature_valid_delete(eth_account, encode_defunct):
    from src.api.utils import verify_order_signature
    ts = int(time.time())
    sig = _make_sig(eth_account, encode_defunct, OWNER_PRIVATE_KEY, f"delete_order:order-42:{ts}")
    assert verify_order_signature("delete_order", "order-42", ts, sig, OWNER_ADDRESS) is True


def test_verify_order_signature_wrong_key(eth_account, encode_defunct):
    from src.api.utils import verify_order_signature
    ts = int(time.time())
    sig = _make_sig(eth_account, encode_defunct, OTHER_PRIVATE_KEY, f"create_order:agent-1:{ts}")
    assert verify_order_signature("create_order", "agent-1", ts, sig, OWNER_ADDRESS) is False


def test_verify_order_signature_wrong_operation(eth_account, encode_defunct):
    from src.api.utils import verify_order_signature
    ts = int(time.time())
    # Signed for "update_order" but verified as "create_order"
    sig = _make_sig(eth_account, encode_defunct, OWNER_PRIVATE_KEY, f"update_order:agent-1:{ts}")
    assert verify_order_signature("create_order", "agent-1", ts, sig, OWNER_ADDRESS) is False


def test_verify_order_signature_wrong_resource_id(eth_account, encode_defunct):
    from src.api.utils import verify_order_signature
    ts = int(time.time())
    sig = _make_sig(eth_account, encode_defunct, OWNER_PRIVATE_KEY, f"create_order:agent-1:{ts}")
    assert verify_order_signature("create_order", "agent-999", ts, sig, OWNER_ADDRESS) is False


def test_verify_order_signature_no_eth_account(monkeypatch):
    import src.api.utils as utils_module
    monkeypatch.setattr(utils_module, "HAS_ETH_ACCOUNT", False)
    from src.api.utils import verify_order_signature
    assert verify_order_signature("create_order", "agent-1", int(time.time()), "0xdeadbeef", OWNER_ADDRESS) is False


# --- scheme dispatch ---

def test_verify_order_signature_accepts_identity_object(eth_account, encode_defunct):
    """Calling with an Identity(scheme='eip191', identifier=...) works the
    same as passing a raw address — the back-compat path coerces strings
    to ``Identity(scheme='eip191', identifier=...)``."""
    from src.api.utils import Identity, verify_order_signature

    ts = int(time.time())
    sig = _make_sig(eth_account, encode_defunct, OWNER_PRIVATE_KEY, f"create_order:agent-1:{ts}")
    identity = Identity(scheme="eip191", identifier=OWNER_ADDRESS)
    assert verify_order_signature("create_order", "agent-1", ts, sig, identity) is True


def test_verify_with_unknown_scheme_returns_false(eth_account, encode_defunct):
    """Unknown scheme dispatched to the registry returns False (not an exception)."""
    from src.api.utils import Identity, verify_order_signature

    ts = int(time.time())
    sig = _make_sig(eth_account, encode_defunct, OWNER_PRIVATE_KEY, f"create_order:agent-1:{ts}")
    identity = Identity(scheme="not-a-real-scheme", identifier=OWNER_ADDRESS)
    assert verify_order_signature("create_order", "agent-1", ts, sig, identity) is False


def test_identity_lowercases_eip191_identifier():
    """The registry Identity matches shared market_identity normalization."""
    from src.api.utils import Identity

    ident = Identity(scheme="eip191", identifier="0xABCDEF0000000000000000000000000000000001")
    assert ident.identifier == "0xabcdef0000000000000000000000000000000001"


def test_identity_preserves_non_eip191_case():
    from src.api.utils import Identity

    ident = Identity(scheme="did-key", identifier="did:key:zMixedCASE")
    assert ident.identifier == "did:key:zMixedCASE"
