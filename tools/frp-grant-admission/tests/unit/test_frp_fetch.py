"""The fetch of the real-frp tests' binaries, against local archive files.

An archive is built in the test's directory with stand-in binaries, so no test here
touches the network: a download is a copy from a `file:` URL.
"""

from __future__ import annotations

import hashlib
import http.client
import io
import os
import tarfile
from pathlib import Path

import pytest

from tests.frp_fetch import (
    PINS_PATH,
    Archive,
    FetchError,
    NoBinaries,
    extract,
    fetch,
    load_pins,
    resolve,
)

VERSION = "0.61.1"
PLATFORM = "linux_amd64"
CONTENTS = {"frps": b"stand-in frps\n", "frpc": b"stand-in frpc\n"}


def build_archive(directory: Path, contents: dict[str, bytes] = CONTENTS) -> Path:
    """A release-shaped archive: `frp_<version>_<platform>/` holding the binaries."""
    path = directory / f"frp_{VERSION}_{PLATFORM}.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for name, data in {**contents, "LICENSE": b"licence\n"}.items():
            member = tarfile.TarInfo(f"frp_{VERSION}_{PLATFORM}/{name}")
            member.size = len(data)
            member.mode = 0o755
            archive.addfile(member, io.BytesIO(data))
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pinned(path: Path, sha256: str | None = None) -> Archive:
    return Archive(path.as_uri(), sha256 or digest(path))


def test_a_matching_archive_extracts_both_binaries(tmp_path: Path) -> None:
    archive = build_archive(tmp_path)
    destination = tmp_path / "bin"

    binaries = extract(archive, digest(archive), destination)

    assert binaries.frps.read_bytes() == CONTENTS["frps"]
    assert binaries.frpc.read_bytes() == CONTENTS["frpc"]
    assert os.access(binaries.frps, os.X_OK) and os.access(binaries.frpc, os.X_OK)
    assert sorted(path.name for path in destination.iterdir()) == ["frpc", "frps"]


def test_a_mismatching_archive_names_both_digests_and_extracts_nothing(tmp_path: Path) -> None:
    archive = build_archive(tmp_path)
    wrong = "0" * 64
    destination = tmp_path / "bin"

    with pytest.raises(FetchError) as refused:
        extract(archive, wrong, destination)

    assert digest(archive) in str(refused.value)
    assert wrong in str(refused.value)
    assert not destination.exists()


def test_an_archive_without_a_binary_is_refused(tmp_path: Path) -> None:
    archive = build_archive(tmp_path, {"frps": CONTENTS["frps"]})

    with pytest.raises(FetchError, match="0 files named frpc"):
        extract(archive, digest(archive), tmp_path / "bin")


def test_a_download_is_verified_cached_and_reused(tmp_path: Path) -> None:
    (tmp_path / "release").mkdir()
    source = build_archive(tmp_path / "release")
    cache = tmp_path / "cache"
    archive = pinned(source)

    first = fetch(archive, VERSION, PLATFORM, cache)

    assert first.frps.read_bytes() == CONTENTS["frps"]
    assert (cache / source.name).read_bytes() == source.read_bytes()
    source.unlink()
    second = fetch(archive, VERSION, PLATFORM, cache)
    assert second == first
    assert second.frpc.read_bytes() == CONTENTS["frpc"]


def test_a_mismatching_download_leaves_nothing_in_the_cache(tmp_path: Path) -> None:
    (tmp_path / "release").mkdir()
    source = build_archive(tmp_path / "release")
    cache = tmp_path / "cache"

    with pytest.raises(FetchError) as refused:
        fetch(pinned(source, "f" * 64), VERSION, PLATFORM, cache)

    assert digest(source) in str(refused.value)
    assert list(cache.iterdir()) == []


def test_a_download_cut_short_leaves_nothing_in_the_cache(tmp_path: Path) -> None:
    def cut_short(url: str, target: Path) -> None:
        target.write_bytes(b"part of an archive")
        raise http.client.IncompleteRead(b"part of an archive")

    cache = tmp_path / "cache"

    with pytest.raises(FetchError, match="cannot download"):
        fetch(Archive("https://x/frp.tar.gz", "a" * 64), VERSION, PLATFORM, cache, cut_short)

    assert list(cache.iterdir()) == []


def test_a_cached_archive_that_no_longer_verifies_is_downloaded_again(tmp_path: Path) -> None:
    (tmp_path / "release").mkdir()
    source = build_archive(tmp_path / "release")
    cache = tmp_path / "cache"
    archive = pinned(source)
    fetch(archive, VERSION, PLATFORM, cache)
    (cache / source.name).write_bytes(b"tampered")
    (cache / f"frp_{VERSION}_{PLATFORM}" / "frps").write_bytes(b"tampered")

    binaries = fetch(archive, VERSION, PLATFORM, cache)

    assert binaries.frps.read_bytes() == CONTENTS["frps"]
    assert digest(cache / source.name) == archive.sha256


def test_resolve_fetches_from_the_pins_only_when_fetching(tmp_path: Path) -> None:
    (tmp_path / "release").mkdir()
    source = build_archive(tmp_path / "release")
    pins = tmp_path / "frp-pins.toml"
    pins.write_text(
        f'version = "{VERSION}"\n[archives.{PLATFORM}]\n'
        f'url = "https://example.invalid/{source.name}"\nsha256 = "{digest(source)}"\n'
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / source.name).write_bytes(source.read_bytes())

    # A verified archive in the cache is still not the default suite's to run.
    with pytest.raises(NoBinaries, match="make test-frp"):
        resolve(fetching=False, environ={}, pins_path=pins, cache_dir=cache, platform_name=PLATFORM)

    binaries = resolve(
        fetching=True, environ={}, pins_path=pins, cache_dir=cache, platform_name=PLATFORM
    )
    assert binaries.frps.read_bytes() == CONTENTS["frps"]
    assert binaries.provenance == (
        f"{source.name}, verified against its pin: SHA-256 {digest(source)}"
    )


def test_resolve_has_no_binaries_for_a_platform_with_no_pin_and_no_override(
    tmp_path: Path,
) -> None:
    with pytest.raises(NoBinaries, match="freebsd_riscv64"):
        resolve(fetching=True, environ={}, cache_dir=tmp_path, platform_name="freebsd_riscv64")


def test_overrides_replace_the_fetch_whether_or_not_fetching(tmp_path: Path) -> None:
    environ = {"FRPS_BIN": "/opt/frp/frps", "FRPC_BIN": "/opt/frp/frpc"}

    for fetching in (True, False):
        binaries = resolve(
            fetching=fetching, environ=environ, cache_dir=tmp_path, platform_name="none"
        )
        assert (binaries.frps, binaries.frpc) == (Path("/opt/frp/frps"), Path("/opt/frp/frpc"))
        assert "not verified" in binaries.provenance
    with pytest.raises(FetchError, match="together"):
        resolve(fetching=True, environ={"FRPS_BIN": "/opt/frp/frps"}, cache_dir=tmp_path)


def test_the_pins_file_pins_frp_0_61_1_for_linux_amd64() -> None:
    pins = load_pins(PINS_PATH)

    assert pins.version == "0.61.1"
    archive = pins.archives["linux_amd64"]
    assert archive.url == (
        "https://github.com/fatedier/frp/releases/download/v0.61.1/frp_0.61.1_linux_amd64.tar.gz"
    )
    assert len(archive.sha256) == 64


def pins_text(
    *, version: str = "0.61.1", url: str = "https://x/frp.tar.gz", sha256: str = "a" * 64,
    top: str = "", entry: str = "",
) -> str:
    return (
        f'version = "{version}"\n{top}[archives.linux_amd64]\n'
        f'url = "{url}"\nsha256 = "{sha256}"\n{entry}'
    )


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        (pins_text(top="extra = 1\n"), "unknown member"),
        (pins_text(entry="size = 1\n"), "unknown member"),
        (pins_text(version="latest"), "release such as"),
        (pins_text(url="http://x/frp.tar.gz"), "https URL"),
        (pins_text(url="https://x/"), r"\.tar\.gz archive"),
        (pins_text(sha256="A" * 64), "64 lowercase hex"),
        ('version = "0.61.1"\n', "table of platforms"),
    ],
)
def test_the_pins_format_refuses_what_it_does_not_define(
    tmp_path: Path, text: str, problem: str
) -> None:
    path = tmp_path / "frp-pins.toml"
    path.write_text(text)

    with pytest.raises(FetchError, match=problem):
        load_pins(path)
