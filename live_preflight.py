"""Worker-owned browser readiness, shared privately over Redis with the API."""
import os
import redis
from local_modes import run_mode, validate_mode, LIVE_ERROR
from production_db import check_database


def client():
    return redis.Redis.from_url(os.environ['REDIS_URL'], socket_connect_timeout=2, socket_timeout=2)


def readiness_key():
    return 'leadpro:worker-ready:' + run_mode()


def publish_ready(available):
    with client() as conn:
        if available:
            conn.set(readiness_key(), 'ready', ex=8)
        else:
            conn.delete(readiness_key())


def preflight():
    try:
        validate_mode()
    except RuntimeError:
        return LIVE_ERROR if run_mode() == 'live' else 'Offline test configuration is invalid'
    if not check_database():
        return 'PostgreSQL is not ready'
    try:
        with client() as conn:
            if not conn.ping() or conn.get(readiness_key()) != b'ready':
                return 'Worker or CamoFox is not ready; discovery was not started'
    except redis.RedisError:
        return 'Redis is not ready; discovery was not started'
    return None
