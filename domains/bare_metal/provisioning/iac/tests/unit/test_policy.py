import copy
import json

import pytest

from tenant_working_data import Refusal, json_load, policy_value


@pytest.mark.parametrize("key,value", [("version", 2), ("version", True), ("uid_min", 0), ("uid_max", 2**32), ("uid_min", True), ("policy_id", ""), ("mount_ids", []), ("mount_ids", [True]), ("state_dir", "/"), ("scratch_roots", ["//tmp"]), ("scratch_roots", ["//root"]), ("state_dir", "//"), ("home_parent", "/root/homes"), ("home_parent", "/tmp/../home"), ("scratch_roots", ["/var/log/data"]), ("scratch_roots", ["/var"]), ("scratch_roots", ["/home"]), ("scratch_roots", "oops"), ("exclude_ids", ["41000"])])
def test_rejects_unsafe_policy(policy_fixture, key, value):
    policy = copy.deepcopy(policy_fixture)
    policy[key] = value
    with pytest.raises(Refusal):
        policy_value(policy)


def test_rejects_overlapping_and_unknown_policy(policy_fixture):
    policy = copy.deepcopy(policy_fixture)
    policy["scratch_roots"] = [policy["home_parent"] + "/child"]
    with pytest.raises(Refusal):
        policy_value(policy)
    policy = copy.deepcopy(policy_fixture)
    policy["extra"] = 1
    with pytest.raises(Refusal):
        policy_value(policy)
    with pytest.raises(Refusal):
        json_load('{"version":1,"version":1}')



def test_supported_explicit_roots(policy_fixture):
    policy_fixture["state_dir"] = "/var/lib/fixture-working-state"
    assert policy_value(policy_fixture) == policy_fixture
