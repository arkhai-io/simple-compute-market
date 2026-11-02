# Payments contract foundation — implementer first use

Nonvisual library/CLI encounter (`visual: false`, no screenshots). This is
implementer evidence for the committed payments-kit surface, not independent
story acceptance, a real-HTTP drive, or evidence of a deployed authority.

## Scope and setup

The task requires a coherent published payments schema/vector pair, an installed
resource API, generated models, and one shared clock-injected authority fixture.
The prepared target is this checkout's built `arkhai-kit-arkhai-payments` wheel,
installed by `uv run --no-project`, not an editable source import or resident
service. Rebuild/replay from the repository root:

```sh
env -u ALL_PROXY -u all_proxy NO_PROXY=localhost,127.0.0.1 \
  no_proxy=localhost,127.0.0.1 make dist
env -u ALL_PROXY -u all_proxy NO_PROXY=localhost,127.0.0.1 \
  no_proxy=localhost,127.0.0.1 uv run --no-project --find-links .dist \
  --with .dist/arkhai_kit_arkhai_payments-0.3.0-py3-none-any.whl \
  python -m market_arkhai_payments.fixtures.conformance
```

Persona: a library consumer using the publisher's public deterministic development
accounts and signing key from the installed vectors, never credentials for a public
network. State: fixed-clock approvals, exact initial reservation funding, no shared
seed or external target. Readiness: the wheel imports its generated models and
loads both selected resources before any approval. The observed first-use command
exited zero. No HTTP listener, browser, container, tunnel or remote deployment was
started.

## Required claims and observations

| Claim / action | Observed result |
|---|---|
| Load the published schema and vectors from a built wheel | Both packaged byte streams equal their canonical vendored inputs; metadata exposes publication status and both SHA-256 hashes. Provenance is recorded only in the kit's `schema/SOURCE.md`. |
| Replay the publisher's mandate IDs, receipt framing/signature and attachments | All identities, exact receipt signature, attachment digests/sizes and approval Agreement hashes match. |
| Replay signed snapshots before and after start, after stops/ends, and clamped approval | Four complete signed snapshots match byte-for-byte, including zero-earned `settled` status and unchanged stored-mandate identity. |
| Replay rate reversals before/after stop | Nine total scenario steps pass across both scenarios; reversal amounts 41 then 81 preserve the original 262/6/256 stop settlement while feePaid changes to 4 after the second reversal. |
| Retry a payer stop whose response was lost | Same-key retries before/after the notice deadline return the original event/sequence, one notice, and the same prorated treatment. This is offline producer-fixture replay, not a lost HTTP response. |
| Share the authority algorithm | The in-process fake consumes `PaymentsAuthority`; the same installed class is available to an HTTP wrapper without any kit-to-tooling dependency. |
| Keep unsupported selections closed | `get_contract("proposed")` refuses by name: no payments candidate is needed for this publication. No mediation delivery-end payload or signing model is invented. |

An additional temporary installed-wheel diagnostic exercised two independent
extension refs on one once part, a lift that left the other hold open, a partial
300-unit reversal, the final lift/release of 700 gross with fee 17, and named
closed/missing/nonextendable/unauthorized refusals. Required nullable caps remain
in serialized mandate bytes. That diagnostic passed; the durable replay entry
point above owns the producer-vector evidence.

The publisher's integration-test evidence for chosen/end/reverse and its limits
are summarized in `kit/arkhai-payments/schema/SOURCE.md`; those results were not
re-run here or relabelled as real-HTTP qualification.

## Verification

Commands use `ALL_PROXY`/`all_proxy` unset and both `NO_PROXY`/`no_proxy` equal to
`localhost,127.0.0.1`, retaining HTTP(S) download proxies.

- `make -C kit/arkhai-payments test`: **92 tests pass**, mypy passes across 21
  source/example files, model/resource drift check passes, all producer vectors
  and signed-snapshot/scenario replays pass.
- `make check-architecture`, `make check-packaging`, `make check-comment-hygiene`
  and pinned OpenSpec strict validation pass. Packaging uses the repository's
  single-package wheel layout; packaged data is generated from the canonical
  schema/vector inputs and checked for byte drift.
- The first `make test` reached provisioning's **607 passing unit tests**, then
  failed its known proxy-sensitive unreachable-storefront assertion (`http_503`
  rather than an unreachable transport), with **453 other integration tests
  passing**. The located fixture now uses an unbound loopback destination;
  **all 454 provisioning integration tests pass** with the same assertions.
  This narrow fixture fix is a separate commit and is recorded on
  [#323](https://github.com/arkhai-io/simple-compute-market/issues/323).
- The aggregate `make test` rerun passed the package suites (including the
  payments kit's **92 tests** and provisioning's **454 integration tests**) and
  reached release-tooling, which reported **1 failed, 1809 passed, 18 skipped**.
  Its sole failure was
  `scripts/tests/test_multi_storefront_compose.py::test_storefront_authorities_are_isolated`:
  `FileNotFoundError: [Errno 2] No such file or directory: 'docker'`.
  `command -v docker` confirms that the Docker CLI is unavailable on this host.
  This environment prerequisite is recorded in
  [#324](https://github.com/arkhai-io/simple-compute-market/issues/324).
  The aggregate is **not green**; rerun it with Docker Compose v2 installed.
  No Docker-dependent assertion was skipped or weakened for this run.
- Verification used `env -u ALL_PROXY -u all_proxy
  NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1` before each command.
  The strict specification command was
  `bunx @fission-ai/openspec@1.14.0 validate agreed-evidence-and-early-termination --strict`.
  Environment setup's lockfile-format-only revisions were restored; no dependency
  or architecture-rule changes were required.

## Boundary and cleanup

Only the schema-required per-part migration of the existing once builder/check
was made: no start/stop permissions, existing reverse authorities, no extensions
and a zero extension cap. Lifecycle-derived holds/options and the replacement of
policy-level dispute configuration belong to the subsequent tasks and are not
implemented here. No permanent acceptance tests were added; kept assertions were
adapted to the deliberate per-part wire structure, not weakened.

No services or deployments remain running. The independent driver should use the
committed wheel/replay entry point, not a pre-existing virtual environment.
