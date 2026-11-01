"""The plugin's configuration: a TOML file of a loopback listen address and issuers.

Each issuer has a name, the audience it signs grants for, one port range, and one or
more Ed25519 public keys. A key's id is derived at load as its RFC 7638 JWK
thumbprint, so ids are unique across independent signers without anyone assigning
them, and the only collision left — one key listed twice — is a real error, since one
key cannot carry two ranges.

Loading collects every problem in the file before refusing it, so an operator fixes
a file in one pass, and `check`, startup, and reload all report the same list.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_LOOPBACK_V4 = ipaddress.IPv4Network("127.0.0.0/8")
_LOOPBACK_V6 = ipaddress.IPv6Address("::1")
_PORT_TEXT = re.compile(r"[0-9]{1,5}")

_TOP_LEVEL_FIELDS = frozenset({"listen", "issuers"})
_ISSUER_FIELDS = frozenset({"name", "audience", "ports", "keys"})
_PORTS_FIELDS = frozenset({"start", "end"})
_KEY_FIELDS = frozenset({"public_key"})


class ConfigError(Exception):
    """A configuration that does not load, carrying every problem found in it."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class ListenAddress:
    """A loopback address and port; `host` is an IPv4 address or `::1`."""

    host: str
    port: int

    def __str__(self) -> str:
        if ":" in self.host:
            return f"[{self.host}]:{self.port}"
        return f"{self.host}:{self.port}"


@dataclass(frozen=True)
class Issuer:
    """A signer of grants: its audience, its port range, and its keys' ids."""

    name: str
    audience: str
    port_start: int
    port_end: int
    kids: tuple[str, ...]

    def covers(self, port: int) -> bool:
        return self.port_start <= port <= self.port_end


@dataclass(frozen=True)
class Key:
    """A configured public key, its thumbprint id, and the issuer it belongs to."""

    kid: str
    public_key: Ed25519PublicKey
    issuer: Issuer


@dataclass(frozen=True)
class Config:
    """A loaded configuration. Immutable: a reload builds a new one and swaps it in."""

    listen: ListenAddress
    issuers: tuple[Issuer, ...]
    keys: Mapping[str, Key]

    def key(self, kid: str) -> Key | None:
        return self.keys.get(kid)


def thumbprint(public_key: Ed25519PublicKey) -> str:
    """The key's RFC 7638 JWK thumbprint (RFC 8037's OKP form), base64url, unpadded."""
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    members = {"crv": "Ed25519", "kty": "OKP", "x": _b64url(raw)}
    canonical = json.dumps(members, separators=(",", ":"), sort_keys=True).encode("ascii")
    return _b64url(hashlib.sha256(canonical).digest())


def load_config(path: str | Path) -> Config:
    """Read and validate a configuration file, raising `ConfigError` with every problem."""
    try:
        text = Path(path).read_bytes().decode("utf-8")
    except OSError as exc:
        raise ConfigError([f"cannot read {path}: {exc.strerror or exc}"]) from None
    except UnicodeDecodeError:
        raise ConfigError([f"{path} is not UTF-8"]) from None
    return parse_config(text)


def parse_config(text: str) -> Config:
    """Validate configuration text, raising `ConfigError` with every problem."""
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError([f"not valid TOML: {exc}"]) from None
    except RecursionError:
        raise ConfigError(["not loadable: its tables or arrays nest too deeply"]) from None
    return _Loader().load(document)


class _Loader:
    def __init__(self) -> None:
        self.problems: list[str] = []

    def load(self, document: dict[str, Any]) -> Config:
        self._unknown_fields(document, _TOP_LEVEL_FIELDS, "the file")
        listen = self._listen(document)
        issuers, keys = self._issuers(document)
        if self.problems or listen is None:
            raise ConfigError(self.problems)
        return Config(listen=listen, issuers=tuple(issuers), keys=MappingProxyType(keys))

    def _listen(self, document: dict[str, Any]) -> ListenAddress | None:
        if "listen" not in document:
            self.problems.append("listen: missing")
            return None
        value = document["listen"]
        if not isinstance(value, str):
            self.problems.append("listen: must be a string such as \"127.0.0.1:7300\"")
            return None
        address = parse_listen(value)
        if address is None:
            self.problems.append(
                f"listen: {value!r} is not an IPv4 address in 127.0.0.0/8 or [::1] "
                "followed by a port from 1 to 65535; hostnames are refused"
            )
        return address

    def _issuers(self, document: dict[str, Any]) -> tuple[list[Issuer], dict[str, Key]]:
        if "issuers" not in document:
            self.problems.append("issuers: missing")
            return [], {}
        entries = document["issuers"]
        if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
            self.problems.append("issuers: must be an array of tables ([[issuers]])")
            return [], {}

        issuers: list[Issuer] = []
        placed: list[tuple[str, int, int]] = []
        listed: dict[str, list[tuple[str, Ed25519PublicKey]]] = {}
        names: dict[str, int] = {}
        for index, entry in enumerate(entries):
            where = f"issuers[{index}]"
            name = self._text(entry, "name", where)
            if name is not None:
                where = f"issuers[{index}] ({name!r})"
                if name in names:
                    self.problems.append(
                        f"{where}: name is also used by issuers[{names[name]}]"
                    )
                else:
                    names[name] = index
            self._unknown_fields(entry, _ISSUER_FIELDS, where)
            audience = self._text(entry, "audience", where)
            ports = self._ports(entry, where)
            kids = self._keys(entry, where, name, listed)
            # A valid range is checked for overlap even when another field of its
            # issuer is wrong, so fixing that field never reveals a new problem.
            if ports is not None:
                placed.append((where, ports[0], ports[1]))
            if name is None or audience is None or ports is None or kids is None:
                continue
            issuers.append(Issuer(name, audience, ports[0], ports[1], tuple(kids)))

        for first in range(len(placed)):
            for second in range(first + 1, len(placed)):
                a, b = placed[first], placed[second]
                if a[1] <= b[2] and b[1] <= a[2]:
                    self.problems.append(
                        f"{a[0]} and {b[0]}: port ranges {a[1]}-{a[2]} and {b[1]}-{b[2]} overlap"
                    )

        for kid, holders in listed.items():
            if len(holders) > 1:
                where = ", ".join(holder for holder, _ in holders)
                self.problems.append(f"key {kid} is listed more than once ({where})")

        by_name = {issuer.name: issuer for issuer in issuers}
        keys: dict[str, Key] = {}
        for kid, holders in listed.items():
            holder_name, public_key = holders[0]
            if holder_name in by_name:
                keys[kid] = Key(kid, public_key, by_name[holder_name])
        return issuers, keys

    def _ports(self, entry: dict[str, Any], where: str) -> tuple[int, int] | None:
        if "ports" not in entry:
            self.problems.append(f"{where}: ports missing")
            return None
        ports = entry["ports"]
        if not isinstance(ports, dict):
            self.problems.append(f"{where}: ports must be a table such as {{ start = 6100, end = 6199 }}")
            return None
        self._unknown_fields(ports, _PORTS_FIELDS, f"{where} ports")
        start = self._integer(ports, "start", f"{where} ports")
        end = self._integer(ports, "end", f"{where} ports")
        if start is None or end is None:
            return None
        if not (1 <= start <= 65535 and 1 <= end <= 65535) or end < start:
            self.problems.append(
                f"{where}: port range {start}-{end} must lie within 1-65535 and end at or after its start"
            )
            return None
        return start, end

    def _keys(
        self,
        entry: dict[str, Any],
        where: str,
        name: str | None,
        listed: dict[str, list[tuple[str, Ed25519PublicKey]]],
    ) -> list[str] | None:
        if "keys" not in entry:
            self.problems.append(f"{where}: keys missing")
            return None
        values = entry["keys"]
        if not isinstance(values, list) or not all(isinstance(v, dict) for v in values):
            self.problems.append(f"{where}: keys must be an array of tables such as [ {{ public_key = \"...\" }} ]")
            return None
        if not values:
            self.problems.append(f"{where}: has no keys")
            return None
        kids: list[str] = []
        valid = True
        for position, value in enumerate(values):
            key_where = f"{where} keys[{position}]"
            self._unknown_fields(value, _KEY_FIELDS, key_where)
            encoded = self._text(value, "public_key", key_where)
            if encoded is None:
                valid = False
                continue
            public_key = parse_public_key(encoded)
            if public_key is None:
                self.problems.append(
                    f"{key_where}: public_key is not the base64 of an Ed25519 "
                    "SubjectPublicKeyInfo in DER"
                )
                valid = False
                continue
            kid = thumbprint(public_key)
            if kid not in kids:
                kids.append(kid)
            listed.setdefault(kid, []).append((name if name is not None else where, public_key))
        return kids if valid else None

    def _text(self, table: dict[str, Any], field: str, where: str) -> str | None:
        if field not in table:
            self.problems.append(f"{where}: {field} missing")
            return None
        value = table[field]
        if not isinstance(value, str) or not value:
            self.problems.append(f"{where}: {field} must be a non-empty string")
            return None
        return value

    def _integer(self, table: dict[str, Any], field: str, where: str) -> int | None:
        if field not in table:
            self.problems.append(f"{where}: {field} missing")
            return None
        value = table[field]
        if not isinstance(value, int) or isinstance(value, bool):
            self.problems.append(f"{where}: {field} must be an integer")
            return None
        return value

    def _unknown_fields(self, table: dict[str, Any], known: frozenset[str], where: str) -> None:
        for field in sorted(set(table) - known):
            self.problems.append(f"{where}: unknown field {field!r}")


def parse_listen(value: str) -> ListenAddress | None:
    """A loopback `host:port`, or None. Decided from the text alone, never by a resolver."""
    if value.startswith("["):
        host_text, separator, port_text = value[1:].partition("]:")
        if not separator:
            return None
        try:
            host = ipaddress.IPv6Address(host_text)
        except ValueError:
            return None
        if host != _LOOPBACK_V6:
            return None
    else:
        host_text, separator, port_text = value.rpartition(":")
        if not separator:
            return None
        try:
            host = ipaddress.IPv4Address(host_text)
        except ValueError:
            return None
        if host not in _LOOPBACK_V4:
            return None
    if not _PORT_TEXT.fullmatch(port_text):
        return None
    port = int(port_text)
    if not 1 <= port <= 65535:
        return None
    return ListenAddress(str(host), port)


def parse_public_key(encoded: str) -> Ed25519PublicKey | None:
    """The Ed25519 key a single-line standard base64 SPKI DER encodes, or None."""
    try:
        der = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None
    try:
        public_key = serialization.load_der_public_key(der)
    except (ValueError, TypeError):
        return None
    if not isinstance(public_key, Ed25519PublicKey):
        return None
    canonical = public_key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    if canonical != der:
        return None
    return public_key


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")
