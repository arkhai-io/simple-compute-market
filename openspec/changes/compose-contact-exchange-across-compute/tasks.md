# Tasks — compose contact exchange across the compute family

Depended on `contact-payload-retention`, which is complete and archived
(`openspec/changes/archive/2026-10-01-contact-payload-retention/`).

Depended on `pass-through-storefront-config`, which is complete. Task 6.5 is blocked on
`bare-metal-mock-provisioned-deal`'s two-storefront topology. Decision 13 in
`design.md` records what planning review settled; the planning pass amends these
sections to match it.

The design was settled in review; see `design.md` decisions 1–12. These tasks are
amended to match it at section level. The planning pass names the files each task
touches and the focused suites that prove it.

## 1. Survey and placement

- [ ] 1.1 Separate the bare-metal introduction composition into domain-neutral
      parts (accepted-state interpretation, `obligation_ref` re-derivation, the
      obligation drive sequence, `load_revealed_introduction`) and domain-supplied
      parts (persistence reads, configuration carrier, route bindings). Do the same
      for bare metal's seller delivery module and its buyer's introduction
      commands. Record the split before moving anything.
- [ ] 1.2 Promote into a new module in `kit/contact-exchange`, taking the
      negotiation-thread read, the settlement-obligation read, and the agreement
      origin read as declared Protocols (`design.md` decisions 2 and 3).
- [ ] 1.2a Add `uuid` to the kit's permitted import roots in its package-boundary
      test, as an explicit reviewable line, for worker-id generation in the drive
      sequence. Leave the deny list — `fastapi`, `httpx`, `market_alkahest`,
      `requests`, `stripe`, `hosted_settlement_client` — exactly as it is.
- [ ] 1.2b Do not land the glue in `kit/storefront`. It declares
      `arkhai-kit-alkahest` and `alkahest-py` as hard runtime dependencies.
- [ ] 1.3 Compose VM, and only VM. Bare metal already composes the mechanism.
- [ ] 1.3a Record API credits as out of scope with its reason (`design.md`
      decision 11), so a later reader does not read the omission as an oversight.
- [ ] 1.4 Confirm what the bare-metal contribution's per-mechanism fulfillment
      declaration says when it is hosted by the VM storefront process, before VM
      registers the mechanism process-wide (`design.md` risks).

## 2. Promote

- [ ] 2.1 Move the domain-neutral bodies into the kit module with the three domain
      reads injected as Protocols through the existing callback contract.
- [ ] 2.2 Promote the bodies unchanged. A promotion that also alters a check is
      unreviewable, and these checks are security checks — the `obligation_ref`
      re-derivation is what prevents a reveal against an obligation the accepted
      plan does not contain.
- [ ] 2.3 Leave the bare-metal storefront holding only its persistence reads,
      configuration carrier, and route bindings.
- [ ] 2.4 Confirm the mechanism kit's package-boundary test still passes and that
      the kit acquired no framework, HTTP client, delivery, or foreign-mechanism
      dependency.
- [ ] 2.5 Run the bare-metal introduction coverage unchanged against the promoted
      implementation before composing any further domain.

## 3. Compose VM

- [ ] 3.1 Register the mechanism in the VM storefront's settlement composition,
      which currently registers Alkahest and Stripe only, supplying persistence and
      configured values only. Declare it as not fulfilling through capacity in the
      composition's per-mechanism fulfillment declaration; that declaration is what
      lets an unbacked VM listing carry the option.
- [ ] 3.2 Add VM's introduction persistence as thin wrappers over the kit's
      `insert_introduction`, `load_introduction`, `delete_introduction_payloads`,
      and `select_expired_introductions`. VM's SQLite client already inherits
      `load_negotiation_thread_row` and `load_thread_binding`.
- [ ] 3.2a Add the contact-exchange migrations to VM's migration tuple at the same
      seam that already composes `*settlement_migrations()`.
- [ ] 3.3 Confirm composition is independent of whether a listing is
      capacity-backed, in both directions: a backed listing may settle by
      introduction, and an unbacked listing is not required to.
- [ ] 3.4 Bind the kit reveal service into VM's routes at `/api/v1/introductions`
      and `/api/v1/introductions/{obligation_ref}`, behind a VM authorization
      adapter, with the same wire shape bare metal serves.
- [ ] 3.5 **Integration.** Through the canonical clients against VM's in-process
      app: an accepted introduction deal reveals to both parties, an exact retry
      replays, a mismatched `obligation_ref` is refused with no payload, and the
      obligation reaches collected without VM fulfillment being invoked.

## 3a. Retention

`contact-payload-retention` implements retention in the mechanism kit and requires
every storefront composing the mechanism to run it. VM inherits the kit parts and the
configuration; this section is VM's wiring of them.

- [ ] 3a.1 Register the kit retention sweep loop with VM's loop controller, with its
      step and preview, on a configurable interval.
- [ ] 3a.2 Bind the kit retention admin service into VM's administrator routes behind
      VM's administrator authentication.
- [ ] 3a.3 Embed the kit disclosure object in VM's readiness response at `/health` and
      `/api/v1/system/health`, nested and present only when the mechanism is enabled,
      exactly as bare metal does.
- [ ] 3a.4 **Integration.** Through VM's canonical typed client: the readiness
      disclosure matches the reveal's; admin deletion leaves the obligation resolvable;
      read, start, and re-delivery answer the deleted outcome; the sweep step and
      preview work while the loops are held.

## 3b. Per-origin contact resolution

- [ ] 3b.1 Add the origin-keyed form `[Settlement.contact.origins.<origin>]` to the
      kit's contact configuration, each origin a table carrying `contact_payload`,
      with origins as bounded opaque strings, their count bounded, and each entry's
      payload required non-empty. Keep `contact_payload` as the single form
      (`design.md` decision 4).
- [ ] 3b.1a Rework `contact_preflight` for the keyed form: unready on no profiles
      or on no contact in either form, otherwise ready whatever individual origins
      lack; no per-origin detail in the public projection (`design.md` decision 4,
      "Readiness").
- [ ] 3b.2 Add the kit's composition check over the domain's known origins: refuse
      both forms together, the single form with more than one origin, and a keyed
      origin the storefront is not configured with, each naming the offending key or
      origins. Each storefront calls it at startup with its configured site keys.
- [ ] 3b.3 Pass the listing's origin into the kit option builder's publication
      inputs from both storefronts, taking it from the value the listing's durable
      binding records — in VM's `create_listing`, reorder so the settlement
      artifacts are built after the capacity source's site is read, and pass that
      site (`design.md` decision 5, "The origin is the binding's origin"). Build no contact-exchange option for an origin
      that resolves no contact; refuse the option when the keyed form is configured
      and no origin is supplied. No check is added at acceptance (`design.md`
      decision 5).
- [ ] 3b.4 Resolve the seller's contact per agreement in the reveal service from the
      agreement's origin under the running configuration; refuse a start whose
      origin resolves none with HTTP 503 `seller_contact_unavailable` before
      persisting, driving, or delivering. Replace bare metal's storefront-wide
      503 check (`design.md` decision 6).
- [ ] 3b.5 Resolve a single-origin deployment configured with the single form to the
      value it configures today, so existing operators see no change.
- [ ] 3b.6 **Unit.** Configuration forms including an empty entry's refusal, every
      startup refusal, readiness under each form, the resolver, and the option
      builder's suppression and fail-closed refusal.
- [ ] 3b.7 **Integration.** Two origins configured behind one storefront: a deal on
      each listing reveals that origin's payload, and neither reveals the other's.
      One listing is followed from publication through acceptance to reveal,
      asserting its binding's origin governed all three.
- [ ] 3b.8 **Integration.** An origin with no configured payload publishes no
      contact option, and a start for an accepted deal whose origin has lost its
      payload is refused with nothing persisted or delivered.

## 4. Delivery

- [ ] 4.1 Extend `kit/delivery`'s `[Delivery]` section with named sink instances:
      `enabled` lists instance names, an instance table may name its plugin with
      `sink`, and a table naming none instantiates the plugin of its own name.
      Reserve `origins` beside `enabled` and `timeout_seconds`.
- [ ] 4.2 Add the seller-side `[Delivery.origins]` routing table with its
      construction refusals (unenabled routed instance, unrouted enabled instance,
      unknown origin) and refuse a routing table on the buyer side. Refuse
      seller-side sinks with no routing table when more than one origin is known,
      unconditionally, naming the origins (`design.md` decision 7).
- [ ] 4.3 Move seller-side background dispatch (task retention, outcome logging),
      sink-set construction with warnings, and re-delivery into `kit/delivery`,
      reading the reveal and the agreement by shape and routing by the agreement's
      origin. Neither kit imports the other (`design.md` decision 7).
- [ ] 4.4 Move bare metal onto the kit dispatch and re-delivery, leaving its
      environment carrier and operator command binding.
- [ ] 4.5 Wire VM's delivery from its TOML `[Delivery]` section through the kit
      dispatch, seller-side off the reveal's critical path, and add VM's operator
      re-delivery command.
- [ ] 4.6 Confirm delivery remains non-authoritative and that re-delivery reads the
      durable reveal and routes by its origin.
- [ ] 4.7 **Unit.** Instance parsing including configurations that predate
      instances, two instances of one plugin, routing and every refusal including the
      multi-origin refusal without a table, a destination shared by every origin, and
      the dispatcher's routing and outcome reporting.

## 4a. Buyer introduction commands

- [ ] 4a.1 Promote the bodies of the bare-metal buyer's `introduce` and
      `introduction [--deliver]` into `core_buyer` as a command group a domain buyer
      mounts with its run-recovery hook and mechanism identity. `core_buyer` imports
      no mechanism package (`design.md` decision 8).
- [ ] 4a.2 Mount the group in the bare-metal buyer and remove its copies; keep its
      `request-introduction`.
- [ ] 4a.3 Add `request-introduction` to the VM buyer over the VM opening, and mount
      the core group, so VM buyers drive the same typed clients bare metal's do.
- [ ] 4a.4 **Unit.** The core group against an injected recovery hook, including the
      deleted outcome and sink failure; each domain buyer's command registration.

## 5. Specification and documentation

- [ ] 5.1 State in `openspec/specs/contact-exchange-settlement/spec.md` that
      accepted-state interpretation and the obligation drive sequence have one
      implementation, and that a composing domain supplies persistence,
      configuration, and route bindings rather than lifecycle logic.
- [ ] 5.2 Add a scenario covering the `obligation_ref` mismatch refusal, so the
      promoted security check is normative rather than incidental.
- [ ] 5.3 Update `openspec/specs/introduction-delivery/spec.md` for one seller-side
      dispatch across composing domains, named instances, and origin routing.
- [ ] 5.4 State in `openspec/specs/contact-exchange-settlement/spec.md` that the
      seller's contact is resolved per opaque origin, with its configuration forms,
      startup refusals, publication suppression, and reveal refusal.
- [ ] 5.5 Add the buyer introduction-command requirement to
      `openspec/specs/buyer-orchestration/spec.md`.
- [ ] 5.6 Document the origin-keyed contact form, its refusals, and delivery
      instances and routing in `docs/development/DEPLOYMENT_AND_CONFIG.md`'s
      contact-exchange section.
- [ ] 5.7 Update `docs/development/ARCHITECTURE.md`'s settlement-configuration
      delivery paragraph for per-origin contact and routing, including that a
      multi-origin storefront must route deliberately.

## 6. Validation

System scenarios are new modules only; no shared end-to-end helper or fixture is
edited. Where a scenario needs topology a lane lacks, the lane configuration edit is
named in the task.

- [ ] 6.1 Mechanism-kit, delivery-kit, and core-buyer boundary and unit suites.
- [ ] 6.2 Per-domain introduction reveal coverage, including retry convergence, the
      mismatch refusal, the per-origin refusals, and the post-deletion outcomes.
- [ ] 6.3 **System.** An end-to-end deal settling by introduction on the VM lane,
      including seller-side delivery.
- [ ] 6.4 **System.** Backed and unbacked VM listings from one storefront are returned
      by one buyer query across running services, and an unbacked one reaches a
      usable introduction. The query is bounded by asking rate, naming its asset and
      period, so it also proves unbacked supply is comparable on price with backed
      supply, and a listing publishing no rate is excluded. Transferred from
      `unbacked-listing-publication` (its 6.7); the rate bound from
      `publish-indicative-listing-rates` (its 7.13).
- [ ] 6.5 **System.** Two seller sites publishing unbacked supply to one storefront
      retain distinct origin and source identity, each introduction reveals its own
      seller's contact, and seller-side delivery reaches only that origin's routed
      instances. Needs 3b and 4.2, and a VM lane topology with two sites behind one
      storefront. Transferred from `unbacked-listing-publication` (its 6.8). The
      bare-metal counterpart belongs to `unbacked-bare-metal-listings`.

## 7. Closeout

- [ ] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. The local rationale to keep at the promoted glue is why the
      re-derivation check exists, not which domain it came from.
- [ ] 7.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where no genuine circular
      import or documented lazy-load reason exists. Verify against the real test
      suite; a promotion is exactly where a latent circular import surfaces.
- [ ] 7.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table.
- [ ] 7.4 **Narrative compression.** Shorten completed-task notes to final
      behaviour, and any remaining open work. Decisions and their alternatives are
      recorded in `design.md`; do not restate their reasoning here.
- [ ] 7.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, remove this change's
      rows from Goal 6's and Goal 7's gap tables and absorb the result into their
      current-state prose: contact exchange composed on VM, the contact resolved per
      origin, and delivery routed per origin. Keep the note beside Goal 6's unowned
      second-delivery-producer row current: the multi-origin routing refusal is
      unconditional, and a second producer revisits it.
- [ ] 7.6 **Campaign index currency.** Update this change's row and its campaign's
      dependency graph in `openspec/changes/README.md`, and
      `unbacked-bare-metal-listings`' blocker.
- [ ] 7.7 **Promotion.** Complete the design-promotion record below.
- [ ] 7.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=compose-contact-exchange-across-compute` and resolve every match.
      An unresolvable citation is a blocking defect under `AGENTS.md`'s
      cross-reference rule, and the target also rejects a citation whose
      target is a *tombstone*: a tombstoned file still exists on disk while
      its content is gone, so a plain existence test cannot fail on a
      rename-to-tombstone.
- [ ] 7.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and
      record the evidence: the run, its result, and the scenarios that
      exercise this change's behaviour. Green unit and integration suites do
      not substitute -- this is the tier that catches a wire contract whose
      two sides disagree, a service that starts cleanly and cannot settle,
      and a configuration gap no in-process test can see. If the pipeline
      cannot run for a reason unrelated to this change, record that as an
      explicit blocker naming the cause and the change that owns it, and
      treat the validations it gates as unrun rather than passed.
- [ ] 7.10 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports: environment and image installs derive their internal packages from
      their locks, every lock is current, and every Python version selection reads
      the root declaration.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Accepted-state interpretation and the obligation drive sequence have one implementation | `openspec/specs/contact-exchange-settlement/spec.md` |
| A composing domain supplies persistence, configuration, and route bindings, not lifecycle logic | `openspec/specs/contact-exchange-settlement/spec.md` |
| The seller's contact is resolved per opaque origin, guarded at publication and reveal; readiness stays storefront-wide; one origin from binding to reveal | `openspec/specs/contact-exchange-settlement/spec.md`; configuration in `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Seller-side delivery has one implementation and remains non-authoritative across composing domains | `openspec/specs/introduction-delivery/spec.md` |
| Sinks are named instances; seller-side delivery routes by origin, and a multi-origin storefront must route deliberately | `openspec/specs/introduction-delivery/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md`; `docs/development/ARCHITECTURE.md` |
| Buyer introduction commands are core-owned and domain-mounted | `openspec/specs/buyer-orchestration/spec.md` |
| Roadmap currency | `docs/development/ROADMAP.md`, Goals 6 and 7 |
| Campaign index currency | `openspec/changes/README.md` |
