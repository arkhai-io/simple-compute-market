from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/enroll_compute_host.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("enroll_compute_host", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_inventory_returns_kvm_host_metadata(tmp_path: Path) -> None:
    module = _load_script_module()
    inventory_path = tmp_path / "hosts"
    inventory_path.write_text(
        "\n".join(
            [
                "[kvm_hosts]",
                "btc1 ansible_host=12.150.85.70 ansible_user=ubuntu gpus=8 ansible_ssh_private_key_file=~/.ssh/id_ed25519",
                "ww1 ansible_host=10.161.42.195 ansible_user=ww_bm gpus=1 ansible_ssh_private_key_file=~/.ssh/id_ed25519",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    hosts = module.parse_kvm_inventory(inventory_path)

    assert hosts["btc1"] == {
        "host_alias": "btc1",
        "ansible_host": "12.150.85.70",
        "ansible_user": "ubuntu",
        "gpus": "8",
    }
    assert hosts["ww1"]["gpus"] == "1"


def test_build_host_commands_covers_repo_validation_and_optional_acceptance(tmp_path: Path) -> None:
    module = _load_script_module()

    commands = module.build_host_commands(
        kvm_host="btc1",
        inventory_path=tmp_path / "inventory/hosts",
        run_acceptance=True,
        vm_name="iac-acceptance-btc1",
        skip_host_kit=False,
        extra_vars_file=tmp_path / "inventory/vars.yaml",
    )

    assert commands == [
        ["make", "validate-inventory"],
        ["make", "validate-playbooks"],
        ["make", "validate-tests"],
        [
            "./scripts/run_acceptance_validation.sh",
            "--kvm-host",
            "btc1",
            "--inventory",
            str(tmp_path / "inventory/hosts"),
            "--vm-name",
            "iac-acceptance-btc1",
            "--extra-vars-file",
            str(tmp_path / "inventory/vars.yaml"),
        ],
    ]


def test_build_host_artifact_uses_shared_role_contract() -> None:
    module = _load_script_module()

    artifact = module.build_host_artifact(
        action="check-ready",
        status="succeeded",
        request_url="ansible://btc1",
        auth_url="ansible://btc1",
        host_alias="btc1",
        details={"ansible_host": "12.150.85.70", "gpus": "8"},
    )

    assert artifact["role"] == "host"
    assert artifact["action"] == "check-ready"
    assert artifact["status"] == "succeeded"
    assert artifact["details"]["host_alias"] == "btc1"
    assert artifact["details"]["ansible_host"] == "12.150.85.70"
    assert artifact["details"]["gpus"] == "8"
