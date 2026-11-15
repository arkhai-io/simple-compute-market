---
tags: [repository, testing]
---

# Testing with payment receipts

How a test obtains the signed payment receipts this capability's receipt fixture
supplies, as
[`contract-fixtures.md`](../../../docs/guidance/engineering/contract-fixtures.md)
asks of every signed protocol message.

## Payment Receipts in Tests

A seller delivers only after verifying a receipt that the payments service
signed for the exact mandate derived from the accepted Agreement. Proving that
gate below the system level needs a receipt for each test's own Agreement. The
published vectors cannot supply one: their receipt covers a fixed vector
mandate that no accepted Agreement derives.

Tests get receipts from the payments kit's fixture:

```python
receipt = build_signed_receipt(signer=SERVICE, mandate=accepted.mandate)
```

Tests and diagnostics never frame or sign a receipt themselves
([`contract-fixtures.md`, "Signed protocol messages come from the producer's fixture"](../../../docs/guidance/engineering/contract-fixtures.md#signed-protocol-messages-come-from-the-producers-fixture)).
Code like this is a second framing implementation that nothing checks against the
service:

```python
signature = service.sign(_frame(("arkhai.payments.receipt.v1", jcs_sha256(receipt))))
```

The fixture is trustworthy because it uses the same framing function as the
kit's verifier, and that framing is pinned by the producer's own vectors. The
kit vendors two vector publications. The current producer vectors' receipt passes the
strict models and verifies. The historical vectors are a separate raw-framing
regression whose receipt the current models refuse. The framing and the
signature cover a receipt's JSON whatever its parts say, so the kit's unit
suite reproduces each publication's message and signature from its raw
published body, byte for byte, and then signs and verifies a receipt for a
mandate the marketplace derives through the same framing:

```python
assert receipt_message(vector_body).hex() == vectors["receipt"]["message"]
assert signer.sign(receipt_message(vector_body)) == vector_signature
assert sign_receipt(SERVICE, derived_body) == build_signed_receipt(signer=SERVICE, mandate=mandate)
```

The fixture exists to supply receipts for mandates the marketplace derives.
`kit/arkhai-payments/schema/SOURCE.md` records the schema's and both vector
publications' content hashes and how to select newer ones.

The fixture takes its signer as an argument and ships no key material.
Integration tests replace `PaymentsClient`, the code that wraps the payments
HTTP boundary, with a fake that serves fixture receipts. Each test varies one
property:

```python
payments.serve(build_signed_receipt(signer=SERVICE, mandate=accepted.mandate))   # delivers
payments.serve(build_signed_receipt(signer=IMPOSTOR, mandate=accepted.mandate))  # 409, no delivery
payments.serve(None)                                                              # 202 pending
```

A receipt's signed mode is one of those properties. `build_signed_receipt` signs in
the `livemode` it is given, default `False`, the mode of a test or development
service. `FakePaymentsClient`'s own `livemode` applies only to the receipts it signs
on approval; a receipt handed to `serve()` keeps the mode it was signed with. A stage
configured for one mode is tested with a receipt signed in the other:

```python
payments.serve(build_signed_receipt(signer=SERVICE, mandate=accepted.mandate, livemode=True))  # refused unless the role sets livemode
```

A snapshot consumed as authority state needs its own verified proof, mode,
deal/mandate/receipt binding and nonregressing event sequence. The payments kit
owns snapshot vectors, `sign_snapshot` and the shared clock-injected
`PaymentsAuthority` fixture engine. `FakePaymentsClient` uses that engine rather
than reimplementing billing; a receipt-only fixture proves only the receipt gate,
not part-state observation. The mediation kit independently owns claim framing,
both signature-scheme vectors and ruling traces. Neither fixture qualifies a
deployed authority or monetary ruling execution. See
[lifecycle contract evidence](architecture.md#lifecycle-contract-evidence).
