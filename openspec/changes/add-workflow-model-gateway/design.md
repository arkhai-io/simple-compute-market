# Design: add the workflow model gateway

Status: design phase. Not planned. The owner has said the gateway's design needs
much more discussion, together with how harnesses other than Claude Code
authenticate. The direction under "Starting direction" is what the discussion
that opened the lesser goal settled. Everything under "Open questions" is
undecided.

## Context

- **How harnesses authenticate today.** An unattended step runs headless Claude
  Code, or Codex for a review, on the owner's machine, with whatever credentials
  that machine holds.
- **Claude Code's options.** Its authentication documentation describes:
  - `ANTHROPIC_BASE_URL` with `ANTHROPIC_AUTH_TOKEN` for routing through an LLM
    gateway that authenticates with bearer tokens;
  - an `apiKeyHelper`;
  - API keys;
  - for subscriptions, a long-lived token from `claude setup-token`
    (`CLAUDE_CODE_OAUTH_TOKEN`), which can only make model requests.
- **Anthropic's terms for subscriptions.** Claude Code's legal and compliance
  documentation permits an end user to sign in to the unmodified binary with their
  own subscription, including where a platform hosts Claude Code. It does not
  permit routing requests through subscription credentials on behalf of users, or
  collecting, storing, or intermediating subscription credentials. It also permits
  a party to provision its own API keys in a secrets manager for its own
  authorized users, billed to the key's owner and not resold.
- **Codex.** It supports a ChatGPT sign-in by device code for machines without a
  browser, or a copied `auth.json`, and API keys. A custom provider can name its
  base URL.
- **Cost today.** `scripts/change_workflow/cost.py` records a Claude run's dollars
  and a Codex review's tokens on each run's log line.

## Starting direction

- **One auth layer for API-key providers.** The gateway replaces a second path,
  such as Vertex alone, rather than sitting beside it.
- **An API key never enters the cluster.** In the first backend, the user's own
  machine holds it, and a local utility serves the gateway's requests for that
  user. Users do not install harnesses locally or run harness work locally; the
  utility is an authentication layer only.
- **The backend graduates without changing the interface.** The same gateway later
  runs in the cluster against a secrets manager, holding each party's own keys.
- **Subscriptions are signed in per user** through the provider's flow and never
  proxied.
- **Each user's credentials must be protected from every other user.** This is to
  be scrutinized heavily, with the hosted runner's design.

## Open questions

- **Build or adopt.** A small purpose-built proxy, or an existing LLM gateway
  configured for this use. The answer turns on protocol fidelity, how much of an
  existing gateway's surface would need locking down, and how a per-user token
  binds to a per-user backend.
- **Reaching the user's machine.** The relay that lets a remote runner reach a
  laptop's utility through the laptop's outbound connection. Open points:
  - how the relay authenticates both ends;
  - how it stops one user's runner from reaching another user's utility;
  - what happens to a running step when the laptop sleeps or disconnects. It
    should wait and retry, not fail mid-step.
- **Tokens.** A token's lifetime, its scope (one session, one change, or one user),
  how it is revoked, and how it reaches the user's own runner without passing
  through anything another user can read.
- **Protocol fidelity.** Streaming, prompt caching, tool use, and each harness's
  expectations about headers must pass through unchanged. Which of Claude Code's,
  Codex's, and the open-model harness's features survive a gateway is checked,
  not assumed.
- **Request content.** The gateway sees every prompt: code, guidance, and records.
  Whether it logs content at all; by default it should not persist it. How that
  is stated and verified.
- **Cost metering.** How a request is attributed to a run, for example a run
  identifier the harness sends. How gateway-metered cost relates to the cost each
  harness reports on its own run line, and which one is authoritative when they
  differ.
- **Cloud inference services.** A cloud service such as Vertex AI authenticates by
  service identity, not by API key. Whether it is a backend of the
  secrets-manager kind, or a kind of its own.
- **Where the code lives.** Inside the engine, beside it as a separate component,
  or as its own distribution. The local utility is installed on every user's
  machine, so its footprint matters.
- **Subscription users on a hosted runner.** The direction is to sign in inside
  their own pod. Whether the gateway plays any part for them, such as metering
  through Claude Code's own cost reporting, or none.
