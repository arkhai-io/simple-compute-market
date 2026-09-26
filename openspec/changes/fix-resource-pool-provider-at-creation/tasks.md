# Tasks

Section 0 keeps the numbering it has in `pools-9-retire-local-physical-authority`,
which points here.

## 0. Fix a pool's executor at creation

- [ ] 0.1 Reject a differing provider in `ResourcePoolService.replace_pool` and the
      patch path, instead of deleting the old handler's configuration and
      reassigning `pool.provider`. Rejection must not delete the existing
      configuration on its way out — a refused request leaves the pool exactly as it
      was. Follow `_require_backing_unchanged`'s placement: refuse before any write.
- [ ] 0.2 Leave provider configuration replaceable and patchable within the declared
      provider. This forbids changing which executor a pool routes to, not how that
      executor is configured.
- [ ] 0.3 **Unit.** Replace with a differing provider is rejected and the existing
      configuration survives; replace with the same provider and new configuration
      succeeds; patch with a differing provider is rejected; patch with the same
      provider is a no-op for the provider field.
- [ ] 0.4 **Integration.** The same cases through the real pool administration
      API and its canonical client, since the deletion this removes happens inside a
      transaction a service-level test can miss.
- [ ] 0.5 Confirm no fixture, bulk import path, definition-document import, or e2e
      setup relies on an in-place provider swap. If one does, migrate it to the
      two-pool path rather than exempting it.
- [ ] 0.6 Confirm `capacity-resource-administration`'s drain invariant covers the
      migration path this section makes the only one, and have the refusal name
      that path.

## 1. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 1.1 **Comment hygiene.** Run `make check-comment-hygiene`.
- [ ] 1.2 **Import placement.** Review imports this change adds or touches.
- [ ] 1.3 **Documentation compliance.** Re-check the accepted decision against
      `openspec/README.md`'s placement rules; it belongs in
      `resource-pool-management`, which owns provider configuration.
- [ ] 1.4 **Narrative compression.**
- [ ] 1.5 **Roadmap currency.** No roadmap gap row names this change; record that
      disposition, and remove the provider-swap sentence from Goal 1's
      current-state text if one was added.
- [ ] 1.6 **Campaign index currency.** Update this change's row in
      `openspec/changes/README.md`'s Goal 1 campaign.
- [ ] 1.7 **Promotion.** Complete the design-promotion record below.
- [ ] 1.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=fix-resource-pool-provider-at-creation` and
      resolve every match.
- [ ] 1.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and
      record the evidence. If the pipeline cannot run for a reason unrelated to
      this change, record that as an explicit blocker naming the cause and the
      change that owns it, and treat the validations it gates as unrun.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A pool's provider is fixed at creation; replace and patch refuse a differing provider without deleting existing configuration | `openspec/specs/resource-pool-management/spec.md` — "A pool's executor is fixed at creation" |
| Inventory moves executors through a second pool and member migration, safe under the drain invariant | `openspec/specs/resource-pool-management/spec.md` — same requirement |
