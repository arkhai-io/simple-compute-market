# Domain implementation-review repairs

Nonvisual implementer qualification of the compute-domain repairs. All HTTP
encounters below use invocation-owned in-process apps and temporary SQLite;
all principals are deterministic public development fixtures, never identities
for a public network. This packet does not claim deployed hosted mediation or
real hardware execution.

## Implemented boundary

- `9061c2062` addresses S-F2/O-F7: VM and bare-metal share the pure compute-family
  site-end classifier. Direct guarded release preserves its physical intent key;
  exact termination/truncation echoes inherit the controlling classification,
  including nonlawful ends. Ambiguous release remains pending and correction
  revisits it after controlling evidence arrives. Earlier independent failures
  remain independently correctable. The classifier has no persistence, authority
  client or concrete-domain dependency. Reservation lookup and proof verification
  remain each domain's ports. `171b08a6a` corrects an existing terminal-command
  assertion to use the accepted negotiation's identity.
- `2ca4537c7` addresses S-F3: accepted bare-metal recovery validates the retained
  mandate against exact Agreement bytes, not current fee/admission policy.
  Financial capability is optional; receipt-only surrender remains available
  after payment configuration removal. Substituted mandate/payer still refuses
  before peer I/O.
- `b905dacdd` addresses O-F17: the existing teardown regression's comment now
  describes its unchanged assertion: only the separate callback proves release.
  This documentation-only finding needs no additional behavior assertion.

## Reproducible first use

From a clean checkout with the repository prerequisites:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist
make -C domains/compute test
make -C domains/bare_metal/storefront reinit
(cd domains/bare_metal/storefront && uv run --find-links ../../../.dist pytest -q \
  tests/integration/test_lifecycle_ends.py \
  tests/integration/test_buyer_lifecycle_recovery.py)
```

The last command directly opens the stories through canonical signed lifecycle
clients, not a menu or a running server. No credential or ignored configuration
is required. The tests create their own accepted hosted deal, owned site binding,
kit-owned payment fake, buyer evidence store and teardown gates. The recovery
cases vary policy after acceptance and reopen the buyer half over the same
retained state.

## Observations

| Criterion | Observation |
| --- | --- |
| Surrender before dispatch | No create is dispatched; one direct release carries the exact journal intent key. |
| Signed release push/retry/pull | One exact retained report, a buyer-surrender controlling source, no seller-fault filing; released lease observation independently proves capacity return. |
| Report arrives before controlling evidence | Classification stays pending with no filing; later surrender resolves it without rewriting the immutable report/request. |
| Independent failure and deadline semantics | Permanent compute unit cases distinguish earlier independent failure, commanded truncation, exact Agreement expiry and reservation lapse. |
| Recovery after policy rotation/removal | Both surrender and same-journal replay succeed; one physical termination, no invented once-payment refund. |
| Substituted recovery artifacts | A mandate for different accepted terms and an approval naming another payer both refuse before peer I/O. |
| Regression sensitivity | Replaying the base production functions under these tests fails on the missing release-command key, false seller-fault classification, changed fee policy and removed payment configuration. |

Focused results: compute family **12 passed**; bare-metal signed release/correction
**2 passed**; bare-metal retained recovery **3 passed**. Existing terminal/restart
assertions were updated to the deliberately changed physical command identity,
not removed or weakened. Their targeted re-drive passes. VM storefront's existing
unit and application-integration targets pass. Packaging, architecture, lock
currency, comment hygiene and pinned strict OpenSpec validation pass.

The complete **`make test` aggregate passes in 7m04s** with the prescribed proxy
exclusions and shell-local Podman shim. It includes bare-metal storefront **527
passed**, VM storefront **1,189 unit passed** (one optional collection skip) and
**501 integration passed**, buyer **16 passed**, e2e harness **316 passed**, release
tooling **1,858 passed** and Helm structural/render checks. The initial aggregate
caught two release-guide dependency rows missing `arkhai-compute`; `1fea9839a`
repairs those rows, and both focused release tooling and the full re-drive pass.
No deployed VM hosted-servicing end-to-end result is claimed by these in-process
observations. No owned runtime remains.

## Continuation boundary

Still owed: O-F8 domain actor attribution, O-F9 seller retention composition,
O-F16 cycle churn/report polling, the remaining permanent domain tests named by
sections 14/15 under O-F1, and O-F18's fresh-stack VM hosted payment/mediation
journey. The shared retention factory and no-op phase-write guard belong to the
parallel servicing-kit repairs; the domains consume those seams rather than
introducing a second retention algorithm or copying journal code. Receipt-claim
signing through the dispute adapter (O-F12, delegated by its owner) must remain
credential-independent; eager authority-client construction cannot replace the
current receipt-only surrender behavior.
