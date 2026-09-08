import os
from contextlib import contextmanager
try: import redis
except ImportError: redis=None
def _client():
 if not redis: return None
 return redis.Redis.from_url(os.getenv('REDIS_URL','redis://localhost:6379/0'),socket_connect_timeout=1)
def redis_ready():
 if os.getenv('APP_ENV','local')!='production' and redis is None:return True
 try: return bool(_client().ping())
 except Exception:return False
@contextmanager
def coordination_lock(name,ttl=30):
 c=_client(); token=None
 if c:
  token=os.urandom(16).hex(); lock=c.lock('leadpro:'+name,timeout=ttl,blocking_timeout=2); lock.acquire();
 try: yield
 finally:
  if c and token:
   try: lock.release()
   except Exception: pass
