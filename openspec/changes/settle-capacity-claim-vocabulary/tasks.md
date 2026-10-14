# Tasks

## 1. Rename the storefront claim key

- [ ] 1.1 Re-verify the surfaces `proposal.md` names still carry the
      `required_attributes` claim key: `admin_controller.py`,
      `admin_settle_service.py`, `vm_fulfillment_service.py`,
      `vm_fulfillment_planner.py`, `vm_job_spec_service.py`,
      `fulfillment_resume_runtime.py`, `capacity_admin_models.py`,
      `vm_fulfillment_models.py`, `core_storefront`'s `settle_models.py`, and
      `storefront_client`'s client. Record drift in `design.md`.
- [ ] 1.2 Rename the key to `capacity_claim` on every writer and reader in one
      step; keep `kit/site`'s `required_attributes` untouched.
- [ ] 1.3 Read the resume context under both keys for one release, writing only the
      new one; add the removal of the old read as a dated note here for the
      following release.
- [ ] 1.4 Bump `storefront_client`'s version; the admin settle body is a published
      model.
- [ ] 1.5 Focused tests: a plan persisted under the old key resumes; a plan
      persisted under the new key resumes; the settle body refuses the old key.

## 2. Decide the flat dimension spelling

- [ ] 2.1 **Decide and record** in `design.md` whether `vcpu_count`/`ram_gb`/`disk_gb`
      become `cpu_count`/`memory_gib`/`storage_gib`, with
      `bare-metal-listing-shapes`' choice of bare-metal flat names in view. State
      the answer permanently either way (`market-composition` architecture
      companion). If not taken, mark the `VM_CAPABILITY_SCHEMA` comment as the
      standing rule rather than an exception, and skip 2.2–2.5.
- [ ] 2.2 If taken: rename the schema rows, the published `listing_resource`
      fields, the claim dimension keys, and the buyer CLIs' filters and examples,
      for VM and bare metal together.
- [ ] 2.3 If taken: bump the compute registry `filter-spec`, refusing the retired
      spellings at the publish boundary, and add the deltas `proposal.md` lists.
- [ ] 2.4 If taken: migrate persisted VM capacity declarations' keys at site
      startup, digest-gated like the definition documents, and prove a site with
      old keys and a site with new keys both admit the same claim.
- [ ] 2.5 If taken: one e2e run proving discovery by the renamed filters and a
      full deal on the renamed dimensions.

## 3. Promote the vocabulary

- [ ] 3.1 Add the claim term table to `docs/development/ARCHITECTURE.md`'s
      vocabulary: capability shape, capacity claim, capacity reservation,
      `dimensions`, `attributes`.
- [ ] 3.2 Record the `dimensions`/`attributes` invariant and why the family form
      does not weaken it in `openspec/specs/site-capacity/architecture.md`.
- [ ] 3.3 **Comment hygiene and import placement, before the pre-closeout review.** Run
      `make check-comment-hygiene` and read the comments this change added for any that
      narrate the review or migration that introduced them; move each import the change
      added to module level unless a verified circular import or a recorded lazy-load
      reason keeps it local. Closeout only confirms both. Read the touched docstrings
      for the old key name.

## 4. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 4.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read
      the comments this change added for any that narrate the review or migration that
      introduced them. Do not edit code here: anything to rewrite returns the change to
      implementation.
- [ ] 4.2 **Import placement — confirm.** Check the imports this change added for any
      still local without a recorded reason. One that should move returns the change to
      implementation.
- [ ] 4.3 **Documentation compliance.** Re-check this change's accepted decisions
      against `openspec/README.md`'s placement rules, and the permanent documents
      against the code they describe.
- [ ] 4.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work, and
      permanent-documentation destinations, moving durable rationale into `design.md`
      first.
- [ ] 4.5 **Roadmap currency.** Update the affected goal's current state and gap
      mapping in `docs/development/ROADMAP.md`, or record that no goal is affected.
      Expected: remove this change's Goal 2 gap row and fold the settled vocabulary
      into the goal's current-state text.
- [ ] 4.6 **Campaign index currency.** Update this change's row, and its campaign's
      dependency graph (Goal 2's), in `openspec/changes/README.md`, or record that both
      are unchanged. Other rows' `Depends on` are left alone: archive cleanup releases
      dependents after the closeout gate.
- [ ] 4.7 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports (a failure needing a code or lock change returns the change to
      implementation).
- [ ] 4.8 **End-to-end pipeline.** Record the passing run the latest validation names,
      its result, and the scenarios that exercise this change — the fulfillment and
      resume stages exercise the renamed key — or an explicit blocker naming its cause
      and the change that owns it, with the validations it gates treated as unrun.
- [ ] 4.9 **Promotion.** Write the permanent documents this change owes — the claim
      term table in `docs/development/ARCHITECTURE.md`'s vocabulary, the flat dimension
      spelling and why in `openspec/specs/market-composition/architecture.md`, and the
      site's resource side in `openspec/specs/site-capacity/architecture.md` — and
      complete the design-promotion record below. The change carries no spec deltas
      unless 2.3 adds them; a `spec.md` they cover (`vm-storefront-fulfillment`'s, if a
      requirement names the key) is written by the archive in 4.11, not by hand, and
      the record names it all the same.
- [ ] 4.10 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=settle-capacity-claim-vocabulary` and resolve every match,
      then `openspec validate settle-capacity-claim-vocabulary --strict`, or, while the change has no spec deltas, record that instead: the validator rejects a change with none.
- [ ] 4.11 **Archival.** Last, once every other part is checked: `openspec archive
      settle-capacity-claim-vocabulary -y` merges the deltas into `openspec/specs/` and moves
      the change under `openspec/changes/archive/` — with `--skip-specs` instead if it
      still carries no deltas; point the index row at the archived directory, and run
      `openspec validate --specs --strict`.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| `claim` names what `probe`/`reserve` take; a capability shape is what a party states and a domain flattens | `docs/development/ARCHITECTURE.md`, vocabulary |
| The storefront's persisted claim key is `capacity_claim`; `kit/site`'s `required_attributes` is the categorical half | `openspec/specs/vm-storefront-fulfillment/spec.md` if a requirement names the key; otherwise `ARCHITECTURE.md` vocabulary |
| The flat dimension spelling, and why | `openspec/specs/market-composition/architecture.md` |
| Why the site's resource side is not expressed in the family form | `openspec/specs/site-capacity/architecture.md` |
