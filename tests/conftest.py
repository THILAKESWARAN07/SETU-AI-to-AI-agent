import os
os.environ["LLM_PROVIDER"] = "mock"
os.environ.pop("BUYER_LLM_PROVIDER", None)
os.environ.pop("MERCHANT_LLM_PROVIDER", None)
os.environ.pop("AUXILIARY_LLM_PROVIDER", None)
os.environ["PAYMENT_MODE"] = "mock"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from sqlalchemy.pool import StaticPool

from backend.app.database import Base, get_db
from backend.seed import seed_db
from backend.app.main import app
from backend.app.config import settings

# SQLite in-memory engine for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function")
def db():
    # Create tables
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    
    # Seed tables with default values
    seed_db(session)
    
    yield session
    
    # Teardown
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass
            
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
