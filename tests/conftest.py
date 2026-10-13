import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from crm.models import Base


@pytest.fixture
def db():
    # Same suite runs on PostgreSQL in CI; SQLite is only a fast local test harness.
    url = os.getenv("TEST_DATABASE_URL", "sqlite://")
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    Base.metadata.create_all(engine)
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
            yield session
        transaction.rollback()
    engine.dispose()
