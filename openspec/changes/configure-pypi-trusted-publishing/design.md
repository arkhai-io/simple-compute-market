## Context

The release workflow lists 22 packages; only a subset has matching live PyPI projects and GitHub environments. Five additional consumable runtime distributions are absent from the matrix, path triggers omit provisioning/bare-metal areas, release documentation lags names/versions, and stale pre-rename environments remain. External setup cannot be completed safely until the package graph builds without source overrides and intended public interfaces stabilize.

## Goals / Non-Goals

**Goals:** authoritative consumable inventory; complete trusted-publisher mapping; source-free builds/installs; verified publication.

**Non-Goals:** publishing demos/test harnesses by default or changing package APIs during external setup.

## Decisions

- Generate/reconcile one reviewed release inventory from current distribution metadata, with explicit inclusion rationale and external environment/project name.
- Gate external setup on `uv build --no-sources`, wheel inspection, and clean dependency-ordered install for every included distribution.
- Use one protected GitHub environment per current distribution and least-privilege PyPI trusted publisher bound to the release workflow/branch.
- Verify downstream role installation from PyPI without `.dist` or repository checkout before declaring completion.
- Keep stale renamed environments until current-name projects publish successfully and repository/workflow references are absent.

## Risks / Trade-offs

- **[Name squatting or missing PyPI admin access]** → Record external owner/blocker and do not claim implementation readiness.
- **[Dependency publication order fails]** → Derive and test topological order from package metadata.
- **[Workflow publishes unintended package]** → Require inventory diff/review and per-package environment protection.
- **[Published wheel depends on source paths]** → Gate on no-sources build and clean PyPI-only smoke install.

## Activation Record Required

- Completed predecessor changes and clean package graph.
- Named PyPI/GitHub administrators and scheduled setup window.
- Final reviewed included/excluded distribution inventory and dependency order.
- Release branch/environment protection decision.

## Permanent Documentation Promotion

Accepted publication inventory, build guarantees, and external setup procedure belong in `openspec/specs/deployment-state/spec.md`/`architecture.md` and `docs/development/RELEASING.md`. External credentials/secrets are never recorded in repository artifacts.
