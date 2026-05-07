#!/usr/bin/env python3
"""Generate PEP 503 simple index HTML files for a local package distribution directory.

Usage:
    python3 scripts/gen_simple_index.py <dist_dir>

Where <dist_dir> contains one subdirectory per package, each containing wheel
and/or sdist files::

    <dist_dir>/
      provisioning-service/
        provisioning_service-0.1.0-py3-none-any.whl
      market-service/
        market_service-0.1.0-py3-none-any.whl

The script writes:
  - ``<dist_dir>/<package>/index.html``  — links for each file in that package dir
  - ``<dist_dir>/index.html``             — links to each package subdirectory

Run this after every ``uv build`` invocation that populates a package directory.
The Makefile ``dist`` target calls this automatically.

The generated HTML is minimal PEP 503-compliant content.  SHA-256 hashes are
embedded in the href fragment so installers can verify integrity without a
separate signature file.

This script has no dependencies beyond the Python standard library.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


_DIST_EXTENSIONS = {".whl", ".tar.gz", ".zip"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_dist_file(path: Path) -> bool:
    return path.is_file() and any(
        path.name.endswith(ext) for ext in _DIST_EXTENSIONS
    )


def _write_package_index(pkg_dir: Path) -> int:
    """Write index.html for a single package directory. Returns file count."""
    files = sorted(f for f in pkg_dir.iterdir() if _is_dist_file(f))
    if not files:
        return 0

    pkg_name = pkg_dir.name
    links = "\n".join(
        f'<a href="{f.name}#sha256={_sha256(f)}">{f.name}</a>'
        for f in files
    )
    html = (
        "<!DOCTYPE html>"
        "<html>"
        f"<head><title>Links for {pkg_name}</title></head>"
        f"<body><h1>Links for {pkg_name}</h1>\n"
        f"{links}\n"
        "</body></html>"
    )
    (pkg_dir / "index.html").write_text(html, encoding="utf-8")
    return len(files)


def _write_root_index(dist_dir: Path) -> int:
    """Write the root index.html listing all package directories."""
    pkg_dirs = sorted(
        d for d in dist_dir.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )
    links = "\n".join(
        f'<a href="{d.name}/">{d.name}</a>' for d in pkg_dirs
    )
    html = (
        "<!DOCTYPE html>"
        "<html>"
        "<head><title>Simple index</title></head>"
        f"<body><h1>Simple index</h1>\n{links}\n</body></html>"
    )
    (dist_dir / "index.html").write_text(html, encoding="utf-8")
    return len(pkg_dirs)


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <dist_dir>", file=sys.stderr)
        sys.exit(1)

    dist_dir = Path(sys.argv[1])
    if not dist_dir.is_dir():
        print(f"Error: {dist_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    # Write per-package indexes
    total_files = 0
    for pkg_dir in sorted(dist_dir.iterdir()):
        if pkg_dir.is_dir() and not pkg_dir.name.startswith("."):
            count = _write_package_index(pkg_dir)
            if count:
                print(f"  {pkg_dir.name}/index.html  ({count} files)")
                total_files += count

    # Write root index
    pkg_count = _write_root_index(dist_dir)
    print(f"  index.html  ({pkg_count} packages)")
    print(f"Generated PEP 503 index in {dist_dir}  [{total_files} total files]")


if __name__ == "__main__":
    main()
