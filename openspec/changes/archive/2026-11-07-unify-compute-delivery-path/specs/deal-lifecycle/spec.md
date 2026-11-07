## MODIFIED Requirements

### Requirement: Billing-start intent and evidence have one owner

End service MUST expose begin_billing(operation_key, activated_delivery_ref) and journal its key/evidence before I/O. Delivery MUST retain only an intent reference. The versioned secret-free `DeliveryEvidence` passed as that reference MUST bind the negotiation, commitment, reservation and fulfillment identities, a nested `ActivatedDeliveryRef` carrying the site activation record reference and instant, and the validated ready-evidence reference and digest. Activation MUST precede rate start; unknown effects MUST resolve by read/same-key retry before disclosure.

#### Scenario: A once-only delivery activates

- **WHEN** validated activation evidence reaches the once-only payment adapter through end service
- **THEN** billing start is a no-op and the delivery record retains only the end-service intent reference

#### Scenario: Billing start lacks activation evidence

- **WHEN** `begin_billing` receives `DeliveryEvidence` with no `ActivatedDeliveryRef`
- **THEN** end service refuses before any authority call and journals no billing intent
