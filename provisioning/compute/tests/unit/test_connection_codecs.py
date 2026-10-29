"""The host authority's codec registry dispatches a connection by its kind and version."""

from __future__ import annotations

import pytest

from compute_provisioning.hosts import ConnectionCodecs, ConnectionEnvelope, ProtectedValue


class _Codec:
    """A codec for one kind at one version, recording what it was asked to build."""

    def __init__(self, kind: str, version: int) -> None:
        self.kind, self.version = kind, version
        self.built: list[tuple[dict, ConnectionEnvelope | None]] = []

    def build(self, public, secrets, *, previous=None):
        self.built.append((dict(public), previous))
        protected = dict(previous.protected) if previous is not None else {}
        return ConnectionEnvelope(self.kind, self.version, public, protected)

    def validate(self, envelope):
        return envelope


def test_a_connection_is_built_by_the_codec_for_its_own_version() -> None:
    first, second = _Codec("wire", 1), _Codec("wire", 2)
    codecs = ConnectionCodecs([first, second])

    built = codecs.build("wire", 2, {"field": "x"}, {})

    assert (built.kind, built.version) == ("wire", 2)
    assert second.built == [({"field": "x"}, None)]
    assert first.built == []


def test_a_single_version_registration_builds_as_before() -> None:
    only = _Codec("wire", 1)

    built = ConnectionCodecs([only]).build("wire", 1, {}, {})

    assert built.version == 1
    assert ConnectionCodecs([only]).versions("wire") == (1,)


def test_a_version_no_codec_serves_is_refused_naming_those_served() -> None:
    codecs = ConnectionCodecs([_Codec("wire", 2), _Codec("wire", 1)])

    with pytest.raises(ValueError, match=r"not supported at version 3; supported versions: \[1, 2\]"):
        codecs.build("wire", 3, {}, {})


def test_an_unknown_kind_is_refused_naming_the_kinds_served() -> None:
    with pytest.raises(ValueError, match=r"kind 'other' is not supported; supported: \['wire'\]"):
        ConnectionCodecs([_Codec("wire", 1)]).build("other", 1, {}, {})


def test_a_kind_and_version_registered_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="duplicate connection codec for kind 'wire' at version 1"):
        ConnectionCodecs([_Codec("wire", 1), _Codec("wire", 1)])


def test_a_previous_connection_at_another_version_is_handed_to_the_new_versions_codec() -> None:
    second = _Codec("wire", 2)
    previous = ConnectionEnvelope(
        "wire", 1, {}, {"secret": ProtectedValue(scheme="s", ciphertext="c")}
    )

    built = ConnectionCodecs([_Codec("wire", 1), second]).build(
        "wire", 2, {}, {}, previous=previous
    )

    assert second.built[0][1] is previous
    assert built.protected["secret"].scheme == "s"


def test_a_previous_connection_of_another_kind_is_not_handed_on() -> None:
    codec = _Codec("wire", 1)
    previous = ConnectionEnvelope("other", 1, {}, {})

    ConnectionCodecs([codec]).build("wire", 1, {}, {}, previous=previous)

    assert codec.built[0][1] is None


def test_a_kind_served_at_one_version_is_found_without_stating_it() -> None:
    only = _Codec("wire", 1)

    assert ConnectionCodecs([only]).codec("wire") is only


def test_a_kind_served_at_several_versions_needs_the_version_stated() -> None:
    first, second = _Codec("wire", 1), _Codec("wire", 2)
    codecs = ConnectionCodecs([first, second])

    with pytest.raises(ValueError, match=r"served at several versions; state one of \[1, 2\]"):
        codecs.codec("wire")
    assert codecs.codec("wire", 2) is second
    assert codecs.codec("wire", 1) is first


def test_an_unknown_kind_is_refused_whether_or_not_a_version_is_stated() -> None:
    codecs = ConnectionCodecs([_Codec("wire", 1)])

    for version in (None, 1):
        with pytest.raises(ValueError, match="kind 'other' is not supported"):
            codecs.codec("other", version)
