# Triage — 139-implementation — unbacked-bare-metal-listings

- **Reviewed commit:** `8ac56577379a50686e6cd6e45fb7c2f2ddeca215`
- **Validated commit (140-validation):** `aa00b15fd4e43dff93b95eac6575856f2d906b01`
- **Commit waiver:** `8ac5657..aa00b15` is one commit, a relock of seven `uv.lock` files
  with no resolved version changed. The owner waived the same-commit rule ("Waive.");
  ledger line `139-implementation` / `commit`.
- Triaged together with `140-validation` (passed, no `V<n>`) and
  `138-implementation-owner` ("No notes from me").
- Base for the fixes: `aa00b15`.

### F1 — Every storefront still builds its Alkahest clients synchronously at startup, unbounded for a websocket chain

- **Lens / basis / severity:** consistency / specification / should (as the reviewer's)
- **Position:** agree — all three storefronts called `build_alkahest_clients` on the
  startup thread; a websocket construction connects and can hang for good, against D20 and
  the `deployment-state` delta. Bounding it at startup instead is D20's own rejected
  alternative, so the reviewer's first option (empty map, the probe builds) is the fix.
- **Proposed outcome:** fix — start every storefront with an empty client map, so the
  chain probe builds every client through its bounded construction; a degraded-start test
  per storefront with a constructor that never returns; reword D20's client bullet.
- **Owner disposition:** agreed.
- **Result:** VM `server.py`, API credits `server.py`, and bare metal `runtime.py` start
  with an empty map the probe owns; bare metal's `build_chain_clients` parameter and
  `_build_chain_clients` are gone. Every consumer already read the map with `.get` and held
  the probe's one map (a chain whose construction failed at start was already that state).
  The kit's `build_alkahest_clients` stays, its docstring saying a storefront's startup does
  not call it, since other active changes' designs name it. Tests: one degraded-start case
  per storefront with a never-returning constructor; existing tests moved to the
  constructor seam. D20's bullet rewritten. The consumer check (the fresh-context check
  of the diff found it) turned up two routes that answered a configured chain without a
  client 400 — VM's settle route and the API-credit Alkahest stage — which, as the
  disposition's "treat a missing client as retryable" requires, now answer 503 for a
  configured chain and keep the refusal for an unconfigured one, as bare metal already
  did; a unit test each. See Section 11's triage-fix note.

### F2 — A provisioning worker can answer `at_gate: true` while a woken timer cycle is about to run

- **Lens / basis / severity:** consistency / specification / should
- **Position:** agree — a resume then a pause before the woken waiter runs answers "at the
  gate", and the woken task passes the single `if`; the routes being sync also touched an
  `asyncio.Event` off the loop's thread.
- **Proposed outcome:** fix — the four pause/resume routes `async def`; both gates a
  `while` around the wait; a unit case per worker.
- **Owner disposition:** agreed.
- **Result:** made; each new unit case failed against the old `if` (run once broken) and
  passes with the `while`. See Section 13's triage-fix note.

### F3 — D20 still says an unreachable registry shows as a failed cycle, which the code and the corrected delta contradict

- **Lens / basis / severity:** documentation / evidence / should
- **Position:** agree — the cycle completes with `registry_not_converged` per listing and
  degraded status; the code's behaviour is the better one.
- **Proposed outcome:** fix (change document) — rewrite D20's sentence; close the Section
  11 open-for-triage note.
- **Owner disposition:** agreed.
- **Result:** D20 rewritten; the Section 11 note records the settlement.

### F4 — Section 13 committed eleven locks rewritten by a different uv, against the round's own handoff

- **Lens / basis / severity:** direction / judgement / should
- **Position:** partly — the churn was real, but `aa00b15` (the owner's relock with
  `make lock`) already reduced `9aa024e..aa00b15`'s lock diff to the 46 lines of version
  bumps; a further relock on uv 0.11.17 would gain nothing. The task notes still described
  the churn as committed.
- **Proposed outcome:** fix (change document) — record the relock in Section 13's 13.6
  note and the Section 11 correction it points to; no further relock.
- **Owner disposition:** "F4: yes." On the validation's tooling observation the owner
  raised pinning exact versions on internal wheels; after discussion, "No action needed on
  the uv-version idea." No issue (the owner does not use GitHub issues).
- **Result:** both notes corrected.

### F5 — Nothing shows the API-credit storefront reporting an unreachable credits service as degraded

- **Lens / basis / severity:** testing / specification / minor
- **Position:** agree.
- **Proposed outcome:** fix — assert `checks["credits_service"] == "unreachable"` and
  `status == "degraded"`.
- **Owner disposition:** agreed.
- **Result:** both asserted in `test_startup_does_not_wait_for_an_unreachable_credits_service`.

### F6 — Two Section 12–13 checks are narrower than their notes claim

- **Lens / basis / severity:** testing / evidence / minor
- **Position:** partly — both gaps are real; an import alias and a `getattr` string are
  cheap to catch, a prefix-built route is not, so that one narrows the note.
- **Proposed outcome:** fix — extend the source check to import aliases and operation-name
  strings and narrow the 13.5 note; the topology test reads Service selectors and asserts
  each release's expected test pods.
- **Owner disposition:** agreed.
- **Result:** made, each new form planted in the check's own test. The topology test now
  reads Service selectors (every chart's Service selector requires `name`) and pins each
  release's test templates; the delta scenario "Both topology releases are rendered" and
  D21 name Service selectors too. Helm is not installed in this session, so the render
  was not run here (see Section 12's triage-fix note).

### F7 — Stale comments, and a nonconforming commit message, from this round

- **Lens / basis / severity:** documentation / guidance / minor
- **Position:** agree — the history rewrite is not worth a force-push of a validated
  branch; the merge commit's message describes `8ac5657`'s change.
- **Proposed outcome:** fix — the API-credit startup comment lists the retired settings
  and the unset credits URL; "but the lane's autouse ones" dropped from three bare-metal
  modules; a Section 13 note about `8ac5657`'s message.
- **Owner disposition:** agreed.
- **Result:** made.

### 13.6 (open item, no review raised it) — `arkhai-e2e-tests` is bumped twice against `origin/dev`

- **Lens / basis / severity:** consistency / guidance / should (assigned by triage)
- **Position:** agree — 0.2.1 on `origin/dev`, 0.3.1 here; `RELEASING.md` allows one bump.
- **Proposed outcome:** fix — 0.3.0, relock `e2e-tests`, correct the Section 8 and 13.6
  notes.
- **Owner disposition:** agreed.
- **Result:** `e2e-tests/pyproject.toml` 0.3.0; `make lock PROJECTS=e2e-tests` changed
  only its own version line; notes corrected.

### Section 12 (open item, no review raised it) — whether the bare-metal chart bumps

- **Lens / basis / severity:** consistency / judgement / minor (assigned by triage)
- **Position:** partly — the test-template changes alone merit no bump, but the values
  schema accepts two new settings, new public surface.
- **Proposed outcome:** fix — `bare-metal-storefront` 0.4.0 and the umbrella's dependency
  entry; 12.4's note records it.
- **Owner disposition:** "bump to 0.4.0".
- **Result:** made.

No point of the owner's notes (`138`) needed a disposition. Every point of this round was
raised by a review or recorded in the task notes; the two open items above are task-note
items no review raised.

Ledger: one line appended, `139-implementation` / `commit` (the waiver). No disposition
corrected course from the proposals, so no other line.

Fix commit: `d185501` (not pushed; its validation pushes it).

## Next

Advance — "advance." The fix commit `d185501` is validated next.
