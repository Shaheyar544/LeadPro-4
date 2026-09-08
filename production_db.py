import os
from sqlalchemy import create_engine, text

def database_url():
 u=os.getenv('DATABASE_URL','sqlite:///./leadpro-local.db')
 if os.getenv('APP_ENV','local')=='production' and not u.startswith(('postgresql://','postgresql+psycopg://')): raise RuntimeError('DATABASE_URL must be PostgreSQL in production')
 return u
def engine(): return create_engine(database_url(), pool_pre_ping=True, future=True)
def check_database():
 try:
  with engine().connect() as c: c.execute(text('SELECT 1'))
  return True
 except Exception: return False
