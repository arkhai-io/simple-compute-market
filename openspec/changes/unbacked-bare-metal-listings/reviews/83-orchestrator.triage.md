# Triage — 83-orchestrator — unbacked-bare-metal-listings

These are the orchestrating session's observations, and the record names no commit. The
record numbers its one point O7; it is labelled R1 here.

### R1 — Closing a round view leaves an empty added file as a phantom edit

- **Lens / basis / severity:** process / evidence / minor (assigned; the record gives none)
- **Position:** agree. `round-view` adds the round's new files as intent-to-add entries,
  and the reset in `round-done` leaves an empty one's entry behind, reported as the owner's
  edit.
- **Proposed outcome:** fix — `round-done` rebuilds the index from the round head after
  resetting, with a test of a round adding an empty file, in this round's commit.
- **Owner disposition:** "Agreed. Add the fix to this rounds commit."
- **Result:** `scripts/round_view.py`'s `done` runs `git read-tree` on the round head after
  the reset; `scripts/tests/test_round_view.py` covers a round adding an empty file.
  `make test-release-tooling` passed.

Evidence for the round triaged in `85-implementation.triage.md`.
