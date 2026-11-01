"""The grant-key stage route refuses a malformed body without quoting it.

Level 1, per `docs/development/TESTING.md`: the framework-free route service
over a mocked relay service. The body may carry a private key, so a refusal
locates each problem and never repeats what was sent, a field name included.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from compute_provisioning.relays import GrantKey, RelayRouteService, StagedGrantKeyView
from compute_provisioning.route_errors import ProvisioningRouteError

_KEY = GrantKey.generate().profile_form()


@pytest.mark.parametrize(
    "payload",
    [_KEY, [_KEY], {"private_key": [_KEY]}, {"private_key": 7}, {_KEY: None}],
    ids=["bare", "listed", "listed-field", "number", "key-as-field-name"],
)
def test_a_malformed_body_is_refused_without_its_input(payload):
    relays = MagicMock()

    with pytest.raises(ProvisioningRouteError) as refused:
        RelayRouteService(relays).stage_grant_key("site-a", payload)

    assert refused.value.status_code == 422
    assert _KEY not in repr(refused.value.detail)
    assert refused.value.__cause__ is None
    assert all(problem["loc"][0] == "body" for problem in refused.value.detail)
    relays.stage_grant_key.assert_not_called()


def test_a_well_formed_body_passes_the_key_on():
    relays = MagicMock()
    relays.stage_grant_key.return_value = StagedGrantKeyView(kid="k", public_key="p")

    staged = RelayRouteService(relays).stage_grant_key("site-a", {"private_key": _KEY})

    relays.stage_grant_key.assert_called_once_with("site-a", _KEY)
    assert (staged.kid, staged.public_key) == ("k", "p")


@pytest.mark.parametrize("payload", [None, {}], ids=["no-body", "empty"])
def test_no_key_asks_the_service_to_generate_one(payload):
    relays = MagicMock()
    relays.stage_grant_key.return_value = StagedGrantKeyView(kid="k", public_key="p")

    RelayRouteService(relays).stage_grant_key("site-a", payload)

    relays.stage_grant_key.assert_called_once_with("site-a", None)
