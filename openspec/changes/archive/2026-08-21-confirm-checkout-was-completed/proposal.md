## Why

An interactive `card.v1` lane against the real Stripe test account fails with
`funding never converged ... status='requires_action', action_kind='payment'`.
The Checkout session it was waiting on is still `open` and `unpaid`. The lane
reports the symptom three steps downstream of the cause, three minutes later,
and names neither the page nor what it did there.

Two separate things produce that.

**The browser never reaches Checkout on a proxied network.** Chromium does not
read `HTTP_PROXY`/`HTTPS_PROXY`; it takes a proxy only as a launch argument or
from system settings. The harness passes the environment through and no
argument, so on a machine whose egress is a proxy the page loads its shell and
mounts nothing. Verified directly: the same session URL renders no card field
in a Chromium launched the way the harness launches it, and renders the
complete form in one launched with the proxy the rest of the run already uses.

**A submitted form is treated as a completed payment.** `pay` clicks submit,
waits five seconds, checks for a CAPTCHA, and returns the outcome it was asked
for. Nothing checks that Checkout accepted anything. The setup path in the same
file already refuses to do this — `_await_checkout_left` exists precisely
because "the submit click is not the outcome" — and the payment path never
adopted it.

## What Changes

- The browser is launched with the run's configured proxy when one is set,
  because it cannot otherwise reach a provider the rest of the run reaches.
  Loopback stays excluded, so the staged marketplace and the authority are
  still spoken to directly.
- A payment claims its outcome only after Checkout leaves its own page, which
  is the same signal the setup path already requires. A form that was silently
  rejected is reported at the browser, naming the stage, rather than surfacing
  minutes later as a funding timeout.
- Unchanged: the decline, insufficient-funds, and authentication outcomes,
  which deliberately stay on the page and already have their own waits.

No requirement changes: a lane that cannot reach the provider must say so, and
a stage failure must name the stage. This change makes the harness do what is
already required of it, so it carries `skip_specs: true`.

## Capabilities

### Modified Capabilities

None. See above.

## Impact

- `e2e-tests/src/hosted_real_stripe/browser.py`
- `e2e-tests/tests/unit/` — coverage for both.
- `docs/development/TESTING.md` — the proxy note for a machine that needs one.
