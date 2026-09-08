"""Ephemeral coordination. PostgreSQL retains all authoritative state."""
import os
import hashlib
import secrets
from contextlib import contextmanager
from functools import lru_cache
import redis

@lru_cache(maxsize=4)
def client(url=None):
    return redis.Redis.from_url(url or os.environ['REDIS_URL'], socket_connect_timeout=2,
                                socket_timeout=3, health_check_interval=5, decode_responses=True)

def _client():
    return client(os.getenv('REDIS_URL', 'redis://localhost:6379/0'))

def redis_ready():
    try:
        return bool(_client().ping())
    except redis.RedisError:
        return False

def wake_worker():
    try:
        with _client().pipeline() as pipe:
            pipe.lpush('leadpro:wakeup', '1').ltrim('leadpro:wakeup', 0, 9).expire('leadpro:wakeup', 60).execute()
    except redis.RedisError:
        pass  # The worker also polls PostgreSQL.

def wait_for_work():
    try:
        _client().blpop('leadpro:wakeup', timeout=1)
    except redis.RedisError:
        pass

def login_attempt(ip):
    key = 'leadpro:login:' + hashlib.sha256(ip.encode()).hexdigest()
    window = int(os.getenv('LOGIN_RATE_WINDOW_SECONDS', '60'))
    count = _client().eval("""
        local n = redis.call('INCR', KEYS[1])
        if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
        return n
    """, 1, key, window)
    return count <= 5

class CoordinationLease:
    """A renewable capacity-one semaphore; lost locks are never silently ignored."""
    def __init__(self, name, ttl=15):
        self.key = 'leadpro:semaphore:' + name
        self.token = secrets.token_hex(24)
        self.ttl = ttl

    def acquire(self):
        return bool(_client().set(self.key, self.token, nx=True, ex=self.ttl))

    def renew(self):
        return bool(_client().eval("""
            if redis.call('GET', KEYS[1]) == ARGV[1] then
                return redis.call('EXPIRE', KEYS[1], ARGV[2])
            end
            return 0
        """, 1, self.key, self.token, self.ttl))

    def release(self):
        try:
            _client().eval("""
                if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
                return 0
            """, 1, self.key, self.token)
        except redis.RedisError:
            pass

@contextmanager
def coordination_lock(name, ttl=30):
    lease = CoordinationLease(name, ttl)
    if not lease.acquire():
        raise RuntimeError('Coordination capacity unavailable')
    try:
        yield
    finally:
        lease.release()
