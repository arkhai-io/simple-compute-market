#!/usr/bin/python3
"""Activate one prepared lease volume under its generation ownership lock."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import stat
import struct
import subprocess
import sys
import uuid
from pathlib import Path


SCHEMA = "arkhai.lease-storage-activation.v1"
REQUEST_SCHEMA = "arkhai.lease-storage-activation-request.v1"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_REQUEST_ID = re.compile(r"[0-9a-f]{64}\Z")
_MAPPER = re.compile(r"arkhai-[0-9a-f]{16}\Z")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_LOOP_CONFIGURE = 0x4C0A
_LOOP_CONFIG = struct.Struct("=IIQQQQQIIII64s64s32sQQ8Q")


class ActivationRefused(RuntimeError):
    """Activation stopped without claiming that an ambiguous mutation is clean."""


class ActivationQuarantined(ActivationRefused):
    """Activation ownership requires later release-owned reconciliation."""


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def request_identity(request: dict[str, object]) -> str:
    return hashlib.sha256(_canonical(request)).hexdigest()


def _load_prepare():
    path = Path(__file__).resolve().with_name("arkhai-prepare-lease-storage.py")
    spec = importlib.util.spec_from_file_location("arkhai_prepared_storage", path)
    if spec is None or spec.loader is None:
        raise ActivationRefused("preparation owner is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_new(path: Path, value: dict[str, object], mode: int = 0o600) -> None:
    data = _canonical(value) + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(path.parent)


def _replace(path: Path, value: dict[str, object], uid: int) -> None:
    st = path.lstat()
    if not (st.st_uid == uid and st.st_nlink == 1 and st.st_mode & 0o777 == 0o600):
        raise ActivationQuarantined("activation journal ownership changed")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    _write_new(temporary, value)
    os.replace(temporary, path)
    _fsync_dir(path.parent)


def _persist(path, journal, uid, state, stage, **evidence) -> None:
    journal.update(state=state, stage=stage, **evidence)
    if path.exists():
        _replace(path, journal, uid)
    else:
        _write_new(path, journal)


class SystemOperations:
    """Fixed command surface for the qualified loop/DM/ext4/native-mount profile."""

    def __init__(
        self,
        *,
        loop_device: Path,
        mount_unit_root: Path,
        mount_point: Path,
        mapper_root: Path = Path("/dev/mapper"),
        sys_dev_block: Path = Path("/sys/dev/block"),
        systemd_search_roots: tuple[Path, ...] = (
            Path("/etc/systemd/system"), Path("/run/systemd/system"),
            Path("/usr/local/lib/systemd/system"), Path("/usr/lib/systemd/system"),
            Path("/lib/systemd/system"),
        ),
        pid1_mountinfo: Path = Path("/proc/1/mountinfo"),
        required_uid: int = 0,
    ):
        self.loop_device = loop_device
        self.mount_unit_root = mount_unit_root
        self.mount_point = mount_point
        self.mapper_root = mapper_root
        self.sys_dev_block = sys_dev_block
        self.systemd_search_roots = systemd_search_roots
        self.pid1_mountinfo = pid1_mountinfo
        self.required_uid = required_uid

    def _run(self, argv, *, stdin=None, timeout=120, pass_fds=()) -> str:
        try:
            result = subprocess.run(
                argv, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                check=False, timeout=timeout, pass_fds=pass_fds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ActivationQuarantined("activation command outcome is uncertain") from exc
        if result.returncode != 0:
            raise ActivationQuarantined("activation command did not complete")
        try:
            return result.stdout.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ActivationQuarantined("activation command output is malformed") from exc

    def attach_loop(self, backing: Path, expected: dict[str, object]) -> dict[str, object]:
        fd = os.open(backing, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            st = os.fstat(fd)
            observed = {
                "st_dev": st.st_dev, "st_ino": st.st_ino, "st_size": st.st_size,
                "st_uid": st.st_uid, "st_gid": st.st_gid,
                "st_mode": stat.S_IMODE(st.st_mode), "st_nlink": st.st_nlink,
            }
            for key, actual in observed.items():
                if expected.get(key) != actual:
                    raise ActivationQuarantined("backing identity changed before loop attach")
            loop_fd = os.open(self.loop_device, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                loop_st = os.fstat(loop_fd)
                if not stat.S_ISBLK(loop_st.st_mode) or os.major(loop_st.st_rdev) != 7:
                    raise ActivationRefused("reserved loop device identity is invalid")
                config = _LOOP_CONFIG.pack(
                    fd, 512, st.st_dev, st.st_ino, 0, 0, st.st_size,
                    0, 0, 0, 0, b"", b"arkhai-owned-backing", b"", 0, 0,
                    *([0] * 8),
                )
                fcntl.ioctl(loop_fd, _LOOP_CONFIGURE, config)
            except OSError as exc:
                raise ActivationQuarantined("loop attachment outcome is uncertain") from exc
            finally:
                os.close(loop_fd)
        finally:
            os.close(fd)
        raw = self._run((
            "losetup", "--list", "--json", "--output",
            "NAME,AUTOCLEAR,BACK-FILE,BACK-INO,BACK-MAJ:MIN,MAJ:MIN,OFFSET,PARTSCAN,RO,SIZELIMIT,DIO,LOG-SEC",
            str(self.loop_device),
        ))
        try:
            devices = json.loads(raw)["loopdevices"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ActivationQuarantined("loop readback is malformed") from exc
        if not isinstance(devices, list) or len(devices) != 1 or not isinstance(devices[0], dict):
            raise ActivationQuarantined("loop readback is ambiguous")
        device = devices[0]
        expected_fields = {
            "name", "autoclear", "back-file", "back-ino", "back-maj:min",
            "maj:min", "offset", "partscan", "ro", "sizelimit", "dio", "log-sec",
        }
        if set(device) != expected_fields:
            raise ActivationQuarantined("loop readback fields are malformed")
        if (
            any(type(device[key]) is not bool for key in ("autoclear", "partscan", "ro", "dio"))
            or any(type(device[key]) is not int for key in ("back-ino", "offset", "sizelimit", "log-sec"))
            or any(not isinstance(device[key], str) for key in ("name", "back-file", "back-maj:min", "maj:min"))
        ):
            raise ActivationQuarantined("loop readback types are malformed")

        def device_number(value: str) -> str:
            match = re.fullmatch(r"\s*(\d+):(\d+)\s*", value)
            if match is None:
                raise ActivationQuarantined("loop device number is malformed")
            major, minor = (int(part) for part in match.groups())
            if major > 4095 or minor > 1048575:
                raise ActivationQuarantined("loop device number is out of range")
            return f"{major}:{minor}"

        loop_number = device_number(device["maj:min"])
        if (
            device.get("name") != str(self.loop_device)
            or device.get("back-ino") != expected["st_ino"]
            or device.get("back-file") != str(backing)
            or device.get("autoclear") is not False
            or device.get("ro") is not False
            or device.get("offset") != 0
            or device.get("sizelimit") != expected["st_size"]
            or device.get("partscan") is not False
            or device.get("dio") is not False
            or device.get("log-sec") != 512
            or loop_number != f"{os.major(loop_st.st_rdev)}:{os.minor(loop_st.st_rdev)}"
        ):
            raise ActivationQuarantined("loop readback does not match backing provenance")
        expected_dev = f"{os.major(expected['st_dev'])}:{os.minor(expected['st_dev'])}"
        observed_dev = device_number(device["back-maj:min"])
        if observed_dev != expected_dev:
            raise ActivationQuarantined("loop backing device readback does not match")
        return {
            "loop_device": str(self.loop_device), "loop_major_minor": loop_number,
            "backing_device": observed_dev, "backing_inode": expected["st_ino"],
            "size": expected["st_size"],
        }

    def _verify_mapper(
        self, mapper: str, expected_luks_uuid: str, loop: dict[str, object]
    ) -> dict[str, object]:
        node = self.mapper_root / mapper
        try:
            link = node.lstat()
            target = os.readlink(node)
            info = node.stat()
        except OSError as exc:
            raise ActivationQuarantined("mapper publication is unavailable") from exc
        if not stat.S_ISLNK(link.st_mode) or link.st_uid != self.required_uid or not re.fullmatch(r"\.\./dm-[0-9]+", target):
            raise ActivationQuarantined("mapper publication identity is invalid")
        if not stat.S_ISBLK(info.st_mode):
            raise ActivationQuarantined("mapper publication is not a block device")
        major, minor = os.major(info.st_rdev), os.minor(info.st_rdev)
        if major > 4095 or minor > 1048575:
            raise ActivationQuarantined("mapper device number is out of range")
        sys_root = self.sys_dev_block / f"{major}:{minor}"
        try:
            name = (sys_root / "dm/name").read_text(encoding="utf-8").strip()
            dm_uuid = (sys_root / "dm/uuid").read_text(encoding="ascii").strip()
            slaves = sorted(item.name for item in (sys_root / "slaves").iterdir())
        except (OSError, UnicodeError) as exc:
            raise ActivationQuarantined("mapper sysfs identity is unavailable") from exc
        expected_prefix = f"CRYPT-LUKS2-{expected_luks_uuid.replace('-', '')}-"
        if (
            name != mapper or not dm_uuid.startswith(expected_prefix)
            or dm_uuid != f"{expected_prefix}{mapper}"
            or slaves != [Path(str(loop.get("loop_device"))).name]
        ):
            raise ActivationQuarantined("mapper dependency identity does not match")
        return {
            "mapper": mapper, "major": major, "minor": minor,
            "dm_uuid": dm_uuid, "dm_node": f"/dev/{Path(target).name}",
        }

    def open_mapper(
        self,
        mapper: str,
        secret: bytes,
        expected_luks_uuid: str,
        loop: dict[str, object],
    ) -> dict[str, object]:
        if (
            len(secret) != 32 or not _MAPPER.fullmatch(mapper)
            or not _UUID.fullmatch(expected_luks_uuid)
        ):
            raise ActivationRefused("mapper input is invalid")
        self._run((
            "cryptsetup", "--batch-mode", "--type", "luks2",
            "--disable-external-tokens", "--disable-keyring", "--key-file", "-",
            "--keyfile-size", "32", "open", str(self.loop_device), mapper,
        ), stdin=secret)
        raw = self._run(("dmsetup", "info", "--columns", "--noheadings", "--separator", ":", "-o", "name,major,minor,uuid", mapper))
        fields = raw.strip().split(":")
        if len(fields) != 4 or fields[0].strip() != mapper:
            raise ActivationQuarantined("mapper identity readback is malformed")
        try:
            major, minor = int(fields[1]), int(fields[2])
        except ValueError as exc:
            raise ActivationQuarantined("mapper device numbers are malformed") from exc
        if major > 4095 or minor > 1048575:
            raise ActivationQuarantined("mapper device numbers are out of range")
        verified = self._verify_mapper(mapper, expected_luks_uuid, loop)
        if verified != {
            "mapper": mapper, "major": major, "minor": minor,
            "dm_uuid": fields[3].strip(), "dm_node": verified["dm_node"],
        }:
            raise ActivationQuarantined("mapper command and kernel identity disagree")
        return verified

    def format_ext4(
        self, mapped: dict[str, object], filesystem_uuid: str,
        expected_luks_uuid: str, loop: dict[str, object],
    ) -> dict[str, object]:
        mapper = mapped.get("mapper")
        if not isinstance(mapper, str) or self._verify_mapper(mapper, expected_luks_uuid, loop) != mapped:
            raise ActivationQuarantined("mapper identity changed before format")
        device = f"/dev/mapper/{mapper}"
        probe = self._run(("wipefs", "--json", "--output", "TYPE,UUID", device))
        try:
            signatures = json.loads(probe)["signatures"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ActivationQuarantined("signature probe is malformed") from exc
        if signatures != []:
            raise ActivationRefused("plaintext volume is not signature-free")
        self._run(("mkfs.ext4", "-F", "-U", filesystem_uuid, "-E", "lazy_itable_init=0,lazy_journal_init=0,nodiscard", device))
        return self.read_filesystem(mapper, filesystem_uuid)

    def read_filesystem(self, mapper: str, filesystem_uuid: str) -> dict[str, object]:
        device = f"/dev/mapper/{mapper}"
        for tag, expected in (("TYPE", "ext4"), ("UUID", filesystem_uuid)):
            raw = self._run((
                "blkid", "--probe", "--output", "value", "--match-tag", tag,
                device,
            ))
            if raw != f"{expected}\n":
                raise ActivationQuarantined(
                    "filesystem identity readback does not match"
                )
        return {"type": "ext4", "uuid": filesystem_uuid}

    def _manager_properties(self, unit: str, names: tuple[str, ...]) -> dict[str, str]:
        raw = self._run((
            "systemctl", "show", "--no-pager",
            *(f"--property={name}" for name in names), unit,
        ), timeout=15)
        values = {}
        for line in raw.splitlines():
            key, separator, value = line.partition("=")
            if not separator or not key or key in values:
                raise ActivationQuarantined("mount manager readback is malformed")
            values[key] = value
        if set(values) != set(names):
            raise ActivationQuarantined("mount manager readback fields do not match")
        return values

    def _reject_unit_collision(self, unit_name: str) -> None:
        for root in self.systemd_search_roots:
            candidate = root / unit_name
            if (
                candidate.exists() or candidate.is_symlink()
                or candidate.with_name(candidate.name + ".d").exists()
                or candidate.with_name(candidate.name + ".d").is_symlink()
            ):
                raise ActivationRefused("native mount unit or drop-in already exists")

    def _pid1_mount_identity(self, mapped, filesystem_uuid) -> dict[str, object]:
        try:
            raw = self.pid1_mountinfo.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ActivationQuarantined("PID 1 mount namespace readback is unavailable") from exc
        matches = []
        for line in raw.splitlines():
            left, marker, right = line.partition(" - ")
            fields, tail = left.split(), right.split()
            if marker and len(fields) >= 6 and len(tail) >= 3 and fields[4] == str(self.mount_point):
                matches.append((fields, tail))
        expected_device = f"{mapped['major']}:{mapped['minor']}"
        expected_sources = {str(self.mapper_root / mapped["mapper"]), mapped["dm_node"]}
        if len(matches) != 1:
            raise ActivationQuarantined("PID 1 mount namespace readback is not singular")
        fields, tail = matches[0]
        options = set(fields[5].split(","))
        if (
            fields[2] != expected_device or tail[0] != "ext4"
            or tail[1] not in expected_sources
            or not {"rw", "nodev", "nosuid", "noexec"}.issubset(options)
        ):
            raise ActivationQuarantined("PID 1 mount identity or options do not match")
        filesystem = self.read_filesystem(mapped["mapper"], filesystem_uuid)
        return {
            "major_minor": expected_device, "source": tail[1],
            "options": sorted(options), **filesystem,
        }

    def mount(
        self, mapped: dict[str, object], filesystem_uuid: str,
        expected_luks_uuid: str, loop: dict[str, object],
    ) -> dict[str, object]:
        mapper = mapped.get("mapper")
        if not isinstance(mapper, str) or not _MAPPER.fullmatch(mapper):
            raise ActivationRefused("mapper identity is invalid")
        if self._verify_mapper(mapper, expected_luks_uuid, loop) != mapped:
            raise ActivationQuarantined("mapper identity changed before mount")
        if not self.mount_point.is_absolute() or self.mount_point == Path("/"):
            raise ActivationRefused("native mount path is invalid")
        unit_name = self._run((
            "systemd-escape", "--path", "--suffix=mount", str(self.mount_point)
        )).strip()
        if not re.fullmatch(r"[A-Za-z0-9_.\\x-]+\.mount", unit_name):
            raise ActivationQuarantined("native mount unit identity is malformed")
        self._reject_unit_collision(unit_name)
        unit_path = self.mount_unit_root / unit_name
        self.mount_point.mkdir(mode=0o700, parents=False, exist_ok=False)
        content = (
            "[Unit]\nDescription=Managed lease volume\nDefaultDependencies=no\n"
            "[Mount]\nWhat=%s\nWhere=%s\nType=ext4\n"
            "Options=rw,nosuid,nodev,noexec\nSlice=system.slice\n"
            "[Install]\nWantedBy=\n" % (self.mapper_root / mapper, self.mount_point)
        ).encode()
        fd = os.open(unit_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        try:
            os.write(fd, content)
            os.fsync(fd)
        finally:
            os.close(fd)
        _fsync_dir(unit_path.parent)
        self._run(("systemctl", "daemon-reload"))
        expected_profile = {
            "LoadState": "loaded", "FragmentPath": str(unit_path),
            "DropInPaths": "", "UnitFileState": "static",
            "What": str(self.mapper_root / mapper), "Where": str(self.mount_point),
            "Type": "ext4", "Options": "rw,nosuid,nodev,noexec", "Slice": "system.slice",
        }
        if self._manager_properties(unit_name, tuple(expected_profile)) != expected_profile:
            raise ActivationQuarantined("effective mount unit profile does not match")
        if self._verify_mapper(mapper, expected_luks_uuid, loop) != mapped:
            raise ActivationQuarantined("mapper identity changed before mount start")
        self._run(("systemctl", "start", unit_name))
        result_expected = {
            "LoadState": "loaded", "ActiveState": "active", "SubState": "mounted",
            "Result": "success",
        }
        if self._manager_properties(unit_name, tuple(result_expected)) != result_expected:
            raise ActivationQuarantined("mount manager result does not match")
        identity = self._pid1_mount_identity(mapped, filesystem_uuid)
        return {"unit": unit_name, "mount_point": str(self.mount_point), **identity}


def execute(config, request, *, runner, custody_factory, operations) -> dict[str, object]:
    prepare = _load_prepare()
    request_id = request_identity(request)
    if request.get("schema") != REQUEST_SCHEMA or request.get("request_id") not in {None, request_id}:
        raise ActivationRefused("activation request identity is invalid")
    preparation_request_id = request.get("preparation_request_id")
    boot_id = request.get("boot_id")
    expected_request_identity = {
        "host_id": config.host_id,
        "machine_id": config.machine_id,
        "generation": config.generation,
    }
    if any(request.get(key) != value for key, value in expected_request_identity.items()):
        raise ActivationRefused("activation request does not match the prepared generation")
    if not isinstance(preparation_request_id, str) or not _REQUEST_ID.fullmatch(preparation_request_id):
        raise ActivationRefused("preparation request identity is invalid")
    if not isinstance(boot_id, str) or not _IDENTIFIER.fullmatch(boot_id):
        raise ActivationRefused("activation boot identity is invalid")
    with prepare.locked_prepared_lease(config, runner=runner) as lease:
        path = lease.lease_dir / "activation.json"
        identity = {
            "schema": SCHEMA, "host_id": config.host_id,
            "machine_id": config.machine_id, "generation": config.generation,
            "nv_index": config.nv_index, "request_id": request_id, "boot_id": boot_id,
        }
        if path.exists() or path.is_symlink():
            existing = prepare._read_private_json(path, uid=config.required_uid)
            if existing.get("state") in {"pending", "quarantined", "completed"}:
                raise ActivationRefused("activation generation is already owned")
            raise ActivationQuarantined("activation journal is invalid")
        journal = dict(identity)
        try:
            lease.require_prepared(preparation_request_id)
        except prepare.PreparationRefused as exc:
            lease.quarantine(str(exc), "activation_prepared_admission_quarantined")
            journal["quarantine_reason"] = type(exc).__name__
            _persist(
                path, journal, config.required_uid, "quarantined",
                "prepared_admission",
            )
            raise ActivationQuarantined(
                "prepared generation admission is ambiguous"
            ) from exc
        _persist(path, journal, config.required_uid, "pending", "loop_attach_pending")
        try:
            backing = lease.manifest["backing_evidence"]
            loop = operations.attach_loop(lease.lease_dir / "volume.luks", backing)
            _persist(path, journal, config.required_uid, "pending", "mapper_open_pending", loop=loop)
            mapper = f"arkhai-{request_id[:16]}"

            def open_and_record(secret):
                mapped_identity = operations.open_mapper(
                    mapper, secret, backing["luks_uuid"], loop
                )
                _persist(
                    path, journal, config.required_uid, "pending", "mapper_opened",
                    mapper=mapped_identity,
                )
                return mapped_identity

            mapped = lease.consume_secret(
                custody_factory, open_and_record
            )
            _persist(path, journal, config.required_uid, "pending", "custody_closed", mapper=mapped)
            filesystem_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"arkhai:{config.host_id}:{config.generation}"))
            _persist(path, journal, config.required_uid, "pending", "format_pending", filesystem_uuid=filesystem_uuid)
            filesystem = operations.format_ext4(
                mapped, filesystem_uuid, backing["luks_uuid"], loop
            )
            _persist(path, journal, config.required_uid, "pending", "mount_pending", filesystem=filesystem)
            mounted = operations.mount(
                mapped, filesystem_uuid, backing["luks_uuid"], loop
            )
            receipt = {**identity, "state": "completed", "loop": loop, "mapper": mapped, "filesystem": filesystem, "mount": mounted}
            _persist(path, journal, config.required_uid, "completed", "completed", receipt=receipt)
            return receipt
        except BaseException as exc:
            journal["quarantine_reason"] = type(exc).__name__
            try:
                _persist(path, journal, config.required_uid, "quarantined", journal.get("stage", "unknown"))
            except BaseException as persist_exc:
                raise ActivationQuarantined("activation quarantine could not be persisted") from persist_exc
            if isinstance(exc, ActivationRefused):
                raise
            raise ActivationQuarantined("activation outcome is uncertain") from exc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.parse_args(argv)
    print(json.dumps({"state": "refused", "reason": "activation requires supervised dependency injection"}), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
