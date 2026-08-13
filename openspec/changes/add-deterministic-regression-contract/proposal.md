## Why

Agent-driven runs are the most expensive tests in this system and the only ones
that find certain defects. Running them repeatedly to protect a defect they
already found is the wrong use of them. Converting a discovered defect into a
deterministic test moves that protection to a layer costing seconds and frees
the expensive layer to look for something new.

The conversion is not obviously safe, and three properties have to hold before
it is.

**A recording is not a specification.** A generated regression captures observed
behaviour. Nothing in the capture distinguishes correct behaviour from a defect
that happened to be present, so a regression generated from a run that passed
can freeze a bug into a fixture and defend it thereafter.

**A generated regression cannot prove what produced it.** It is hermetic by
construction, so it cannot exercise concurrency against a real barrier or a real
provisioner. A green regression suite must never be readable as concurrency or
capacity evidence — and it will be, because it is fast, it is green, and the
distinction lives in someone's memory unless it lives in the artifact.

**It is the one artifact that crosses jurisdictions.** `TESTING.md` places the
harness outside the four-level hierarchy deliberately. A generated regression
lands *inside* it. That crossing raises a question the document does not
currently answer: which level receives it, and who owns it afterwards.

This change defines the contract those three properties require. It generates
nothing.

## What Changes

- **Representation separated from execution.** A regression declares normalized
  actions and expected outcomes; how they are executed is an adapter. Hermetic
  execution is the default where adequate; a reviewed configuration may use a
  controlled integration environment where higher fidelity is justified.
- **Evidence proportionate to risk.** A regression protecting a corrected defect
  carries fail-before/pass-after or mutation sensitivity. Where neither is
  practical, another focused demonstration may be accepted and the substitution
  is recorded rather than assumed.
- **An evidence class that travels with the artifact**, recording which layer
  authored the regression and what it therefore cannot prove. A regression
  derived from an agent run is not evidence about agent-run conditions.
- **A sanitization requirement**: a regression derived from agent evidence is
  sanitized before it becomes a fixture in this repository, through the same
  allowlist boundary as any other crossing.
- **A jurisdiction rule**: a generated regression enters the level that owns the
  behaviour it protects, and is owned by that level thereafter.

Not in scope, and deliberately: deciding a regression is useful, when to
generate one, semantic reuse against existing coverage, materializing a
candidate, and the work-packet coverage record. Those are generation semantics
and they belong to the private change, which is design phase because they cannot
honestly be designed before a single regression exists.

## Impact

- Affected specs: `test-compatibility`
- Affected code: `e2e-tests/`, `docs/development/TESTING.md`
- Depends on `add-harness-findings-projection` for the evidence-class vocabulary
  a regression inherits, and on `refactor-e2e-fulfillment-lifecycle` for a
  target layer that asserts on fulfillment identity rather than provisioning job
  identity. A regression generated against the current assertions would encode
  the identity confusion that change is removing.
- **Ownership after the crossing is the unresolved consequence.** A generated
  regression sits in the product's test suite, was written from a trace the
  product team cannot read, and protects behaviour discovered by a tool they do
  not run. Someone maintains it when it fails for an unrelated reason. See
  `design.md`.
- **This change makes generation possible and does not authorize it.** Nothing
  here creates a regression, and the private generation semantics remain
  unplanned.
- Behaviour change to record: none. This defines a contract and adds no test.
- Evidence bound: whatever tests exercise the contract itself. It establishes
  that the contract holds of an artifact and nothing about any product
  behaviour.

## Permanent documentation impact

- [ ] `docs/development/TESTING.md` — which level a generated regression enters,
      who owns it, what its evidence class must record, and that a green
      regression suite is not concurrency or capacity evidence
- [ ] Existing subsystem specification — `test-compatibility`
- [ ] `docs/development/ARCHITECTURE.md` — none owed
- [ ] New subsystem specification — none owed
- [ ] `docs/development/ROADMAP.md` — none owed; the harness holds no goal row

### Knowledge to promote

See the design-promotion record in `tasks.md`.
