# Market CLI Installer

Cross-platform installer for the packaged `market` CLI. This installer is a
thin CLI/bootstrap surface: it installs the repo into `~/.market`, creates the
runtime virtualenv at `core/.venv`, and exposes `~/.local/bin/market`. It does
not claim to install the full production role-wrapper surface.

## Installation Methods

### Remote Install (Latest)

```bash
curl -fsSL https://us-central1-ww-migration-arkhai.cloudfunctions.net/downloadMarketCli | bash
```

### Remote Install (Specific Version)

```bash
curl -fsSL https://us-central1-ww-migration-arkhai.cloudfunctions.net/downloadMarketCli | bash -s -- --version market-cli-v1.0.0
```

### Self-Extracting Script (Offline)

```bash
bash market-installer.sh
```

### Manual Development Install

```bash
cd core
uv sync
```

## Requirements

- **OS**: macOS or Linux
- **Architecture**: x86_64 or arm64
- **Python**: 3.12+
- **Tools**: curl or wget, git, rsync

## Overall Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        CI/CD Pipeline                           │
│  Tag push (market-cli-v*) or manual dispatch                   │
│                                                                 │
│  1. Checkout repo                                               │
│  2. Determine version from tag or dev-{sha}                    │
│  3. Build canonical tarball via scripts/build_package_tarball.py│
│  4. Upload tarball + checksum to GCS                           │
│  5. Create GitHub Release                                      │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     GCS Bucket Layout                           │
│  gs://ww-migration-arkhai-installer-files/                     │
│  ├── install.sh                  (remote installer entry point) │
│  ├── releases/                                                   │
│  │   ├── latest/                                                 │
│  │   └── {CLI_VERSION}/                                          │
│  └── checksums/                                                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      install.sh                                 │
│                                                                 │
│  1. Detect platform (macOS/Linux) and arch (x86_64/arm64)       │
│  2. Validate Python 3.12+ is installed                          │
│  3. Install/verify uv v0.8.13                                   │
│  4. Copy project files to ~/.market                             │
│  5. Sync the CLI runtime into core/.venv                        │
│  6. Symlink ~/.local/bin/market → ~/.market/core/.venv/bin/market │
│  7. Add ~/.local/bin to PATH in shell RC file                   │
│  8. Verify: market --help                                       │
└─────────────────────────────────────────────────────────────────┘
```

## Canonical Packaging

The release workflow, offline installer builder, and manual upload script all
delegate to the same tarball builder:

```bash
python scripts/build_package_tarball.py --output market-cli.tar.gz
```

That builder consumes the canonical package manifest in
`scripts/package_manifest.py`, including the installed layout and tarball
include/exclude rules.

## Install Contract

The packaged install contract is:

- repo root: `~/.market`
- runtime venv: `~/.market/core/.venv`
- installed entrypoint: `~/.local/bin/market`

The installer intentionally stops at a working `market` CLI. It does not pull
Docker images, authenticate to GCP, or claim that the production role wrappers
under `scripts/` are supported from the installed bundle.

If you want local agent/registry/contracts dependencies inside the installed
checkout, run:

```bash
market install
```

That command uses the canonical contracts dependency contract:

```bash
npm ci --legacy-peer-deps
```

## Versioning

Releases follow the tag format `market-cli-v{major}.{minor}.{patch}`.

- **Tagged builds** → `/releases/{CLI_VERSION}/market-cli.tar.gz`
- **Dev builds** → `/releases/dev-{short-sha}/market-cli.tar.gz`
- **Latest** → `/releases/latest/market-cli.tar.gz`
- **Checksums** → `/checksums/{CLI_VERSION}.sha256`

## Key Files

| File | Description |
|------|-------------|
| `install.sh` | Main thin installer (platform detection, venv setup, symlinks) |
| `scripts/install-remote.sh` | Remote cURL installer that downloads the tarball and hands off to `install.sh` |
| `scripts/build_package_tarball.py` | Canonical tarball builder used by release/build/upload surfaces |
| `scripts/build-installer.sh` | Builds the self-extracting `market-installer.sh` for offline use |
| `scripts/upload-gcs.sh` | Manual upload script for pushing canonical tarballs to GCS |
| `.github/workflows/release-cli.yml` | CI/CD workflow triggered by `market-cli-v*` tags or manual dispatch |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MARKET_INSTALL_DIR` | `~/.market` | Where the repo payload is installed |
| `CLI_VERSION` | latest | Target version for remote installs |
| `GCS_BUCKET` | `ww-migration-arkhai-installer-files` | GCS bucket name (CI/CD and upload script only) |
| `GCS_STG_WRITER_KEY` | — | GCP service account credentials (CI/CD secret) |

## After Install

Installing the CLI is only the first step. After `market --help` works, choose
the path that matches your role:

- start with [docs/role-entrypoints.md](docs/role-entrypoints.md)
- buyers:
  - [docs/standup/buyer-quickstart.md](docs/standup/buyer-quickstart.md)
- sellers:
  - onboarding:
    - [docs/standup/seller-onboarding.md](docs/standup/seller-onboarding.md)
  - [docs/standup/seller-quickstart.md](docs/standup/seller-quickstart.md)
- platform operators:
  - [docs/standup/platform-quickstart.md](docs/standup/platform-quickstart.md)
- compute host operators:
  - [docs/standup/host-quickstart.md](docs/standup/host-quickstart.md)
- support operators:
  - [docs/standup/support-quickstart.md](docs/standup/support-quickstart.md)

Important: the installed bundle supports the generic `market` entrypoint. The
production-facing buyer, seller, platform, host, and support role wrappers are
repo-checkout surfaces today, not supported installed entrypoints.

## Creating a Dev Build

Dev builds are created by triggering the CI/CD workflow manually (without a
`market-cli-v*` tag). The version will be `dev-{short-sha}`.

**GitHub UI**: Go to Actions → "Release Market CLI" → "Run workflow".

**GitHub CLI**:

```bash
gh workflow run release-cli.yml
```

The tarball is uploaded to `/releases/dev-{sha}/market-cli.tar.gz` in the GCS
bucket and can be installed with:

```bash
curl -fsSL https://us-central1-ww-migration-arkhai.cloudfunctions.net/downloadMarketCli | bash -s -- --version dev-abc1234
```

## Testing

Build the offline installer locally:

```bash
bash scripts/build-installer.sh
```

Build the canonical tarball locally:

```bash
python scripts/build_package_tarball.py --output /tmp/market-cli.tar.gz
```
