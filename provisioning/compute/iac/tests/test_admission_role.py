"""Installer structure and native configuration boundaries for relay admission."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "ansible/roles/relay-server"


def tasks(name):
    return yaml.safe_load((ROLE / "tasks" / f"{name}.yml").read_text())


def flatten(document):
    for task in document:
        yield task
        for key in ("block", "rescue", "always"):
            yield from flatten(task.get(key, []))


def named(name):
    return {task["name"]: task for task in flatten(tasks(name))}


def test_inputs_are_supplied_and_python_is_checked_before_environment_creation():
    document = named("plugin-artifacts")
    names = list(document)
    assert names.index("Require Python with TOML support for admission") < names.index("Create the candidate admission virtual environment")
    assertion = document["Require Python with TOML support for admission"]["ansible.builtin.assert"]
    assert "3.11" in assertion["that"][0]
    assert all(name in str(document["Require operator-supplied admission artifacts"])
               for name in ("frp_grant_admission_wheel", "frp_grant_admission_requirements", "frp_grant_admission_config"))
    assert not any("ansible.builtin.get_url" in task or "ansible.builtin.git" in task for task in document.values())


def test_dependencies_are_hash_checked_and_operator_wheel_installs_without_resolution():
    document = named("plugin-artifacts")
    dependencies = document["Install admission dependencies with required hashes"]["ansible.builtin.command"]["argv"]
    wheel = document["Install only the supplied admission wheel"]["ansible.builtin.command"]["argv"]
    assert "--require-hashes" in dependencies and "--only-binary=:all:" in dependencies
    assert "--no-deps" in wheel and "--force-reinstall" in wheel
    names = list(document)
    assert names.index("Install admission dependencies with required hashes") < names.index("Install only the supplied admission wheel") < names.index("Record successful admission installation")
    assert "/releases/" in document["Select the immutable candidate admission environment"]["ansible.builtin.set_fact"]["frp_grant_admission_release"]


def test_checked_staged_bytes_are_the_only_published_configuration():
    artifacts = named("plugin-artifacts")
    check = artifacts["Check the candidate configuration with the supplied program"]
    assert check["ansible.builtin.command"]["argv"][1] == "check"
    assert "--config" not in check["ansible.builtin.command"]["argv"]
    assert artifacts["Read the exact checked candidate configuration"]["ansible.builtin.slurp"]["src"].endswith("/config.toml")
    fact = artifacts["Retain the checked admission listener and candidate configuration"]["ansible.builtin.set_fact"]
    assert "checked_config.content | b64decode" in fact["frp_grant_admission_candidate_config"]
    assert "lookup" not in str(fact)
    for name in ("Copy the candidate admission configuration privately", "Check the candidate configuration with the supplied program", "Read the exact checked candidate configuration", "Retain the checked admission listener and candidate configuration"):
        assert artifacts[name]["no_log"] is True
    publish = named("plugin")["Publish the checked protected admission configuration"]
    assert publish["no_log"] is True
    module = publish["ansible.builtin.copy"]
    assert module["owner"] == "root" and module["mode"] == "0640"
    assert module["content"] == "{{ frp_grant_admission_candidate_config }}"


def test_program_restart_and_config_reload_are_mutually_coherent():
    document = named("plugin")
    reload_task = document["Reload only the running unchanged program for configuration changes"]
    assert "not frp_grant_admission_restart_required" in reload_task["when"]
    assert "frp_grant_admission_running.rc == 0" in reload_task["when"]
    assert reload_task["ansible.builtin.systemd"]["state"] == "reloaded"
    names = list(document)
    assert names.index("Inspect whether admission was already running") < names.index("Enable and start the checked admission program") < names.index("Wait for admission before starting or restarting frps") < names.index(reload_task["name"])
    assert "restart frps" not in str(document)
    main = [task["name"] for task in tasks("main")]
    assert main.index("Install and start checked relay admission") < main.index("Deploy the relay server configuration")


def test_service_is_unprivileged_and_frps_consults_new_proxy_only():
    document = named("plugin")
    assert "Refuse a privileged admission account" in document
    assert document["Create the unprivileged admission account"]["ansible.builtin.user"]["groups"] == ""
    unit = (ROLE / "templates/frp-grant-admission.service.j2").read_text()
    assert "User={{ frp_grant_admission_user }}" in unit
    assert "Group={{ frp_grant_admission_user }}" in unit
    assert "ExecReload=/bin/kill -HUP $MAINPID" in unit
    for setting in ("NoNewPrivileges=true", "PrivateTmp=true", "ProtectSystem=strict", "ProtectHome=true"):
        assert setting in unit
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    assert defaults["frp_grant_admission_user"] != "root"
    assert defaults["frp_grant_admission_root"] == "/opt/frp-grant-admission"
    frps = (ROLE / "templates/frps.toml.j2").read_text()
    assert 'ops = ["NewProxy"]' in frps and 'path = "/"' in frps
    assert "frp_grant_admission_address" in frps
    assert "Wants=network-online.target frp-grant-admission.service" in (ROLE / "templates/frps.service.j2").read_text()


def test_listener_relocation_is_refused_before_any_publication():
    document = named("plugin")
    names = list(document)
    refusal = document["Refuse an in-place admission listener relocation"]
    assert refusal["when"] == "frp_grant_admission_existing_config.stat.exists"
    assert names.index(refusal["name"]) < names.index("Publish the checked protected admission configuration") < names.index("Select the checked admission program")
    assert "separate drained maintenance" in refusal["ansible.builtin.assert"]["fail_msg"]


def test_program_modes_support_the_unprivileged_daemon_without_following_links():
    document = named("plugin-artifacts")
    permissions = document["Make installed program files readable without granting write access"]["ansible.builtin.file"]
    assert permissions["owner"] == permissions["group"] == "root"
    assert permissions["mode"] == "u=rwX,go=rX"
    assert permissions["recurse"] is True and permissions["follow"] is False
    names = list(document)
    assert names.index("Make installed program files readable without granting write access") < names.index("Record successful admission installation")


def test_privileged_account_is_refused_before_user_or_group_mutation():
    names = list(named("plugin"))
    assert names.index("Require a dedicated non-root admission account name") < names.index("Create the unprivileged admission group")
    assert names.index("Refuse an existing privileged admission account before changing it") < names.index("Create the unprivileged admission account")
    assert names.index("Refuse an existing privileged admission group before changing it") < names.index("Create the unprivileged admission group")
