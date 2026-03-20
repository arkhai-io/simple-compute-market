# Market Agent

A base ReAct agent built with Google's Agent Development Kit (ADK)
Agent generated with [`googleCloudPlatform/agent-starter-pack`](https://github.com/GoogleCloudPlatform/agent-starter-pack) version `0.16.0`

## Project Structure

This project is organized as follows:

```
core/agent/
├── app/                 # Core Python package modules
├── packages/            # Shared agent packages and integrations
├── scripts/             # Operational scripts
├── Makefile             # Make targets for core-agent workflows
└── README.md            # This file
```

Project tooling root:
- `core/pyproject.toml` (single project config)
- `core/.venv` (single virtual environment)
- Commands in `core/agent/Makefile` are wired to use the parent project via `uv --project ..`.

## Requirements

Before you begin, ensure you have:
- **uv**: Python package manager (used for all dependency management in this project) - [Install](https://docs.astral.sh/uv/getting-started/installation/) ([add packages](https://docs.astral.sh/uv/concepts/dependencies/) with `uv add <package>`)
- **Google Cloud SDK**: For GCP services - [Install](https://cloud.google.com/sdk/docs/install)
- **Terraform**: For infrastructure deployment - [Install](https://developer.hashicorp.com/terraform/downloads)
- **make**: Build automation tool - [Install](https://www.gnu.org/software/make/) (pre-installed on most Unix-based systems)


## Quick Start (Local Testing)

Install required packages and launch the local development environment:

```bash
make install && make playground
```

## Commands

| Command              | Description                                                                                 |
| -------------------- | ------------------------------------------------------------------------------------------- |
| `make install`       | Install all required dependencies using uv                                                  |
| `make register`      | Register agent on-chain before starting |
| `make serve-a2a`     | Start A2A agent server (requires on-chain registration first) |
| `make playground`    | Launch local development environment with backend and frontend - leveraging `adk web` command.|
| `make import-resources` | Import resource portfolio rows from CSV into Agent DB |
| `make backend`       | Deploy agent to Cloud Run (use `IAP=true` to enable Identity-Aware Proxy) |
| `make local-backend` | Launch local development server |
| `make test`          | Run unit and integration tests                                                              |
| `make lint`          | Run code quality checks (codespell, ruff, mypy)                                             |
| `make setup-dev-env` | Set up development environment resources using Terraform                         |
| `uv run jupyter lab` | Launch Jupyter notebook                                                                     |

For full command options and usage, refer to the [Makefile](Makefile).

### Resource Portfolio CSV Import

Import resources into the local Agent DB:

```bash
make import-resources CSV=path/to/resources.csv
```

Try the bundled sample:

```bash
make import-resources CSV=app/data/resources.sample.csv DRY_RUN=true
```

Optional:

- `ENV_FILE=.env` (env file for `AGENT_DB_PATH`)
- `DB_PATH=/tmp/agent.db` (explicit DB path override)
- `DRY_RUN=true` (validate/report only, no DB write)

## Agent Registration Workflow

Register your agent on-chain **before** starting the agent server:

### Step 1: Register On-Chain

```bash
# Configure your .env file with:
# - AGENT_PRIV_KEY
# - CHAIN_RPC_URL
# - IDENTITY_REGISTRY_ADDRESS
# - AGENT_WALLET_ADDRESS
# - CHAIN_ID (optional, defaults to 1337)

make register
```

This will:
- Register your agent on the ERC-8004 IdentityRegistry contract
- Output the numeric agent ID (e.g., `22`)
- Output the canonical agent ID (e.g., `eip155:1337:0x...:22`)
- Optionally update your `.env` file with `ONCHAIN_AGENT_ID`

### Step 2: Start Agent

```bash
make serve-a2a
```

The agent will use the `ONCHAIN_AGENT_ID` from your `.env` file (or find it automatically via blockchain events) to build the canonical ID for heartbeats and API calls.

**Why this approach?**
- ✅ Idempotent: safe to run multiple times (finds existing registration)
- ✅ Clear workflow: explicit registration step before starting agent


## Usage

This template follows a "bring your own agent" approach - you focus on your business logic, and the template handles everything else (UI, infrastructure, deployment, monitoring).

1. **Prototype:** Build your Generative AI Agent using the intro notebooks in `notebooks/` for guidance. Use Vertex AI Evaluation to assess performance.
2. **Integrate:** Import your agent into the app by editing `app/agent.py`.
3. **Test:** Explore your agent functionality using the Streamlit playground with `make playground`. The playground offers features like chat history, user feedback, and various input types, and automatically reloads your agent on code changes.
4. **Deploy:** Set up and initiate the CI/CD pipelines, customizing tests as necessary. Refer to the [deployment section](#deployment) for comprehensive instructions. For streamlined infrastructure deployment, simply run `uvx agent-starter-pack setup-cicd`. Check out the [`agent-starter-pack setup-cicd` CLI command](https://googlecloudplatform.github.io/agent-starter-pack/cli/setup_cicd.html). Currently supports GitHub with both Google Cloud Build and GitHub Actions as CI/CD runners.
5. **Monitor:** Track performance and gather insights using Cloud Logging, Tracing, and the Looker Studio dashboard to iterate on your application.

The project includes a `GEMINI.md` file that provides context for AI tools like Gemini CLI when asking questions about your template.


## Deployment

> **Note:** For a streamlined one-command deployment of the entire CI/CD pipeline and infrastructure using Terraform, you can use the [`agent-starter-pack setup-cicd` CLI command](https://googlecloudplatform.github.io/agent-starter-pack/cli/setup_cicd.html). Currently supports GitHub with both Google Cloud Build and GitHub Actions as CI/CD runners.

### Dev Environment

You can test deployment towards a Dev Environment using the following command:

```bash
gcloud config set project <your-dev-project-id>
make backend
```


The generic `make backend` workflow comes from the upstream agent-starter-pack scaffold. For the repo-specific production stand-up path, start with:

- `docs/standup/overview.md`
- `docs/standup/agent-seller.md`
- `docs/standup/agent-buyer.md`

### Production Deployment

Use the repo's canonical production runbooks rather than the missing scaffold docs:

- `docs/standup/overview.md` for the full stack deployment order
- `docs/standup/agent-seller.md` for the seller agent deployment path
- `docs/standup/agent-buyer.md` for the buyer agent deployment path


## Monitoring and Observability
> You can use [this Looker Studio dashboard](https://lookerstudio.google.com/reporting/46b35167-b38b-4e44-bd37-701ef4307418/page/tEnnC
) template for visualizing events being logged in BigQuery. See the "Setup Instructions" tab to getting started.

The application uses OpenTelemetry for comprehensive observability with all events being sent to Google Cloud Trace and Logging for monitoring and to BigQuery for long term storage.
