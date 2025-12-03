from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from src.config import settings
from src.db.models import Base

# Create engine based on database type
if settings.is_sqlite:
    engine = create_engine(
        settings.database_url.replace("sqlite:///", "sqlite:///"),
        connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
        poolclass=StaticPool if "sqlite" in settings.database_url else None,
    )
else:
    engine = create_engine(
        settings.database_url,
        pool_size=20,
        max_overflow=0,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    """Dependency for getting database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)

