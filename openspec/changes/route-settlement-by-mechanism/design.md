## Context

`settle-through-arkhai-payments` added `arkhai.payments.v1` as a peer of Alkahest by bypassing the escrow-shaped servicing path. The bypass works, but domains reach it through scattered ID comparisons and the core "escrow or not" branch, and bare metal reused its escrow table for payment evidence. This change makes dispatch declared once per domain. The rest of the escrow-to-Alkahest refactor follows in `move-escrow-into-alkahest` and `drop-escrow-from-shared-wire`.

The aim is an architecture whose port to another language would be mechanical: module boundaries are typed data contracts, dispatch is a declared table, and nothing depends on runtime dynamism.

## Decisions

### A table of domain-owned stages, not a shared settle port

A shared `accept / buyer_settle / seller_verify` interface was considered and rejected. Mechanisms differ in what they need from a domain. Arkhai needs payer and payee accounts and an amount; Alkahest needs chains, demands and arbiters; contact exchange needs introduction payloads. A shared signature would either be too weak to use or would make every kit carry every other kit's concepts. This is the same reason the pipeline decision rejected a neutral signal vocabulary.

Instead, each domain writes one stage per mechanism it supports, against that kit's own API, and registers it in a table:

```text
BuyerSettleStages  = {mechanism_id: (agreement, settlement_data) -> SettlementEvidence | Pending}
SellerSettleStages = {mechanism_id: (agreement, settlement_data, request) -> SettlementEvidence | Pending}
SettlementEvidence = {negotiation_id, mechanism, settlement_ref, status, evidence}
```

Compatibility stays explicit per domain and per mechanism. The difference is that it is declared in one place.

### Evidence is the boundary after settlement

Everything after settlement reads `SettlementEvidence`. Where provisioning needs mechanism-specific facts (for example, the receipt's hold expiry), the stage translates them into the domain's evidence fields at the point it produces the evidence. The mechanism ID stays on the record for audit and display only.

## Open Questions

- Whether the API-credits service should receive evidence or only an issuance authorization from the storefront. It currently compares mechanisms in `keys_service.py`.
