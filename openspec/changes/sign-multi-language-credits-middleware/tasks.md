# Tasks

## 1. Validation layer, before the signing work

- [ ] 1.1 Decide the scenario shape: one gated-app scenario per
      implementation, or one parameterised scenario that swaps the gated
      container. The Python sample app is already in the compose topology as
      `arkhai:apicredits-sample-app`; the question is whether the TS and Rust
      gated apps join it as sibling services or replace it per-run.
- [ ] 1.2 Build the gated app image for each implementation, wired the way
      the Python sample app is: the middleware in front of one metered
      endpoint, pointed at `credits-service`, with a mounted `service`-role
      credential and the authority's trusted principal.
- [ ] 1.3 A scenario per implementation, against a credits service with
      signed authentication **enabled**. Following the Python path: buy
      credits, call the metered endpoint, exhaust the key, observe the 402 and
      its purchase pointer, top up, call again. A scenario that passes against
      an unsigned service proves nothing this change cares about, so assert
      the service is in signed mode rather than assuming it.
- [ ] 1.4 Per-implementation unit and integration tiers consistent with
      `docs/development/TESTING.md`: unit owning the envelope construction,
      integration owning the client against a real service surface. Both trees
      currently have a conformance harness and little else, so this is new
      structure rather than an extension.
- [ ] 1.5 Confirm each new scenario fails against the unsigned client before
      the signing work in section 2 lands. A validation layer that passes
      before the thing it validates exists is not a validation layer — this
      repository has spent runs on that mistake three times.

## 2. Signing

- [ ] 2.1 TypeScript: request signing in the `service` role, ed25519, RFC 8785
      canonical JSON, the v2 envelope and its seven headers.
- [ ] 2.2 Rust: the same.
- [ ] 2.3 Both: the three gated operations and their signed resources must
      agree with `CREDITS_ROUTE_CONTRACTS` — `credits_key_consume` and
      `credits_key_verify` keyed by `key_id`, `credits_key_consume_batch` by
      the empty resource. That is now a fourth and fifth copy of one table;
      `domains/apicredits/tests/test_credits_route_parity.py` is the Python
      precedent for keeping copies honest and the pattern to extend.
- [ ] 2.4 Both: response verification against the authority's trusted
      principal, refusals included, mapped onto each gate's existing
      fail-closed deny path.
- [ ] 2.5 Both: credential and trust configuration, on the terms
      `domains/apicredits/compose.yml` already uses for the Python gated app —
      a read-only mounted credential and the authority principal supplied
      explicitly. Note that a mounted credential may be newline-terminated
      where the committed dev identities are not.

## 3. Conformance contract

- [ ] 3.1 Decide whether outbound authentication enters `session.json`.
      Extending it means every harness drives a signer; leaving it out means
      stating in `conformance/README.md` that the fixture's cross-language
      equivalence claim excludes authentication. Either is defensible; leaving
      it undecided is what let this gap exist unnoticed.
- [ ] 3.2 Whichever way 3.1 goes, reconcile `conformance/README.md`'s current
      interim note, which records the TS and Rust clients as shared-secret
      only.

## 4. Closeout

- [ ] 4.1 **Comment hygiene.** `make check-comment-hygiene`.
- [ ] 4.2 **Import placement.** Python-only rule; record the disposition if no
      Python changed.
- [ ] 4.3 **Documentation compliance.** Re-check this change's accepted
      decisions against `openspec/README.md`'s placement rules.
- [ ] 4.4 **Narrative compression.** Reduce completed-task notes to final
      behavior, validation evidence, and deferred work.
- [ ] 4.5 **Roadmap currency.** Update `docs/development/ROADMAP.md`, or
      record that this change has no roadmap impact.
- [ ] 4.6 **Campaign index currency.** Update this change's row and its
      campaign's dependency graph in `openspec/changes/README.md`.
- [ ] 4.7 **Promotion.** Complete the design-promotion record. The "a shared
      behavioural fixture that pins inbound behaviour does not pin outbound
      authentication" finding wants a permanent home; `conformance/README.md`
      is the candidate.
