# Market CLI Installer

The `market` CLI ships as a tarball attached to each GitHub Release. The
remote installer downloads the tarball, verifies its checksum, and runs
the bundled `install.sh` locally.

> A PyPI package is planned once the `arkhai` organization is approved.
> Once published, `pipx install arkhai-market` will be the recommended path.

## Install

```bash
curl -fsSL https://github.com/arkhai-io/simple-compute-market/releases/latest/download/install.sh | bash
```

Pin a specific version:

```bash
curl -fsSL https://github.com/arkhai-io/simple-compute-market/releases/latest/download/install.sh | \
  bash -s -- --version market-cli-v0.5.1
```

## Dev install (from a clone)

```bash
cd buyer
make init   # uv venv --python 3.12 + uv sync
```

Run via `uv run market <command>` from inside `buyer/`, or activate the
venv directly: `source buyer/.venv/bin/activate`.

## Requirements

- **OS**: macOS or Linux
- **Arch**: x86_64 or arm64
- **Python**: 3.12+
- **Tools**: `curl` or `wget`, `make`, `git`

## Release flow

```
┌──────────────────────────────────────────────────────────────┐
│ Trigger: push of tag `market-cli-v*.*.*` (or manual dispatch) │
│                                                              │
│ .github/workflows/release-cli.yml:                           │
│   1. Build market-cli.tar.gz (repo minus build artifacts)    │
│   2. Generate market-cli.tar.gz.sha256                       │
│   3. Copy scripts/install-remote.sh -> install.sh            │
│   4. Create GitHub Release with all three files attached     │
└──────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ End user: curl <release-url>/install.sh | bash               │
│                                                              │
│ install.sh (= scripts/install-remote.sh):                    │
│   1. Parse --version flag (default: latest)                  │
│   2. Download market-cli.tar.gz and .sha256                  │
│   3. Verify checksum                                         │
│   4. Extract and hand off to bundled install.sh              │
└──────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ Bundled install.sh (repo-root install.sh):                   │
│   1. Detect platform (macOS/Linux, x86_64/arm64)             │
│   2. Install system deps (curl, rsync, git, gcc, python3.12,│
│      jq) via apt on Linux; prompt to use brew on macOS       │
│   3. Install uv if missing                                   │
│   4. rsync the tarball contents to $MARKET_INSTALL_DIR        │
│      (default: ~/.market). .env files in target are preserved.│
│   5. uv sync --project ~/.market/buyer (no-dev)              │
│   6. Symlink ~/.local/bin/market -> ~/.market/buyer/.venv/bin/market │
│   7. Append ~/.local/bin to PATH in the user's shell rc      │
│   8. Verify with `market --help`                             │
└──────────────────────────────────────────────────────────────┘
```

## Versioning

Releases are tagged `market-cli-v{major}.{minor}.{patch}` (e.g.
`market-cli-v0.5.1`). The `latest` release pointer at GitHub always
resolves to the most recent published tag.

Manual dispatch (no tag) produces a `dev-{short-sha}` build that is
**not** published to a Release — the version string is only used in the
build summary. To get a tagged dev release, push a `market-cli-vX.Y.Z`
tag.

## Key Files

| File | Description |
|------|-------------|
| `install.sh` | Local installer (platform detection, deps, venv, symlink). Bundled inside the tarball. |
| `scripts/install-remote.sh` | Remote curl installer. Uploaded to each Release as `install.sh`. |
| `scripts/build-installer.sh` | Wraps the tarball into a self-extracting offline `market-installer.sh`. |
| `.github/workflows/release-cli.yml` | CI flow triggered by `market-cli-v*` tags. |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MARKET_INSTALL_DIR` | `~/.market` | Where the CLI is installed |

## Offline install

For air-gapped environments, build a self-extracting installer locally:

```bash
bash scripts/build-installer.sh
```

This produces `market-installer.sh` -- a single shell script with the
tarball embedded. Copy it to the target machine and run `bash market-installer.sh`.
