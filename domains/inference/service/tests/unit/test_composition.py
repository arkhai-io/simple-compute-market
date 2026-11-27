"""The service composes the site ledger over the pool authority's reader.

The ledger learns every pool fact from the reader it is built with. This
service delivers quotas through no host, so its reader carries no host
requirement and no pool needs a host: a requirement here would refuse every
quota declaration, which names none.
"""

from __future__ import annotations

from market_resource_pools import ResourcePoolFacts
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from inference_service.container import build_capacity_ledger


def test_the_ledger_reads_pools_through_a_reader_with_no_host_requirement():
    session_factory = sessionmaker(bind=create_engine("sqlite://"))

    ledger = build_capacity_ledger(session_factory)

    assert isinstance(ledger._pool_facts, ResourcePoolFacts)
    assert ledger._pool_facts.host_requirement is None
    assert ledger._session_factory is session_factory
