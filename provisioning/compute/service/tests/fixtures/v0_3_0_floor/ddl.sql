CREATE TABLE "ansible_jobs" (id VARCHAR PRIMARY KEY, status VARCHAR NOT NULL, params JSON NOT NULL, host_id VARCHAR, result JSON, logs TEXT, error TEXT, execution_handle JSON, retry_count INTEGER NOT NULL, max_retries INTEGER NOT NULL, next_retry_at DATETIME, capacity_reservation_id VARCHAR, offering_mode VARCHAR, action_kind VARCHAR, executor_action VARCHAR, idempotency_key VARCHAR, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE "ansible_pool_configs" (
	pool_id VARCHAR NOT NULL, 
	playbook_path VARCHAR, 
	requirement_delegate VARCHAR DEFAULT 'vm_management_v1' NOT NULL, 
	extra_vars JSON NOT NULL, 
	default_vm_ram INTEGER, 
	default_vm_vcpus INTEGER, 
	default_vm_disk_size VARCHAR, 
	PRIMARY KEY (pool_id), 
	FOREIGN KEY(pool_id) REFERENCES resource_pools (id)
);

CREATE TABLE capacity_buckets (
	capacity_bucket_id VARCHAR NOT NULL, 
	backing_resource_id VARCHAR NOT NULL, 
	pool_id VARCHAR, 
	host_id VARCHAR, 
	resource_type VARCHAR NOT NULL, 
	resource_subtype VARCHAR, 
	total_units INTEGER, 
	capacity JSON NOT NULL, 
	attributes JSON NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (capacity_bucket_id), 
	CONSTRAINT uq_capacity_buckets_backing_resource UNIQUE (backing_resource_id), 
	UNIQUE (host_id)
);

CREATE TABLE capacity_events (
	version INTEGER NOT NULL, 
	kind VARCHAR NOT NULL, 
	resource_id VARCHAR, 
	dimensions JSON, 
	claim_attributes JSON, 
	occurred_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (version)
);

CREATE TABLE capacity_release_callback_outbox (
	capacity_reservation_id VARCHAR NOT NULL, 
	attempt_count INTEGER DEFAULT '0' NOT NULL, 
	last_error TEXT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	last_attempted_at DATETIME, 
	delivered_at DATETIME, 
	PRIMARY KEY (capacity_reservation_id)
);

CREATE TABLE capacity_reservation_debits (
	capacity_reservation_id VARCHAR NOT NULL, 
	capacity_bucket_id VARCHAR NOT NULL, 
	dimensions JSON NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (capacity_reservation_id), 
	CONSTRAINT uq_capacity_reservation_debits_reservation UNIQUE (capacity_reservation_id), 
	FOREIGN KEY(capacity_reservation_id) REFERENCES capacity_reservations (capacity_reservation_id) ON DELETE CASCADE, 
	FOREIGN KEY(capacity_bucket_id) REFERENCES capacity_buckets (capacity_bucket_id) ON DELETE RESTRICT
);

CREATE TABLE capacity_reservations (
	capacity_reservation_id VARCHAR NOT NULL, 
	settlement_resource_id VARCHAR, 
	units INTEGER NOT NULL, 
	dimensions JSON, 
	claim_attributes JSON, 
	state VARCHAR NOT NULL, 
	deal_ref JSON, 
	escrow_uid VARCHAR, 
	hold_expires_at VARCHAR, 
	offering_mode VARCHAR, 
	executor_target VARCHAR, 
	release_job_id VARCHAR, 
	executor_ref JSON, 
	lease_start_utc VARCHAR, 
	lease_end_utc VARCHAR, 
	create_job_id VARCHAR, 
	failure_reason VARCHAR, 
	failure_message TEXT, 
	released_at VARCHAR, 
	release_requested_at VARCHAR, 
	activated_at_utc VARCHAR, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (capacity_reservation_id)
);

CREATE TABLE credentials (
	id VARCHAR NOT NULL, 
	job_id VARCHAR NOT NULL, 
	envelope JSON NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(job_id) REFERENCES ansible_jobs (id)
);

CREATE TABLE definition_document_imports (
	document_kind VARCHAR NOT NULL, 
	digest VARCHAR NOT NULL, 
	imported_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (document_kind)
);

CREATE TABLE "hosts" (host_id VARCHAR PRIMARY KEY, connection_kind VARCHAR NOT NULL, connection_version INTEGER NOT NULL DEFAULT '1', connection_public JSON NOT NULL, connection_protected JSON NOT NULL, enabled BOOLEAN NOT NULL, pool_id VARCHAR, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (pool_id) REFERENCES resource_pools (id));

CREATE TABLE lease_end_report_outbox (
	event_id VARCHAR NOT NULL, 
	capacity_reservation_id VARCHAR NOT NULL, 
	peer VARCHAR NOT NULL, 
	report TEXT NOT NULL, 
	parked BOOLEAN DEFAULT '0' NOT NULL, 
	attempt_count INTEGER DEFAULT '0' NOT NULL, 
	last_error TEXT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	last_attempted_at DATETIME, 
	delivered_at DATETIME, 
	PRIMARY KEY (event_id)
);

CREATE TABLE pool_relays (
	pool_id VARCHAR NOT NULL, 
	relay_id VARCHAR NOT NULL, 
	PRIMARY KEY (pool_id), 
	FOREIGN KEY(pool_id) REFERENCES resource_pools (id), 
	FOREIGN KEY(relay_id) REFERENCES relays (id)
);

CREATE TABLE provisioned_resources (
	provisioned_resource_id VARCHAR NOT NULL, 
	capacity_reservation_id VARCHAR NOT NULL, 
	fulfillment_id VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (provisioned_resource_id), 
	FOREIGN KEY(capacity_reservation_id) REFERENCES settlement_records (capacity_reservation_id) ON DELETE CASCADE
);

CREATE TABLE provisioning_identity_rotation_audit (
	nonce VARCHAR NOT NULL, 
	role VARCHAR NOT NULL, 
	current_scheme VARCHAR NOT NULL, 
	current_identifier VARCHAR NOT NULL, 
	replacement_scheme VARCHAR NOT NULL, 
	replacement_identifier VARCHAR NOT NULL, 
	overlap_seconds INTEGER NOT NULL, 
	intent_expires_at INTEGER NOT NULL, 
	applied_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (nonce)
);

CREATE TABLE provisioning_replay_reservations (
	principal_scheme VARCHAR NOT NULL, 
	principal_identifier VARCHAR NOT NULL, 
	request_id VARCHAR NOT NULL, 
	request_hash VARCHAR NOT NULL, 
	dispatch_lease_expires_at DATETIME NOT NULL, 
	dispatch_attempt_count INTEGER DEFAULT '1' NOT NULL, 
	response_status INTEGER, 
	response_body JSON, 
	response_body_empty BOOLEAN DEFAULT '0' NOT NULL, 
	response_media_type VARCHAR, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	completed_at DATETIME, 
	PRIMARY KEY (principal_scheme, principal_identifier, request_id)
);

CREATE TABLE provisioning_trusted_principals (
	role VARCHAR NOT NULL, 
	principal_scheme VARCHAR NOT NULL, 
	principal_identifier VARCHAR NOT NULL, 
	generation INTEGER NOT NULL, 
	valid_until DATETIME, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (role, principal_scheme, principal_identifier)
);

CREATE TABLE relay_port_leases (
	id VARCHAR NOT NULL, 
	relay_id VARCHAR NOT NULL, 
	remote_port INTEGER NOT NULL, 
	host_id VARCHAR, 
	pool_id VARCHAR, 
	owner_kind VARCHAR NOT NULL, 
	owner_id VARCHAR NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	released_at DATETIME, 
	grant_expires_at DATETIME, 
	grant_key_id VARCHAR, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_relay_port_leases_endpoint UNIQUE (relay_id, remote_port), 
	FOREIGN KEY(relay_id) REFERENCES relays (id)
);

CREATE TABLE relay_retired_grant_keys (
	relay_id VARCHAR NOT NULL, 
	key_id VARCHAR NOT NULL, 
	retired_at DATETIME NOT NULL, 
	PRIMARY KEY (relay_id, key_id), 
	FOREIGN KEY(relay_id) REFERENCES relays (id)
);

CREATE TABLE relays (
	id VARCHAR NOT NULL, 
	label VARCHAR, 
	relay_addr VARCHAR NOT NULL, 
	relay_port INTEGER NOT NULL, 
	vm_port_range_start INTEGER NOT NULL, 
	vm_port_range_count INTEGER NOT NULL, 
	relay_token_encrypted VARCHAR, 
	grant_key_encrypted VARCHAR, 
	grant_key_id VARCHAR, 
	grant_key_public VARCHAR, 
	grant_key_activated_at DATETIME, 
	staged_grant_key_encrypted VARCHAR, 
	staged_grant_key_id VARCHAR, 
	staged_grant_key_public VARCHAR, 
	enabled BOOLEAN DEFAULT 1 NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_relays_endpoint UNIQUE (relay_addr, relay_port)
);

CREATE TABLE resource_pools (
	id VARCHAR NOT NULL, 
	label VARCHAR NOT NULL, 
	provider VARCHAR NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	policy_tags JSON NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE scheduling_cursors (
	resource_kind VARCHAR NOT NULL, 
	last_pool_id VARCHAR, 
	last_resource_by_pool JSON NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (resource_kind)
);

CREATE TABLE schema_migrations (
                id VARCHAR PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

CREATE TABLE settlement_records (
	capacity_reservation_id VARCHAR NOT NULL, 
	fulfillment_id VARCHAR, 
	market VARCHAR NOT NULL, 
	scheduling_requirements JSON NOT NULL, 
	resource_id_constraint VARCHAR, 
	settlement_resource_id VARCHAR, 
	pool_id VARCHAR, 
	provider VARCHAR, 
	resource_attributes JSON, 
	resource_host_id VARCHAR, 
	fulfillment_request JSON, 
	prepared_create_operation JSON, 
	prepared_teardown_operation JSON, 
	provider_metadata JSON NOT NULL, 
	teardown_provider_metadata JSON, 
	state VARCHAR NOT NULL, 
	failure_reason VARCHAR, 
	failure_message TEXT, 
	claimed_by VARCHAR, 
	claim_expires_at DATETIME, 
	attempt_count INTEGER NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (capacity_reservation_id)
);

CREATE TABLE site_lease_ended_events (
	event_id VARCHAR NOT NULL, 
	capacity_reservation_id VARCHAR NOT NULL, 
	transition_key VARCHAR NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (event_id), 
	UNIQUE (capacity_reservation_id, transition_key)
);

CREATE INDEX ix_ansible_jobs_allocation_id ON ansible_jobs (capacity_reservation_id);

CREATE INDEX ix_ansible_jobs_capacity_reservation_id ON ansible_jobs (capacity_reservation_id);

CREATE INDEX ix_ansible_jobs_host_id ON ansible_jobs (host_id);

CREATE UNIQUE INDEX uq_ansible_jobs_contract_idempotency ON ansible_jobs (capacity_reservation_id, action_kind, idempotency_key);

CREATE INDEX ix_capacity_buckets_backing_resource_id ON capacity_buckets (backing_resource_id);

CREATE INDEX ix_capacity_buckets_pool_id ON capacity_buckets (pool_id);

CREATE UNIQUE INDEX uq_capacity_buckets_host_id ON capacity_buckets (host_id);

CREATE INDEX ix_capacity_events_resource_id ON capacity_events (resource_id);

CREATE INDEX ix_capacity_reservation_debits_capacity_bucket_id ON capacity_reservation_debits (capacity_bucket_id);

CREATE INDEX ix_capacity_reservations_escrow_uid ON capacity_reservations (escrow_uid);

CREATE INDEX ix_capacity_reservations_settlement_resource_id ON capacity_reservations (settlement_resource_id);

CREATE INDEX ix_capacity_reservations_state ON capacity_reservations (state);

CREATE INDEX ix_credentials_job_id ON credentials (job_id);

CREATE INDEX ix_lease_end_report_outbox_capacity_reservation_id ON lease_end_report_outbox (capacity_reservation_id);

CREATE INDEX ix_pool_relays_relay_id ON pool_relays (relay_id);

CREATE INDEX ix_provisioned_resources_capacity_reservation_id ON provisioned_resources (capacity_reservation_id);

CREATE INDEX ix_provisioned_resources_fulfillment_id ON provisioned_resources (fulfillment_id);

CREATE INDEX ix_relay_port_leases_owner_id ON relay_port_leases (owner_id);

CREATE INDEX ix_relay_port_leases_relay_id ON relay_port_leases (relay_id);

CREATE UNIQUE INDEX uq_relay_port_leases_active_owner ON relay_port_leases (owner_kind, owner_id) WHERE released_at IS NULL;

CREATE UNIQUE INDEX ix_settlement_records_fulfillment_id ON settlement_records (fulfillment_id);

CREATE INDEX ix_settlement_records_settlement_resource_id ON settlement_records (settlement_resource_id);

CREATE INDEX ix_site_lease_ended_events_capacity_reservation_id ON site_lease_ended_events (capacity_reservation_id);
