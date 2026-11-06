# Nested codec and contract evidence

Observed 2026-11-06 on the stacked open-ended-terms branch. This is section 1's
contract freeze and code-level first encounter, not recurring execution or a
completed terms product. D2a retains monetary Agreement.amount. The implementation
inputs are in `openspec/changes/negotiate-open-ended-compute-terms/dependency-contracts.md`.

## Setup and target

From the repository root, build repository wheels with `make dist-ci` and run:

```sh
make -C kit/deal-lifecycle reinit
make -C kit/arkhai-payments reinit
make -C core/registry reinit
make -C domains/vms/buyer reinit
make -C domains/bare_metal/buyer reinit
```

The probes use only deterministic development identities, example accounts and an
invocation-owned SQLite registry. No secrets, seeded external state, live service,
browser, wallet approval or physical resources are needed. No server survives the
probe. The registry probe checks `/health` before publishing through its typed
client. Its in-process ASGI transport is the owned target, not a shared deployment.

## Buyer and publication probes

Run from the root. The shared script invokes the installed hosted once option
builder, registry request/response carriers and lifecycle codec. Both domains then
use their actual pre-approval checks against the same accepted bytes and mandate.
The temporary publication file contains only public development fixture data.

```sh
(cd domains/vms/buyer && uv run --frozen --no-sync python - <<'PY'
import base64
import json
import runpy
from pathlib import Path
from arkhai_vms_buyer.settlement_stages import PaymentsBuyerStage

probe = runpy.run_path('../../../openspec/changes/negotiate-open-ended-compute-terms/codec_probe.py')
outcome, approval, publication = probe['probe']()
PaymentsBuyerStage().validate_acceptance(outcome)
approval.check(base64.b64decode(outcome.agreement_bytes), outcome.settlement_data)
Path('/tmp/open-terms-publication.json').write_text(json.dumps(publication))
print('VM acceptance and pre-approval checks: PASS')
PY
)
(cd domains/bare_metal/buyer && uv run --frozen --no-sync python - <<'PY'
import runpy
from arkhai_bare_metal_buyer.settlement_stages import PaymentStage

probe = runpy.run_path('../../../openspec/changes/negotiate-open-ended-compute-terms/codec_probe.py')
outcome, approval, _ = probe['probe']()
PaymentStage.validate_acceptance(outcome, approval)
print('bare-metal pre-approval check: PASS')
PY
)
(cd core/registry && uv run --frozen --no-sync python \
  ../../openspec/changes/negotiate-open-ended-compute-terms/registry_codec_probe.py \
  /tmp/open-terms-publication.json)
```

All pass. The registry returns 201 on typed publication and 200 on readback;
its stored seller proof verifies historically, and the nested lifecycle remains
identical through readback and codec projection. Both buyer pre-approval checks
pass without invoking payment approval I/O. Alkahest is admitted without lifecycle
and refused with it by the shared authority-selection policy. The richer payer/
payee early-termination object round-trips structurally and changing notice changes
its option ID; no hosted recurring materialization is claimed.

Corrected diagnostic attempts: the first wrapper used one excess `../`; the
registry fixture initially omitted required `listing_resource.region`; and the
probe was corrected to use the verifier's `verified` property. These were probe
setup errors, not product failures. The commands above include the corrections.

## Existing focused regressions

```sh
(cd kit/deal-lifecycle && uv run --frozen --no-sync pytest tests/unit/test_terms.py -q)
(cd kit/arkhai-payments && uv run --frozen --no-sync pytest \
  tests/test_agreement.py tests/test_buyer.py tests/test_settlement_config.py -q)
(cd core/registry && uv run --frozen --no-sync pytest tests/integration/test_listings.py -q)
(cd domains/vms/buyer && uv run --frozen --no-sync pytest \
  tests/test_negotiate_stage_dispatch.py tests/test_buy_orchestrator.py -q)
(cd domains/bare_metal/buyer && env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy uv run --frozen --no-sync pytest \
  tests/test_buyer_composition.py tests/test_run_log_recovery.py -q)
```

Results: 47 + 51 + 17 + 21 + 15 passed. The bare-metal invocation initially failed
because ambient SOCKS proxy configuration needed an uninstalled optional socksio
package. Clearing proxies only for this local invocation passed all 15; no
product change or dependency installation was needed. Registry tests report
existing Pydantic/SQLAlchemy deprecation warnings.

The lifecycle/payments suites are unit-level. Registry listing tests are
application integration through the typed registry client. VM tests use mocked
negotiation/transport seams. Bare-metal tests mix pure composition checks with a
controlled in-process storefront negotiation/recovery path; they are not deployed
system evidence. No new permanent acceptance tests were added.

`make check-packaging` and `make check-change CHANGE=negotiate-open-ended-compute-terms`
passed, including comment hygiene and pinned strict OpenSpec validation.

## Limits and next encounter

No UI surface, actual buyer selection flow, hosted rate approval, billing stop,
materialization, startup continuation, delivery, E2E stack, promotion or archival
has been attempted. Section 1 freezes contracts; section 2.1 must implement the
unit accessor and preserve verified accepted pricing evidence before migrating
recovery/mandate readers. The current VM buyer's listing subset is not yet that
full evidence packet. Independent implementation review is still pending.
