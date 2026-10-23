# Triage — 39-design — unbacked-bare-metal-listings

Reviewed commit: `0ccbee3af1ca018437369e36e4f6247cc0ca852b`. `HEAD` at triage, `cbacb7e`,
differs from it only in `.claude/change-steps.toml`, the change index, and the new
`redesign-storefront-stage-events` proposal; none of the review's evidence is affected.

### F1 — No mechanism produces a reachability blocker

- **Lens / basis / severity:** consistency / evidence / blocking (as the reviewer's)
- **Position:** agree — `ReadinessBlocker` has only `code` and `message`; Alkahest's
  contract probe runs only when a composition passes `contract_probe` with non-empty
  `required_addresses`, which no production composition does, and conflates an
  unreachable chain with an undeployed contract; Arkhai payments and contact exchange
  contact nothing. D7's hold, D19's kinds, and D20's scenario had no producer.
- **Proposed outcome:** decision — (a) add a probe, (b) keep the kind with no producer,
  or (c) drop the kind and the hold; recommended (c).
- **Owner disposition:** (a), then confirmed the drafted shape: the probe in
  `kit/alkahest`, built by `kit/storefront`'s client seam, run in the loops at most once
  per chain per interval (30 s default) with 5 s bounded calls; readiness reads its last
  result; `alkahest.chain_unreachable` (reachability) apart from `chain_id_mismatch` and
  `contract_missing` (configuration); not-yet-probed reads as reachability; a failed
  client is rebuilt at its next probe; `ReadinessBlocker` gains a required `kind`.
- **Result:** decision 19 records the probe and the blocker kinds, and its rejected
  alternatives; decisions 7 and 20 and the cadence refer to it; the settlement-configuration
  delta gains "Alkahest probes its chains apart from readiness" and revised kind scenarios;
  the proposal names the probe. Ledger entry appended.

### F2 — Challenges D7: a misconfigured second mechanism turns an outage hold into a close

- **Lens / basis / severity:** direction / judgement / should (as the reviewer's)
- **Position:** agree, with a sharpening — classify per mechanism, not per blocker: a
  mechanism with any configuration blocker is ruled out by configuration; one whose
  blockers are all reachability is unknown; hold when any mechanism is unknown.
- **Proposed outcome:** decision — reaffirm D7, adopt hold-when-unknown per mechanism, or
  decide per published option; recommended the second.
- **Owner disposition:** agreed with the sharpening.
- **Result:** decision 7 rewritten to the per-mechanism rule with the rejected
  alternatives; the storefront-publication delta's requirement reworded, with scenarios
  for the mixed case and for a mechanism carrying both kinds.

### F3 — Challenges D25: this change has upgrade-order points to record

- **Lens / basis / severity:** direction / guidance / should (as the reviewer's)
- **Position:** agree on points 1 and 2; partly on 3 — the bare-metal buyer pins
  `arkhai-core-buyer==0.5.0`, so the buyer skew needs a forced install.
- **Proposed outcome:** decision — reaffirm D25 or replace it with a record; recommended
  the record.
- **Owner disposition:** reaffirmed: points 1 and 2 cannot happen because a bare-metal
  storefront and its provisioning service are deployed by the same Helm release, the only
  supported deployment shape; point 3 is prevented by the pin.
- **Result:** decision 25 retitled and rewritten to state the points and why none can
  arise. Ledger entry appended.

### F4 — Degraded start is contradicted by the VM and API-credit preflights; no VM `startupProbe`

- **Lens / basis / severity:** consistency / evidence / should (as the reviewer's)
- **Position:** agree — VM's `_preflight_provisioning` and the API-credit credits
  preflight raise by default after 30 s; only the bare-metal chart has a `startupProbe`;
  an Alkahest client that fails to construct is dropped for the process's life.
- **Proposed outcome:** decision — extend D20 or narrow the requirement to init
  containers; recommended extending.
- **Owner disposition:** extend D20.
- **Result:** decision 20 removes both preflights and their settings, adds a VM
  `startupProbe` and its render assertion, and rebuilds a failed Alkahest client at its
  next probe; the deployment-state delta forbids in-process waits, requires a startup
  probe, and gains a scenario; the proposal's Impact names the configuration removed.

### F5 — D17's older-run-log fallback funds seller terms; "sent only by bare metal" is false

- **Lens / basis / severity:** consistency / evidence / should (as the reviewer's)
- **Position:** agree — `accepted_escrow_artifacts_from_proposal` is called by all three
  domains; VM and API-credit resume fund recorded terms unchecked.
- **Proposed outcome:** decision — (i) derive against the current listing and compare, or
  (ii) refuse with a named reason; recommended (ii). Edit D17's premise either way.
- **Owner disposition:** (ii).
- **Result:** decision 17's premise corrected and the older run-log refused before funding,
  with the rejected alternative; the buyer-orchestration delta's requirement and a new
  scenario say so.

### F6 — D16 misses post-acceptance readers; D19's condition already has an answer

- **Lens / basis / severity:** consistency / evidence / should (as the reviewer's)
- **Position:** agree — VM's admin dry-run verify reads the current listing; the heartbeat
  comes from the current setting through re-derivation; VM's admin interrupt reads the
  current listing's `interruptible`. The release model is read directly only at
  publication and startup; bare metal reads it indirectly through refreshed `demands`,
  which D16 removes; interrupts are VM-only.
- **Proposed outcome:** edit — extend D16's list; record D19's condition as checked.
- **Owner disposition:** agreed.
- **Result:** decision 16 lists the three readers; decision 19 states the condition as
  checked; the settlement-servicing delta names the readers and gains a preview scenario.

### F7 — The bare-metal lifecycle delta goes beyond D19

- **Lens / basis / severity:** documentation / specification / should (as the reviewer's)
- **Position:** agree — the delta made missing chains and key unready, dropped the
  stale-input refusal, and weakened recovery, none of which D19 decided.
- **Proposed outcome:** decision — extend D19 to address, chains, and key, keep the
  stale-input refusal, widen the known limit; or align the delta to the wallet address.
  Recommended extending.
- **Owner disposition:** extend D19 as suggested.
- **Result:** decision 19 extended with the stale-input refusal kept and the known limit
  widened; the lifecycle delta's requirement and startup scenario restore the stale-input
  refusal; the settlement-configuration delta names the missing key and chains.

### F8 — D7 contradicts an unmodified publication requirement; API credits under D19 is unaddressed

- **Lens / basis / severity:** documentation / specification / should (as the reviewer's)
- **Position:** agree — "Publication derives all ready settlement options" says
  publication fails; API-credit listings are created once and never re-derived; a create
  with supplied escrows and no clauses never checks readiness.
- **Proposed outcome:** edit — modify the requirement; record the API-credit known limit
  in D19; extend D19's API-credit sentence to supplied escrows.
- **Owner disposition:** agreed; starting with Alkahest unready is a change but more
  correct.
- **Result:** the storefront-publication delta modifies "Publication derives all ready
  settlement options" with a per-pool scenario and adds a supplied-escrows scenario;
  decision 19 records the API-credit limit and the supplied-escrow rule; decision 7
  points to it.

### F9 — The carrier's backing label has no named source

- **Lens / basis / severity:** architecture / guidance / should (as the reviewer's)
- **Position:** agree — the per-generation reader with the older-producer rule is in
  `kit/resource-pools`, which `arkhai_bare_metal` must not depend on.
- **Proposed outcome:** edit — `trusted_bare_metal_projection(*, site_id, projection,
  backings)`; the storefront reads pools before views; the site passes F10's context.
- **Owner disposition:** agreed.
- **Result:** decision 6 names the signature, the reading order, why per-pool resolution
  is right at the site, and the rejected alternatives.

### F10 — D4's pool context needs a seam that does not exist

- **Lens / basis / severity:** architecture / evidence / should (as the reviewer's)
- **Position:** partly — the seam is missing as the reviewer says, but the race between
  `kit/site`'s two reads does not exist: backing and provider are fixed at creation and
  pools are never hard-deleted. First recommended (b), `kit/site` passing rows; after the
  owner's redirection, recommended (a) on an independent responsibility-based check.
- **Proposed outcome:** decision — (a) the service resolves context in its own resource
  pass through `compute_provisioning`'s protocol, or (b) `kit/site` passes rows.
- **Owner disposition:** asked for placement by which package's responsibilities fit, not
  least work, checked independently; chose (a).
- **Result:** decision 4 names the pool-context type and protocol in `compute_provisioning`,
  its new contracts declaration, the service's resource pass, the adapters, why the reads
  need not agree, and the rejected seams; the physical-provisioning delta says the site
  kit carries no pool state into the resource pass; the proposal's Impact is corrected.
  Ledger entry appended.

### F11 — `kit/site` has no replay outcomes to record into

- **Lens / basis / severity:** scope / evidence / should (as the reviewer's)
- **Position:** agree — `InMemoryReplayStore` keeps reservations only; retry-safe routes
  re-execute and the one unsafe route refuses with a signed 409; only the unsigned 500 is
  a gap there. Nothing need be handed to `redesign-authenticated-replay-state`, whose
  subject it already is.
- **Proposed outcome:** edit — narrow D23's `kit/site` half; split the delta.
- **Owner disposition:** agreed.
- **Result:** decision 23 and the physical-provisioning delta distinguish the two
  middlewares, with a scenario for the API-credits service; the proposal says so.

### F12 — The site-derivation log's semantics are incomplete; a stale VM category

- **Lens / basis / severity:** architecture / evidence / minor (as the reviewer's)
- **Position:** agree — gap 2 is partly speculative, since `ARCHITECTURE.md` does not
  clearly say one process composes both, but keying by source costs nothing;
  `legacy_overrides_in_effect` was retired.
- **Proposed outcome:** edit.
- **Owner disposition:** agreed.
- **Result:** decision 10 and the delta key the log by publication source and site, make
  a site with no cycle since start absent, and use `retired_pricing_keys` as the example;
  the delta gains a scenario.

### F13 — Smaller interface gaps

- **Lens / basis / severity:** architecture / evidence / minor (as the reviewer's)
- **Position:** agree — the adapter's undeclared contracts import, the VM adapter (settled
  by F10), the boolean presence rule, and the refusal's home, placed by responsibility in
  `kit/storefront`.
- **Proposed outcome:** edit.
- **Owner disposition:** accepted, with the placement to be confirmed independently; the
  check confirmed `kit/storefront` and added that the kit holds no mechanism wording and
  that the refusal decide by a new required stage declaration rather than
  `fulfils_through_capacity`, which the owner accepted.
- **Result:** decisions 4 and 5 name the adapter's declaration and the presence rule;
  decision 9 names `kit/storefront`, the `completes_outside_settlement` declaration, and
  the rejected homes; the storefront-publication and resource-pool-management deltas
  match; the market-composition companion is added as a promotion destination. Ledger
  entry appended.

### F14 — `tasks.md` describes the 2026-10-14 design

- **Lens / basis / severity:** readiness / guidance / minor (as the reviewer's)
- **Position:** agree; also D26 still described `redesign-storefront-stage-events` as
  uncommitted, which `cbacb7e` committed.
- **Proposed outcome:** edit — header, gate 1.14, a note on 2.1, D26's sentence.
- **Owner disposition:** agreed.
- **Result:** `tasks.md`'s header rewritten, gate 1.14 appended before 1.2 with the
  2026-10-20 decisions and this triage's, 2.1 annotated with groups B to D's evidence;
  decision 26 corrected; `design.md`'s context notes the review's revisions.

## Next

Another round — "Yes this merits another review round." The dispositions changed central
decisions: decision 19 gains a chain probe and blocker kinds (F1), decision 7's hold rule
(F2), decision 4's interface and its packages (F10), and decision 9's stage declaration and
home (F13), so this review no longer describes the design.
