# Bare-metal lifecycle implementation and local qualification

This records implementation and local qualification, not independent acceptance.
The storefront foundation and recovery cover 15.1; canonical buyer/site ingress
and fresh-stack qualification cover 15.2. Section 7.4 remains parent-owned. The first foundation started at
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

This does not qualify an actual mediation service, respondent case execution
or real hardware teardown. The continuation below drives callback/pull transport
through the mounted in-process application.

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
- Fresh-stack domain scenarios and real payments/mediation qualification were
  **unrun at that checkpoint**; the final observed runs are recorded below.

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

## Prior recovery checkpoint

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

That checkpoint left the following work. The continuation below implements the
code paths while keeping deployed qualification open:

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

## Canonical buyer and site-report continuation

The continuation composes hosted commit and buyer end through `BuyerLifecycle`
with the profile-adjacent file evidence store and its durable end journal.
`market bare-metal teardown --run-id <run>` prints separate payment, delivery
and case outcomes; `market bare-metal delivery --run-id <run>` reads their
independent records. The old domain teardown HTTP route and settlement transport
are removed. Alkahest settlement and contact introduction remain on their
existing paths. A synchronous command uses a short-lived event-loop thread so
an application embedding the CLI can already own an event loop.

The accepted site's authenticated `lease-ended` callback retains the exact
report and verifies both the transport's service identity and the report proof
against that reservation's site. The independent recovery loop reads the
selected site's lease and retains the same original signed report when push is
missed. The site's routing binding survives release for later report recovery.
An intended-end report leaves progress at `tearing_down`; only the separate
release callback or an authenticated released lease advances it to `released`.

The existing first-use entry point now drives report push, refreshed transport
retries, lease-read recovery, wrong-site refusal, exact report reads and the
separate proven-release callback. All three invocations above pass. The existing
CLI integration also reopens the buyer composition, retries surrender, and
observes unchanged receipt/observation time and retained observation/receipt
evidence with one physical termination:

~~~sh
(cd domains/bare_metal/storefront && uv run --find-links ../../../.dist pytest -q \
  tests/integration/test_payment_settlement_client.py)
~~~

Two minimal shared fixes accompany the domain work: receipt acknowledgement does
not require an installed dispute adapter (nor invent a refund), and report
replay compares the immutable signed report rather than requiring refreshed
push headers to equal pull's absent headers. The first exact body and headers
remain retained. No VM production source, configuration model or wire codec is
changed. Buyer dependencies on the existing lifecycle client/contracts are
explicit, generated consumer locks are refreshed, and the release-guide buyer
row includes them once.

Existing scenario functions now send canonical surrender, retrieve and verify
site reports before release, and observe neutral released progress separately.
The real-host scenario uses the installed buyer's actual `--run-id` command
surface and its delivery read; no operator host is prepared or claimed.
At this checkpoint, fresh-stack mock-deal and real payment/mediation
qualification were unrun, so neither 15.2 nor 7.4 was checked off. The fresh-stack
qualification below supplies that evidence for 15.2. The real-host lane still
needs an operator-owned target; 7.4 remains for the parent.

Initial regression found that an embedded CLI caller already owned an event
loop and that recovery did not consume the bare-metal-only acceptance event.
The thread bridge fixes the former; canonical `negotiation_completed` plus
retained Agreement bytes/data in the run end fixes the latter. A callback trust
fixture manufactured a fulfillment without its delivery journal; it now seeds
the journal in an explicit transaction, without weakening identity assertions.
No permanent test function was added or removed.

Continuation validation passes: the complete `make test` aggregate in **8m10s**
with proxy exclusions and the shell-local Podman shim, including **522** bare-metal
storefront cases, **16** buyer cases, **18** lifecycle-buyer cases, **315** e2e
harness unit cases, **1,858** release-tooling cases and Helm render/structural
checks. This aggregate does not run deployed domain scenarios. Fresh `make dist`,
affected generated locks, architecture, packaging, lock currency, comment hygiene
and pinned strict OpenSpec validation also pass. The existing optional
Torch-dependent VM collection skip remains; no skip was added.

Build/lock continuation must use repository-root `make dist` and
`make lock PROJECTS="domains/bare_metal/buyer domains/bare_metal/storefront e2e-tests"`.
The package Makefiles have neither `build` nor `lock` targets; trying those did not
regenerate artifacts. The corrected root targets and subsequent checks passed.

## Fresh-stack qualification

At `3876c2295`, fresh checkout-built images and isolated empty lane state reached
Compose readiness. Real local payments (Formance/Postgres) and mediation HTTP
were healthy from the host and role namespaces. An authenticated registry read
confirmed both Alkahest and hosted options; the hosted option pinned the served
mediation authority, a 300-second delivery deadline, a 1,296,000-second dispute
window and an unbounded case hold. Payment `window=P7D` remains distinct.

Inside the owned branch-built runner, with the documented lane and payment
configuration, the direct invocation was:

~~~sh
.venv/bin/pytest -q --tb=short \
  tests/e2e/roles/scenarios/bare_metal/test_bare_metal_mock_deal.py
~~~

All **39 stages passed in 16.56s**, with zero skips. They cover negotiation and
Alkahest fulfillment, controlled lease expiry, teardown/release, capacity reuse,
repeated canonical surrender with stable receipt, the verified signed site
report before physical completion, and exactly one proven capacity release.
These are implementer observations, not independent acceptance.

The additional hosted-payment scenario initially stopped before purchase
because its pool override omitted required lifecycle publication parameters.
Repair `892ed4d5d` supplies and asserts the compute deadline, sufficient dispute
window and unbounded case hold in that existing fixture. No test function was
added or removed. The repaired fixture's **315** harness unit checks, packaging
and comment hygiene pass.

At that revision a new branch-built run passed the **39 mock stages in 13.23s**
and all **three existing hosted payment calls in 7.63s**, with zero skips.
The payment observer verified baseline, held, replayed and refunded checkpoints:
wallet-free buyer approval and canonical commit delivered once; canonical commit
replay retained the same payment and fulfillment; seller reversal restored the
buyer's baseline; physical surrender/convergence separately returned capacity.
This does not claim rate-stop support, case filing/ruling execution, or real SSH.
The launcher then attempted to remove a buyer namespace before its mediation
forwarder. Its fallback cleanup still removed every owned resource. The final
clean-exit replay removes those dependents first and passes at the same source
revision: **39 mock stages in 13.39s**, **three hosted calls in 7.88s**, zero
skips, all four payment checkpoints and process exit zero. Host and role health
checks and dispute-bearing publication passed before pytest. Final owned
container, network and volume inventories are empty; service source is unchanged.

Initial setup attempts stopped at readiness before pytest: the disposable
configuration mixed TOML inline and table arrays, then supplied only the
authority minimum without adding the compute delivery deadline. Correcting the
configuration, rather than weakening publication validation, reached the ready
state above. Readiness reads the settlement envelope as documented in
[#327](https://github.com/arkhai-io/simple-compute-market/issues/327).
All attempted deployments were removed, including their networks and volumes.
No external tooling source, raw logs or private runtime artifacts enter this
packet.

### Reproduction boundary

Build this revision's wheelhouse and images with `make build-e2e-bare-metal`
through the shell-local Podman shim. Use an unused owned Compose project with
fresh volumes, remapped loopback host ports and the public bare-metal mock lane;
do not select an inherited deployment. Supply actual development payments and
mediation HTTP authorities with real Formance/Postgres, using the same pinned
payment signer and mediation description for both roles. Loopback-only payment
authentication must remain loopback in each role's network namespace; namespace
forwarders can reach the shared isolated authority without relaxing that guard.

Add hosted payment policy to the mounted storefront TOML, retain its Alkahest
option, and publish the hosted clause with the deadline/window/cap above. The
registry recommendation must contain that exact served mediation authority and
its advertised minima; seller and buyer use registry recommendations. Supply
and forward the named `PAYMENTS` configuration in
[the shared payment setup](../../../e2e-tests/README.md#shared-payment-scenario-configuration),
funding disposable development personas through `/operator/test-funds`. Gate on
Compose health, host/role payment health, mediation health and an authenticated
registry read with `option["settlement"]["schema"]` plus matching lifecycle terms.
Only then invoke the two existing files inside the branch-built buyer runner
with `ACTIVE_PROFILES=docker,payments`:

~~~sh
.venv/bin/pytest -q --tb=short \
  tests/e2e/roles/scenarios/bare_metal/test_bare_metal_mock_deal.py
.venv/bin/pytest -q --tb=short \
  tests/e2e/roles/scenarios/bare_metal/test_bare_metal_payment_deal.py
~~~

The direct scenario commands above were personally run. The first-use app
command remains a self-cleaning committed entry point for checkout-only replay;
it is not a substitute for this deployed qualification. Remove role forwarders
before namespace owners, then remove only the owned Compose projects, volumes
and networks. Keep raw runtime evidence outside the public repository.

## Cleanup

The earlier in-process checkpoints created no external runtime. Fresh-stack
qualification creates only run-owned local containers, networks and ephemeral
volumes, removes namespace dependents before their owners, and verifies an empty
owned inventory. No browser, tunnel, remote deployment or resident development
server is needed. Source checkouts supplying external services remain unchanged.
