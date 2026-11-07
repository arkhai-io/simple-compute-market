# VM site reports and buyer lifecycle wiring

Nonvisual implementer self-check, not independent acceptance. This packet covers
the application-wiring portion of VM task 14.5; its end/report e2e extensions and
fresh-stack qualification remain unrun.

## Prepared target and replay

The entry point owns temporary storefront SQLite, buyer evidence/end journal and
deterministic public development identities. Never use these fixture principals
on a public network. HTTP runs in process: signed VM lifecycle and site callback
routes, a vector-derived payment fixture, a signed typed provisioning lease read
and controlled physical teardown. No secret or resident service is required.
From repository root:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist
make -C domains/vms/storefront reinit
(cd domains/vms/storefront && PYTHONPATH=. uv run --locked \
  --find-links ../../../.dist python ../../../docs/attachments/vm-site-report/first_use.py)
```

The script opens the actual buyer half and canonical lifecycle client, then the
site callback receiver. It also invokes the real VM buyer CLI and stage as
`market end --from fixture --wait-timeout 1` with an injected recovered run context
and profile resolver. That CLI encounter uses real HTTP proofs, persistence,
evidence capture and end journaling; it does not qualify discovering a registry,
loading a real profile/run log or running a subprocess against a deployed stack.

The installed command was also opened directly:

```sh
(cd domains/vms/buyer && uv run --locked --find-links ../../../.dist market end --help)
```

## Observed application behavior

- Canonical buyer `commit` reaches the mounted VM seller with the accepted
  transaction and starts the existing delivery continuation.
- A site-authenticated callback with a forged inner report is refused. A valid
  report is retained once across fresh-request duplicates; changed signed
  content under the same event identity is refused.
- A signed typed lease read recovers the same report and an earlier report.
  Repeated recovery keeps both sources once, the earliest end and the first
  push's exact wrapper/headers. Site-signature and durable reservation/site
  binding verification are the same for push and pull.
- A buyer-authenticated read returns the exact site payload/proof. The buyer
  keeps it as a seller assertion unless it has independently established site
  trust; it does not elevate it into a financial authority fact.
- Surrender verifies and keeps the signed receipt. Same-key retry retains receipt
  time. Once-only payments report no supported stop; absent mediation credentials
  leave case progress unknown/retryable independently of accepted delivery.
- The report and termination acknowledgement stay tearing down. Only the
  capacity-return callback's local effect marks this delivered deal released.
  Existing callback regressions cover that authenticated route; the script
  invokes its local effect rather than simulating provider success.
- The CLI reports payment, receipt, case and capacity separately, and awaits
  signed capacity-return progress without an authority read blocking that wait.

Approval enforces admission policy before commitment; end recovery binds the
kept mandate and refuses a changed payer rather than applying new admission
policy to accepted work. Missing financial configuration removes that financial
capability, not receipt-only surrender. Alkahest settlement creation is unchanged.

## Validation and encountered corrections

The existing 213 VM buyer cases pass after changing their payment peer fixture
from the former settlement handoff to signed canonical commit. The 74 existing
focused site/callback/payment cases pass. No permanent test function was added
or kept assertion weakened; the static-callback test was renamed to distinguish
the dynamic lease-report route. Fresh wheels, architecture, packaging, locks and
comment hygiene pass. Full `make test` passes in 7m15s with the shell-local
Podman shim and proxy exclusions; the final application/packaging re-drive after
recovery-policy hardening passes as well. Strict OpenSpec validation passes.
Scoped citation checking reports only the three known future lifecycle-document
references tracked in [#325](https://github.com/arkhai-io/simple-compute-market/issues/325).

Preparation initially omitted the new lifecycle-client dependency from the
installed VM environment; wheel rebuild and lock refresh supplied it. Another
attempt serialized a mandate without wire aliases; the public artifact's wire
codec corrected it. The buyer regression's new peer transport initially supplied
transport twice; the fixture now replaces it. None remains unresolved.

The change declares the lifecycle client/contracts directly, refreshes buyer,
storefront and e2e lock closure and updates the unique existing release row.
No new distribution, configuration model or Helm schema is introduced. Shared
immutable-report retry behavior comes from the integrated servicing-kit fix,
not a second VM implementation.

## Remaining acceptance boundary

- Failure-source classification/correlation and direct failure-policy release
  remain unwired; site reports keep pending classification while physical work
  proceeds.
- Extend VM `e2e_deal` and `e2e_deal_buyer_cli` with end/report stages and prove
  callback-driven capacity return on a fresh branch-built stack.
- Qualify that stack through the shell-local Podman shim with real local payments
  and mediation, following [the integration recipe](../aeet-s8-integration/index.md).
- Leave shared buyer task 7.4 unchecked for parent integration and acceptance.

No fresh-stack lifecycle scenario, real local authority qualification, rate
mandate or notice execution is claimed. Permanent promotion remains reviewed
closeout to lifecycle spec/architecture, VM fulfillment and buyer-orchestration
documents. No shared-kit or sibling-domain source is changed by this continuation.
