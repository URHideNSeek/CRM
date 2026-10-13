import os
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@lru_cache
def engine():
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("Set DATABASE_URL to a postgresql+psycopg:// connection string.")
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 10})


@contextmanager
def session():
    with Session(engine(), expire_on_commit=False) as db, db.begin():
        yield db
