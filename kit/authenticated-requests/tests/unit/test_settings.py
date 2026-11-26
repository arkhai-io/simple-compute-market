from __future__ import annotations

import pytest
from pydantic import ValidationError

from market_authenticated_requests import AuthenticatedRequestsSettings


def test_the_retention_and_the_sweep_interval_default_to_a_day_when_absent() -> None:
    settings = AuthenticatedRequestsSettings()

    assert settings.recorded_outcome_retention_seconds == 86_400
    assert settings.replay_prune_interval_seconds == 86_400


def test_each_setting_takes_a_positive_integer() -> None:
    settings = AuthenticatedRequestsSettings.model_validate(
        {"recorded_outcome_retention_seconds": 3_600, "replay_prune_interval_seconds": 600}
    )

    assert (settings.recorded_outcome_retention_seconds, settings.replay_prune_interval_seconds) == (3_600, 600)


@pytest.mark.parametrize("field", ["recorded_outcome_retention_seconds", "replay_prune_interval_seconds"])
@pytest.mark.parametrize("value", [0, -1, 1.5, True, "86400"])
def test_anything_but_a_positive_integer_is_refused(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match=field):
        AuthenticatedRequestsSettings.model_validate({field: value})


def test_an_unknown_setting_is_refused() -> None:
    with pytest.raises(ValidationError, match="replay_retention"):
        AuthenticatedRequestsSettings.model_validate({"replay_retention": 1})
