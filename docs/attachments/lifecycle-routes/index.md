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

## Validation

The servicing first-use examples and source typing pass; the existing lifecycle
suite passes (62 cases). Fresh wheel builds, `make check-packaging`,
`make check-locks`, architecture, comment hygiene and pinned strict OpenSpec
validation pass. No permanent acceptance test was added. Domain mounting remains
sections 14 and 15; permanent contract and rationale promotion remains closeout.
