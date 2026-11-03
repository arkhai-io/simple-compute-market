## Why

Each harness authenticates to its model provider in its own way, with
credentials kept wherever it runs. Claude Code uses a subscription sign-in or an
API key. Codex uses a ChatGPT sign-in or an API key. A harness serving open
models uses its provider's API key. That works while every step runs on the
owner's own machine. It stops working once steps run anywhere else:

- **A hosted runner would need credentials in the cluster.** A personal
  credential placed there can be read by anyone with access to the pod that holds
  it. The owner's requirement is that a user's personal credential is never
  exposed to other users of the runner, and an API key should not have to leave
  its owner's machine at all.
- **Every harness and every environment would be a separate credential
  problem,** with no single place to reason about who can use which credential.
- **Cost is visible only harness by harness.** Claude Code reports dollars, Codex
  reports tokens, and an open-model provider reports whatever it reports. Nothing
  sees one change's spending across providers.

The long-term direction makes this sharper. Hosted agents for other parties would
need each party's own provider credentials, kept and used without the operator
of the runner ever holding them in a running container.

## What Changes

- **A model gateway for API-key providers.**
  - It speaks the provider APIs the harnesses use: Anthropic-compatible and
    OpenAI-compatible.
  - Harnesses reach it through their base-URL overrides. For Claude Code, that is
    the documented LLM-gateway configuration (`ANTHROPIC_BASE_URL` with a bearer
    token).
  - A harness holds only a short-lived, revocable token that is valid against the
    gateway alone, issued to one user.
- **Credential backends behind one interface.**
  - **First backend:** the credential stays on the user's own machine. A small
    local utility holds the key and keeps an outbound connection to a relay, so a
    remote runner can reach it while the key itself never leaves the machine.
  - **Later backend:** keys held in a secrets manager.
  - The interface a harness sees does not change between backends.
- **Providers as backends, not separate paths.** The Anthropic API, the OpenAI
  API, an open-model provider such as Venice, and a cloud inference service such
  as Vertex AI are all routes behind the gateway. A container needs no second
  authentication path for any of them.
- **Subscriptions stay outside the gateway.** Anthropic's terms for Claude Code
  permit a user to sign in to the unmodified Claude Code binary with their own
  subscription, including where it is hosted. They forbid routing requests
  through, or intermediating, subscription credentials. A subscription user
  therefore signs in through the provider's own flow in their own session, and
  nothing proxies the subscription. Codex's ChatGPT sign-in is per user in the
  same way.
- **Cost metered per change and per user.** The gateway records each request's
  usage against the run that made it, so a change's spending across providers is
  reported in one place.

## Capabilities

### New Capabilities

- Possibly a capability for the gateway, if design makes it a component in its own
  right, separate from the engine.

### Modified Capabilities

- `change-workflow`, or the engine capability: harnesses configured to reach the
  gateway, and cost recorded from it.

## Non-Goals

- **Do not build the hosted runner.** The gateway serves it, but is useful without
  it: local runs through the gateway gain cross-provider cost accounting.
- **Do not proxy subscription credentials,** for any provider.
- **Do not decide the secrets-manager backend's operation.** This change defines
  the backend interface and builds the local backend. Running a secrets-manager
  backend for other parties' keys is later work.
- **Do not inspect or filter request content.** Defending guidance against
  extraction is deferred.

## Impact

- A new gateway component and the local utility, at locations decided in design.
- `scripts/change_workflow/harness.py`, or the harness adapters once
  `add-workflow-harness-adapters` lands, for pointing each harness at the gateway.
- `scripts/change_workflow/cost.py` and `scripts/change_cost.py`, for cost metered
  at the gateway.
- The workflow's specification and architecture companion, and
  `docs/agents/change-workflow.md`.

## Dependencies and Related Changes

- **Independent:** nothing must land first, and the design discussion can start
  now.
- **`add-workflow-harness-adapters`.** Each adapter configures its harness to
  reach the gateway. Whichever lands second wires the other in.
- **The hosted runner change, still to be opened,** relies on this change so that
  no API key enters the cluster. It shares this change's constraint that each
  user's credentials are isolated from every other user.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `change-workflow`, or the engine
      capability `specify-change-workflow-and-engine` creates
- [ ] New subsystem specification, if the gateway becomes a capability of its own
- [ ] No permanent documentation change

The lesser goal's gap "Model credentials have no common path" in
`openspec/changes/README.md` is owned by this change and closes with it.

### Knowledge to promote

To be determined at design completion.
