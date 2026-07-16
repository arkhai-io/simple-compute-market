from market_site.db import Base, SiteAllocation, SiteResource
from market_site.ledger import CapacityLedgerService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def test_assignment_moves_existing_capacity_without_double_counting(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'ledger.db'}")
    Base.metadata.create_all(engine)
    sf=sessionmaker(bind=engine)
    with sf() as db:
        db.add_all([SiteResource(resource_id='a', total_units=4, enabled=True), SiteResource(resource_id='b', total_units=4, enabled=True)])
        db.add(SiteAllocation(allocation_id='alloc', resource_id='a', units=4, state='reserved'))
        db.commit()
    ledger=CapacityLedgerService(session_factory=sf)
    result=ledger.assign_settlement_resource(allocation_id='alloc', settlement_resource_id='b')
    assert result['resource_id']=='b'
    again=ledger.assign_settlement_resource(allocation_id='alloc', settlement_resource_id='b')
    assert again['resource_id']=='b'
