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

## Actor, retention and VM-cycle continuation

Starting revision: `8b1a5cfb5`. Implemented as whole findings:

- **O-F8 — `6172aaac0`:** VM maps the accepted opaque payer/payee accounts to
  buyer/seller; both domains map the dispute account to its pinned record signer.
  The shared kit supplies ruling attribution independently of that account map.
  Unknown accounts fail closed. No account syntax implies a marketplace role.
- **O-F9 — `d9e4ddfa2`:** both domain watch factories compose the kit's
  `seller_retention` observer. Bare-metal settlement verification records its
  evidence commitment in the same transaction, so a committed deal uses the
  completion boundary rather than acceptance expiry. Pruning through the seller
  API refreshes required authorities before applying the frozen Agreement window.
- **O-F16 — `ba051e273`:** VM recovery does not re-admit an unchanged phase on
  each sweep. It still delegates missed availability deadlines to end service.
  A released reservation without its end report remains recoverable; with retained
  proof, site polling stops.

These are in-process consumer observations, not a new authority algorithm or
live rate-stop qualification. The synthetic neutral stop observations exercise
actor mapping for a future supported rate adapter; the once adapter still sends
no stops. No deployed service or private runtime artifact was used.

### Reproduce the prepared first-use surface

After `make dist-ci` and each storefront's `make reinit`, run from the repository
root with the proxy exclusions above:

```sh
(cd domains/vms/storefront && uv run --find-links ../../../.dist pytest -q \
  tests/integration/test_servicing_composition.py \
  tests/integration/test_lifecycle_cycle.py)
(cd domains/bare_metal/storefront && uv run --find-links ../../../.dist pytest -q \
  tests/integration/test_servicing_composition.py)
```

This directly opens the hosted-deal setup in invocation-owned real SQLite and
in-process storefront applications. The existing signed typed clients verify
payment commitment before observation; public deterministic buyer/seller/site
personas and kit-owned payment fixtures are the only authentication/seed state.
The commands need no secret or ignored local setup and clean up their own state.
No HTTP server, container, browser, tunnel or remote target was started.

### Regression observations

| Finding | Before repair | Re-drive |
| --- | --- | --- |
| O-F8 | VM payer and authority stops and bare-metal authority stop are attributed to the seller. | All five actor sources per domain retain actor, cause and source: 10 passed. |
| O-F9 | Complete authority/recovery observations still cannot prune in either domain; bare metal also has no evidence commitment. | Held/unknown funds, open cases, unrecovered capacity, unavailable mediation and missing credentials retain evidence; complete observations prune at the frozen window: 2 passed. |
| O-F16 | Two unchanged cycles alter admission revision; three recovery calls make three lease reads even with released proof. | Revision remains stable; released-without-proof still reads, the first report is retained once, and the third call performs no lease read: 2 passed. |

The first bare-metal retention setup attempted to re-accept a real existing
acceptance with a different author/expiry; its rejection was correct. The kept
regression uses that original accepted envelope and terms instead. No acceptance
criterion or production authorization was relaxed. All 14 focused continuation
cases pass.

The required validation sequence, including the full **`make test`**, passes in
**8m34s** at `ba051e273` with the prescribed proxy exclusions and Podman shim.
Architecture, packaging (fresh wheelhouse), lock currency, comment hygiene and
pinned strict OpenSpec validation all pass. The aggregate includes VM storefront
**1,189 unit passed** (one optional collection skip) and **509 integration passed**,
bare-metal storefront **533 passed**, VM buyer **213 passed**, bare-metal buyer
**16 passed**, e2e harness **316 passed**, release tooling **1,858 passed**, and Helm
structural/render checks. No dependency declaration or lock changed; no relock
was needed. This is not a deployed e2e run. No resident process or owned external
resource remains.

## Continuation boundary

Still owed: the remaining permanent domain tests named by sections 14/15 under
O-F1 and O-F18's fresh-stack VM hosted payment/mediation journey. These remain
implementation/qualification work, not waived tasks. The already-authorized
application cases should replace the remaining temporary-only verification:
hosted commit/list/acceptance capture, VM hardware failure and buyer tear-down,
VM second-precision lease ends, entitled/unentitled admin dispatch, signed site
report push/retry/pull and capacity proof, buyer dispatch/evidence capture, and
bare-metal create-in-flight/owner-refusal/repeated teardown. Existing permanent
cases can be cited where they already prove the named property.

O-F18 must extend the VM e2e surface, build a fresh owned branch stack through
the Podman shim, and gate payment/mediation health and dispute-bearing hosted
publication before pytest, as described in the existing hosted-policy and VM
qualification packets. No deployment attempt or hosted end-to-end pass is
claimed at this checkpoint. Source checkouts supplying those services were
inspected read-only; no external runtime or configuration was changed.

Receipt-claim signing through the dispute adapter (O-F12, delegated by its owner)
must remain credential-independent; eager authority-client construction cannot
replace the receipt-only surrender behavior. The independent off-loop ingress
continuation (O-F10) remains with its assigned owner. Permanent-document
promotion stays in reviewed closeout to the existing lifecycle, settlement,
VM-fulfillment and compute/site authority destinations.
