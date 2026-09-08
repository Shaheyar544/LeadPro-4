"""One bounded, reconnecting pool per process; no production SQLite driver."""
import os
from functools import lru_cache
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from alembic.config import Config
from alembic.script import ScriptDirectory

def database_url():
    value = os.getenv('DATABASE_URL', '')
    if not value.startswith(('postgresql://', 'postgresql+psycopg://')):
        raise RuntimeError('DATABASE_URL must be PostgreSQL')
    return value.replace('postgresql://', 'postgresql+psycopg://', 1)

@lru_cache(maxsize=4)
def _engine(url):
    return create_engine(url, pool_size=5, max_overflow=2, pool_pre_ping=True,
                         pool_recycle=300, hide_parameters=True,
                         connect_args={'connect_timeout': 3, 'application_name': 'leadpro-' + os.getenv('SERVICE_ROLE', 'migration')})

def engine():
    return _engine(database_url())

@contextmanager
def transaction():
    with Session(engine(), expire_on_commit=False) as session:
        with session.begin():
            yield session

def migration_head():
    return ScriptDirectory.from_config(Config('alembic.ini')).get_current_head()

def check_database(require_head=True):
    try:
        with engine().connect() as conn:
            conn.execute(text('SELECT 1'))
            return not require_head or conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == migration_head()
    except Exception:
        return False
