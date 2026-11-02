# Bare-metal lifecycle composition checkpoint

This is an **in-progress implementation checkpoint**, not acceptance or completed
domain qualification. The storefront foundation and recovery work cover 15.1;
15.2 and the bare-metal half of 7.4 remain open. The first foundation started at
458610d22; recovery continues from f283742ab. The surface is nonvisual; no
screenshots apply.

## Prepared setup

The prepared target is this checkout's bare-metal storefront app with real SQLite
persistence and the production lifecycle router. Site and payment boundaries use
the existing kit-backed regression setup; no external runtime is required.
Buyer, seller and administrator are explicitly deterministic public development
identities from that setup and must never be used on a public network.

The invocation owns its temporary database and in-process ASGI transport. It
starts and stops the application's lifespan and leaves no server or other
outside resource behind. It does not consume ignored configuration, inherited
deployment selectors or external credentials.

From the repository root:

~~~sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist
make -C domains/bare_metal/storefront reinit
(cd domains/bare_metal/storefront &&
  PYTHONPATH=tests uv run --find-links ../../../.dist python examples/lifecycle_first_use.py)
~~~

The same entry point also accepts `before-dispatch` and `create-in-flight`:

~~~sh
(cd domains/bare_metal/storefront &&
  PYTHONPATH=tests uv run --find-links ../../../.dist python examples/lifecycle_first_use.py before-dispatch &&
  PYTHONPATH=tests uv run --find-links ../../../.dist python examples/lifecycle_first_use.py create-in-flight)
~~~

The [entry point](../../../domains/bare_metal/storefront/examples/lifecycle_first_use.py)
uses the existing checkout regression setup, not an installed standalone service.
That setup has no registry publication configuration; its unrelated publication
timer may log that omission. No deployed-stack readiness is claimed.

## Observed first use

- The canonical signed lifecycle client sends hosted commit twice, and the
  seller starts exactly one fulfillment after verifying the payment receipt.
- The seller's bounded list includes the negotiation and the evidence store
  retains the exact acceptance transport envelope.
- Signed end-delivery and same-key retry preserve receipt time and one physical
  termination. The receipt carries the owning mediation contract's reusable
  signed claim.
- Delivery reads report tearing down, not released capacity.
- A different authenticated principal is refused as the buyer.

The additional modes surrender while scheduling is paused before dispatch and
while the existing create gate is held. Both receipts return without waiting for
the gate. On adoption, the first mode sends no create and releases the one hold;
the second terminates once. Neither discloses credentials. Verified payment
`approvedAt`, rather than negotiation acceptance, initializes commitment timing.

Temporary diagnostics also populate more than one bounded recovery page, recreate
the lifecycle composition, and observe the persisted continuation reaching the
last end without a payment adapter. A verified site termination retaining the
seller's exact source reference preserves its lawful classification and creates
no seller-failure filing. A synthetic report predating that request correctly did
not correlate; the corrected diagnostic uses the site's actual later instant.

This does not qualify an actual mediation service, respondent case execution,
authenticated site callback/pull transport or real hardware teardown.

## Regression and checks

- Existing bare-metal storefront suite: **522 passed**.
- Fresh wheel builds and affected generated locks: passed.
- Architecture, packaging, lock currency, comment hygiene and pinned strict
  OpenSpec validation: passed.
- The mounted first-use invocation above: passed.
- Shared servicing-kit typing and all existing first-use examples pass.
- The new loop is present even without payment publication and participates in
  the existing pause/step/timer controls. Existing loop-list expectations include
  it; no test function or acceptance assertion was removed or weakened.
- Full **`make test` passes in 6m59s**, including **1,858 release-tooling cases**
  and Helm structural/render assertions. It used the prescribed proxy exclusions
  and shell-local Podman shim. The aggregate retains one existing optional
  Torch-dependent VM collection skip; no new skip was added.
- Fresh-stack domain scenarios and real payments/mediation qualification remain
  **unrun**.

The initial regression run failed because registration did not begin the caller's
SQLite transaction. That is fixed. Availability now records the seller's own
observation instead of treating a site's fixture timestamp as its observation.
A locking approach which could wait on an in-flight create was removed: the end
remains pending until create adoption re-drives the effect. The first route drive
also caught the required delivery-end claim kind; the owning model now receives
it explicitly. Original kept assertions were not weakened, and no permanent
test function was added.

The continuation's initial regression found five expected-loop lists which did
not yet name the independent recovery loop. Those assertions now cover the
larger set, without removing any prior member. A temporary site-correlation
drive also caught a shadowed reservation lookup, repaired before its successful
re-drive. The first aggregate passed all package suites but failed three release
checks because the storefront's servicing dependency was not published and its
release-guide dependencies were stale. Separate repair `542b04638` registers
the servicing kit once, removes duplicate mediation manifest/workflow entries,
and states the exact storefront dependencies. Its focused 1,858-case rerun and
the final complete aggregate pass. No known failure is carried as unrelated.

## Remaining implementation

The recovery implementation adds a durable 100-deal page rotation and an
independent `delivery-recovery` loop. One failed authority read cannot suppress
physical retries or starve later pages. Respondent discovery resolves a case
against the full retained binding set, not just the current page. Terms expiry
and missed delivery deadlines are established through the end journal before
physical retry; a final access admission recheck follows the live access read.

A small shared-kit seam distinguishes accepted delivery metadata from verified
commitment: `DeliveryRecord.committed_at` may be absent until
`EndSession.confirm_commitment` binds it exactly once in the verified-evidence
transaction. Re-registration preserves that instant and pre-dispatch ends.
Public seller pages exclude uncommitted rows; recovery can explicitly include
them. Shared authorization/billing refuses to act on unverified commitment.
No VM source, dependency declaration, configuration model or wire codec changed.

Before completing 15.2 and the bare-metal half of 7.4, retain these prerequisites
and finish the following work:

- Mount authenticated site-report receipt and recover exact reports from lease
  reads; update neutral delivery progress only on proven release.
- Remove the unbegun teardown refusal and use the buyer half's canonical
  end-delivery method, durable end journal and evidence store.
- Compose hosted buyer commit instead of the settlement transport, leaving
  Alkahest and introduction paths unchanged.
- Extend the existing domain end/report stages and qualify the fresh
  mock-provisioned lane against ready local payment and mediation authorities
  with dispute-bearing options.

The real-host lane remains unavailable without an operator-owned host. Pending
work is not counted as passing. Permanent documentation promotion remains
reviewed closeout, with destinations recorded in the change's task checkpoint.

## Cleanup

No container, HTTP server, browser page, tunnel, remote deployment or external
runtime was created. Only checkout-owned package environments and managed
build/test commands were used.
