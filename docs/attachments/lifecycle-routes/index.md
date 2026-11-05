# Lifecycle router and cooperative ending

Nonvisual implementer first-use evidence, not independent acceptance. No hosted
service, external credential, browser or container is required or created.

## Prepared target and entry point

The checkout-owned environment installs internal dependencies from fresh `.dist`
wheels. The invocation creates and deletes its own SQLite database and mounts the
production router on FastAPI with an in-process ASGI transport. Buyer, seller,
administrator and stranger use explicitly deterministic public development
identities; never use them on a public network. No inherited deployment selector
or ignored configuration is consumed.

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist
make -C kit/deal-servicing first-use typecheck
```

`examples/routes_first_use.py` opens the mounted surface with the shipped typed
client. It observes accepted commit/hint, a readable delivery view without an
adapter, six exact signed request/response captures, administrator-only listing,
wrong-owner refusal and refusal to relay buyer payment commands. The injected
peer callback is the domain seam for its existing authority-verifying settlement
handler and hint read; this packet does not claim domain wiring.

`examples/budget_first_use.py` observes recommendations for a 300-second reserve
against a 350-second configured budget, then a 450-second runtime budget. Zero
payer notice also warns. Both measured servicing cycles run and return unchanged;
no codec, publication rule or buyer guarantee is changed.

The mounted surrender surface rejects both supplied past/future `at`, a different
buyer and an introduction-stage binding. A valid end records receipt without a
payment read/stop; a retry keeps its time and one physical operation while showing
`tearing_down`. The neutral offline verifier checks both kept signatures. The
buyer read returns exact opaque site bytes/proof headers and refuses another
principal. Delivery reads use kept state, not authority I/O. The existing ingress
example also exercises surrender before fulfillment. Physical I/O failure leaves
its journaled effect pending without discarding the durable acknowledgement.

## Respondent discovery and answers

`examples/respondent_first_use.py` uses the vendored in-process mediation peer
and separate payer/payee credentials. Discovery is bound to verified signed
filing records. Matching durable end/available facts produce canonical payee
concurrence; a different instant produces explicit contesting evidence. The
example loses an append response, closes the case, reopens the poller, and
recovers the original acknowledgement/key before advancing its cursor. Exactly
two appends remain, one concurrence and one contest, both under mandate.to.

`RespondentPoller` persists the page independently of deal watch so an answer
removed from discovery by an uncertain append cannot disappear on restart. The
composition supplies one poller per accepted authority/account with seller
credentials and an exact Agreement resolver. Run it before deal watch: both
adopt one case-keyed append journal, and watch never replaces a prepared answer.
Missing local Agreements remain pending for repair/triage, not silent agreement.

## Reusable receipt claims

`examples/receipt_first_use.py` drives the mounted route for both Ed25519 and
EIP-191 sellers using the producer's public vector signers. The receipt embeds
the owning adapter's SignedDeliveryEndClaim at durable receipt time. Claim and
proof are stored atomically with receipt/end recording, not regenerated on retry.
The adapter verifies the Agreement digest, exact seller and exact claim, maps the
unchanged claim into Filing.concurrence, and refuses a one-second backdate.
The neutral receipt verifier continues to verify request/response v2 signatures;
no competing claim frame or standalone acknowledgement claim is introduced.

The previous neutral test asserted the temporary null-only embedding gate. Its
expected behavior now follows the available owning contract: preserve the opaque
claim unchanged. Cryptographic rejection is exercised by the owning mediation
suite and the shipped mounted-receipt example; no test function was added.

## Canonical buyer ending

The installed-wheel buyer entry point is:

```sh
uv run --no-project --find-links .dist \
  --with .dist/arkhai_kit_deal_servicing-0.1.0-py3-none-any.whl \
  --with .dist/arkhai_kit_deal_lifecycle_client-0.1.0-py3-none-any.whl \
  --with .dist/arkhai_kit_deal_lifecycle_buyer-0.1.0-py3-none-any.whl \
  --with .dist/arkhai_kit_arkhai_mediation-0.1.0-py3-none-any.whl \
  python docs/attachments/lifecycle-routes/end_first_use.py
```

It mounts the real router/client, uses the owning mediation adapter and its
vector-derived HTTP peer, and injects payment outcomes (not a rate engine).
Observed first-use and reopened-journal recovery:

| Condition | Initial payment / delivery / case | Retry |
| --- | --- | --- |
| Payment outage | unknown / accepted / accepted | accepted / accepted / accepted |
| Both authorities down | unknown / accepted / unknown | accepted / accepted / accepted |
| No storefront acknowledgement | unknown / unknown / accepted, contested observed time | accepted / accepted / accepted; original contested filing unchanged |
| No adapters | rejected / accepted / rejected | unchanged; no refund or authority call |

Stops precede surrender and retain the same command/derived key on retry.
Receipt-backed filings carry exact verified concurrence; an unacknowledged
observed instant remains contested and is never rewritten as signed history.
The client rejects a supplied instant, verifies response/echo binding and keeps
both exact envelopes. The buyer verifies the Agreement principals and owning
claim, retains observation/receipt evidence with export producer/digest context,
and journals each command before I/O. `FileEvidenceStore.end_journal` shares its
store file so authorized evidence pruning removes retained end plans too.
The driver composes this journal and exact Agreement principals into the buyer
half; neither domain's stage table or CLI is wired here.

The fixture accepts filings but computes no mediation remedies. Mechanical
rulings, time/replay guards and signed ruling bases remain qualified by the
existing 40-case mediation suite, including all 14 published producer traces.
Rate stop/notice execution and hosted qualification are not claimed.

## Validation

The production-code head is `5041360c9`; subsequent packet/setup cleanup changes
no production behavior. The start was `0b6da919a`. Per-task commits preserve the
requested order and check their task boxes in the same commit.

| Validation | Observation |
| --- | --- |
| Lifecycle contracts | 37 existing cases pass |
| Lifecycle foundation | 62 existing cases pass |
| Mediation | 40 existing cases pass, generated-model/resource drift and both signature vectors pass; mypy checks 11 files |
| Buyer evidence/lifecycle | 18 existing cases pass; additional buyer/client typing checks 9 source files |
| Servicing | All nine first-use examples pass; mypy checks 10 source files |
| Client transport regression | Existing commit/hint/read example passes, including signature tampering and changed-request-ID rejection |
| Installed-wheel ending | All four outage/no-adapter scenarios pass after reopening the journal |
| Packaging | Fresh `.dist` wheels, architecture, `make check-packaging`, lock currency and comment hygiene pass |
| Active change | Pinned OpenSpec 1.14.0 strict validation passes |
| Full aggregate | `make test` passes in 7m54s with the shell-local Podman shim and prescribed proxy settings, including 1,858 release-tooling cases and Helm structural/render assertions |
| Documentation citations | Exactly the three known future lifecycle destinations in [#325](https://github.com/arkhai-io/simple-compute-market/issues/325); no new citation failure |

The aggregate retains the existing optional Torch-dependent VM test collection
skip. No permanent acceptance test was added. A separate small repair,
`e39dbe511`, narrows pre-existing evidence retention/export values for static typing
without changing their behavior. No dependency/version/configuration model was
changed beyond the servicing router's FastAPI runtime dependency and client
example dev dependency; its lock was regenerated through `make lock` and all
locks pass. No new distribution or Helm schema is introduced.

Domain mounting remains sections 14 and 15; permanent contract and rationale
promotion remains closeout. There is no new live-authority or domain end-to-end
qualification claim. No server, browser, container, tunnel, remote target or
outside resource is left running.
