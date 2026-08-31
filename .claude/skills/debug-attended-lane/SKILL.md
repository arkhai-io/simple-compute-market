---
name: debug-attended-lane
description: Diagnose a hosted-settlement Stripe lane that failed, whether a human drove it through attended-lanes.sh or it ran unattended. Use when a lane reports a result other than passed, when someone says "debug the attended lane in <dir>", or when protected evidence carries a stage and a diagnostic code and nothing else.
---

# Debugging a failed lane

A lane a human drove and a lane that ran unattended fail the same way and get
fixed the same way. This skill exists so the human-driven one does not become
a worse debugging experience than the automated one.

## The fact that shapes everything

A protected run keeps no diagnostics. `retain_diagnostics` is set to
`release.mode == "local"` in three places in `e2e-tests/src/hosted_real_stripe/driver.py`,
and evidence validation permits a failed run exactly one stage-matched
diagnostic code and nothing else. That is the sanitization requirement working,
not a bug, and it is why `payer_profile_unavailable` was undiagnosable until
`openspec/changes/archive/2026-08-19-separate-protected-run-release-gate` made
the body runnable outside a protected run.

So do not try to extract more from protected evidence, and do not weaken what
a protected run discards. Reproduce the lane as a development run instead.

## The loop

1. **Read the artifacts.** An attended lane leaves a directory under
   `.dist/attended-runs/<stamp>-<scenario>/` holding `lane.env` (the resolved
   environment, no secrets), `evidence.json`, `console.log`, and `rerun.sh`.
   Start with `result`, `stage`, and `diagnostic.code` in the evidence. If a
   run left no directory, the same three fields are in whatever evidence file
   it wrote.

2. **Reproduce it as a development run.** Same lane, `make hosted-stripe-test-local`
   instead of `hosted-stripe-test`. This is the step that discloses the child
   exception the protected run threw away:

   ```bash
   set -a; . .env.stripe-protected.local; . .dist/attended-runs/<dir>/lane.env; set +a
   make hosted-stripe-test-local HOSTED_STRIPE_TEST_EVIDENCE=.dist/local-evidence.json
   ```

   A development run prints `[development] <ExceptionType>: <message>` for each
   cause in the chain. That line is the thing you came for.

3. **Fix against the development run.** Iterate there. It is faster, it keeps
   its diagnostics, and it does not spend a fresh connected account.

4. **Re-qualify under a protected run.** Only protected evidence qualifies. For
   an attended lane, run the directory's `rerun.sh`, which restores the exact
   environment. Development evidence never qualifies no matter how green it is.

## Reading the stage

The stage names where the lane stopped, which is often several steps from what
broke. Past examples worth knowing:

- `browser_checkout` with `chromium_unavailable` on an interactive card lane
  used to be reported as the provider's CAPTCHA. Measured against a live
  Checkout page, that was a false positive: hCaptcha loads its challenge frame
  on *every* submitted Checkout, button and all, and hides it in the parent
  document. Asking the frame about its own contents cannot see the parent's
  CSS, so it answered `visible` on pages showing nothing. The detector now
  asks the hosting iframe instead. What headless Chromium actually meets is
  not a challenge but a silent stall: the submit button sits at `Processing`,
  the page shows no error, and no PaymentIntent is ever created -- for a plain
  `4242` success card as much as a 3DS one, and in a visible window as much as
  a headless one. Someone touching the page is what releases it, which is why
  interactive card lanes are `excluded` when unattended. An attended run now
  asks for the payment to be finished in the window and waits five minutes,
  for a stall and for a real challenge alike, so `checkout_contract_rejected`
  from an attended run means nobody finished it in time. `_complete_
  authentication` also names the controls the page was offering when it gave
  up: `Pay Processing` there means the submit stalled and 3DS never started,
  and it is not evidence that the 3DS selectors are stale. If a lane reports
  `excluded` with `interactive_lane_not_automated`, it was never attempted:
  it needs `--attended`.
- `loss_boundary` on `ach_return` or `post_collection_loss` reports `excluded`
  with `loss_projection_unimplemented`. Nothing on the consumer side observes an
  authoritative funding loss or blocks fulfilment on one. That is a known gap,
  not a lane to debug.
- `funding_authorization` with no `settlement_ref` was the storefront caller
  allowlist being unset. See `openspec/changes/archive/2026-08-19-name-hosted-rejection-reasons`.

## What not to do

Do not add fields to protected evidence to make a failure easier to read. Do not
treat a development run's pass as qualification. Do not re-run an interactive
card lane unattended to "check quickly": it will be excluded, or it will fail on
a challenge nobody is there to answer.
