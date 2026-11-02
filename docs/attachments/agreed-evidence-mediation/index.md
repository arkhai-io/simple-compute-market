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

## Remaining boundaries

The published models and standalone claim signature API are installed. Delivery-end
intent mapping and its mechanical qualification, respondent HTTP polling, receipt
embedding and setup-bearing presets remain separate unchecked tasks. The hosted
service has not deployed this contract revision, so no live evidence is claimed.
