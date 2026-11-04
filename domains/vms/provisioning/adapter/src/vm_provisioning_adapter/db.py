"""VM's table: the Ansible pool configuration.

It is VM's own metadata. The provisioning service holds it in its database
beside every other capability's tables: its schema creation creates this
metadata, and its migration history reads this model to create and evolve it.
"""

from sqlalchemy import JSON, Column, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base

from market_resource_pools import ResourcePool

Base = declarative_base()


class AnsiblePoolConfig(Base):
    """Ansible-provider-specific config for a resource pool.

    Provider-specific data lives in its own side table rather than as
    generic columns on ``resource_pools``. Only the "vm.ansible" provider is
    implemented; other providers (kubernetes, gcp, ...) would get their own
    side table, not new columns here.

    No ORM ``relationship()`` back to ``ResourcePool``: that model lives in a
    different declarative registry (``market_resource_pools``), so navigation
    is by explicit ``pool_id`` lookup, which is how the pool configuration
    handler reads and writes this table.
    """

    __tablename__ = "ansible_pool_configs"

    pool_id = Column(String, ForeignKey(ResourcePool.__table__.c.id), primary_key=True)
    # Nullable: a pool that states no playbook runs the service's configured
    # VM playbook, frozen into each job when the job is prepared.
    playbook_path = Column(String, nullable=True)
    requirement_delegate = Column(
        String, nullable=False, default="vm_management_v1", server_default="vm_management_v1"
    )
    extra_vars = Column(JSON, nullable=False, default=dict)
    # Fulfillment-time fallback shape, read only by VM's fulfillment plan's
    # three-tier precedence (derived > requirements > pool default) when
    # neither the negotiated requirements nor a requirement delegate
    # supplies a dimension. Nullable: a pool with no configured default
    # simply contributes nothing at that tier.
    default_vm_ram = Column(Integer, nullable=True)
    default_vm_vcpus = Column(Integer, nullable=True)
    default_vm_disk_size = Column(String, nullable=True)
