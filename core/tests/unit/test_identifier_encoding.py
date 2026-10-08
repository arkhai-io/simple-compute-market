"""The length-prefixed identifier encoding keeps component boundaries exact."""

from __future__ import annotations

from market_core.identifier_encoding import length_prefixed, length_prefixed_join


def test_encodes_length_then_value():
    assert length_prefixed("pool-a") == "6:pool-a"
    assert length_prefixed("") == "0:"


def test_delimiter_bearing_components_do_not_collide():
    assert length_prefixed_join("a", "b:c") != length_prefixed_join("a:b", "c")
    assert length_prefixed_join("a", "b:c") == "1:a:3:b:c"


def test_multibyte_components_are_counted_in_characters():
    # Stored keys were written with str length; the encoding must not change unit.
    assert length_prefixed("é") == "1:é"
