CREATE TABLE api_keys (
	key_id VARCHAR NOT NULL, 
	secret_hash VARCHAR NOT NULL, 
	owner_scheme VARCHAR, 
	owner_id VARCHAR, 
	status VARCHAR NOT NULL, 
	balance INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (key_id)
);

CREATE TABLE credit_grants (
	id INTEGER NOT NULL, 
	key_id VARCHAR NOT NULL, 
	fulfillment_id VARCHAR, 
	negotiation_id VARCHAR, 
	service VARCHAR, 
	resource_id VARCHAR, 
	key_mode VARCHAR, 
	key_target_id VARCHAR, 
	owner_scheme VARCHAR, 
	owner_id VARCHAR, 
	request_digest VARCHAR, 
	capacity_reservation_id VARCHAR, 
	result_balance INTEGER, 
	quantity INTEGER NOT NULL, 
	reason VARCHAR NOT NULL, 
	granted_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(key_id) REFERENCES api_keys (key_id), 
	UNIQUE (fulfillment_id), 
	UNIQUE (negotiation_id)
);

CREATE INDEX ix_credit_grants_key_id ON credit_grants (key_id);

CREATE TABLE consumption_events (
	id INTEGER NOT NULL, 
	key_id VARCHAR NOT NULL, 
	amount INTEGER NOT NULL, 
	idempotency_key VARCHAR, 
	occurred_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_consumption_idem UNIQUE (key_id, idempotency_key), 
	FOREIGN KEY(key_id) REFERENCES api_keys (key_id)
);

CREATE INDEX ix_consumption_events_key_id ON consumption_events (key_id);

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

CREATE TABLE site_lease_ended_events (
	event_id VARCHAR NOT NULL, 
	capacity_reservation_id VARCHAR NOT NULL, 
	transition_key VARCHAR NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (event_id), 
	UNIQUE (capacity_reservation_id, transition_key)
);

CREATE INDEX ix_site_lease_ended_events_capacity_reservation_id ON site_lease_ended_events (capacity_reservation_id);

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

CREATE INDEX ix_capacity_buckets_backing_resource_id ON capacity_buckets (backing_resource_id);

CREATE INDEX ix_capacity_buckets_pool_id ON capacity_buckets (pool_id);

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

CREATE INDEX ix_capacity_reservations_settlement_resource_id ON capacity_reservations (settlement_resource_id);

CREATE INDEX ix_capacity_reservations_state ON capacity_reservations (state);

CREATE INDEX ix_capacity_reservations_escrow_uid ON capacity_reservations (escrow_uid);

CREATE TABLE capacity_events (
	version INTEGER NOT NULL, 
	kind VARCHAR NOT NULL, 
	resource_id VARCHAR, 
	dimensions JSON, 
	claim_attributes JSON, 
	occurred_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (version)
);

CREATE INDEX ix_capacity_events_resource_id ON capacity_events (resource_id);

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

CREATE INDEX ix_capacity_reservation_debits_capacity_bucket_id ON capacity_reservation_debits (capacity_bucket_id);

CREATE TABLE schema_migrations (
                id VARCHAR PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

