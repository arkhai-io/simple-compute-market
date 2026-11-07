from __future__ import annotations

import base64
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from frp_grant_admission.config import ConfigError, load_config, parse_config, thumbprint
from tests.rfc8032 import TEST_1, TEST_1_THUMBPRINT, TEST_2, TEST_3

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "config.toml"


def issuer(name: str, start: int, end: int, *keys: str, audience: str = "relay-1") -> str:
    key_list = ", ".join(f'{{ public_key = "{key}" }}' for key in keys)
    return (
        f'[[issuers]]\nname = "{name}"\naudience = "{audience}"\n'
        f"ports = {{ start = {start}, end = {end} }}\nkeys = [ {key_list} ]\n"
    )


def config(*issuers: str, listen: str = "127.0.0.1:7300") -> str:
    return f'listen = "{listen}"\n\n' + "\n".join(issuers)


def problems(text: str) -> tuple[str, ...]:
    with pytest.raises(ConfigError) as caught:
        parse_config(text)
    return caught.value.problems


def test_the_example_loads() -> None:
    loaded = load_config(EXAMPLE)

    assert str(loaded.listen) == "127.0.0.1:7300"
    assert [(i.name, i.audience, i.port_start, i.port_end) for i in loaded.issuers] == [
        ("issuer-a", "relay-1", 6100, 6199),
        ("issuer-b", "relay-1", 6200, 6249),
    ]
    assert loaded.issuers[0].kids == (TEST_1_THUMBPRINT,)


def test_the_example_keys_are_rfc8032_test_1_and_test_2() -> None:
    loaded = load_config(EXAMPLE)
    raw = {
        issuer.name: loaded.key(issuer.kids[0]).public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ).hex()
        for issuer in loaded.issuers
    }

    assert raw == {"issuer-a": TEST_1.public_hex, "issuer-b": TEST_2.public_hex}


def test_a_key_id_is_its_rfc7638_thumbprint() -> None:
    assert thumbprint(TEST_1.private_key.public_key()) == TEST_1_THUMBPRINT


def test_both_keys_of_one_issuer_resolve_to_it() -> None:
    loaded = parse_config(config(issuer("a", 6100, 6199, TEST_1.spki_base64, TEST_2.spki_base64)))

    kid_1 = thumbprint(TEST_1.private_key.public_key())
    kid_2 = thumbprint(TEST_2.private_key.public_key())
    assert loaded.key(kid_1).issuer.name == "a"
    assert loaded.key(kid_2).issuer.name == "a"
    assert loaded.issuers[0].kids == (kid_1, kid_2)


def test_an_unknown_key_id_resolves_to_nothing() -> None:
    loaded = parse_config(config(issuer("a", 6100, 6199, TEST_1.spki_base64)))

    assert loaded.key(thumbprint(TEST_2.private_key.public_key())) is None


def test_a_key_listed_twice_in_one_issuer_is_refused() -> None:
    found = problems(config(issuer("a", 6100, 6199, TEST_1.spki_base64, TEST_1.spki_base64)))

    assert found == (f"key {TEST_1_THUMBPRINT} is listed more than once (a, a)",)


def test_a_key_listed_in_two_issuers_is_refused() -> None:
    found = problems(
        config(
            issuer("a", 6100, 6199, TEST_1.spki_base64),
            issuer("b", 6200, 6249, TEST_1.spki_base64),
        )
    )

    assert found == (f"key {TEST_1_THUMBPRINT} is listed more than once (a, b)",)


def test_two_issuers_with_one_name_are_refused() -> None:
    found = problems(
        config(
            issuer("a", 6100, 6199, TEST_1.spki_base64),
            issuer("a", 6200, 6249, TEST_2.spki_base64),
        )
    )

    assert found == ("issuers[1] ('a'): name is also used by issuers[0]",)


def test_overlapping_ranges_are_refused_naming_both_issuers() -> None:
    found = problems(
        config(
            issuer("a", 6100, 6199, TEST_1.spki_base64),
            issuer("b", 6199, 6249, TEST_2.spki_base64),
        )
    )

    assert found == (
        "issuers[0] ('a') and issuers[1] ('b'): port ranges 6100-6199 and 6199-6249 overlap",
    )


def test_adjacent_ranges_load() -> None:
    parse_config(
        config(
            issuer("a", 6100, 6199, TEST_1.spki_base64),
            issuer("b", 6200, 6249, TEST_2.spki_base64),
        )
    )


def test_an_issuer_with_no_keys_is_refused() -> None:
    assert problems(config(issuer("a", 6100, 6199))) == ("issuers[0] ('a'): has no keys",)


@pytest.mark.parametrize(
    ("start", "end"), [(0, 10), (6100, 65536), (6200, 6100), (-1, 5)]
)
def test_a_range_outside_the_port_space_or_reversed_is_refused(start: int, end: int) -> None:
    assert problems(config(issuer("a", start, end, TEST_1.spki_base64))) == (
        f"issuers[0] ('a'): port range {start}-{end} must lie within 1-65535 "
        "and end at or after its start",
    )


def test_a_one_port_range_loads() -> None:
    loaded = parse_config(config(issuer("a", 6100, 6100, TEST_1.spki_base64)))

    assert loaded.issuers[0].covers(6100)
    assert not loaded.issuers[0].covers(6101)


@pytest.mark.parametrize(
    "public_key",
    [
        "not base64!",
        "MCowBQYDK2VwAyEA11qYAYKxCrfVS/7TyWQHOg7hcvPapiMlrwIaaPcHURo",  # unpadded
        TEST_1.public_hex,  # raw hex, not SPKI
        base64.b64encode(bytes.fromhex(TEST_1.public_hex)).decode(),  # raw key, not SPKI
        base64.b64encode(  # SPKI DER with trailing bytes
            base64.b64decode(TEST_1.spki_base64) + b"\x00"
        ).decode(),
        # A P-256 SubjectPublicKeyInfo: valid DER, not Ed25519.
        base64.b64encode(
            ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        ).decode(),
    ],
)
def test_a_key_that_is_not_ed25519_spki_der_base64_is_refused(public_key: str) -> None:
    assert problems(config(issuer("a", 6100, 6199, public_key))) == (
        "issuers[0] ('a') keys[0]: public_key is not the base64 of an Ed25519 "
        "SubjectPublicKeyInfo in DER",
    )


def test_missing_fields_are_refused() -> None:
    found = problems('[[issuers]]\nkeys = [ { } ]\n')

    assert found == (
        "listen: missing",
        "issuers[0]: name missing",
        "issuers[0]: audience missing",
        "issuers[0]: ports missing",
        "issuers[0] keys[0]: public_key missing",
    )


def test_mistyped_fields_are_refused() -> None:
    text = (
        "listen = 7300\n"
        "[[issuers]]\n"
        'name = 5\naudience = ""\n'
        'ports = { start = "6100", end = true }\n'
        f'keys = [ {{ public_key = "{TEST_1.spki_base64}" }} ]\n'
    )

    assert problems(text) == (
        'listen: must be a string such as "127.0.0.1:7300"',
        "issuers[0]: name must be a non-empty string",
        "issuers[0]: audience must be a non-empty string",
        "issuers[0] ports: start must be an integer",
        "issuers[0] ports: end must be an integer",
    )


def test_ports_as_a_list_is_refused() -> None:
    text = (
        'listen = "127.0.0.1:7300"\n[[issuers]]\nname = "a"\naudience = "r"\n'
        "ports = [ { start = 6100, end = 6199 } ]\n"
        f'keys = [ {{ public_key = "{TEST_1.spki_base64}" }} ]\n'
    )

    assert problems(text) == (
        "issuers[0] ('a'): ports must be a table such as { start = 6100, end = 6199 }",
    )


def test_unknown_fields_are_refused() -> None:
    text = "leeway = 60\n" + config(issuer("a", 6100, 6199, TEST_1.spki_base64)) + "range = 1\n"

    assert problems(text) == (
        "the file: unknown field 'leeway'",
        "issuers[0] ('a'): unknown field 'range'",
    )


def test_a_file_with_several_problems_reports_all_of_them() -> None:
    found = problems(
        config(
            issuer("a", 6100, 6199, TEST_1.spki_base64),
            issuer("a", 6150, 6249, TEST_1.spki_base64),
            issuer("c", 7000, 6000, TEST_3.spki_base64),
            issuer("d", 7100, 7199),
            listen="localhost:7300",
        )
    )

    assert found == (
        "listen: 'localhost:7300' is not an IPv4 address in 127.0.0.0/8 or [::1] followed "
        "by a port from 1 to 65535; hostnames are refused",
        "issuers[1] ('a'): name is also used by issuers[0]",
        "issuers[2] ('c'): port range 7000-6000 must lie within 1-65535 and end at or after its start",
        "issuers[3] ('d'): has no keys",
        "issuers[0] ('a') and issuers[1] ('a'): port ranges 6100-6199 and 6150-6249 overlap",
        f"key {TEST_1_THUMBPRINT} is listed more than once (a, a)",
    )


def test_an_overlap_is_reported_beside_its_issuers_other_problems() -> None:
    found = problems(
        config(
            issuer("a", 6100, 6199, TEST_1.spki_base64),
            issuer("b", 6150, 6249, "not base64!"),
        )
    )

    assert found == (
        "issuers[1] ('b') keys[0]: public_key is not the base64 of an Ed25519 "
        "SubjectPublicKeyInfo in DER",
        "issuers[0] ('a') and issuers[1] ('b'): port ranges 6100-6199 and 6150-6249 overlap",
    )


def test_an_overlap_is_reported_for_an_issuer_with_no_name() -> None:
    text = config(issuer("a", 6100, 6199, TEST_1.spki_base64)) + (
        '[[issuers]]\naudience = "relay-1"\nports = { start = 6150, end = 6249 }\n'
        f'keys = [ {{ public_key = "{TEST_2.spki_base64}" }} ]\n'
    )

    assert problems(text) == (
        "issuers[1]: name missing",
        "issuers[0] ('a') and issuers[1]: port ranges 6100-6199 and 6150-6249 overlap",
    )


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ('listen = "127.0.0.1:7300"\n', "issuers: missing"),
        (
            'listen = "127.0.0.1:7300"\nissuers = "issuer-a"\n',
            "issuers: must be an array of tables ([[issuers]])",
        ),
        (
            'listen = "127.0.0.1:7300"\n[[issuers]]\nname = "a"\naudience = "r"\n'
            "ports = { start = 6100, end = 6199 }\n",
            "issuers[0] ('a'): keys missing",
        ),
        (
            'listen = "127.0.0.1:7300"\n[[issuers]]\nname = "a"\naudience = "r"\n'
            f'ports = {{ start = 6100, end = 6199 }}\nkeys = [ "{TEST_1.spki_base64}" ]\n',
            "issuers[0] ('a'): keys must be an array of tables such as "
            '[ { public_key = "..." } ]',
        ),
        (
            'listen = "127.0.0.1:7300"\n[[issuers]]\nname = "a"\naudience = "r"\n'
            f'ports = {{ end = 6199 }}\nkeys = [ {{ public_key = "{TEST_1.spki_base64}" }} ]\n',
            "issuers[0] ('a') ports: start missing",
        ),
        (
            'listen = "127.0.0.1:7300"\n[[issuers]]\nname = "a"\naudience = "r"\n'
            f'ports = {{ start = 6100 }}\nkeys = [ {{ public_key = "{TEST_1.spki_base64}" }} ]\n',
            "issuers[0] ('a') ports: end missing",
        ),
        (
            'listen = "127.0.0.1:7300"\n[[issuers]]\nname = "a"\naudience = "r"\n'
            "ports = { start = 6100, end = 6199 }\nkeys = [ { public_key = 5 } ]\n",
            "issuers[0] ('a') keys[0]: public_key must be a non-empty string",
        ),
    ],
)
def test_each_missing_or_mistyped_structure_is_refused(text: str, problem: str) -> None:
    assert problems(text) == (problem,)


def test_unknown_fields_in_ports_and_keys_are_refused() -> None:
    text = (
        'listen = "127.0.0.1:7300"\n[[issuers]]\nname = "a"\naudience = "r"\n'
        "ports = { start = 6100, end = 6199, step = 1 }\n"
        f'keys = [ {{ public_key = "{TEST_1.spki_base64}", kid = "x" }} ]\n'
    )

    assert problems(text) == (
        "issuers[0] ('a') ports: unknown field 'step'",
        "issuers[0] ('a') keys[0]: unknown field 'kid'",
    )


def test_text_that_is_not_toml_is_refused() -> None:
    (problem,) = problems("listen = \n")

    assert problem.startswith("not valid TOML: ")


def test_a_file_nesting_too_deeply_for_the_parser_is_refused() -> None:
    (problem,) = problems("listen = " + "[" * 5000 + "]" * 5000)

    assert problem.startswith("not loadable: ")


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as caught:
        load_config(tmp_path / "absent.toml")

    (problem,) = caught.value.problems
    assert problem.startswith(f"cannot read {tmp_path / 'absent.toml'}: ")


@pytest.mark.parametrize(
    "listen",
    [
        "0.0.0.0:7300",
        "192.0.2.1:7300",
        "localhost:7300",
        "[::]:7300",
        "127.0.0.1",
        "127.0.0.1:0",
        "127.0.0.1:65536",
        "127.0.0.1:+80",
        "127.1:7300",
        "::1:7300",
        "[::1]",
        "[::2]:7300",
        "[::ffff:127.0.0.1]:7300",
    ],
)
def test_a_listen_address_that_is_not_loopback_is_refused(listen: str) -> None:
    assert problems(config(issuer("a", 6100, 6199, TEST_1.spki_base64), listen=listen)) == (
        f"listen: {listen!r} is not an IPv4 address in 127.0.0.0/8 or [::1] followed "
        "by a port from 1 to 65535; hostnames are refused",
    )


@pytest.mark.parametrize(
    ("listen", "host", "port"),
    [
        ("127.0.0.1:7300", "127.0.0.1", 7300),
        ("127.1.2.3:7300", "127.1.2.3", 7300),
        ("[::1]:7300", "::1", 7300),
    ],
)
def test_a_loopback_listen_address_loads(listen: str, host: str, port: int) -> None:
    loaded = parse_config(config(issuer("a", 6100, 6199, TEST_1.spki_base64), listen=listen))

    assert (loaded.listen.host, loaded.listen.port) == (host, port)
    assert str(loaded.listen) == listen
