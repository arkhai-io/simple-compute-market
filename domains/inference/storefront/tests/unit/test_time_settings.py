"""The inference storefront's ``[Time] source``."""

from __future__ import annotations

from dynaconf import Dynaconf

from inference_storefront.utils.config import configured_time_source


def test_the_time_source_is_unset_by_default_and_read_in_any_case() -> None:
    assert configured_time_source(Dynaconf(environments=False)) is None
    source = Dynaconf(environments=False)
    source.set("Time", {"SOURCE": "injected"})

    assert configured_time_source(source) == "injected"
