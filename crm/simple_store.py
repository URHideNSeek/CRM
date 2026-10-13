"""Versioned persistent state shared by Streamlit and its integration API."""
import json
from functools import lru_cache
from sqlalchemy import create_engine, text


class ConflictError(Exception):
    pass


@lru_cache
def engine(url):
    if url.startswith(('postgres://', 'postgresql://')):
        url = 'postgresql+psycopg://' + url.split('://', 1)[1]
    if not url.startswith(('postgresql+psycopg://', 'sqlite://')):
        raise ValueError('Use a PostgreSQL connection string.')
    return create_engine(url, pool_pre_ping=True)


def load(url):
    with engine(url).begin() as db:
        db.execute(text('CREATE TABLE IF NOT EXISTS ur_simple_crm_state (id INTEGER PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL)'))
        db.execute(text("INSERT INTO ur_simple_crm_state (id, version, payload) VALUES (1, 0, :payload) ON CONFLICT (id) DO NOTHING"), {'payload': json.dumps({'contacts': [], 'interactions': [], 'tasks': []})})
        row = db.execute(text('SELECT version, payload FROM ur_simple_crm_state WHERE id=1')).one()
    return row.version, json.loads(row.payload)


def save(url, version, payload):
    with engine(url).begin() as db:
        result = db.execute(text('UPDATE ur_simple_crm_state SET payload=:payload, version=version+1 WHERE id=1 AND version=:version'), {'payload': json.dumps(payload), 'version': version})
        if result.rowcount != 1:
            raise ConflictError('Another user updated the CRM. Reload before applying your change.')
    return version + 1
