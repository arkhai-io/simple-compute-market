# Design

## Grounding

Audited against `origin/dev` at `e91767a3b074b20168bbcb87a8418d8287e5f8a6`.

### The documented buyer path

`docs/buyer-quickstart.md` is the product-owned target. Its six sections —
Prerequisites, Install, Configure, Browse, Buy, Resume, Tear down, plus Common
pitfalls — instruct a reader to run:

```
uv tool install arkhai-core-buyer --with arkhai-vms-buyer
market --version
market listing list  /  market listing list --gpu-model  /  market listing show
market buy  /  market buy --from
market logs runs  /  market logs show
market escrow reclaim
```

Configuration is a `[registry] urls` list, optional per-registry read tokens
keyed by exact URL, and a negotiation policy chain. That is the surface an
adapter binds to.

Binding elsewhere is the failure worth naming. An adapter that calls an internal
buyer client, or posts to a negotiation endpoint directly, would run green while
the documented path was broken — which is the specific defect class this harness
exists to catch. The installed CLI is the contract because it is what a buyer
has.

One current obstruction, recorded not resolved: `market buy` cannot load the VM
buyer domain until `compose-domain-wheels-and-policies` closes. The binding is
still to the documented target; end-to-end exercise waits.

### What the archival branch did instead

`wrappers/emit-buyer-request.sh`, `wrappers/publish-listing.sh`, and
`wrappers/start-seller-service.sh` are controller-side action emission. The
reconcile change's own rejected-alternatives entry names the reason:
controller-owned buyer actions measure a controller driver, not the intended
agent-driven load generator.

The instructive part is not that the boundary was crossed. It is that nothing
detected it. The wrappers made the harness simpler, more deterministic, and
easier to test, and produced results shaped exactly like the results the
intended design would produce.

## Decisions

### The boundary is enforced by capability, not by instruction

The controller has no code path that performs a documented buyer action. Not a
discouraged one, not one behind a flag — none. Buyer actions live in the buyer
adapter, which the controller starts and does not call into.

Rejected: a rule in the actor instructions telling the controller not to emit
buyer actions. That is the control the archival branch had, in the form of a
design intent, and a wrapper script satisfied every test while violating it.

Rejected: a runtime assertion that the emitting process is the actor. It catches
the violation later than the design does, and it can be satisfied by a
controller that starts a process solely to emit on its behalf — which is the
same defect with an extra hop.

The consequence to accept: some things are harder. A controller that cannot
perform a buyer action also cannot conveniently pre-seed buyer state, and
scenario setup that wants that must express it as an actor action or as
product-owned preparation. That inconvenience is the boundary working.

### Requests are frozen before the barrier

Each buyer's request is fixed before the barrier releases and immutable
afterwards. Freezing is what makes concurrent outcomes comparable: buyers whose
requests differ are not contending, they are doing different things at the same
time.

The frozen request is part of the result record, so a reviewer can confirm the
buyers were actually contending rather than take it on trust.

Rejected: letting an actor construct its request at release time. It is more
realistic and it destroys the comparison — an actor that composes a slightly
different request has changed the experiment, and nothing in the result would
show it.

### Observation is independent of the observed

An observer captures what happened; the actor's own account is a separate
record, never the only one. Where they disagree, both are retained and the
disagreement is itself reportable.

Rejected: trusting actor self-reports. The actor is the component whose
behaviour is least predictable and whose account is most likely to be a
plausible reconstruction. A harness whose evidence is the actor's narrative
inherits the actor's failure modes.

### Live adapters fail closed by configuration

Selecting a live market, wallet, cloud, host, provisioning, VM, GPU, or
authenticated repository-hosting adapter fails before a subprocess starts or a
socket opens. The check is on the resolved configuration, not on a
runtime branch an actor could reach.

Rejected: refusing at the point of use. It is one bug away from not refusing,
and the failure mode is an external effect nobody authorized.

### Whether a real model runs

The prevailing rule is that a real-model component is warranted only where a
changed boundary cannot be exercised faithfully by fake processes, and that
otherwise the right output is a recorded reason why fakes are adequate — the
intent being not to run a model ceremonially. That rule is correct for what it
protects: proving a seam works does not need a model, and running one to feel
thorough is waste.

It does not cover the other reason a real model is necessary.

The harness's cheapest genuine capability is establishing that the documented
buyer path is executable by someone with no repository context. That claim
cannot be established by a fake process. A fake follows a script someone wrote
after reading the code; it cannot fail the way a reader fails, on a missing
prerequisite, a stale command, an install that assumes an unpublished wheel, or
a step whose output no longer matches. Substituting a fake does not weaken the
evidence — it produces no evidence for that claim at all.

So this change recognises two reasons a real-model component may be necessary,
and asks that the governing rule be widened to match rather than reinterpreted
quietly:

1. a changed boundary that fakes cannot exercise faithfully — the original
   reason; and
2. a claim about documentation executability, which fakes cannot support by
   construction.

Under reason 2, the smallest sufficient component is one actor following the
published buyer quickstart with no repository context, against a local stack.
Not a campaign, not a contention row, not a model in the controller.

Whether that component runs *in this change* or is deferred depends on the
widened rule being accepted. Until it is, this change
implements the diagnosis handoff and the fake-process paths, and records the
model-dependent claim as unproven rather than asserting it. It does not
substitute a fake result and call it evidence.

Rejected: reading the existing rule as already permitting reason 2. It does not,
and quietly widening a criterion is how a plan loses track of which version of
itself is in force. The widening is requested and recorded, not assumed.

### A passing run produces receipts and no diagnosis narrative

An actor owes a structured investigation and root-cause handoff. The shape is
clear for a failure. For a run that succeeded, it is not clear whether the actor
owes anything beyond its receipts — and requiring narrative for a passing run
invites plausible narrative, which is the thing least worth recording.

**Decided:** a passing run produces receipts and no diagnosis. Revisit if a
recurring class of near-miss turns out to need one.

## Open questions

### Is the widened real-model rule accepted?

Requested above. If accepted, one actor following the buyer quickstart against a
local stack becomes in scope, and the documentation-executability claim can be
proven here. If not, the claim stays unproven and nothing in the public work
owns establishing it.

Needs a decision from whoever governs the harness's execution rules, not a code
reading.


---

## Disposition

**Archived 2026-08-26.** Superseded by `define-participant-contracts-and-action-boundary`, in the testing-harness repository, not implemented.

**What carried forward.** The action-ownership boundary, independent observation, and frozen requests carry forward close to verbatim. The boundary is now expressed per effect rather than per role, because the same effect class is a fixture before a scenario starts and under test after it, for the same participant.

**Referenced, not duplicated.** `design.md`'s account of how the abandoned branch crossed this boundary — a wrapper emitting a buyer request from the controller side, with tests passing throughout — is why the successor enforces by capability rather than by review. It is cited, not restated.
