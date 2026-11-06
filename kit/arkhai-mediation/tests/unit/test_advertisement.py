"""Authority policy remains schema data; hosted defaults are not consumer policy."""

from copy import deepcopy

from jsonschema.exceptions import ValidationError
import pytest

from market_arkhai_mediation.contract import validate, vectors


@pytest.mark.parametrize("minimum", [0, 60, 1209600, 9007199254740991])
def test_advertised_window_is_a_nonnegative_safe_integer(minimum):
    description = deepcopy(vectors()["description"])
    description["minimum_dispute_window_seconds"] = minimum
    assert validate("Description", description) == description


@pytest.mark.parametrize("minimum", [-1, 0.5, 9007199254740992, True, "60", None])
def test_malformed_or_unsafe_advertised_window_is_refused(minimum):
    description = deepcopy(vectors()["description"])
    description["minimum_dispute_window_seconds"] = minimum
    with pytest.raises(ValidationError):
        validate("Description", description)


def test_published_default_description_is_unchanged():
    description = vectors()["description"]
    assert description["minimum_dispute_window_seconds"] == 14 * 86400
    assert validate("Description", description) == description
