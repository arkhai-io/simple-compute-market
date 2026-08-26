#!/usr/bin/env python3
"""Every consumer pins the same hosted client, or the tree says which does not.

`kit/hosted-settlement/pyproject.toml` is where the version a run must obtain is
stated -- `select-hosted-client-channel.py` derives the entire binding from it.
Two other distributions pin the same package, and nothing related them, so a
raised contract could land in one and not the others. That disagreement surfaces
today as a resolver error naming a version nobody wrote down, in whichever lane
happens to install first.

This states it where it happened instead, and `--fix` moves the followers to the
version the source names.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PIN = re.compile(r"(arkhai-hosted-settlement-client==)([0-9]+\.[0-9]+\.[0-9]+)")

#: Where the version is stated. The channel selector reads this same file.
SOURCE = Path("kit/hosted-settlement/pyproject.toml")
#: Distributions that must consume the version the source names.
FOLLOWERS = (
    Path("domains/bare_metal/storefront/pyproject.toml"),
    Path("domains/bare_metal/buyer/pyproject.toml"),
)


class PinUndecidable(RuntimeError):
    """A file states no hosted client version, or more than one."""


def pinned(path: Path) -> str:
    found = sorted(set(match.group(2) for match in _PIN.finditer(path.read_text("utf-8"))))
    if len(found) != 1:
        raise PinUndecidable(f"{path} states {len(found)} hosted client versions; one is required")
    return found[0]


def disagreements(root: Path) -> tuple[str, list[tuple[Path, str]]]:
    expected = pinned(root / SOURCE)
    return expected, [
        (path, pinned(root / path)) for path in FOLLOWERS if pinned(root / path) != expected
    ]


def rewrite(root: Path, path: Path, expected: str) -> None:
    target = root / path
    text = target.read_text("utf-8")
    target.write_text(_PIN.sub(rf"\g<1>{expected}", text), "utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_REPO_ROOT)
    parser.add_argument(
        "--fix", action="store_true", help="move the followers to the version the source names"
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        expected, wrong = disagreements(root)
    except (PinUndecidable, OSError) as exc:
        print(f"hosted client pin: {exc}", file=sys.stderr)
        return 1
    if not wrong:
        print(f"OK: every consumer pins hosted client {expected}")
        return 0
    for path, found in wrong:
        if args.fix:
            rewrite(root, path, expected)
            print(f"fixed: {path} {found} -> {expected}")
        else:
            print(
                f"{path} pins hosted client {found}, but {SOURCE} names {expected}",
                file=sys.stderr,
            )
    if args.fix:
        print("re-lock the affected projects before building")
        return 0
    print("run scripts/check-hosted-client-pin.py --fix to move them", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
