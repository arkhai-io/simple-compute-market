# VM provisioning adapter

The VM adapter contributes the exact fulfillment route `("ansible", "compute.gpu")` to the compute provisioner. It validates and executes only the scheduler-selected resource; it never places or substitutes a host.

`prepare_create` and `prepare_teardown` freeze the VM host, target, sizing, playbook, provider variables, and deterministic command contract in versioned envelopes. Recovery dispatches only those envelopes. Pool edits therefore affect future work, not accepted work.

Active result reads run a private reset-password job, consume and delete its transient credential rows, and return credentials only to the authenticated owner. Generic fulfillment state stores only `credential_generation`.

The adapter also owns the pure historical VM backfill compiler. Generic migrations provide validated executor coordinates and provider configuration; the compiler produces strict backfilled metadata and immutable teardown input without making generic service code import VM models. Native metadata remains stricter and requires its create-job identity.

VM lease release has no executor fallback. Settlement-backed expiry and termination route through durable fulfillment teardown and release capacity only after provider success.
