# Mediation library first-use evidence

## Scope and target

- Published `arkhai.mediation.v1` revision: see `kit/arkhai-mediation/schema/SOURCE.md`.
- Prepared target: the kit-owned vector-derived in-process contract fake, created and
  disposed by each invocation. No hosted service, container, database or deployment.
- Persona: payee claimant, with an explicitly supplied deterministic fixture bearer
  credential. No external secrets, seed files or ignored runtime state are required.
- Visual evidence: not applicable (library/CLI surface).

## Reproduce

```sh
make dist && env -u ALL_PROXY -u all_proxy NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1 make -C kit/arkhai-mediation demo
```

Observed first use: the authority records a filing before the response is deliberately
lost. The adapter reports `unknown`; read returns one case; the same-key retry returns
`accepted` without creating a second case. A payee claimant appends an evidence item,
receives `accepted`, and read returns record sequences `[1, 2]`. The client and fake
are closed at command completion. This is client-side contract evidence, not a ruling
or a live-service qualification.

## Validation

All commands use the proxy environment above (HTTP/HTTPS download proxies retained).

- `make -C kit/arkhai-mediation test`: 12 passed; mypy checks source and demo;
  generated models are current; producer record vectors and both ed25519/eip191
  claim frames and signatures verify and reproduce exactly.
- Built-wheel verification through `uv run --no-project --no-cache --find-links .dist
  --with .dist/arkhai_kit_arkhai_mediation-0.1.0-py3-none-any.whl python
  kit/arkhai-mediation/scripts/check_contract.py`: passed.
- `make check-architecture`, `make check-packaging`, `make check-comment-hygiene`:
  passed.
- `bunx @fission-ai/openspec@1.14.0 validate agreed-evidence-and-early-termination
  --strict`: passed.
- `make test`: attempted; provisioning units passed (607); provisioning integration
  initially passed 453 with one ambient-proxy fixture failure. The existing defect
  is tracked in [#323](https://github.com/arkhai-io/simple-compute-market/issues/323).
  The unreachable storefront fixture traversed an HTTP proxy and saw HTTP 503 instead
  of connection refusal. Its narrow closed-loopback-port repair preserves every
  assertion and changes no production behavior. The complete provisioning integration
  rerun then passed (454). Later aggregate targets were not reached; the full aggregate
  was not rerun after the fixture repair.

## Delivery-end trace qualification

Prepared target: `RulingTraceFake`, an invocation-owned, in-process peer replaying
producer outcomes, injected with the shared `PaymentsAuthority`. Both payer and
payee use the committed deterministic fixture credentials; there are no external
secrets or deployment selectors. The peer does not implement mediation remedies.
The payments dependency is dev-only, and no payment mechanism is imported by the
dispute kit or its fake.

Clean-checkout entry point (also run here):

```sh
make dist && env -u ALL_PROXY -u all_proxy NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1 make -C kit/arkhai-mediation test
```

Before: the lifecycle adapter refused every delivery-end intent. After: all 14
producer traces replay through the direct client and through lifecycle dispatch
(28 replay cases, plus the existing 12 integration cases: **40 passed**). See
`kit/arkhai-mediation/tests/integration/test_ruling_traces.py`. Observed coverage:

- Payee-filed returned stops, held-earnings reversal, unserved ordinary once share,
  capped penalty and setup kept/returned by the delivered flag.
- Receipt concurrence in a payer filing and later payee append; committed charged,
  returned and prorated treatment, including scheduled notice ends and past ends.
- Bad signature, wrong digest, different claim, missing/chosen payer stop entries,
  pre-start claims and repeat mechanical claims left open for the operator.
- Earlier ruling netting and an accepted stop whose lost response is retried with
  the exact original payment key/body/event, producing one effect.
- Lost filing/append responses, stable lifecycle keys, same-key adoption and
  changed-command refusal before I/O. A seller filing sends no payment events;
  every payment call comes from the producer-scripted authority peer.

Every signed record exposed by the client and adapter's retained evidence is
canonical-byte-identical to the trace. The independent shared payments peer
reproduces exact approval receipts, setup events, ordered per-call event responses,
post-call signed snapshots and final signed state. No signature or receipt field
is normalized. Raw invalid concurrence remains submit-able as operator evidence;
only verified matching concurrence is adopted by the intent mapper.

Validation:

- `make -C kit/arkhai-mediation test`: **40 passed**, mypy clean, generated models
  current, both ed25519/eip191 frames/signatures verified and reproduced.
- Installed-wheel replay in an isolated `uv run --no-project --no-cache` environment:
  exact resource bytes and publication hash checked, signing conformance passed,
  and all **40 integration cases passed** with both kits installed from `.dist`.
- Vector resource: **2,340,717 bytes**; wheel: **138,345 bytes** (vector compressed
  to 111,255 bytes). The schema remains byte-identical; provenance is recorded
  only in `kit/arkhai-mediation/schema/SOURCE.md`.
- `make check-architecture`, `make check-packaging`, `make check-comment-hygiene`
  and pinned strict OpenSpec validation: passed.
- Full `make test` was not rerun for this bounded library change. No browser,
  container, hosted target, server or background runtime was prepared or left up.
  Visual evidence remains not applicable.

## Remaining boundaries

The published models, claim signature API and delivery-end intent mapper are
installed. Respondent HTTP polling, receipt embedding and setup-bearing presets
remain separate unchecked tasks. The hosted
service has not deployed this contract revision, so no live evidence is claimed.
