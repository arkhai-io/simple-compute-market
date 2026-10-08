# Tasks

Proposed 2026-10-05, from `bare-metal-mock-provisioned-deal`'s 5B.10 gate. Not yet
designed: the first task decides how specs express the restructured requirements
(MODIFIED deltas promoted at closeout, or another route the maintainer chooses),
and `skip_specs` in `.openspec.yaml` is revisited with it.

- [ ] 1. Inventory every requirement 1.14.1 flags in `openspec/specs/`, per
      capability, and decide the delta mechanism with the maintainer.
- [ ] 2. Restructure each flagged requirement without changing its meaning;
      record any requirement that cannot be restructured without a meaning change
      as a finding for its capability's owner.
- [ ] 3. Move the validator pin in `openspec/README.md` forward, and pass
      `validate --all --strict` under it.
- [ ] 4. Closeout, per `openspec/README.md#plan-closeout-requirements`: comment
      hygiene; import placement (no code is expected to change, so a recorded
      no-op); documentation compliance; narrative compression; roadmap currency
      (expected: no roadmap impact, recorded explicitly); campaign index currency
      (this change's row in `changes/README.md`); documentation citations; packaging
      (expected: no package change, recorded); end-to-end pipeline (expected: no
      behavior change, recorded with the run used); promotion record.
