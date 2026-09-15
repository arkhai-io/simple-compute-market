"""A disposable loopback SSH endpoint for host-key decisions.

Shared by every test that needs a peer a real OpenSSH client will talk to.
Only what a host-key decision needs is implemented: version exchange, a real
curve25519 key exchange signed by the current Ed25519 host key, and — once a
client has accepted that key — enough of the encrypted stream to refuse its
authentication attempts. No authentication ever succeeds and no session is ever
opened, so a client reaching the endpoint cannot obtain anything.

The listening socket is bound to loopback before any client exists and is never
rebound, so "the same endpoint" needs no port bookkeeping and no readiness poll
that could observe some other listener. ``close()`` is unconditional: it shuts
down any connection still in flight, stops the accept loop and requires the
thread to have terminated, so no test can leave a live peer behind.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import socket
import struct
import threading

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

LOOPBACK = "127.0.0.1"

SOCKET_TIMEOUT = 20.0
SETTLE_TIMEOUT = 10.0
ACCEPT_POLL = 0.25
MAX_PACKET = 65536
MAX_AUTH_MESSAGES = 12

SERVER_VERSION = b"SSH-2.0-ArkhaiTrustFixture"

MSG_DISCONNECT = 1
MSG_IGNORE = 2
MSG_DEBUG = 4
MSG_SERVICE_REQUEST = 5
MSG_SERVICE_ACCEPT = 6
MSG_KEXINIT = 20
MSG_NEWKEYS = 21
MSG_KEX_ECDH_INIT = 30
MSG_KEX_ECDH_REPLY = 31
MSG_USERAUTH_REQUEST = 50
MSG_USERAUTH_FAILURE = 51


# --- SSH wire encoding ----------------------------------------------------


def _string(value: bytes) -> bytes:
    return struct.pack(">I", len(value)) + value


def _mpint(value: int) -> bytes:
    if value == 0:
        return struct.pack(">I", 0)
    # A leading zero byte where the high bit is set: an SSH mpint is signed.
    return _string(value.to_bytes(value.bit_length() // 8 + 1, "big"))


def _read_string(payload: bytes, offset: int) -> tuple[bytes, int]:
    (length,) = struct.unpack(">I", payload[offset : offset + 4])
    start = offset + 4
    return payload[start : start + length], start + length


def _public_blob(key: ed25519.Ed25519PrivateKey) -> bytes:
    raw = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return _string(b"ssh-ed25519") + _string(raw)


def known_hosts_line(port: int, key: ed25519.Ed25519PrivateKey) -> str:
    """The pin entry OpenSSH looks up for this endpoint."""
    authorized = key.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    )
    # OpenSSH records a non-default port as [host]:port.
    return f"[{LOOPBACK}]:{port} {authorized.decode()}\n"


def _derive(shared: bytes, exchange_hash: bytes, letter: bytes, length: int) -> bytes:
    key = hashlib.sha256(shared + exchange_hash + letter + exchange_hash).digest()
    while len(key) < length:
        key += hashlib.sha256(shared + exchange_hash + key).digest()
    return key[:length]


class _PeerGone(Exception):
    """The client closed the connection — its decision, not a fixture fault."""


class _Session:
    """One connection: key exchange, then a refusal if the key was accepted.

    Reads and writes SSH binary packets, unencrypted before ``NEWKEYS`` and
    aes128-ctr + hmac-sha2-256-etm after it. Encryption exists only so the
    client reaches the authentication stage and prints the denial the positive
    control asserts on; no key material here protects anything.
    """

    def __init__(
        self,
        sock: socket.socket,
        host_key: ed25519.Ed25519PrivateKey,
        transcript: list[str],
    ) -> None:
        self._sock = sock
        self._host_key = host_key
        self._transcript = transcript
        self._buffer = b""
        self._in_seq = 0
        self._out_seq = 0
        self._in_cipher = None
        self._out_cipher = None
        self._in_mac_key = b""
        self._out_mac_key = b""

    # framing ------------------------------------------------------------

    def _recv_exact(self, count: int) -> bytes:
        while len(self._buffer) < count:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise _PeerGone("client_closed")
            self._buffer += chunk
        taken, self._buffer = self._buffer[:count], self._buffer[count:]
        return taken

    def _read_version(self) -> bytes:
        line = b""
        while not line.endswith(b"\n"):
            line += self._recv_exact(1)
            if len(line) > 4096:
                raise ValueError("client version line is implausibly long")
        return line.rstrip(b"\r\n")

    def _send_packet(self, payload: bytes) -> None:
        if self._out_cipher is None:
            pad = 8 - ((5 + len(payload)) % 8)
            if pad < 4:
                pad += 8
            body = bytes([pad]) + payload + os.urandom(pad)
            self._sock.sendall(struct.pack(">I", len(body)) + body)
        else:
            # Encrypt-then-MAC: the length field stays in the clear and the
            # padding covers only what is encrypted.
            pad = 16 - ((1 + len(payload)) % 16)
            if pad < 4:
                pad += 16
            encrypted = self._out_cipher.update(
                bytes([pad]) + payload + os.urandom(pad)
            )
            header = struct.pack(">I", len(encrypted))
            tag = hmac.new(
                self._out_mac_key,
                struct.pack(">I", self._out_seq) + header + encrypted,
                hashlib.sha256,
            ).digest()
            self._sock.sendall(header + encrypted + tag)
        self._out_seq = (self._out_seq + 1) & 0xFFFFFFFF

    def _read_packet(self) -> bytes:
        header = self._recv_exact(4)
        (length,) = struct.unpack(">I", header)
        if not 8 <= length <= MAX_PACKET:
            raise ValueError(f"implausible packet length {length}")
        if self._in_cipher is None:
            body = self._recv_exact(length)
        else:
            encrypted = self._recv_exact(length)
            tag = self._recv_exact(32)
            expected = hmac.new(
                self._in_mac_key,
                struct.pack(">I", self._in_seq) + header + encrypted,
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(tag, expected):
                raise ValueError("client packet failed its MAC")
            body = self._in_cipher.update(encrypted)
        self._in_seq = (self._in_seq + 1) & 0xFFFFFFFF
        pad = body[0]
        return body[1 : len(body) - pad]

    def _read_interesting_packet(self) -> bytes:
        while True:
            payload = self._read_packet()
            if payload and payload[0] not in (MSG_IGNORE, MSG_DEBUG):
                return payload

    # protocol -----------------------------------------------------------

    @staticmethod
    def _kexinit() -> bytes:
        name_lists = (
            "curve25519-sha256",
            "ssh-ed25519",
            "aes128-ctr",
            "aes128-ctr",
            "hmac-sha2-256-etm@openssh.com",
            "hmac-sha2-256-etm@openssh.com",
            "none",
            "none",
            "",
            "",
        )
        return b"".join(
            (
                bytes([MSG_KEXINIT]),
                secrets.token_bytes(16),
                *(_string(item.encode()) for item in name_lists),
                b"\x00",
                struct.pack(">I", 0),
            )
        )

    def run(self) -> None:
        self._sock.sendall(SERVER_VERSION + b"\r\n")
        client_version = self._read_version()
        self._transcript.append("version_exchange")

        server_kexinit = self._kexinit()
        self._send_packet(server_kexinit)
        client_kexinit = self._read_interesting_packet()
        if client_kexinit[0] != MSG_KEXINIT:
            raise ValueError(f"expected KEXINIT, got message {client_kexinit[0]}")
        self._transcript.append("client_kexinit")

        ecdh_init = self._read_interesting_packet()
        if ecdh_init[0] != MSG_KEX_ECDH_INIT:
            raise ValueError(f"expected KEX_ECDH_INIT, got message {ecdh_init[0]}")
        self._transcript.append("kex_ecdh_init")

        client_public, _ = _read_string(ecdh_init, 1)
        ephemeral = x25519.X25519PrivateKey.generate()
        server_public = ephemeral.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        shared = ephemeral.exchange(
            x25519.X25519PublicKey.from_public_bytes(client_public)
        )
        shared_mpint = _mpint(int.from_bytes(shared, "big"))
        host_key_blob = _public_blob(self._host_key)
        exchange_hash = hashlib.sha256(
            b"".join(
                (
                    _string(client_version),
                    _string(SERVER_VERSION),
                    _string(client_kexinit),
                    _string(server_kexinit),
                    _string(host_key_blob),
                    _string(client_public),
                    _string(server_public),
                    shared_mpint,
                )
            )
        ).digest()
        signature = _string(b"ssh-ed25519") + _string(
            self._host_key.sign(exchange_hash)
        )
        self._send_packet(
            bytes([MSG_KEX_ECDH_REPLY])
            + _string(host_key_blob)
            + _string(server_public)
            + _string(signature)
        )
        self._transcript.append("host_key_offered")
        self._send_packet(bytes([MSG_NEWKEYS]))

        # The client sends NEWKEYS only after it has verified the host key
        # signature and accepted the key against its known_hosts. Anything else
        # here means the key was refused.
        reply = self._read_interesting_packet()
        if reply[0] != MSG_NEWKEYS:
            self._transcript.append(f"client_message_{reply[0]}_instead_of_newkeys")
            return
        self._transcript.append("client_accepted_host_key")
        self._enable_encryption(shared_mpint, exchange_hash)
        self._refuse_authentication()

    def _enable_encryption(self, shared_mpint: bytes, exchange_hash: bytes) -> None:
        self._in_cipher = Cipher(
            algorithms.AES(_derive(shared_mpint, exchange_hash, b"C", 16)),
            modes.CTR(_derive(shared_mpint, exchange_hash, b"A", 16)),
        ).decryptor()
        self._out_cipher = Cipher(
            algorithms.AES(_derive(shared_mpint, exchange_hash, b"D", 16)),
            modes.CTR(_derive(shared_mpint, exchange_hash, b"B", 16)),
        ).encryptor()
        self._in_mac_key = _derive(shared_mpint, exchange_hash, b"E", 32)
        self._out_mac_key = _derive(shared_mpint, exchange_hash, b"F", 32)

    def _refuse_authentication(self) -> None:
        for _ in range(MAX_AUTH_MESSAGES):
            payload = self._read_interesting_packet()
            message = payload[0]
            if message == MSG_SERVICE_REQUEST:
                service, _ = _read_string(payload, 1)
                self._transcript.append(f"service_request:{service.decode()}")
                self._send_packet(bytes([MSG_SERVICE_ACCEPT]) + _string(service))
            elif message == MSG_USERAUTH_REQUEST:
                self._transcript.append("userauth_request")
                self._send_packet(
                    bytes([MSG_USERAUTH_FAILURE]) + _string(b"publickey") + b"\x00"
                )
            elif message == MSG_DISCONNECT:
                self._transcript.append("client_disconnect")
                return
            else:
                self._transcript.append(f"client_message_{message}")
        raise ValueError("client kept authenticating past the fixture bound")


class Endpoint:
    """A loopback SSH endpoint whose host key can change under a fixed address.

    Faults inside the fixture are collected in ``errors`` rather than discarded;
    a client that walks away is recorded in the transcript instead.
    """

    def __init__(self, host_key: ed25519.Ed25519PrivateKey) -> None:
        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind((LOOPBACK, 0))
        self._listener.listen(8)
        self._listener.settimeout(ACCEPT_POLL)
        self.port: int = self._listener.getsockname()[1]
        self.host_key = host_key
        self.transcripts: list[list[str]] = []
        self.errors: list[str] = []
        self._lock = threading.Lock()
        self._idle = threading.Condition()
        self._accepted = 0
        self._completed = 0
        # Every connection still open, so close() can end one mid-exchange
        # instead of waiting out a socket timeout.
        self._live: set[socket.socket] = set()
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def use_host_key(self, host_key: ed25519.Ed25519PrivateKey) -> None:
        with self._lock:
            self.host_key = host_key

    def settle(self) -> None:
        """Wait until every connection accepted so far has been handled."""
        with self._idle:
            settled = self._idle.wait_for(
                lambda: self._completed == self._accepted, timeout=SETTLE_TIMEOUT
            )
        if not settled:
            raise AssertionError(
                f"endpoint still handling a connection after {SETTLE_TIMEOUT}s; "
                f"transcripts={self.transcripts} errors={self.errors}"
            )

    def close(self) -> None:
        """Stop accepting, end connections in flight, and require the thread to end."""
        self._stopping.set()
        self._listener.close()
        with self._lock:
            live = list(self._live)
        for connection in live:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                connection.close()
            except OSError:
                pass
        self._thread.join(timeout=SETTLE_TIMEOUT)
        assert not self._thread.is_alive(), (
            f"endpoint thread still running after {SETTLE_TIMEOUT}s; "
            f"transcripts={self.transcripts} errors={self.errors}"
        )

    def _serve(self) -> None:
        while not self._stopping.is_set():
            try:
                connection, _ = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self._idle:
                self._accepted += 1
            with self._lock:
                host_key = self.host_key
                self._live.add(connection)
            transcript: list[str] = []
            self.transcripts.append(transcript)
            try:
                with connection:
                    connection.settimeout(SOCKET_TIMEOUT)
                    _Session(connection, host_key, transcript).run()
            except _PeerGone as gone:
                transcript.append(str(gone))
            except OSError as closed:
                # close() ended this connection; not a fixture fault.
                transcript.append(f"connection_closed:{closed.__class__.__name__}")
            except Exception as failure:  # a fixture fault, never the client's
                transcript.append("fixture_error")
                self.errors.append(f"{type(failure).__name__}: {failure}")
            finally:
                with self._lock:
                    self._live.discard(connection)
                with self._idle:
                    self._completed += 1
                    self._idle.notify_all()
