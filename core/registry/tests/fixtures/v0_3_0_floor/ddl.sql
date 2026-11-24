CREATE TABLE publishers (
	publisher_id INTEGER NOT NULL, 
	storefront_url TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (publisher_id)
);

CREATE TABLE publisher_replay_reservations (
	id INTEGER NOT NULL, 
	principal_scheme VARCHAR NOT NULL, 
	principal_identifier VARCHAR NOT NULL, 
	request_id VARCHAR NOT NULL, 
	request_hash VARCHAR NOT NULL, 
	response_status INTEGER, 
	response_body JSON, 
	lease_owner VARCHAR, 
	lease_expires_at DATETIME, 
	created_at DATETIME NOT NULL, 
	completed_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_publisher_replay_principal_request UNIQUE (principal_scheme, principal_identifier, request_id)
);

CREATE INDEX idx_publisher_replay_lease_expires_at ON publisher_replay_reservations (lease_expires_at);

CREATE INDEX idx_publisher_replay_created_at ON publisher_replay_reservations (created_at);

CREATE TABLE api_keys (
	id INTEGER NOT NULL, 
	name VARCHAR NOT NULL, 
	key_hash VARCHAR NOT NULL, 
	scope VARCHAR DEFAULT 'read' NOT NULL, 
	created_at DATETIME NOT NULL, 
	revoked_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (key_hash)
);

CREATE INDEX idx_api_keys_revoked_at ON api_keys (revoked_at);

CREATE TABLE identities (
	id INTEGER NOT NULL, 
	publisher_id INTEGER NOT NULL, 
	scheme VARCHAR NOT NULL, 
	identifier VARCHAR NOT NULL, 
	status VARCHAR DEFAULT 'primary' NOT NULL, 
	active_until DATETIME, 
	retired_at DATETIME, 
	disabled_at DATETIME, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(publisher_id) REFERENCES publishers (publisher_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX ux_identities_scheme_identifier ON identities (scheme, identifier);

CREATE UNIQUE INDEX ux_identities_one_primary_per_publisher ON identities (publisher_id) WHERE status = 'primary';

CREATE INDEX idx_identities_publisher_id ON identities (publisher_id);

CREATE TABLE publisher_identity_rotations (
	id INTEGER NOT NULL, 
	publisher_id INTEGER NOT NULL, 
	nonce VARCHAR NOT NULL, 
	intent_hash VARCHAR NOT NULL, 
	current_scheme VARCHAR NOT NULL, 
	current_identifier VARCHAR NOT NULL, 
	replacement_scheme VARCHAR NOT NULL, 
	replacement_identifier VARCHAR NOT NULL, 
	overlap_seconds INTEGER NOT NULL, 
	expires_at INTEGER NOT NULL, 
	status VARCHAR NOT NULL, 
	applied_at DATETIME NOT NULL, 
	retire_at DATETIME, 
	retired_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_publisher_rotation_nonce UNIQUE (publisher_id, nonce), 
	FOREIGN KEY(publisher_id) REFERENCES publishers (publisher_id) ON DELETE CASCADE
);

CREATE INDEX idx_publisher_rotations_publisher_id ON publisher_identity_rotations (publisher_id);

CREATE TABLE listings (
	listing_id VARCHAR NOT NULL, 
	publisher_id INTEGER NOT NULL, 
	listing_resource JSON NOT NULL, 
	accepted_escrows JSON, 
	settlement_options JSON, 
	demands JSON, 
	max_duration_seconds INTEGER, 
	oracle_address TEXT, 
	status VARCHAR(7) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (listing_id), 
	FOREIGN KEY(publisher_id) REFERENCES publishers (publisher_id) ON DELETE CASCADE
);

CREATE INDEX idx_listings_created_at ON listings (created_at);

CREATE INDEX idx_listings_publisher_id ON listings (publisher_id);

CREATE INDEX idx_listings_status ON listings (status);

CREATE TABLE alembic_version (
	version_num VARCHAR(32) NOT NULL, 
	CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
