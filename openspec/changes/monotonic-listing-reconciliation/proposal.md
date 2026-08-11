## Why

A storefront reconciles its derived listings when a capacity delta arrives. The
reconciliation is deliberately site-wide rather than scoped to the resource that
changed — another seller's reservation invalidates our listings just the same — and
that scope is correct. What is not correct is that a reconciliation triggered for
capacity version N decides using an availability snapshot that may predate version
N+1, and the reopen pass acts on that older view.

Observed in end-to-end run 31482372498, over 321 milliseconds:

```
10:32:32.639  reserve 2 of 4 units on compute-e2e-dynamic-4x
              -> closes the 3x and 4x slice listings   (correct)
10:32:32.650  delta subscriber processes version 5 (a different resource)
              -> reopens those same 3x and 4x listings (wrong: 2 units are held)
10:32:32.960  reconciliation at version 7
              -> closes them again                     (correct)
```

Between the second and third line, the storefront advertised slices its own
authority could not serve. The system converges, so this is not a durable
inconsistency — but a buyer discovering a listing inside that window negotiates for
capacity that is not there, and the refusal arrives at `negotiate/new` rather than at
discovery. It also makes any assertion about listing state racy: a scenario that reads
status immediately after a reserve samples whichever side of the flap it lands on.

The close pass has the same input and does not exhibit the problem for a simple
reason: closing on a stale-but-larger availability view is conservative, and reopening
on one is not. Under-advertising corrects itself harmlessly; over-advertising sells
something that is not there.

## What Changes

- Make reopen decisions monotonic with respect to observed capacity version: a
  reconciliation MUST NOT reopen a listing using an availability view older than the
  most recent capacity version the storefront has observed for that site.
- Leave the close pass's behavior as it is. Closing early is safe, and making both
  passes version-gated for symmetry would delay a correction that costs nothing.
- Leave the site-wide reconciliation scope alone. Reacting to another resource's delta
  is the intended behavior and is not what makes this wrong.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `storefront-publication`: reopening a derived listing requires an availability view
  no older than the latest observed capacity version for that site.

## Non-Goals

- Do not scope reconciliation to the resource named in the delta. The site-wide sweep
  is deliberate.
- Do not make the projection cache authoritative for admission — it remains advisory,
  and this change constrains only when a *reopen* may act on it.
- Do not add a barrier or settle-wait to the end-to-end scenarios as the fix. A
  scenario may need one to observe the corrected behavior deterministically, but that
  is a consequence, not the remedy.

## Impact

- **Affected code (indicative):**
  `domains/vms/storefront/src/market_storefront/services/capacity_client.py`
  (the delta subscriber's reopen pass),
  `domains/vms/storefront/src/market_storefront/services/publication_service.py`
  (`reopen_available_compute_listings_after_capacity_change`), and whatever records the
  latest observed capacity version per site.
- **Affected tests:** storefront unit and integration suites for reconciliation; the VM
  dynamic-listing e2e scenario, which currently samples the flap.
- **Wire compatibility:** none — this is internal reconciliation ordering.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification — `openspec/specs/storefront-publication/spec.md`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Reopening a listing on a stale availability view over-advertises capacity, while
  closing on one is conservative; the two passes therefore have different freshness
  requirements — `openspec/specs/storefront-publication/spec.md`.

## Dependencies and Related Changes

- `pools-8-capacity-projection-and-listing-hints` built the projection consumption this
  reconciliation reads. No conflict; this constrains when a reopen may act on it.
- `replace-polling-with-authenticated-push` replaces the delta poller with authenticated
  delivery. It changes how a delta arrives, not whether a reopen may act on an older
  view, so this change is worth landing independently of it.
