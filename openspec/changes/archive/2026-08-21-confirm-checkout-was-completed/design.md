## Context

`ChromiumCheckout` has two page-driving methods with the same shape and
different endings. `complete_setup` fills the form, submits, and then calls
`_await_checkout_left`, whose docstring states the rule: Checkout redirects to
the configured success URL once the intent is confirmed and stays where it is
otherwise, so leaving the page is the only in-browser signal separating a saved
instrument from a form that was silently rejected. `pay` fills the form,
submits, sleeps five seconds, checks for an interactive CAPTCHA, and returns.

Both are launched through `_browser_environment()`, which passes the process
environment minus sensitive keys. That is the right rule for everything the
environment actually controls, and a proxy is not one of those things for
Chromium.

Established by direct probe against the session a failed run left open:
launched as the harness launches it, the page reports `#cardNumber count=0` and
an empty body; launched with `proxy={"server": ...}`, the same URL reports the
complete form. The lane failure and the blank page are the same fact.

## Goals / Non-Goals

**Goals:**

- The card profile is exercisable locally on a machine whose egress is a proxy.
- A Checkout interaction that did not do what it claims says so, at the browser,
  naming what it was doing.

**Non-Goals:**

- Changing what the harness fills in, or which outcomes exist.
- Proxying the staged marketplace subprocess or the authority. Those speak to
  loopback and a proxy there would break them; the existing rule that the
  staged bridge inherits no ambient proxy stays exactly as it is.
- Making a protected run's egress implicit. The proxy is read from the run's own
  environment, which is where every other network setting for the run comes
  from, and a run with none behaves exactly as it does today.

## Decisions

**D1 — Pass the proxy explicitly rather than expecting Chromium to find it.**
Chromium ignores `HTTP_PROXY`/`HTTPS_PROXY` and consults system configuration.
Depending on the operator's system proxy would make the run's behaviour depend
on state the run cannot see or report, and a lane that silently fails to reach
the provider is what this change exists to remove. Reading the same variables
the rest of the run reads keeps one answer to "how does this run reach the
internet".

**D2 — Take only the HTTP proxy variables, never `ALL_PROXY`.** `ALL_PROXY`
here is a SOCKS endpoint, and Chromium's `--proxy-server` accepts SOCKS, but
the rest of the run cannot use it: the Python HTTP client refuses a SOCKS proxy
unless an optional dependency is installed. Taking a variable the rest of the
run has to have stripped would make the browser reach the provider by a route
nothing else in the run could, which is worse than not reaching it.

**D3 — Never proxy loopback.** The bypass list carries the loopback hosts
unconditionally, added to whatever `NO_PROXY` already names. The staged
marketplace, the authority, and the webhook forwarder are all loopback, and
sending them through a proxy would break a run that currently works.

**D4 — A payment waits for Checkout to leave, exactly as a setup does.** The
signal is already implemented, already documented, and already trusted for the
setup path. The five-second sleep it replaces was never a check — it was a
pause before a CAPTCHA probe — and the CAPTCHA probe stays, because a page that
answered with a challenge must still be reported as an environment failure
rather than a defect.

**D5 — The outcomes that stay on the page keep their own waits.** `decline` and
`insufficient_funds` succeed by Checkout refusing and remaining; `authentication`
completes a challenge first. Requiring them to leave would invert what they
assert.

## Risks / Trade-offs

- **A slow redirect could now fail a lane that previously passed by accident.**
  The wait is the setup path's existing timeout, which has been sufficient
  there; and a lane that "passed" without Checkout accepting the payment was
  going to fail at funding anyway, later and less clearly.
- **The proxy is read from the ambient environment.** That is where the rest of
  the run's egress already comes from, and a run with no proxy set is
  bit-for-bit unchanged.
