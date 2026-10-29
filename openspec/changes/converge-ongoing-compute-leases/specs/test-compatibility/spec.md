## ADDED Requirements

### Requirement: One rate-servicing matrix qualifies both compute lanes

VM and bare-metal lanes MUST execute the rate-servicing matrix against the runnable payment and mediation doubles, including spot's prepared entry points. Each row MUST record physical progress, financial work and kept evidence separately. Reports MUST use the lane-double-owned classes Qualification against the published contract, Qualification against a proposed contract, and Live evidence; no double run MUST be labelled live.

#### Scenario: The full matrix runs

- **WHEN** either compute lane qualifies rate servicing
- **THEN** it covers baseline, payment-outage buyer end, absent-storefront withdrawal, interrupted effects, stop/disclosure races, rate activation expiry, exhaustion/hidden top-up, notice/earlier payer stop, start without disclosure, absolute maximum term with its own treatment, on-demand refused entitled notice followed by payment-adapter exceptional_end, and identity-rotation overlap/re-anchoring
- **AND** it records both completion facts and authority/evidence references for every row, including read-before-end on last-poll top-up and outage-only bare-timer correction

#### Scenario: Interim spot needs explicit buyer policy

- **WHEN** rows 7 or 9 use interim charged payee or term-end treatment
- **THEN** the run records explicit non-default buyer acceptance and separately observes default-policy refusal
- **AND** returned-capable terms have a distinct acceptance observation once vendored

#### Scenario: A notice outlives servicing

- **WHEN** the lane records seller notice and pauses the storefront loop past its effective time
- **THEN** the double stops without another seller call and resumed watch adopts the resulting record

### Requirement: Lane interruption is not durable restart evidence

Lane scenarios MUST use pause/resume and uncertain-response controls for cross-service convergence. Durable restart MUST be proven at integration level by rebuilding the production application over the same database in both compute domains. Pause/resume MUST NOT be reported as process restart; bare-metal lanes MUST retain their no-service-restart boundary.

#### Scenario: A filing response is lost

- **WHEN** a lane loses a filing response and resumes servicing
- **THEN** it proves same-operation cross-service resolution, not durability across process restart

#### Scenario: Production application is rebuilt

- **WHEN** integration rebuilds after a journaled final request or partially applied ruling
- **THEN** the original operations/cursors and completion history recover without duplicate effects

### Requirement: Rate lanes use coherent real time

Cross-service rate scenarios MUST run the doubles in wall-clock mode with short fixture periods/deadlines and bounded readiness/event waits. Setup MUST check clock skew and wait budgets and fail on incoherence before scenarios. Double clock jumps MUST NOT outrun storefront/site clocks. Deterministic injected-clock expiry/race permutations MUST remain library-integration evidence, not a new lane clock API.

#### Scenario: Funding and site deadlines are observed

- **WHEN** the lane waits for authority funding expiry or a site activation deadline
- **THEN** all peers use real UTC instants and typed due-work barriers reporting per-authority watermarks, pending effects and blocked dependencies; future work stays pending and blocked effects never count as completion
