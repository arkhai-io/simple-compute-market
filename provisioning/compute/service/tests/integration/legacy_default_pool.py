"""The ``default`` pool a database from before resource pools came to hold.

Migration creates no pool, so a test of data an older database holds — hosts,
VM leases, jobs placed in ``default`` — stores the pool and its VM
configuration itself, in the shape the rest of the chain left them.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from compute_provisioning_service.db.models import DEFAULT_POOL_ID, ResourcePool
from vm_provisioning_adapter.db import AnsiblePoolConfig


def add_legacy_default_pool(engine, *, playbook_path: str) -> None:
    with Session(engine) as session, session.begin():
        session.add(ResourcePool(
            id=DEFAULT_POOL_ID,
            label="Default Pool",
            provider="vm.ansible",
            enabled=True,
            policy_tags={
                "deliverable_modes": ["vm"],
                "advertisable_modes": ["vm"],
                "capacity_backing": "backed",
            },
        ))
        session.flush()
        session.add(AnsiblePoolConfig(
            pool_id=DEFAULT_POOL_ID,
            playbook_path=playbook_path,
            extra_vars={},
        ))
