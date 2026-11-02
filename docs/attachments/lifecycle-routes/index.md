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

## Validation

The servicing first-use examples and source typing pass; the existing lifecycle
suite passes (62 cases). Fresh wheel builds, `make check-packaging`,
`make check-locks`, architecture, comment hygiene and pinned strict OpenSpec
validation pass. No permanent acceptance test was added. Domain mounting remains
sections 14 and 15; permanent contract and rationale promotion remains closeout.
