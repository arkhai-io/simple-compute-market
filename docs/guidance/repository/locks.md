---
tags: [repository, packaging, uv]
---

# Locks

How this repository's locks are written and kept steady between uv releases, as
[`packaging-uv.md`](../engineering/packaging-uv.md) gives the relock and the stated
minimum uv.

## Locks

`make lock` is the relock
([`packaging-uv.md`, "Relock against fresh artifacts"](../engineering/packaging-uv.md#relock-against-fresh-artifacts)),
building the wheelhouse first and installing nothing; `make lock PROJECTS="kit/site
core/buyer"` narrows it. `check-locks` compares names and specifiers but not markers,
so it does not stand in for the relock, and neither does `make test`.

Locks are written by uv 0.12.22 or newer, the first release that writes lock revision 5,
the revision every committed lock carries
([`packaging-uv.md`, "Locks are written by a stated minimum uv"](../engineering/packaging-uv.md#locks-are-written-by-a-stated-minimum-uv)).
Two checks hold the locks steady between uv releases:

- `scripts/uv_project.py` refuses a uv older than the minimum, naming both versions,
  before its `lock` and `reinit` commands run uv, so the repository's relock and
  environment refresh — `make lock`, `make review-locks`, and each package's `make
  reinit` and `make init` — refuse before writing. `make lock` also runs `make
  check-uv-version` first, so it refuses before building the wheelhouse; change
  validation runs it before building anything. A plain `uv run` that relocks a changed
  project is not guarded.
- `check-locks` fails on a lock carrying any revision but 5, naming the lock and both
  revisions.

The minimum is `MINIMUM` in `scripts/check_uv_version.py`, and the revision
`LOCK_REVISION` in `scripts/check_locks.py`; CI's `tests.yml` and `e2e.yml` install the
minimum, uv 0.12.22. A lock that names internal packages is brought to the running
uv's revision by `make lock PROJECTS=<its project>`, which rewrites it; `make lock`
upgrades nothing in any other lock, which is relocked in its project as
[`packaging-uv.md`, "Locks are written by a stated minimum uv"](../engineering/packaging-uv.md#locks-are-written-by-a-stated-minimum-uv)
says, after `make check-uv-version`.

Relocking needs the indexes each lock resolves from. `domains/vms/buyer` and
`domains/vms/storefront` declare the PyTorch CPU index, so relocking them needs
`download.pytorch.org`; resolution fetches metadata only, not the wheels.
