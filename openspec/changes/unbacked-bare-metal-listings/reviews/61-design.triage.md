# Triage — 61-design — unbacked-bare-metal-listings

Reviewed commit: `2c344acfe8800a414ac99b2bd9373699be633909`, which was `HEAD` at triage.
Triaged together with `60-orchestrator.md`. The findings were presented in the order F3,
F1, F2, F4, F5, F6, F7, because F3's placement shapes F1 and F5.

### F3 — The probe's construction, scheduling and client rebuild go on `kit/storefront`'s excepted edge to `kit/alkahest`

- **Lens / basis / severity:** architecture / guidance / should (as the reviewer's)
- **Position:** agree. The scope exception (`ARCHITECTURE.toml:280-286`) has a remedy that
  moves the factory out of the kit, and `ARCHITECTURE.md:149` forbids growing such an
  edge. `build_alkahest_clients` imports only `alkahest_py` and `market_alkahest` and
  returns a plain dict. Each domain registers its own loops, so "with no domain code"
  had no mechanism behind it.
- **Proposed outcome:** decision. Either (one) the probe, its schedule and the live client
  map in `kit/alkahest`, with each storefront registering it as a loop, or (two) keep it
  in `kit/storefront` and record it in `move-escrow-into-alkahest`. I recommended one.
- **Owner disposition:** option one; "the kit/alkahest responsibilities in particular are
  well clustered."
- **Result:** decision 19's "Who owns it" bullet now places the probe object in
  `kit/alkahest`: the chains, a constructor supplied at composition, the live client map,
  the results, and a step. Each storefront registers it as `alkahest-chain-probe`. The
  `kit/storefront` placement is rejected in the decision. The settlement-configuration
  delta and the proposal (What Changes, Impact) match.

### F1 — "Not yet probed reads as reachability" defeats the API-credit startup seed

- **Lens / basis / severity:** consistency / evidence / should (as the reviewer's)
- **Position:** agree. The seed runs before the loops (`startup.py:116-126`) and reads
  readiness through `publication_artifacts` (`listing_service.py:110-136`), and its
  failure is only logged. Checking this also found that the storefront CLI's `publish`
  builds its own services in a process with no loops (`cli.py:166-181`), so it would
  never have a probe result.
- **Proposed outcome:** decision. The options were (a) one bounded, non-fatal startup
  probe pass, (b) a retrying seed after the loops start, and (c) an on-demand probe on
  one-shot paths. I recommended (a), and for the CLI, one probe pass before creating.
- **Owner disposition:** delay the seed until the dependencies it needs are available, and
  give an operator's create against an unavailable dependency a clear error. The CLI calls
  the running storefront's route: "What's the point of publishing a listing if there
  isn't a running storefront to serve it?" The CLI's `listings` command is migrated too.
- **Result:** decision 19's "Paths that publish once" bullet:
  - the seed is the `listing-seed` loop step, which waits, gives up on configuration, or
    finishes;
  - a create refused only for reachability answers 503 naming the mechanism, and a
    configuration refusal stays a 400;
  - the CLI's `publish` and `listings` commands go through the typed listing client, which
    gains a list method.

  The startup pass, the on-demand probe and the CLI probing for itself are rejected in
  the decision. The storefront-publication delta gains "API-credit listing creation waits
  for or names an unreachable mechanism" with four scenarios. The proposal matches.
  Ledger entry appended.

### F2 — Challenges D7: classifying every configured mechanism lets an unusable mechanism's outage hold a listing due to close

- **Lens / basis / severity:** direction / judgement / should (as the reviewer's)
- **Position:** agree, with a sharpening. A candidate's clauses are its pool's override or
  the configured clauses, then admissibility for its backing
  (`publication_composition.py:49-85`), so the set to classify is the admissible
  clauses, not admissibility by backing alone. An empty admissible set currently raises
  an untyped `ValueError`, which would leave the listing open forever.
- **Proposed outcome:** decision. Either (a) classify the candidate's admissible clauses,
  with an empty set becoming the typed refusal, or (b) keep classifying every configured
  mechanism. I recommended (a).
- **Owner disposition:** (a).
- **Result:** decision 7 classifies the mechanisms of the candidate's admissible clauses,
  makes the empty set the typed refusal that closes, adds the converse case to its
  rationale, and lists the rejected alternatives. The storefront-publication delta's
  requirement is reworded and gains two scenarios: "An unreachable mechanism the
  candidate could never publish" and "A pool override leaves no admissible clause". The
  proposal's bullet matches.

### F4 — `kit/site` must change to carry `publication_view_problems`

- **Lens / basis / severity:** consistency / evidence / should (as the reviewer's)
- **Position:** agree. `resource_pool_projection` copies named fields only
  (`kit/site/src/market_site/projections.py:107-121`).
- **Proposed outcome:** edit.
- **Owner disposition:** agreed.
- **Result:** decision 4's bullet names `kit/site`'s `resource_pool_projection` and the
  site-client fixture as carrying the field opaquely. The physical-provisioning delta
  says the site kit carries it without reading it, and the proposal's Impact is
  corrected.

### F5 — Probe and blocker-kind semantics left undefined

- **Lens / basis / severity:** architecture / guidance / minor (as the reviewer's)
- **Position:** agree. F3 settles the shared client map. The loop names follow the
  table's hyphenated form.
- **Proposed outcome:** edit.
- **Owner disposition:** agreed.
- **Result:** decision 19 and the settlement-configuration delta now say:
  - results do not expire while the loops are held (new scenario "A scenario holds the
    loops");
  - the loop is `alkahest-chain-probe` with its step;
  - consumers read clients through the probe's map;
  - the runtime's `not_configured` and `disabled` blockers are configuration blockers
    (new scenario "A mechanism is disabled").

  F1's seed step is `listing-seed`. The `TESTING.md` loop-table rows are added to the
  promotion list.

### F6 — Decision 25's reason overstates what one Helm release guarantees

- **Lens / basis / severity:** direction / judgement / minor (as the reviewer's)
- **Position:** agree. A rollout or rollback rolls both Deployments concurrently. The
  effect is a whole-site hold that clears once both pods are current, so the
  reaffirmed disposition stands.
- **Proposed outcome:** edit.
- **Owner disposition:** ok.
- **Result:** decision 25's first point says the mixed-version window lasts only as long
  as a rollout, and that within it the site's listings are held and never closed.

### F7 — Decision 19's unowned API-credit limit has no roadmap row

- **Lens / basis / severity:** documentation / guidance / minor (as the reviewer's)
- **Position:** agree. `ROADMAP.md`'s Goal 6 table has unowned rows of this form, and the
  promotion list omitted this one.
- **Proposed outcome:** edit.
- **Owner disposition:** agreed.
- **Result:** the ROADMAP bullet in the design's promotion list gains the Goal 6 unowned
  row.

## Next

Advance — "Advance to planning." I recommended another round, because F3, F1 and F2
changed the probe's package, the API-credit create paths and CLI, and decision 7's
classification. The owner chose to advance. Ledger entry appended.
