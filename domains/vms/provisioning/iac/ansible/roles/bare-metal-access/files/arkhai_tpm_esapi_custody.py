"""Same-process ESAPI boundary for lease-key custody.

The executor owns only transient handles returned by its live ESAPI context.
Durable numeric handles are evidence for an interrupted attempt, never authority
to flush a resource after process restart.
"""

from __future__ import annotations

import re
from typing import NamedTuple


_DIRECT_DEVICE = re.compile(r"/dev/tpm[0-9]+\Z")
_SEALED_ATTRIBUTES = frozenset(("fixedtpm", "fixedparent"))
_MAX_SEALED_BLOB = 64 * 1024


class CustodyRefused(RuntimeError):
    """The requested transport or TPM metadata is outside the owned boundary."""


class CustodyUncertain(CustodyRefused):
    """A TPM command or durable ownership transition has an uncertain outcome."""


class SealedEvidence(NamedTuple):
    name: bytes
    policy: bytes
    attributes: frozenset[str]
    type: str


def refuse_incomplete_prior_lifetime(records) -> None:
    """Reject old process-lifetime handles without issuing TPM cleanup."""
    for record in records:
        if not isinstance(record, dict) or record.get("state") != "confirmed_closed":
            raise CustodyUncertain(
                "prior ESAPI ownership is incomplete; stale handles cannot be flushed"
            )


class EsapiCustodyExecutor:
    """Own load/use/flush as one checked transaction on one ESAPI context."""

    def __init__(self, backend, *, _checkpoint=None) -> None:
        self._backend = backend
        self._checkpoint = _checkpoint or (lambda _event: None)

    def verify_resources(self, **expected) -> None:
        try:
            self._backend.verify_resources(**expected)
        except CustodyRefused:
            raise
        except BaseException as exc:
            raise CustodyUncertain("TPM resource verification failed") from exc

    def read_counter(self) -> int:
        try:
            return self._backend.read_counter()
        except BaseException as exc:
            raise CustodyUncertain("NV counter read failed") from exc

    def increment_counter(self) -> None:
        try:
            self._backend.increment_counter()
        except BaseException as exc:
            raise CustodyUncertain("NV counter increment outcome is uncertain") from exc

    def close(self) -> None:
        try:
            self._backend.close()
        except BaseException as exc:
            raise CustodyUncertain("ESAPI ownership boundary did not finalize") from exc

    def _close_owned(self, record, handle, recorder) -> BaseException | None:
        try:
            recorder.close_pending(record)
            self._backend.flush(handle)
            self._checkpoint(f"after-flush-{record['kind']}")
            recorder.closed(record)
        except BaseException as exc:
            return exc
        return None

    def _close_unrecorded(self, handle) -> BaseException | None:
        """Best-effort same-process close without converting a pending gap to proof."""
        try:
            self._backend.flush(handle)
        except BaseException as exc:
            return exc
        return None

    def build_policy(self, counter: int, recorder) -> bytes:
        record = recorder.pending("session", "build-policy-nv")
        handle = None
        live_recorded = False
        result = None
        failure = None
        try:
            handle = self._backend.start_policy(True)
            self._checkpoint("after-policy-session-create")
            recorder.live(record, self._backend.handle_identity(handle))
            live_recorded = True
            self._backend.policy_nv(handle, counter)
            result = self._backend.policy_digest(handle)
        except BaseException as exc:
            failure = exc
        if handle is not None:
            close_failure = (
                self._close_owned(record, handle, recorder)
                if live_recorded
                else self._close_unrecorded(handle)
            )
            failure = failure or close_failure
        if failure is not None:
            raise CustodyUncertain("PolicyNV transaction did not close cleanly") from failure
        if not isinstance(result, bytes) or len(result) != 32:
            raise CustodyUncertain("PolicyNV did not return a SHA-256 digest")
        return result

    def create_sealed(self, secret: bytes, policy: bytes) -> tuple[bytes, bytes]:
        if len(secret) != 32 or len(policy) != 32:
            raise CustodyRefused("sealed secret and policy must each be 32 bytes")
        try:
            private_blob, public_blob = self._backend.create_sealed(secret, policy)
        except BaseException as exc:
            raise CustodyUncertain("sealed-object creation outcome is uncertain") from exc
        if not private_blob or not public_blob:
            raise CustodyUncertain("sealed-object creation returned an empty blob")
        return private_blob, public_blob

    def recover_and_verify(
        self,
        *,
        private_blob: bytes,
        public_blob: bytes,
        expected_policy: bytes,
        expected_name: bytes | None = None,
        counter: int,
        recorder,
    ) -> tuple[SealedEvidence, bytes]:
        if (
            len(expected_policy) != 32
            or (expected_name is not None and len(expected_name) != 34)
            or not 0 < len(private_blob) <= _MAX_SEALED_BLOB
            or not 0 < len(public_blob) <= _MAX_SEALED_BLOB
        ):
            raise CustodyRefused("sealed blobs or PolicyNV digest have invalid lengths")
        object_record = recorder.pending("object", "load-sealed-object")
        object_handle = None
        object_live_recorded = False
        session_record = None
        session_handle = None
        session_live_recorded = False
        evidence = None
        secret = None
        failure = None
        try:
            object_handle = self._backend.load_sealed(private_blob, public_blob)
            self._checkpoint("after-object-load")
            recorder.live(
                object_record, self._backend.handle_identity(object_handle)
            )
            object_live_recorded = True
            public = self._backend.sealed_public(object_handle)
            evidence = SealedEvidence(
                name=public["name"],
                policy=public["policy"],
                attributes=frozenset(public["attributes"]),
                type=public["type"],
            )
            if (
                evidence.type != "keyedhash"
                or evidence.attributes != _SEALED_ATTRIBUTES
                or evidence.policy != expected_policy
                or len(evidence.name) != 34
                or evidence.name[:2] != b"\x00\x0b"
            ):
                raise CustodyRefused("sealed object public area does not match custody policy")
            if expected_name is not None and evidence.name != expected_name:
                raise CustodyRefused("sealed object Name does not match prepared evidence")
            session_record = recorder.pending("session", "unseal-policy-nv")
            session_handle = self._backend.start_policy(False)
            self._checkpoint("after-unseal-session-create")
            recorder.live(
                session_record, self._backend.handle_identity(session_handle)
            )
            session_live_recorded = True
            self._backend.policy_nv(session_handle, counter)
            secret = self._backend.unseal(object_handle, session_handle)
            self._checkpoint("after-unseal")
            if not isinstance(secret, bytes) or len(secret) != 32:
                raise CustodyRefused("sealed object did not yield a 32-byte secret")
        except BaseException as exc:
            failure = exc

        if session_handle is not None:
            close_failure = (
                self._close_owned(session_record, session_handle, recorder)
                if session_live_recorded
                else self._close_unrecorded(session_handle)
            )
            failure = failure or close_failure
        if object_handle is not None:
            close_failure = (
                self._close_owned(object_record, object_handle, recorder)
                if object_live_recorded
                else self._close_unrecorded(object_handle)
            )
            failure = failure or close_failure
        if failure is not None:
            raise CustodyUncertain(
                "sealed-object transaction did not complete with checked cleanup"
            ) from failure
        assert evidence is not None and secret is not None
        return evidence, secret


class PytssBackend:
    """Thin tpm2-pytss 2.2.1 adapter; construction selects device TCTI only."""

    def __init__(self, esys, pytss) -> None:
        self._esys = esys
        self._tcti = esys.get_tcti() if hasattr(esys, "get_tcti") else None
        self._tss = pytss
        self._parent = None
        self._nv = None

    @classmethod
    def open_device(cls, device: str):
        if not _DIRECT_DEVICE.fullmatch(device) or device == "/dev/tpmrm0":
            raise CustodyRefused("production custody requires an explicit raw TPM device")
        try:
            import tpm2_pytss as pytss
            from importlib.metadata import version
        except (ImportError, OSError) as exc:
            raise CustodyRefused("tpm2-pytss 2.2.1 runtime is unavailable") from exc
        if version("tpm2-pytss") != "2.2.1":
            raise CustodyRefused("tpm2-pytss 2.2.1 is required")
        tcti = None
        try:
            tcti = pytss.TCTILdr("device", device)
            esys = pytss.ESAPI(tcti)
        except BaseException as exc:
            if tcti is not None:
                try:
                    tcti.close()
                except BaseException:
                    pass
            raise CustodyRefused("explicit TPM device TCTI cannot be opened") from exc
        return cls(esys, pytss)

    @classmethod
    def for_test_transport(cls, tcti, *, pytss):
        """Isolated qualification seam; production callers cannot select a TCTI name."""
        return cls(pytss.ESAPI(tcti), pytss)

    def bind(self, *, parent_handle: int, nv_index: int) -> None:
        if self._parent is not None or self._nv is not None:
            raise CustodyRefused("ESAPI backend is already bound")
        self._parent = self._esys.tr_from_tpmpublic(parent_handle)
        try:
            self._nv = self._esys.tr_from_tpmpublic(nv_index)
        except BaseException:
            self._esys.tr_close(self._parent)
            self._parent = None
            raise

    def close(self) -> None:
        failures = []
        for attribute in ("_nv", "_parent"):
            handle = getattr(self, attribute)
            if handle is None:
                continue
            try:
                self._esys.tr_close(handle)
            except BaseException as exc:
                failures.append(exc)
            setattr(self, attribute, None)
        try:
            self._esys.close()
        except BaseException as exc:
            failures.append(exc)
        if self._tcti is not None:
            try:
                self._tcti.close()
            except BaseException as exc:
                failures.append(exc)
            self._tcti = None
        if failures:
            raise CustodyUncertain("ESAPI local finalization failed") from failures[0]

    def _require_bound(self):
        if self._parent is None or self._nv is None:
            raise CustodyRefused("ESAPI backend is not bound to recorded resources")

    def handle_identity(self, handle) -> int:
        """Return evidence for the live handle, never restart cleanup authority."""
        return int(self._esys.tr_get_tpm_handle(handle))

    def verify_resources(self, *, parent_handle: int, parent_name: bytes, nv_index: int) -> None:
        self._require_bound()
        public, name, _ = self._esys.read_public(self._parent)
        area = public.publicArea
        required = (
            self._tss.TPMA_OBJECT.FIXEDTPM
            | self._tss.TPMA_OBJECT.FIXEDPARENT
            | self._tss.TPMA_OBJECT.RESTRICTED
            | self._tss.TPMA_OBJECT.DECRYPT
        )
        if (
            int(self._esys.tr_get_tpm_handle(self._parent)) != parent_handle
            or bytes(name) != parent_name
            or area.objectAttributes & required != required
            or area.objectAttributes & self._tss.TPMA_OBJECT.SIGN_ENCRYPT
            or area.type not in (self._tss.TPM2_ALG.RSA, self._tss.TPM2_ALG.ECC)
        ):
            raise CustodyRefused("persistent parent does not match its recorded template")
        nv_public, _ = self._esys.nv_read_public(self._nv)
        nv = nv_public.nvPublic
        if (
            int(nv.nvIndex) != nv_index
            or nv.attributes.nt != self._tss.TPM2_NT.COUNTER
            or nv.attributes & self._tss.TPMA_NV.ORDERLY
            or not nv.attributes & self._tss.TPMA_NV.WRITTEN
            or int(nv.dataSize) != 8
        ):
            raise CustodyRefused("reserved NV index is not a written non-orderly counter")

    def read_counter(self) -> int:
        self._require_bound()
        raw = bytes(self._esys.nv_read(self._nv, 8))
        if len(raw) != 8:
            raise CustodyRefused("NV counter read did not return eight bytes")
        return int.from_bytes(raw, "big")

    def increment_counter(self) -> None:
        self._require_bound()
        self._esys.nv_increment(self._nv)

    def start_policy(self, trial: bool):
        self._require_bound()
        handle = self._esys.start_auth_session(
            self._tss.ESYS_TR.NONE,
            self._tss.ESYS_TR.NONE,
            self._tss.TPM2_SE.TRIAL if trial else self._tss.TPM2_SE.POLICY,
            self._tss.TPMT_SYM_DEF(algorithm=self._tss.TPM2_ALG.NULL),
            self._tss.TPM2_ALG.SHA256,
        )
        try:
            self._esys.trsess_set_attributes(
                handle,
                self._tss.TPMA_SESSION.CONTINUESESSION,
                self._tss.TPMA_SESSION.CONTINUESESSION,
            )
        except BaseException as exc:
            try:
                self._esys.flush_context(handle)
            except BaseException as close_exc:
                raise CustodyUncertain(
                    "new policy session could not be configured or closed"
                ) from close_exc
            raise CustodyRefused(
                "new policy session cannot preserve checked-cleanup ownership"
            ) from exc
        return handle

    def policy_nv(self, session, counter: int) -> None:
        self._require_bound()
        self._esys.policy_nv(
            self._nv,
            self._nv,
            session,
            self._tss.TPM2B_OPERAND(counter.to_bytes(8, "big")),
            self._tss.TPM2_EO.EQ,
        )

    def policy_digest(self, session) -> bytes:
        return bytes(self._esys.policy_get_digest(session))

    def create_sealed(self, secret: bytes, policy: bytes) -> tuple[bytes, bytes]:
        self._require_bound()
        sensitive = self._tss.TPM2B_SENSITIVE_CREATE()
        sensitive.sensitive.data = self._tss.TPM2B_SENSITIVE_DATA(secret)
        public = self._tss.TPM2B_PUBLIC.parse(
            "keyedhash",
            objectAttributes=(
                self._tss.TPMA_OBJECT.FIXEDTPM
                | self._tss.TPMA_OBJECT.FIXEDPARENT
            ),
        )
        public.publicArea.authPolicy = self._tss.TPM2B_DIGEST(policy)
        private, created_public, _, _, _ = self._esys.create(
            self._parent, sensitive, public
        )
        return private.marshal(), created_public.marshal()

    def load_sealed(self, private_blob: bytes, public_blob: bytes):
        self._require_bound()
        private, private_end = self._tss.TPM2B_PRIVATE.unmarshal(private_blob)
        public, public_end = self._tss.TPM2B_PUBLIC.unmarshal(public_blob)
        if private_end != len(private_blob) or public_end != len(public_blob):
            raise CustodyRefused("sealed blob contains trailing data")
        return self._esys.load(self._parent, private, public)

    def sealed_public(self, handle) -> dict[str, object]:
        public, name, _ = self._esys.read_public(handle)
        area = public.publicArea
        expected_attributes = (
            self._tss.TPMA_OBJECT.FIXEDTPM
            | self._tss.TPMA_OBJECT.FIXEDPARENT
        )
        attrs = frozenset(
            label
            for flag, label in (
                (self._tss.TPMA_OBJECT.FIXEDTPM, "fixedtpm"),
                (self._tss.TPMA_OBJECT.FIXEDPARENT, "fixedparent"),
                (self._tss.TPMA_OBJECT.USERWITHAUTH, "userwithauth"),
                (self._tss.TPMA_OBJECT.ADMINWITHPOLICY, "adminwithpolicy"),
            )
            if area.objectAttributes & flag
        )
        if int(area.objectAttributes) != int(expected_attributes):
            attrs = attrs | {"unapproved"}
        if bytes(public.get_name()) != bytes(name):
            raise CustodyRefused("sealed object Name does not match its public area")
        return {
            "name": bytes(name),
            "policy": bytes(area.authPolicy),
            "attributes": attrs,
            "type": (
                "keyedhash"
                if area.type == self._tss.TPM2_ALG.KEYEDHASH
                else f"unsupported:{int(area.type):#x}"
            ),
        }

    def unseal(self, handle, session) -> bytes:
        return bytes(self._esys.unseal(handle, session1=session))

    def flush(self, handle) -> None:
        self._esys.flush_context(handle)
