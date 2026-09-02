import enum
import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from sqlalchemy.sql.expression import true as sa_true


Base = declarative_base()


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class CredentialRole(str, enum.Enum):
    root = "root"
    tenant = "tenant"

class ProvisioningReplayReservation(Base):
    """Durable principal-scoped request reservation and recorded outcome."""

    __tablename__ = "provisioning_replay_reservations"

    principal_scheme = Column(String, primary_key=True)
    principal_identifier = Column(String, primary_key=True)
    request_id = Column(String, primary_key=True)
    request_hash = Column(String, nullable=False)
    dispatch_lease_expires_at = Column(DateTime(timezone=True), nullable=False)
    dispatch_attempt_count = Column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    response_status = Column(Integer, nullable=True)
    response_body = Column(JSON, nullable=True)
    response_body_empty = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    response_media_type = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

class CapacityReleaseCallbackOutbox(Base):
    """Durable acknowledgement state for one released reservation callback."""

    __tablename__ = "capacity_release_callback_outbox"

    capacity_reservation_id = Column(String, primary_key=True)
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    last_error = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_attempted_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)



class ProvisioningTrustedPrincipal(Base):
    """Versioned role binding retained through bounded rotation overlap."""

    __tablename__ = "provisioning_trusted_principals"

    role = Column(String, primary_key=True)
    principal_scheme = Column(String, primary_key=True)
    principal_identifier = Column(String, primary_key=True)
    generation = Column(Integer, nullable=False)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ProvisioningIdentityRotationAudit(Base):
    """Immutable accepted rotation intent for audit and nonce replay rejection."""

    __tablename__ = "provisioning_identity_rotation_audit"

    nonce = Column(String, primary_key=True)
    role = Column(String, nullable=False)
    current_scheme = Column(String, nullable=False)
    current_identifier = Column(String, nullable=False)
    replacement_scheme = Column(String, nullable=False)
    replacement_identifier = Column(String, nullable=False)
    overlap_seconds = Column(Integer, nullable=False)
    intent_expires_at = Column(Integer, nullable=False)
    applied_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )



class AnsibleJob(Base):
    __tablename__ = "ansible_jobs"
    __table_args__ = (
        UniqueConstraint(
            "capacity_reservation_id",
            "action_kind",
            "idempotency_key",
            name="uq_ansible_jobs_contract_idempotency",
        ),
    )

    id = Column(String, primary_key=True)
    status = Column(String, nullable=False)
    params = Column(JSON, nullable=False)
    result = Column(JSON, nullable=True)
    logs = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    process_id = Column(String, nullable=True)  # PID of running ansible process for cancellation
    retry_count = Column(Integer, default=0, nullable=False)  # Number of retry attempts made
    max_retries = Column(Integer, default=3, nullable=False)  # Maximum retry attempts allowed
    next_retry_at = Column(DateTime(timezone=True), nullable=True)  # Scheduled time for next retry
    escrow_uid = Column(String, nullable=True, index=True)  # On-chain escrow UID linking this job to a deal
    contract_version = Column(String, nullable=True)
    capacity_reservation_id = Column(String, nullable=True, index=True)
    deal_ref = Column(JSON, nullable=True)
    executor_kind = Column(String, nullable=True)
    action_kind = Column(String, nullable=True)
    idempotency_key = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    credentials = relationship("Credential", back_populates="job", cascade="all, delete-orphan")


class Credential(Base):
    __tablename__ = "credentials"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("ansible_jobs.id"), nullable=False, index=True)
    role = Column(String, nullable=False)  # "root" or "tenant"
    password = Column(String, nullable=True)
    ssh_commands = Column(JSON, nullable=True)
    ssh_key_path_host = Column(String, nullable=True)
    key_type = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job = relationship("AnsibleJob", back_populates="credentials")


# Provider-neutral resource-pool identity now lives in the shared
# market_resource_pools package (kit); re-exported here because the
# service's modules and tests reach all persistence models through
# db.models. The table rides market_resource_pools' own metadata —
# init_db creates it alongside this service's own Base and market_site's.
from market_resource_pools import DEFAULT_POOL_ID, ResourcePool  # noqa: F401


class Relay(Base):
    """A VM-facing tunnel rendezvous, and the remote-port window it accepts.

    **This is not the host management tunnel.** A host holds two reverse
    tunnels and they are easy to confuse, so: the management tunnel is the
    operator's failsafe path to the host itself, static for a whole
    provisioning service, established when the host is prepared outside this
    repository, and absent from this table. What a row here describes is the
    rendezvous a host's VM tunnel client dials on behalf of the VMs rented on
    it. The two may be the same server; they are never the same concern, and
    nothing in this service writes or restarts the management side.

    One row per rendezvous. ``UNIQUE(relay_addr, relay_port)`` is what makes
    identity trustworthy: a remote port binds a listening socket on the relay
    itself, so one rendezvous recorded twice would issue the same port to two
    callers and the refusal would surface asynchronously in a tunnel client's
    log rather than as a failed allocation.

    The admission token is stored encrypted under the deployment's
    ``ssh_decryption_key``, the same key that protects embedded host key
    material. The database therefore holds no usable credential: recovering a
    token requires both this row and a key held outside the database. No read
    path that serves an API response, an export, or a reconciliation
    comparison may return it — see the pool configuration handlers, which
    expose a redacted read under the unqualified name and secrets only through
    an explicitly named execution read.
    """

    __tablename__ = "relays"
    __table_args__ = (
        UniqueConstraint("relay_addr", "relay_port", name="uq_relays_endpoint"),
    )

    id = Column(String, primary_key=True)
    label = Column(String, nullable=True)
    relay_addr = Column(String, nullable=False)
    relay_port = Column(Integer, nullable=False)
    vm_port_range_start = Column(Integer, nullable=False)
    vm_port_range_count = Column(Integer, nullable=False)
    # Ciphertext, or NULL when no token has been supplied yet. A relay with no
    # token is rejected before dispatch rather than dialled and refused.
    relay_token_encrypted = Column(String, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default=sa_true())
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=True, onupdate=func.now())

    @staticmethod
    def normalize_addr(addr: str) -> str:
        """Canonical spelling of a rendezvous address.

        Applied on write so two spellings of one endpoint collide on the
        unique constraint instead of creating two rows that would each issue
        ports the other already holds.
        """
        return addr.strip().lower()


class AnsiblePoolConfig(Base):
    """Ansible-provider-specific config for a resource pool.

    Provider-specific data lives in its own side table rather than as
    generic columns on ``resource_pools`` — see ARCHITECTURE.md § Physical
    Settlement Scheduler and FulfillmentProvider Architecture, "Settlement
    record metadata envelope" for the same principle applied to settlement
    records. Only the "ansible" provider is implemented; other providers
    (kubernetes, gcp, ...) would get their own side table, not new columns
    here.

    No ORM ``relationship()`` back to ``ResourcePool``: that model now lives
    in a different declarative registry (``market_resource_pools``), so
    navigation is by explicit ``pool_id`` lookup — which is how
    ``PoolConfigHandler`` implementations already read/write this table.
    """

    __tablename__ = "ansible_pool_configs"

    pool_id = Column(String, ForeignKey(ResourcePool.__table__.c.id), primary_key=True)
    playbook_path = Column(String, nullable=False)
    requirement_delegate = Column(
        String, nullable=False, default="vm_management_v1", server_default="vm_management_v1"
    )
    inventory_group = Column(String, nullable=False)
    extra_vars = Column(JSON, nullable=False, default=dict)
    # Fulfillment-time fallback shape, read only by AnsibleFulfillmentProvider's
    # three-tier precedence (derived > requirements > pool default) when
    # neither the negotiated requirements nor a requirement delegate
    # supplies a dimension. Nullable: a pool with no configured default
    # simply contributes nothing at that tier.
    default_vm_ram = Column(Integer, nullable=True)
    default_vm_vcpus = Column(Integer, nullable=True)
    default_vm_disk_size = Column(String, nullable=True)

    # Which relay this pool's hosts dial for buyer VM tunnels. A reference,
    # not the endpoint itself: the rendezvous address, its port window, and
    # its token are shared by every pool pointing at the same relay, so they
    # belong to the relay row. Holding the window here would let two pools
    # allocate from one listening namespace under disagreeing bounds.
    #
    # Nullable: a pool with no relay configured serves VMs by direct NAT.
    relay_id = Column(String, ForeignKey("relays.id"), nullable=True, index=True)


class RelayPortLease(Base):
    """A remote port held on a relay for one VM.

    Uniqueness is ``(relay_id, remote_port)`` because that is the resource: a
    ``tcp`` proxy's remote port binds a listening socket on the relay itself.
    Hosts sharing a relay share one port namespace, and so do pools; keying on
    either would issue a port already bound, and the relay's refusal surfaces
    asynchronously in a tunnel client's log rather than as a failed allocation.

    The relay recorded here is the VM's relay for the whole of its life.
    Teardown and reclamation read it rather than the pool's current
    configuration, which may since have been rebound: the lease is what knows
    where the port actually went, and releasing against anything else frees a
    port that was never bound and leaves bound the one that was.

    A lease is recorded before the job that will use it is dispatched, so a
    crash between the two cannot leave a port bound on the relay that no record
    claims. It is released on every terminal outcome rather than on teardown
    alone, because a dispatch that never starts, a permanently failed creation,
    a cancellation, and an expiry all end a VM's life without a teardown
    running. Reconciliation bounds whatever path is missed.
    """

    __tablename__ = "relay_port_leases"
    __table_args__ = (
        UniqueConstraint("relay_id", "remote_port", name="uq_relay_port_leases_endpoint"),
    )

    id = Column(String, primary_key=True)
    # References the relay row rather than a string assembled from its address,
    # so a relay moving to a new address updates one field and its leases
    # follow it instead of becoming records under an identity nothing points at.
    relay_id = Column(String, ForeignKey("relays.id"), nullable=False, index=True)
    remote_port = Column(Integer, nullable=False)
    # Recorded for operator visibility and reconciliation, not for uniqueness.
    host_name = Column(String, nullable=True)
    pool_id = Column(String, nullable=True)
    # The job or fulfillment whose terminal state releases this lease.
    owner_kind = Column(String, nullable=False)
    owner_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    released_at = Column(DateTime, nullable=True)


class DefinitionDocumentImport(Base):
    """Digest of the definition document last reconciled, per document kind.

    Import treats a document as authoritative: it overwrites entries that
    differ and disables entries the document omits. That authority belongs to
    the act of submitting a document. A process start is not a submission, and
    re-applying a document nobody submitted reverts whatever else changed the
    database — silently, on eviction, drain, and crash recovery.

    So a startup reconciles only when the mounted document differs from the
    digest recorded here. The digest is written in the same transaction that
    applies the reconciliation, so a failed apply does not record a document
    that was never applied and suppress the next attempt.
    """

    __tablename__ = "definition_document_imports"

    document_kind = Column(String, primary_key=True)
    digest = Column(String, nullable=False)
    imported_at = Column(DateTime, nullable=False, server_default=func.now())


class Host(Base):
    """Registered provisioning host.

    This is the single source of truth for host inventory. The Ansible INI
    file is an input format only (via ``POST /hosts/import`` or the
    ``PROVISIONING_INVENTORY_INI`` env var at startup); at runtime, all host
    lookups and inventory rendering use this table. Rows may represent KVM
    hypervisors, bare-metal nodes, or future executor hosts; the row name is
    the Ansible alias used by executor jobs.

    ssh_key_type:
        "path"     — ssh_key_value is a filesystem path (e.g. a mounted
                     Kubernetes Secret at /home/appuser/.ssh/id_ed25519).
        "embedded" — ssh_key_value is a Fernet-encrypted PEM string stored
                     in the DB. Requires SSH_DECRYPTION_KEY to be set.

    enabled:
        False hosts are excluded from list queries and inventory rendering.
        Hosts are never hard-deleted (append-only) so that job history FKs
        (vm_host name references) remain resolvable.

    ssh_port:
        Port the provisioner connects to, defaulting to 22. The registry is
        the authority for how a host is reached — address, user, key, and
        port — and every execution path derives its connection from a
        rendered inventory rather than constructing one.

    pool_id:
        Resource pool this host belongs to. Every host has a pool — there is
        no "unassigned" state. New rows default to the system-created
        "default" pool (DEFAULT_POOL_ID) at both the ORM layer (for
        freshly-created schemas) and the DB layer (for the migration that
        backfills pre-existing rows) so the column can be NOT NULL from the
        start rather than carrying a nullable transitional state.
    """

    __tablename__ = "hosts"

    name = Column(String, primary_key=True)  # Ansible alias, e.g. "kvm1"
    kvm_host = Column(String, nullable=False)  # IP/hostname the provisioner SSHes to
    # Address tenants use to reach this host's VM port-forwards (public IP,
    # DNS, or overlay IP). Distinct from kvm_host: the provisioner may reach
    # the host over a different network than buyers do. NULL → fall back to
    # kvm_host in tenant-facing connection info.
    public_host = Column(String, nullable=True)
    ssh_user = Column(String, nullable=False)  # SSH login user on the KVM host
    # Port the provisioner connects to. Non-default when the host answers
    # through a reverse tunnel, a NAT forward, or a bastion rather than on 22
    # at kvm_host. NOT NULL with a server default so the registry never holds
    # an "unspecified" state that each reader would resolve independently.
    ssh_port = Column(Integer, nullable=False, default=22, server_default="22")
    ssh_key_type = Column(String, nullable=False, default="path")  # "path" | "embedded"
    ssh_key_value = Column(String, nullable=False)  # path string or encrypted PEM
    gpu_count = Column(Integer, nullable=False, default=0)
    # Descriptive hardware identity (e.g. "H100", "A100") -- categorical,
    # matched by equality, not by sufficiency like gpu_count. Nullable: a
    # host with gpu_count=0 has no GPU model to report, and an operator
    # may not have recorded one yet for an existing host.
    gpu_model = Column(String, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    pool_id = Column(
        String,
        ForeignKey(ResourcePool.__table__.c.id),
        nullable=False,
        default=DEFAULT_POOL_ID,
        server_default=DEFAULT_POOL_ID,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# The site-authority ledger models live in the shared market_site
# package; re-exported here because the service's modules and tests
# reach all persistence models through db.models. The tables ride
# market_site's own metadata — init_db creates both.
from market_site.db import (  # noqa: F401
    HELD_RESERVATION_STATES,
    ReservationState,
    CapacityEvent,
    CapacityReservation,
)

# The settlement/fulfillment aggregate lives in the shared
# market_fulfillment package; re-exported here for the same reason. The
# tables ride market_fulfillment's own metadata — init_db creates it
# alongside this service's own Base, market_site's, and
# market_resource_pools'.
from market_fulfillment.db import (  # noqa: F401
    ProvisionedResource,
    SettlementRecord,
    SettlementRecordState,
)
