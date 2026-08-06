# Implementation Tasks

## 1. Publish declared dimensions

- [ ] 1.1 Re-verify `design.md`'s Context findings before editing: the five fields
      `vm_offer_resource_for_listing` currently builds, `ComputeResource`'s optional
      dimension fields, and the reconciler discarding all of `resource["capacity"]`
      except `gpu_count`.
- [ ] 1.2 Carry the projection's declared capacity map through `_publishable_slices`
      and the slice dictionaries instead of reducing it to `gpu_count`.
- [ ] 1.3 Extend `vm_offer_resource_for_listing` to emit each declared dimension the
      domain vocabulary recognizes, omitting undeclared ones. Derive the set from
      `arkhai_vms.DIMENSION_KEYS`, not a literal tuple.
- [ ] 1.4 Confirm no provisioning default (`default_vm_ram`, `default_vm_vcpus`,
      `default_vm_disk_size`) and no host-derived value can reach the published
      candidate.
- [ ] 1.5 Focused tests: all dimensions declared; some declared; none declared
      (byte-identical to today's published shape); a vocabulary dimension the
      projection does not declare stays absent.

## 2. Prove the discovery path end to end

- [ ] 2.1 Registry integration coverage: a listing declaring a dimension matches a
      `*_min` filter at or below its value and is excluded above it.
- [ ] 2.2 Regression coverage for the fail-closed case: a listing that declares
      nothing is still excluded by a dimension filter, unchanged from today.
- [ ] 2.3 One e2e path exercising `--ram-gb-min` against a real published listing,
      demonstrating the defect this change fixes.

## 3. Validation

- [ ] 3.1 Run the publication, reconciler, and registry suites, plus the VM e2e
      scenarios that assert published listing shape. Disclose any suite not run.
- [ ] 3.2 Run `openspec validate --all --strict` against the baseline current at
      implementation time.

## 4. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 4.1 **Comment hygiene.** Run `make check-comment-hygiene`. Read
      `vm_offer_resource_for_listing`'s and `_publishable_slices`' docstrings
      directly; both describe a GPU-only shape.
- [ ] 4.2 **Import placement.** Review imports this change adds or touches.
- [ ] 4.3 **Documentation compliance.** Confirm the publish-what-is-declared rule
      landed in `openspec/specs/storefront-publication/spec.md` and the
      omission-versus-inference reasoning in this change's `design.md`.
- [ ] 4.4 **Narrative compression.** Compress completed-task notes to final behavior,
      validation evidence, and promotion destinations.
- [ ] 4.5 **Roadmap currency.** Update Goal 2's current-state description and gap
      mapping in `docs/development/ROADMAP.md` — specifically the statement that
      listings advertise a GPU-only shape and that dimension filters match nothing.
- [ ] 4.6 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Published candidates carry declared dimensions and omit undeclared ones rather than substituting a value | `openspec/specs/storefront-publication/spec.md` — "Published candidates carry declared capacity" |
| The publishable dimension set derives from the domain vocabulary, not a fixed list | Same requirement, final scenario |
| Why omission beats inference (fail-closed under-matching versus over-matching that sells undeclared capacity) | This change's `design.md` |
| Deferral of the `ram_gb`/`memory_gib` naming discrepancy to `structured-capacity-requirements` | This change's `design.md` Open Questions |
