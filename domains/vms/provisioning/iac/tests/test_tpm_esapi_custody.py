"""Deterministic tests for the same-process TPM custody boundary."""

from __future__ import annotations

import importlib.util
from enum import IntFlag
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


MODULE = (
    Path(__file__).resolve().parents[1]
    / "ansible"
    / "roles"
    / "bare-metal-access"
    / "files"
    / "arkhai_tpm_esapi_custody.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("arkhai_tpm_esapi_custody", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Recorder:
    def __init__(self):
        self.events = []

    def pending(self, kind, purpose):
        record = {"kind": kind, "purpose": purpose, "state": "pending"}
        self.events.append(("pending", kind, purpose))
        return record

    def live(self, record, handle):
        record["state"] = "live"
        self.events.append(("live", record["kind"], handle))

    def close_pending(self, record):
        record["state"] = "close_pending"
        self.events.append(("close_pending", record["kind"]))

    def closed(self, record):
        record["state"] = "confirmed_closed"
        self.events.append(("closed", record["kind"]))


class Backend:
    def __init__(self, fail_at=None):
        self.fail_at = fail_at
        self.calls = []
        self.handles = iter((0x03000001, 0x80000001, 0x03000002))

    def _call(self, name, *args):
        self.calls.append((name, *args))
        if self.fail_at == name:
            raise RuntimeError(name)

    def start_policy(self, trial):
        self._call("start_policy", trial)
        return next(self.handles)

    def handle_identity(self, handle):
        return handle

    def policy_nv(self, session, counter):
        self._call("policy_nv", session, counter)

    def policy_digest(self, session):
        self._call("policy_digest", session)
        return b"P" * 32

    def create_sealed(self, secret, policy):
        self._call("create_sealed", secret, policy)
        return b"private", b"public"

    def load_sealed(self, private, public):
        self._call("load_sealed", private, public)
        return next(self.handles)

    def sealed_public(self, handle):
        self._call("sealed_public", handle)
        return {
            "name": b"\x00\x0b" + b"N" * 32,
            "policy": b"P" * 32,
            "attributes": frozenset(("fixedtpm", "fixedparent")),
            "type": "keyedhash",
        }

    def unseal(self, handle, session):
        self._call("unseal", handle, session)
        return b"S" * 32

    def flush(self, handle):
        self._call(f"flush:{handle:#x}", handle)


class _SessionAttributes(IntFlag):
    CONTINUESESSION = 1


class _NullSymmetric:
    def __init__(self, *, algorithm):
        self.algorithm = algorithm


class _Pytss22:
    ESYS_TR = SimpleNamespace(NONE=0)
    TPM2_SE = SimpleNamespace(TRIAL=3, POLICY=1)
    TPM2_ALG = SimpleNamespace(NULL=16, SHA256=11)
    TPMA_SESSION = _SessionAttributes
    TPMT_SYM_DEF = _NullSymmetric


class _SessionLifecycleEsys:
    def __init__(self, *, attribute_failure=None, flush_failure=None):
        self.attribute_failure = attribute_failure
        self.flush_failure = flush_failure
        self.calls = []
        self.live = False
        self.continued = False

    def tr_from_tpmpublic(self, handle):
        self.calls.append(("tr_from_tpmpublic", handle))
        return handle

    def start_auth_session(
        self, tpm_key, bind, session_type, symmetric, auth_hash
    ):
        if not isinstance(symmetric, _NullSymmetric):
            raise TypeError(
                "expected symmetric to be TPMT_SYM_DEF, "
                f"got {type(symmetric).__name__}"
            )
        self.calls.append(
            (
                "start_auth_session",
                tpm_key,
                bind,
                session_type,
                symmetric.algorithm,
                auth_hash,
            )
        )
        self.live = True
        return 0x03000001

    def trsess_set_attributes(self, handle, attributes, mask):
        self.calls.append(("trsess_set_attributes", handle, attributes, mask))
        if self.attribute_failure is not None:
            raise self.attribute_failure
        self.continued = bool(
            attributes & mask & _SessionAttributes.CONTINUESESSION
        )

    def unseal(self, handle, *, session1):
        self.calls.append(("unseal", handle, session1))
        if not self.continued:
            self.live = False
        return b"S" * 32

    def flush_context(self, handle):
        self.calls.append(("flush_context", handle))
        if self.flush_failure is not None:
            raise self.flush_failure
        if not self.live:
            raise RuntimeError("TPM2_RC_HANDLE: session is no longer loaded")
        self.live = False


def test_policy_session_is_recorded_and_checked_closed_before_digest_returns():
    module = _load_module()
    recorder = Recorder()
    backend = Backend()

    digest = module.EsapiCustodyExecutor(backend).build_policy(10, recorder)

    assert digest == b"P" * 32
    assert recorder.events == [
        ("pending", "session", "build-policy-nv"),
        ("live", "session", 0x03000001),
        ("close_pending", "session"),
        ("closed", "session"),
    ]
    assert backend.calls[-1] == ("flush:0x3000001", 0x03000001)


def test_pytss_22_policy_session_uses_null_symmetric_and_survives_until_flush():
    module = _load_module()
    esys = _SessionLifecycleEsys()
    backend = module.PytssBackend(esys, _Pytss22)
    backend.bind(parent_handle=0x81000020, nv_index=0x01500020)

    session = backend.start_policy(False)
    assert backend.unseal(0x80000001, session) == b"S" * 32
    backend.flush(session)

    assert esys.calls == [
        ("tr_from_tpmpublic", 0x81000020),
        ("tr_from_tpmpublic", 0x01500020),
        ("start_auth_session", 0, 0, 1, 16, 11),
        (
            "trsess_set_attributes",
            0x03000001,
            _SessionAttributes.CONTINUESESSION,
            _SessionAttributes.CONTINUESESSION,
        ),
        ("unseal", 0x80000001, 0x03000001),
        ("flush_context", 0x03000001),
    ]


def test_session_attribute_failure_does_not_swallow_checked_flush_failure():
    module = _load_module()
    invalid_handle = RuntimeError("TPM2_RC_HANDLE")
    esys = _SessionLifecycleEsys(
        attribute_failure=RuntimeError("attribute failure"),
        flush_failure=invalid_handle,
    )
    backend = module.PytssBackend(esys, _Pytss22)
    backend.bind(parent_handle=0x81000020, nv_index=0x01500020)

    with pytest.raises(module.CustodyUncertain) as failure:
        backend.start_policy(True)

    assert failure.value.__cause__ is invalid_handle
    assert esys.calls[-1] == ("flush_context", 0x03000001)


@pytest.mark.parametrize(
    "failure",
    ["load_sealed", "unseal", "flush:0x80000001", "flush:0x3000001"],
)
def test_recovery_never_returns_secret_when_use_or_any_checked_close_fails(failure):
    module = _load_module()
    recorder = Recorder()
    backend = Backend(fail_at=failure)

    with pytest.raises(module.CustodyUncertain):
        module.EsapiCustodyExecutor(backend).recover_and_verify(
            private_blob=b"private",
            public_blob=b"public",
            expected_policy=b"P" * 32,
            counter=10,
            recorder=recorder,
        )

    assert not any(event[0] == "secret_returned" for event in recorder.events)
    if failure == "load_sealed":
        assert recorder.events == [
            ("pending", "object", "load-sealed-object")
        ]
    elif failure == "flush:0x80000001":
        assert ("close_pending", "session") in recorder.events
        assert ("closed", "session") not in recorder.events
    elif failure == "flush:0x3000001":
        assert ("close_pending", "object") in recorder.events
        assert ("closed", "object") not in recorder.events


def test_recovery_uses_one_live_object_and_policy_session_then_closes_both():
    module = _load_module()
    recorder = Recorder()
    backend = Backend()

    evidence, secret = module.EsapiCustodyExecutor(backend).recover_and_verify(
        private_blob=b"private",
        public_blob=b"public",
        expected_policy=b"P" * 32,
        counter=10,
        recorder=recorder,
    )

    assert evidence.name == b"\x00\x0b" + b"N" * 32
    assert secret == b"S" * 32
    assert backend.calls == [
        ("load_sealed", b"private", b"public"),
        ("sealed_public", 0x03000001),
        ("start_policy", False),
        ("policy_nv", 0x80000001, 10),
        ("unseal", 0x03000001, 0x80000001),
        ("flush:0x80000001", 0x80000001),
        ("flush:0x3000001", 0x03000001),
    ]
    assert [event[0] for event in recorder.events].count("closed") == 2


def test_production_transport_is_explicit_direct_device_only(monkeypatch):
    module = _load_module()
    calls = []

    class FakePytss:
        class TCTILdr:
            def __init__(self, name, conf):
                calls.append(("tcti", name, conf))

        class ESAPI:
            def __init__(self, tcti):
                calls.append(("esapi", tcti.__class__.__name__))

    monkeypatch.setitem(sys.modules, "tpm2_pytss", FakePytss)
    monkeypatch.setattr("importlib.metadata.version", lambda name: "2.2.1")
    backend = module.PytssBackend.open_device("/dev/tpm0")
    assert backend is not None
    assert calls == [("tcti", "device", "/dev/tpm0"), ("esapi", "TCTILdr")]

    for rejected in ("/dev/tpmrm0", "device:/dev/tpm0", "mssim:host=x", ""):
        with pytest.raises(module.CustodyRefused):
            module.PytssBackend.open_device(rejected)


def test_production_transport_rejects_an_unreviewed_binding_version(monkeypatch):
    module = _load_module()
    monkeypatch.setitem(sys.modules, "tpm2_pytss", SimpleNamespace())
    monkeypatch.setattr("importlib.metadata.version", lambda name: "2.3.0")

    with pytest.raises(module.CustodyRefused, match="2.2.1 is required"):
        module.PytssBackend.open_device("/dev/tpm0")


def test_prior_lifetime_records_are_quarantine_evidence_not_cleanup_authority():
    module = _load_module()

    for state in ("pending", "live", "close_pending", "handle_recorded"):
        with pytest.raises(module.CustodyUncertain):
            module.refuse_incomplete_prior_lifetime(
                [{"kind": "session", "state": state, "handle": "0x03000001"}]
            )


def test_lost_live_handle_record_stays_pending_even_when_same_process_flushes():
    module = _load_module()
    backend = Backend()

    class LostRecord(Recorder):
        def live(self, record, handle):
            del record, handle
            raise OSError("controlled fsync failure")

    recorder = LostRecord()
    with pytest.raises(module.CustodyUncertain):
        module.EsapiCustodyExecutor(backend).build_policy(10, recorder)

    assert recorder.events == [("pending", "session", "build-policy-nv")]
    assert backend.calls == [
        ("start_policy", True),
        ("flush:0x3000001", 0x03000001),
    ]
