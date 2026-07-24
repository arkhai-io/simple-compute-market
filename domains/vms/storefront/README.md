# VM storefront

The VM storefront is a market-facing client of configured site authorities and the compute fulfillment API. It does not select physical hosts or submit executor actions.

Negotiation acceptance persists a capacity hold with the trusted configured `site_id`. Settlement creates a durable storefront workflow containing the reservation, canonical schedule/begin requests, and buyer SSH key before remote lifecycle work. The reconciler then:

1. schedules at the persisted site;
2. persists the selected resource and commits the reservation there;
3. begins fulfillment and persists `fulfillment_id`;
4. polls durable status and result;
5. atomically stores buyer-facing access with the observed credential generation;
6. submits the chain fulfillment and claim.

The worker resumes these phases after restart. Once a reservation exists it never broadcasts, forwards, or falls back to another site. Persisted routing contains `site_id`, never authority URLs or API credentials. Provisioning `fulfillment_id` remains distinct from chain `fulfillment_uid`.

The workflow table contains no credential payload. Buyer-facing access remains in the storefront escrow credential fields and status reads require the wallet recorded by the negotiation; another valid signer receives not found.

Configuration may use one shared legacy admin key or per-site structured URL/key entries. Keys are operator secrets and must not appear in listings, projections, workflow state, logs, or errors.
