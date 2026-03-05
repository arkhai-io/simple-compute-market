# Market CLI Installer

Cross-platform installer for the Market CLI, supporting both offline and cloud-based distribution via Google Cloud Storage.

## Installation Methods

### Remote Install (Latest)

```bash
curl -sL https://storage.googleapis.com/ww-migration-installer-stg/install.sh -o install.sh
bash install.sh
```

### Remote Install (Specific Version)

```bash
curl -sL https://storage.googleapis.com/ww-migration-installer-stg/install.sh -o install.sh
bash install.sh --version cli-v1.0.0
```

### Self-Extracting Script (Offline)

```bash
bash market-installer.sh
```

### Manual Development Install

```bash
cd cli
uv venv
uv pip install -e .
```

## Requirements

- **OS**: macOS or Linux
- **Architecture**: x86_64 or arm64
- **Python**: 3.10+
- **Tools**: curl or wget, make, git

## Overall Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        CI/CD Pipeline                           │
│  Tag push (cli-v*) or manual dispatch                           │
│                                                                 │
│  1. Checkout repo                                               │
│  2. Determine version from tag or dev-{sha}                     │
│  3. Create tarball (excluding .git, .venv, __pycache__, etc.)   │
│  4. Authenticate to GCP via GCS_STG_WRITER_KEY                  │
│  5. Upload to GCS bucket                                        │
│  6. Create GitHub Release                                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     GCS Bucket Layout                           │
│  gs://ww-migration-installer-stg/                               │
│  ├── install.sh                  (remote installer entry point) │
│  ├── market-cli-latest.tar.gz    (always latest build)          │
│  ├── cli-v1.0.0/                                                │
│  │   └── market-cli.tar.gz       (pinned release)               │
│  └── dev-a1b2c3d/                                               │
│      └── market-cli.tar.gz       (dev build)                    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              User Runs Remote Installer                         │
│  curl ... -o install.sh && bash install.sh                      │
│                                                                 │
│  install-remote.sh:                                             │
│  1. Parse --version flag (optional)                             │
│  2. Download tarball from GCS (latest or versioned)             │
│  3. Extract to temp directory                                   │
│  4. Call bundled install.sh                                      │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      install.sh                                 │
│                                                                 │
│  1. Detect platform (macOS/Linux) and arch (x86_64/arm64)       │
│  2. Validate Python 3.10+ is installed                          │
│  3. Install/verify uv v0.8.13                                   │
│  4. Copy project files to ~/.market                             │
│  5. Create Python venv in cli/.venv                             │
│  6. Run: uv pip install -e .                                    │
│  7. Symlink ~/.local/bin/market → ~/.market/cli/.venv/bin/market │
│  8. Add ~/.local/bin to PATH in shell RC file                   │
│  9. Verify: market --help                                       │
└─────────────────────────────────────────────────────────────────┘
```

### Build Phase

The CI/CD pipeline (`.github/workflows/release-cli.yml`) triggers on `cli-v*` tag pushes or manual dispatch. It creates a tarball of the repository excluding build artifacts:

```bash
tar czf market-cli-latest.tar.gz \
  --transform 's,^\./,market-cli/,' \
  --exclude='.git' --exclude='__pycache__' --exclude='.venv' ...
```

For offline distribution, `scripts/build-installer.sh` wraps the tarball into a single self-extracting shell script (`market-installer.sh`).

### Upload Phase

The workflow authenticates to GCP using the `GCS_STG_WRITER_KEY` secret and uploads three artifacts:

| File | Destination | Purpose |
|------|-------------|---------|
| `market-cli-latest.tar.gz` | Bucket root | Always points to the latest build |
| `market-cli.tar.gz` | `/{CLI_VERSION}/` | Version-pinned release |
| `install.sh` | Bucket root | Remote installer entry point |

### Download & Extract Phase

When a user runs the remote installer (`scripts/install-remote.sh`):

1. Detects available download tool (curl or wget)
2. Downloads the tarball from GCS — latest or a specific `--version`
3. Extracts to a temporary directory
4. Hands off to the bundled `install.sh`

### Install Phase

The main script (`install.sh`) handles:

1. **Platform detection** — OS (macOS/Linux) and architecture (x86_64/arm64)
2. **Python validation** — Ensures Python 3.10+ is available
3. **uv installation** — Installs or verifies `uv` v0.8.13
4. **File copy** — Copies project to `$MARKET_INSTALL_DIR` (default: `~/.market`)
5. **Virtual environment** — Creates a venv in `cli/.venv`
6. **CLI install** — Runs `uv pip install -e .` (editable install)
7. **Symlink** — Creates `~/.local/bin/market` pointing to the venv binary
8. **Shell integration** — Adds `~/.local/bin` to PATH in `.zshrc`, `.bashrc`, or `config.fish`
9. **Verification** — Runs `market --help` to confirm success

## Versioning

Releases follow the tag format `cli-v{major}.{minor}.{patch}` (e.g., `cli-v1.0.0`).

- **Tagged builds** → `/{CLI_VERSION}/market-cli.tar.gz`
- **Dev builds** → `/dev-{short-sha}/market-cli.tar.gz`
- **Latest** → always updated at root as `market-cli-latest.tar.gz`

## Key Files

| File | Description |
|------|-------------|
| `install.sh` | Main installation script (platform detection, venv setup, symlinks) |
| `scripts/install-remote.sh` | Remote cURL installer — downloads tarball from GCS then calls `install.sh` |
| `scripts/build-installer.sh` | Builds the self-extracting `market-installer.sh` for offline use |
| `scripts/upload-gcs.sh` | Manual upload script for pushing artifacts to GCS |
| `.github/workflows/release-cli.yml` | CI/CD workflow triggered by `cli-v*` tags or manual dispatch |
| `Dockerfile.installer-test` | Docker image for testing the installer in a clean environment |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MARKET_INSTALL_DIR` | `~/.market` | Where the CLI is installed |
| `CLI_VERSION` | latest | Target version for remote installs |
| `GCS_BUCKET` | `ww-migration-installer-stg` | GCS bucket name |
| `GCS_STG_WRITER_KEY` | — | GCP service account credentials (CI/CD secret) |

## Creating a Dev Build

Dev builds are created by triggering the CI/CD workflow manually (without a `cli-v*` tag). The version will be `dev-{short-sha}`.

**GitHub UI**: Go to Actions → "Release Market CLI" → "Run workflow".

**GitHub CLI**:

```bash
gh workflow run release-cli.yml
```

The tarball is uploaded to `/dev-{sha}/market-cli.tar.gz` in the GCS bucket and can be installed with:

```bash
curl -sL https://storage.googleapis.com/ww-migration-installer-stg/install.sh -o install.sh
bash install.sh --version dev-abc1234
```

## Testing

Run the installer in a clean Docker container:

```bash
docker build -f Dockerfile.installer-test .
```

Test against a remote URL:

```bash
docker build -f Dockerfile.installer-test \
  --build-arg INSTALLER_URL=https://storage.googleapis.com/ww-migration-installer-stg/install.sh .
```
