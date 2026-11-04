"""Static role contracts supplement execution tests; they prove asset structure."""

from pathlib import Path
import tomllib

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLES = ROOT / "ansible/roles"


def tasks(role, name="main"):
    return yaml.safe_load((ROLES / role / "tasks" / (name + ".yml")).read_text())


def flatten(document):
    for task in document:
        yield task
        for key in ("block", "rescue", "always"):
            yield from flatten(task.get(key, []))


def test_roles_have_named_parseable_tasks():
    for role in ("frp-binary", "relay-client", "relay-proxy", "relay-server"):
        for path in (ROLES / role / "tasks").glob("*.yml"):
            for task in flatten(yaml.safe_load(path.read_text())):
                assert isinstance(task, dict) and task.get("name"), path


def test_pin_is_official_and_platform_map_can_be_overridden():
    defaults = yaml.safe_load((ROLES / "frp-binary/defaults/main.yml").read_text())
    assert defaults["frp_version"] == "0.61.1"
    assert defaults["frp_platform"] == "linux_amd64"
    assert defaults["frp_install_root"] == "/usr/local/lib/frp"
    plugin = tomllib.loads((ROOT.parents[2] / "tools/frp-grant-admission/frp-pins.toml").read_text())
    assert defaults["frp_version"] == plugin["version"]
    assert defaults["frp_archives"]["linux_amd64"] == plugin["archives"]["linux_amd64"]


def test_secret_bearing_tasks_are_suppressed():
    names = {
        "relay-client": ["Require the relay address and admission token", "Synchronize the client baseline and retain its per-host password"],
        "relay-server": ["Require the supplied relay admission token", "Deploy the relay server configuration"],
        "relay-proxy": [],
    }
    for role, required in names.items():
        found = {task["name"]: task for task in tasks(role)}
        for name in required:
            assert found[name].get("no_log") is True
    for document in (tasks("relay-proxy", "add"), tasks("relay-proxy", "remove")):
        for task in document:
            if "ansible.builtin.include_role" not in task:
                assert task.get("no_log") is True, task["name"]


def test_admin_api_is_authenticated_and_privileged():
    defaults = yaml.safe_load((ROLES / "relay-client/defaults/main.yml").read_text())
    assert 0 < defaults["frp_admin_port"] < 1024
    assert any("ip_unprivileged_port_start" in str(task) for task in tasks("relay-client"))
    calls = [task["ansible.builtin.uri"] for task in tasks("relay-proxy", "add") if "ansible.builtin.uri" in task]
    assert len(calls) == 2
    for call in calls:
        assert "127.0.0.1:" in call["url"]
        assert call["url_username"] == "admin"
        assert "webServer.password" in call["url_password"]
        assert call["force_basic_auth"] is True
        assert call["use_proxy"] is False


def test_proxy_is_tcp_has_a_grant_and_removal_never_restarts():
    add = tasks("relay-proxy", "add")
    block = next(task["ansible.builtin.blockinfile"]["block"] for task in add if "ansible.builtin.blockinfile" in task)
    assert 'type = "tcp"' in block
    assert "metadatas.grant" in block
    assert "loadBalancer" not in block and "group" not in block
    removal = (ROLES / "relay-proxy/files/remove_proxy.sh").read_text()
    assert "--config -" in removal
    assert "systemctl" not in removal
    assert "restarted" not in str(tasks("relay-proxy", "remove"))


def test_relay_server_discloses_nothing_and_uses_one_port_window():
    document = tasks("relay-server")
    for task in document:
        assert "delegate_to" not in task
        assert not any(key in task for key in ("ansible.builtin.debug", "ansible.builtin.set_stats", "ansible.builtin.reboot"))
    text = str(document).lower()
    assert not any(word in text for word in ("certbot", "nginx", "dashboard"))
    assert "frp_auth_token" not in (ROLES / "relay-server/defaults/main.yml").read_text()
    templates = ROLES / "relay-server/templates"
    assert "frp_proxy_ports" in (templates / "frps.toml.j2").read_text()
    assert "frp_proxy_ports" in (templates / "fail2ban.conf.j2").read_text()
    firewall = next(task for task in document if task["name"] == "Allow every configured proxy range")
    assert firewall["loop"] == "{{ frp_proxy_ports }}"
    for filename in ("frps.service.j2",):
        unit = (templates / filename).read_text()
        assert "ExecStart={{ frp_binary_path }}" in unit
    client = (ROLES / "relay-client/templates/frpc-buyers.service.j2").read_text()
    assert "ExecStart={{ frp_binary_path }}" in client


def test_family_roles_are_available_in_repository_and_image():
    repository = ROOT.parents[2]
    config = (repository / "domains/vms/provisioning/iac/ansible/ansible.cfg").read_text()
    line = next(line for line in config.splitlines() if line.startswith("roles_path ="))
    relative = line.split("=", 1)[1].strip().split(":")[0]
    assert (repository / "domains/vms/provisioning/iac/ansible" / relative).resolve() == ROLES
    dockerfile = (repository / "provisioning/compute/service/Dockerfile").read_text()
    assert "provisioning/compute/iac /opt/provisioning/compute/iac" in dockerfile
    assert 'ANSIBLE_ROLES_PATH="/opt/provisioning/compute/iac/ansible/roles"' in dockerfile


def test_every_proxy_attempt_installs_the_root_owned_shared_helper_first():
    main = tasks("relay-proxy")
    names = [task["name"] for task in main]
    before = names.index("Ensure the shared teardown helper is available on every attempt")
    assert before < names.index("Add the buyer proxy")
    assert before < names.index("Remove the buyer proxy")
    helper = tasks("relay-proxy", "helper")
    for task in helper[:2]:
        module = task.get("ansible.builtin.file", task.get("ansible.builtin.copy"))
        assert module["owner"] == module["group"] == "root"
        assert module["mode"] == "0700"
    defaults = yaml.safe_load((ROLES / "relay-proxy/defaults/main.yml").read_text())
    assert defaults["relay_proxy_library_path"] == "/usr/local/lib/arkhai-relay/remove_proxy.sh"
    shell = tasks("relay-proxy", "remove")[0]["ansible.builtin.shell"]
    assert "source {{ relay_proxy_teardown_library | quote }}" in shell
    assert "set -euo pipefail" in shell
