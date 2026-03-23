# Lessons Learned

This document captures what the live stand-up, deployed canary, and human buyer
operator work taught us while taking the repo from strong local coverage to
repeatable live proof on Ethereum Sepolia.

## Local e2e Was Necessary But Not Sufficient

Local e2e was necessary but not sufficient.

The repo already had meaningful local and CI coverage, but that still left gaps
at the live edge:

- deployed containers could keep stale chain configuration after `docker restart`
- real funding behavior could differ from local assumptions
- SSH behavior through real FRP endpoints could differ from local dry runs
- the live seller inventory could drift away from example values in the docs

The practical lesson was that "the repo tests pass" and "a human can buy
compute from the live isolated environment right now" are different claims.

## Live Configuration Must Be Treated As A Contract

Several failures turned out to be configuration-contract failures rather than
core protocol failures:

- switching chains was not a drop-in change
- updating local env files did not guarantee the remote containers were using them
- the human walkthrough hardcoded an `H200` seller offer even when the live
  seller was only advertising a different resource through `/resources/portfolio`

That is why the live path needed:

- chain preflight checks
- scripted rollout instead of ad hoc restarts
- seller-offer seeding from the live portfolio

## Funding Was More Subtle Than "Buyer Has Some ETH"

The buyer path needed more than one simple balance check:

- native ETH for gas
- WETH for payment
- enough extra native ETH to perform the WETH wrap and still pay escrow gas

This is what drove the fixes in `scripts/pre_canary_fund.py`. Real live use
exposed that the funding plan had to reserve for both the payment asset and the
transaction envelope around it.

## Human Operator Paths Fail On Small Mismatches

The human flow exposed issues that earlier automation had hidden:

- the CLI needed separate request and auth URLs because requests went through a
  local tunnel while signatures still had to target the canonical `AGENT_AUTH_URL`
- the wait helper initially selected stale create jobs
- the SSH probe needed IPv4 forcing on this machine even though the FRP port
  itself was reachable

These were not deep architectural problems, but they were enough to break the
human path until they were encoded into the scripts.

## Inventory Must Come From The Live System, Not From Examples

One of the clearest lessons was that the seller order should be derived from the
live portfolio, not from an example copied into a runbook.

The walkthrough originally let an operator create a seller order for inventory
that the seller could not actually fulfill. The fix was to make the seller
offer come from the live portfolio instead of relying on a hardcoded GPU model.

## TDD Was Most Useful Once A Live Failure Was Reproducible

The best working pattern was:

1. hit a real live failure
2. extract the concrete defect into a focused failing test
3. patch the narrowest possible thing
4. run focused tests
5. run the repo sweep
6. commit immediately

That pattern paid off for:

- signed transaction compatibility in `scripts/pre_canary_fund.py`
- buyer-side WETH funding and gas reservation
- tunnel/auth URL handling in the CLI path
- live-portfolio seller seeding
- IPv4 SSH probing in `scripts/wait_for_human_purchase.py`

## Repo Consistency Tests Were Worth Expanding

The repo consistency checks were useful not only for code correctness, but also
for workflow correctness:

- making sure the human-buyer scripts existed
- making sure the runbook referenced the right entrypoints
- making sure the new lessons learned note stayed linked from the stand-up index

That prevented the live operator workflow from drifting away from the repo again.

## The Canonical Full Matrix Was Helpful, But Not The Whole Story

`run_full_repo_validation.py` was the right baseline, but it was not the
entire live-risk surface by itself. The local dual-agent e2e, the live canary,
and the human buyer flow each exercised operational seams that the matrix did
not fully prove on their own.

The lesson is not that the matrix was wrong. The lesson is that live proof still
needed explicit outer-loop workflows on top of it.

## Shared Local Secrets Were The Right Direction

Moving reusable RPC and wallet material into `~/.config/web3-ops` reduced
project-specific secret sprawl and made the live tooling easier to reuse safely
across projects, while still allowing the local project overlay to render the
exact env bundle it needed.

## Cleanup Has To Be Part Of The Happy Path

Repeated live testing only stayed viable because cleanup became part of the
normal contract:

- close seller and buyer orders
- reclaim the VM
- verify destroy and undefine complete
- persist artifacts for the run

Without that, the environment would quickly become noisy and difficult to trust.

## Bottom Line

The hard part was not the basic buyer/seller protocol. The hard part was the
edge contract around it:

- live chain configuration
- funding behavior
- tunnel and auth assumptions
- inventory truth
- operator ergonomics

The repo is materially better now because those edge conditions are encoded in
scripts, tests, and docs instead of being left as tribal knowledge. The live
outer-loop proof now complements the local test matrix instead of sitting
outside it.
