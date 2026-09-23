# Tasks — bare-metal publication reads pool declarations

## 1. Design

- [ ] 1.1 Decide the open question in `design.md` (candidate source versus join) and
  record the decision there.

## 2. Publication

- [ ] 2.1 Load each trusted site's resource-pool projection in the bare-metal
  storefront's publication path, with `arkhai-kit-resource-pools` as a storefront
  dependency.
- [ ] 2.2 Resolve every candidate's pool through `read_site_declarations`; drop
  candidates whose pool does not advertise `bare_metal` or is disabled, hold those
  whose pool is unresolvable, and refuse an unbacked pool with an operator notice.
- [ ] 2.3 Close existing listings whose pool no longer authorizes them through the
  bare-metal source reconciliation.

## 3. Validation

- [ ] 3.1 Tests for each outcome in 2.2 and 2.3, including a held pool whose listings
  are neither closed nor refreshed.
- [ ] 3.2 `make test-bare-metal` and `make check-reinit`.

## 4. Closeout

- [ ] 4.1 The closeout task defined in `openspec/README.md#plan-closeout-requirements`,
  including widening the advertisement requirement in
  `openspec/specs/storefront-publication/spec.md`.
