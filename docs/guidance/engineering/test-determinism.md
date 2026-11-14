---
tags: [engineering, testing]
---

# Deterministic tests

A test that depends on timing passes or fails by chance. These rules keep every
test's outcome a function of the code under test.

## No sleeps

A test exercising a background job-processing loop never sleeps or races a bare
timeout to wait for a side effect, which produces intermittent failures. It uses an
explicit seam instead: an injectable callback invoked at the point the test needs to
synchronize on, absent in production and free there, which the test uses to signal
an event it then waits on with a bound. If no such seam exists where a test needs
one, adding it is the fix, not a sleep.

## Tests wait on events, never on durations

A test does not spend the time a scenario passes through. An interval, timeout, or
deadline the code under test waits out is driven in fake time, through the injected
clock and sleep or wait the code already takes, or a seam added for it. A state the
test needs is signalled by the code reaching it, such as a thread arriving at a
lock, not assumed after a pause. A deadline the scenario is defined by is asked as a
deadline of now, and a lock the code must find held is met with no busy timeout. Real
time is spent only to prove a real operating-system timeout, such as a subprocess
killed at its limit, by one test per boundary. The one standing exception is a real
server a test cannot replace with an in-process transport, whose library stops only
at its next poll ([Testing Python](testing-python.md), "Waiting on a background
job").

## Leave nothing held

A test that holds work at a gate — a job paused before its result, say — ends that
hold itself, by releasing the gate or cancelling the work, so the test is idempotent:
it leaves nothing parked for the next test, the next module, or a rerun, and holds no
queue slot. A job's status is not the evidence: a cancelled job is terminal the
moment its cancellation commits, while its execution may still be waiting. The test
waits on the execution itself — the gate's release, the queue going idle — and
asserts nothing is still waiting. Cancelling held work ends its execution without a
release; a double whose cancellation leaves the run waiting is a defect in the
double, not something to release around.
