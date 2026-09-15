"""The per-lease access artifacts render one confined tenant environment.

The role renders four artifacts for a lease generation: a socket on the buyer
port, an accept-per-connection SSH service instance, a slice holding every
tenant process, and the lease daemon configuration inside a generated runtime
view. These tests render the real templates with Ansible's templar against
controlled inputs and assert the properties that make the environment a
boundary rather than a host login.

Where a path matters, the assertion is that the path is *reachable in the
namespace the unit builds* -- resolved through the unit's own mounts -- not
that some string appears in the file. A daemon told to read a path its mount
view hides fails at run time while looking correct in review.

Rendering is not activation: nothing here starts a unit, and the values are
synthetic. Whether the host actually supplies the volume, namespace and
controls these artifacts reference is answered on the host, and until a
verifier for that exists the role refuses to grant at all.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

try:
    # ansible-core 2.19 renders only templates marked trusted; a role template
    # is trusted input exactly as it is when Ansible loads it from the role.
    from ansible.template import trust_as_template
except ImportError:  # ansible-core < 2.19 has no trust model
    def trust_as_template(value):
        return value

TEMPLATES = (
    Path(__file__).resolve().parents[1]
    / "ansible" / "roles" / "bare-metal-access" / "templates"
)

GENERATION = "g-7f3a9c21"
TENANT = "arkhai-70f5f19cca87f7e6"
BUYER_PORT = 2222
VOLUME = f"/var/lib/arkhai/lease-{GENERATION}/volume"
VIEW = f"/run/arkhai/lease-{GENERATION}/view"
NETNS = f"arkhai-lease-{GENERATION}"
GPU_NODES = ["/dev/nvidia0", "/dev/nvidiactl", "/dev/nvidia-uvm"]


def _render(name: str) -> str:
    templar = Templar(loader=DataLoader(), variables={
        "bare_metal_lease_generation": GENERATION,
        "bare_metal_ssh_user": TENANT,
        "bare_metal_lease_buyer_port": BUYER_PORT,
        "bare_metal_lease_volume_path": VOLUME,
        "bare_metal_lease_view_path": VIEW,
        "bare_metal_lease_netns": NETNS,
        "bare_metal_lease_gpu_nodes": GPU_NODES,
        "bare_metal_lease_sshd_binary": "/usr/sbin/sshd",
        "bare_metal_lease_privsep_user": "sshd",
        "bare_metal_lease_tenant_uid": 61001,
        "bare_metal_lease_tenant_gid": 61001,
    })
    return templar.template(trust_as_template((TEMPLATES / name).read_text(encoding="utf-8")))


def _directives(text: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        key, separator, value = line.partition("=")
        if separator:
            found.setdefault(key.strip(), []).append(value.strip())
    return found


class MountView:
    """The paths a unit's mount directives make visible inside its namespace.

    Only what the unit maps is reachable: the root is a fresh tmpfs, so a path
    that is not bound is not there, whatever the host holds.
    """

    def __init__(self, directives: dict[str, list[str]]):
        self.tmpfs_root = "/:ro" in directives.get("TemporaryFileSystem", [])
        self.mounts: dict[str, str] = {}
        self.writable: set[str] = set()
        for key in ("BindReadOnlyPaths", "BindPaths"):
            for value in directives.get(key, []):
                source, _, target = value.partition(":")
                target = target or source
                self.mounts[target.rstrip("/") or "/"] = source
                if key == "BindPaths":
                    self.writable.add(target.rstrip("/") or "/")
        self.hidden = {
            value.rstrip("/") for value in directives.get("InaccessiblePaths", [])
        }

    def _mount_for(self, path: str) -> str | None:
        candidate = path.rstrip("/")
        while candidate:
            if candidate in self.mounts:
                return candidate
            candidate = candidate.rsplit("/", 1)[0]
        return "/" if "/" in self.mounts else None

    def reachable(self, path: str) -> bool:
        for hidden in self.hidden:
            if path == hidden or path.startswith(hidden + "/"):
                return False
        return self._mount_for(path) is not None

    def source_of(self, path: str) -> str | None:
        mount = self._mount_for(path)
        if mount is None:
            return None
        return self.mounts[mount] + path[len(mount):]

    def is_writable(self, path: str) -> bool:
        mount = self._mount_for(path)
        return mount in self.writable if mount else False


def _service_view() -> tuple[dict[str, list[str]], MountView]:
    directives = _directives(_render("lease-sshd@.service.j2"))
    return directives, MountView(directives)


# --- socket ---------------------------------------------------------------


def test_socket_listens_on_the_buyer_port_and_accepts_per_connection():
    directives = _directives(_render("lease.socket.j2"))

    assert directives["ListenStream"] == [str(BUYER_PORT)]
    # Accept=yes is what makes each connection its own service instance.
    assert directives["Accept"] == ["yes"]
    assert directives["Slice"] == [f"arkhai-lease-{GENERATION}.slice"]
    # A socket unit that executes something is not socket activation.
    assert "ExecStart" not in directives


# --- service instance -----------------------------------------------------


def test_service_runs_the_daemon_per_connection(tmp_path):
    directives, _ = _service_view()

    assert directives["StandardInput"] == ["socket"]
    exec_start = directives["ExecStart"][0]
    # -i is the accept-per-connection mode: the daemon serves the passed
    # connection and exits, so there is no listening daemon inside the lease.
    assert " -i " in f" {exec_start} "
    assert directives["Slice"] == [f"arkhai-lease-{GENERATION}.slice"]


def test_the_daemon_can_actually_read_the_configuration_it_is_given():
    """The -f path must exist in the namespace, not merely in the text."""
    directives, view = _service_view()
    exec_start = directives["ExecStart"][0]

    match = re.search(r"-f\s+(\S+)", exec_start)
    assert match, "the unit must tell the daemon which configuration to read"
    config_path = match.group(1)

    assert view.reachable(config_path), (
        f"{config_path} is not reachable inside the unit's mount view"
    )
    # It resolves to the generated view the role rendered.
    assert view.source_of(config_path) == f"{VIEW}/etc/ssh/sshd_config"


def test_the_daemon_can_actually_read_its_host_key():
    directives, view = _service_view()
    config = _render("sshd_config.j2")

    match = re.search(r"^HostKey\s+(\S+)$", config, re.M)
    assert match, "the lease daemon must name a host key"
    key_path = match.group(1)

    assert view.reachable(key_path), (
        f"{key_path} is not reachable inside the unit's mount view"
    )
    assert view.source_of(key_path) == f"{VIEW}/etc/ssh/lease_host_key"


def test_the_runtime_layout_a_login_needs_is_present():
    """A shell and the loader must resolve, or every session fails."""
    _, view = _service_view()

    for needed in ("/bin/bash", "/usr/sbin/sshd", "/run/sshd"):
        assert view.reachable(needed), f"{needed} is not reachable in the lease view"
    # The ELF loader's search paths.
    assert view.reachable("/lib"), "the loader's /lib is not reachable"


def test_service_root_is_read_only_with_host_paths_masked():
    directives, view = _service_view()

    assert view.tmpfs_root, "the lease root must be a fresh read-only tmpfs"
    assert "/usr" in directives["BindReadOnlyPaths"]
    assert not view.is_writable("/usr"), "/usr must not be writable by the tenant"
    assert not view.reachable("/usr/local"), "/usr/local must be masked"


def test_every_writable_path_lives_inside_the_lease_volume():
    """Including scratch: nothing writable may be backed by host storage."""
    _, view = _service_view()

    for target in sorted(view.writable):
        source = view.mounts[target]
        assert source.startswith(VOLUME) or source.startswith("/dev/"), (
            f"{target} is writable but backed by {source}, outside the lease volume"
        )


def test_scratch_directories_come_from_the_volume_not_the_host():
    """systemd's private directories are host-backed; these are not."""
    directives, view = _service_view()

    assert "PrivateTmp" not in directives, (
        "PrivateTmp supplies host-backed /tmp and /var/tmp; unlinking them on "
        "stop is not cryptographic destruction"
    )
    for scratch in ("/tmp", "/var/tmp"):
        assert view.is_writable(scratch), f"{scratch} must be writable for the tenant"
        assert view.source_of(scratch).startswith(VOLUME), (
            f"{scratch} is backed by {view.source_of(scratch)}, outside the volume"
        )


def test_the_daemon_is_told_where_to_log():
    """Without -E the daemon uses syslog, and the lease has no /dev/log.

    A unit-level stderr target does not change that: the records would be lost
    inside the namespace rather than arriving anywhere.
    """
    directives, view = _service_view()
    exec_start = directives["ExecStart"][0]

    match = re.search(r"-E\s+(\S+)", exec_start)
    assert match, (
        "the daemon must be given an explicit log file; otherwise it logs via "
        "syslog and the lease namespace has no socket to carry it"
    )
    log_path = match.group(1)

    # Resolved by the daemon inside the namespace, so it has to exist there and
    # be writable there.
    assert view.reachable(log_path), (
        f"{log_path} is not reachable inside the unit's mount view"
    )
    assert view.is_writable(log_path), f"{log_path} is not writable in the lease"
    assert view.source_of(log_path).startswith(VOLUME)


def test_the_startup_stderr_target_is_a_host_side_file_not_the_journal():
    """systemd opens StandardError before the unit's mounts exist.

    So it names the volume's host mount point, which is a different resolution
    from the daemon's own -E path even when the string matches. It must still
    never be the journal.
    """
    directives, _ = _service_view()

    standard_error = directives["StandardError"][0]
    assert standard_error.startswith("append:"), (
        f"startup diagnostics are routed to {standard_error!r}, not a file"
    )
    assert standard_error.removeprefix("append:").startswith(VOLUME)
    assert "journal" not in standard_error
    assert "syslog" not in standard_error


def test_the_two_log_destinations_are_distinct_files():
    """One is the daemon's own log, the other only catches startup failures."""
    directives, _ = _service_view()

    startup = directives["StandardError"][0].removeprefix("append:")
    daemon = re.search(r"-E\s+(\S+)", directives["ExecStart"][0]).group(1)

    assert startup != daemon, (
        "the daemon appends to its -E file while systemd holds the stderr file "
        "open; pointing both at one path interleaves two writers"
    )


def test_service_refuses_privilege_namespace_and_keyring_escapes():
    directives, _ = _service_view()

    assert directives["NoNewPrivileges"] == ["yes"]
    assert directives["RestrictNamespaces"] == ["yes"]
    assert directives["RestrictSUIDSGID"] == ["yes"]
    assert any("@keyring" in value for value in directives["SystemCallFilter"])
    assert directives["ProtectProc"] == ["invisible"]
    assert directives["PrivateIPC"] == ["yes"]
    assert directives["NetworkNamespacePath"] == [f"/run/netns/{NETNS}"]


def test_qualified_gpu_nodes_are_both_present_and_permitted():
    """An allow rule for a node that is not mounted grants nothing."""
    directives, view = _service_view()

    assert directives["PrivateDevices"] == ["yes"]
    allowed = {value.split()[0] for value in directives["DeviceAllow"]}
    assert allowed == set(GPU_NODES)
    for node in GPU_NODES:
        assert view.reachable(node), (
            f"{node} is allowed by policy but never bound into the private /dev"
        )


def test_no_tpm_raw_disk_or_runtime_socket_is_exposed():
    directives, view = _service_view()

    allowed = {value.split()[0] for value in directives["DeviceAllow"]}
    for forbidden in ("/dev/tpm0", "/dev/tpmrm0", "/dev/sda", "/dev/nvme0n1",
                      "/var/run/docker.sock"):
        assert forbidden not in allowed
        assert not view.reachable(forbidden), f"{forbidden} is reachable in the lease"


def test_service_and_slice_deny_swap_and_core_dumps():
    service, _ = _service_view()
    slice_unit = _directives(_render("lease.slice.j2"))

    assert service["LimitCORE"] == ["0"]
    assert slice_unit["MemorySwapMax"] == ["0"]
    # Device policy is closed at the slice so no instance can widen it.
    assert slice_unit["DevicePolicy"] == ["closed"]


# --- lease daemon configuration -------------------------------------------


def test_daemon_config_disables_host_login_mechanisms():
    config = _render("sshd_config.j2")

    assert re.search(r"^UsePAM no$", config, re.M)
    assert re.search(r"^PasswordAuthentication no$", config, re.M)
    assert re.search(r"^KbdInteractiveAuthentication no$", config, re.M)
    assert re.search(r"^PermitRootLogin no$", config, re.M)
    assert re.search(r"^UseDNS no$", config, re.M)
    assert re.search(r"^PrintLastLog no$", config, re.M)


def test_daemon_config_states_no_log_destination_of_its_own():
    """The unit owns the destination; a keyword here would be decoration."""
    config = _render("sshd_config.j2")

    assert "ARKHAI_LEASE_LOG" not in config, (
        "an environment variable does not configure daemon logging"
    )
    assert re.search(r"^LogLevel VERBOSE$", config, re.M)


def test_daemon_config_keeps_added_keys_inside_the_lease_volume():
    config = _render("sshd_config.j2")

    match = re.search(r"^AuthorizedKeysFile\s+(\S+)$", config, re.M)
    assert match, "the lease daemon must state where authorized keys live"
    # Keys the tenant adds land inside the volume, so they are revoked with it.
    assert match.group(1).startswith(VOLUME)


def test_daemon_config_routes_sftp_through_the_same_boundary():
    config = _render("sshd_config.j2")

    match = re.search(r"^Subsystem\s+sftp\s+(\S+)$", config, re.M)
    assert match, "the lease daemon must define the sftp subsystem"
    # internal-sftp is served by the daemon already inside the lease view; an
    # external binary would run outside it.
    assert match.group(1) == "internal-sftp"


def test_daemon_config_restricts_forwarding_to_the_lease():
    config = _render("sshd_config.j2")

    assert re.search(r"^X11Forwarding no$", config, re.M)
    assert re.search(r"^PermitTunnel no$", config, re.M)
    assert re.search(r"^AllowStreamLocalForwarding no$", config, re.M)
    assert re.search(r"^AllowAgentForwarding no$", config, re.M)
    assert re.search(r"^AllowTcpForwarding local$", config, re.M)


def test_daemon_config_admits_only_the_lease_tenant():
    config = _render("sshd_config.j2")

    assert re.search(rf"^AllowUsers {re.escape(TENANT)}$", config, re.M)


# --- generated runtime view ----------------------------------------------


def test_generated_passwd_holds_only_root_privsep_and_the_tenant():
    rendered = _render("view-passwd.j2")
    names = [line.split(":", 1)[0] for line in rendered.splitlines() if line.strip()]

    assert names == ["root", "sshd", TENANT]
    tenant_line = [line for line in rendered.splitlines() if line.startswith(TENANT)][0]
    fields = tenant_line.split(":")
    assert fields[2] == "61001" and fields[3] == "61001"
    # The tenant's home is inside the lease volume, not on the host.
    assert fields[5].startswith(VOLUME)


def test_generated_group_covers_the_same_principals():
    group_names = [
        line.split(":", 1)[0]
        for line in _render("view-group.j2").splitlines()
        if line.strip()
    ]

    assert group_names == ["root", "sshd", TENANT]


def test_the_tenant_password_is_unusable_without_locking_the_account():
    """``!`` marks a locked account, which the daemon rejects before keys.

    With ``UsePAM no`` the daemon performs its own account admission, so the
    tenant's field must be an invalid hash rather than a lock marker. The
    principals that must never authenticate keep the lock.
    """
    shadow = {
        line.split(":", 1)[0]: line.split(":")[1]
        for line in _render("view-shadow.j2").splitlines()
        if line.strip()
    }

    assert shadow[TENANT] == "*", (
        f"the tenant's password field is {shadow[TENANT]!r}; a leading '!' locks "
        "the account and is refused before key authentication"
    )
    assert not shadow[TENANT].startswith("!")
    for principal in ("root", "sshd"):
        assert shadow[principal].startswith("!"), (
            f"{principal} must never authenticate, so it stays locked"
        )


def test_generated_nsswitch_resolves_from_files_only():
    rendered = _render("view-nsswitch.conf.j2")

    for database in ("passwd", "group", "shadow"):
        match = re.search(rf"^{database}:\s+(.*)$", rendered, re.M)
        assert match, f"nsswitch must state {database}"
        assert match.group(1).split() == ["files"]


@pytest.mark.parametrize(
    "template",
    [
        "lease.socket.j2",
        "lease-sshd@.service.j2",
        "lease.slice.j2",
        "sshd_config.j2",
        "view-passwd.j2",
        "view-group.j2",
        "view-shadow.j2",
        "view-nsswitch.conf.j2",
    ],
)
def test_no_artifact_references_host_state_outside_the_lease(template):
    rendered = _render(template)

    for host_path in ("/root", "/var/lib/docker", "/var/run/docker.sock",
                      "/dev/tpm", "/var/log/journal", "/home/"):
        assert host_path not in rendered, f"{template} maps host state {host_path}"
