# VM administrator interruption checkpoint

Nonvisual implementer self-check, not independent acceptance. No screenshots apply.
This packet covers administrator dispatch, not the remaining VM lifecycle wiring.

## Prepared target and first use

The actual target is this checkout's VM storefront, using rebuilt internal wheels,
invocation-owned SQLite, signed in-process HTTP and deterministic public development
buyer, seller and administrator identities. Never use these fixtures on a public
network. No remote target, inherited selector, secret, container or resident server
is required. The administrator is explicitly trusted in its own role; the transport
and response verification are the production implementations.

From a clean checkout at repository root:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist
make -C domains/vms/storefront reinit
(cd domains/vms/storefront && PYTHONPATH=. uv run --locked --find-links ../../../.dist \
  python ../../../docs/attachments/vm-admin-interrupt/first_use.py)
uv run --project domains/vms/storefront --locked --find-links .dist \
  python domains/vms/storefront/examples/payment_smoke.py
```

Both entry points were opened successfully. The first reuses the existing payment
application fixture, mounts the actual administrator router and identity middleware,
and uses the kit-owned vector-derived mediation peer. It exercises:

- **Unentitled once deal:** the signed administrator request retains its identity
  and reason, records one end and one payee delivery-end filing, and drives physical
  teardown. The mediation transport deliberately waits for the physical driver,
  records the case and loses its response. The first authority outcome is unknown;
  same-key retry returns accepted with one case and one completed filing intent.
- **Entitled dispatch:** an injected future payment adapter receives only a stop,
  with no supplied time. Before its effective authority event, no local end or
  self-penalty filing exists. The observed authority event determines the end instant;
  no self-penalty filing is created. This installs an accepted option projection
  solely to qualify dispatch/order: the current once adapter deliberately supports
  no rate mandate or stop. It is not rate-payment execution evidence.
- **Dry run and retry:** preview makes no effect; same-key retry preserves the
  delivery view; changing the reason under the same key is refused before I/O.

The payment example additionally exercises administrator exceptional end with no
mediation credential: delivery reaches teardown while the required filing remains
journaled for repair/retry. Its existing approval/delivery and buyer end-before-
delivery examples still pass.

## Implementation boundary

The existing administrator interrupt path accepts a hosted negotiation ID or the
existing Alkahest escrow UID. Hosted actions use the accepted option's payee right,
never listing state. An entitled request calls the seller half's stop command;
only the authority's subsequent verified stop establishes its delivery end.
Without entitlement the seller half atomically journals attributed receipt-time
end and correction, while the domain drives physical effects concurrently with
filing. An unavailable authority cannot serialize teardown behind its response.

Hosted interruptions require an administrator reason, accept an optional stable
operation key, and reject supplied interruption times and payout amounts. Without
an explicit key the route derives one from negotiation, administrator and reason.
Immutable retained evidence binds notice requests to their administrator and
reason too. Responses carry separate authority outcome and delivery progress.
The Alkahest splitter-backed path remains unchanged.

The payment integration fixture now names the installed mediation interface and
its vector-derived authority instead of an unrelated example interface. No
permanent test function was added and no existing assertion was weakened.
No shared kit, client, provisioning source or sibling-domain source changed;
there are no dependency or configuration-model changes, so no relock or Helm
schema regeneration is needed. Permanent promotion remains reviewed closeout,
to the deal-lifecycle spec/architecture and VM fulfillment documents.

## Validation

- Initial administrator/payment regressions: **27 passed**.
- Final administrator/payment/application route regressions: **72 passed**.
- Both signed first-use dispatch branches, lost filing response and same-key
  recovery pass; payment example passes normal delivery, administrator ending and
  end-before-delivery.
- Architecture, packaging, lock currency, comment hygiene and pinned strict
  OpenSpec validation pass again after the final source/fixture changes.
- Full **`make test` passes in 8m10s**, with both all-proxy variables unset,
  loopback no-proxy exclusions and the shell-local Podman shim. This includes
  the VM unit/application suites, release tooling and Helm render/structural
  checks. It is not deployed domain e2e qualification.
- Scoped documentation citation checking reports exactly the three known future
  lifecycle destinations tracked by [#325](https://github.com/arkhai-io/simple-compute-market/issues/325);
  there is no additional citation failure.

## Continuation boundary

Still unimplemented: the authenticated site-report HTTP receiver and pull recovery,
callback-proven release progress, failure-source classification/correlation and
remaining direct failure-policy release dispatch, VM buyer lifecycle stages/CLI
and the VM half of the shared buyer-composition task. Keep that shared checkbox
unchecked. The site report proof verifier and physical/end ports are already
available in `deal_lifecycle.py` and `delivery_lifecycle.py`.

Fresh branch-built VM e2e with real local payments/mediation and the buyer-end/report
scenario extensions are **unrun**, not waived. No rate or hosted qualification is
claimed. No browser, server, container, tunnel or external deployment was started
or left running by these first-use checks.
