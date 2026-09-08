"""Real PostgreSQL invariants. CI supplies an isolated PostgreSQL service."""
import os
from datetime import timedelta
import pytest

pytestmark = pytest.mark.skipif(os.getenv('RUN_POSTGRES_TESTS') != '1', reason='Opt-in real PostgreSQL integration')


def test_schema_is_at_head_and_matches_models():
    from alembic.migration import MigrationContext
    from alembic.autogenerate import compare_metadata
    from production_db import engine, check_database
    from production_models import Base
    assert check_database()
    with engine().connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    assert len(Base.metadata.tables) == 13


def test_transaction_rollback_and_foreign_keys():
    from sqlalchemy import select, func
    from sqlalchemy.exc import IntegrityError
    from production_db import transaction
    from production_models import User, Session, utcnow, uid
    marker = uid()
    with pytest.raises(RuntimeError):
        with transaction() as db:
            db.add(User(id=marker, username=marker, password_hash='test-only'))
            db.flush()
            raise RuntimeError('rollback fixture')
    with transaction() as db:
        assert db.get(User, marker) is None
    with pytest.raises(IntegrityError):
        with transaction() as db:
            db.add(Session(user_id=marker, expires_at=utcnow()))
            db.flush()


def test_skip_locked_claim_and_expired_lease_fencing():
    from sqlalchemy import select, delete
    from production_db import transaction
    from production_models import User, SearchJob, utcnow, uid
    from production_repository import ProductionRepository, LeaseLost
    # CI database is exclusive to this test process; do not run against live data.
    repo = ProductionRepository()
    user_id, a, b = uid(), uid(), uid()
    with transaction() as db:
        db.add(User(id=user_id, username=user_id, password_hash='fixture'))
        db.flush()
        db.add_all([SearchJob(id=x, user_id=user_id, payload={}) for x in (a, b)])
    try:
        with transaction() as locked:
            locked.scalar(select(SearchJob).where(SearchJob.id == a).with_for_update())
            claimed = repo.claim_job()
            assert claimed.id == b  # Another PostgreSQL connection skips locked a.
        stale = claimed.lease_token
        with transaction() as db:
            db.get(SearchJob, b).lease_until = utcnow() - timedelta(seconds=1)
            db.get(SearchJob, a).status = 'completed'
        replacement = repo.claim_job()
        assert replacement.id == b and replacement.lease_token != stale
        with pytest.raises(LeaseLost):
            repo.finish(b, stale)
        repo.finish(b, replacement.lease_token)
    finally:
        with transaction() as db:
            db.execute(delete(SearchJob).where(SearchJob.user_id == user_id))
            db.execute(delete(User).where(User.id == user_id))


def test_production_imports_never_load_legacy_storage():
    import subprocess
    import sys
    code = "import sys; import lead_engine.api, lead_engine.worker; assert not {'sqlite3', 'database', 'engine_store', 'config', 'app'} & set(sys.modules)"
    result = subprocess.run([sys.executable, '-c', code], capture_output=True)
    assert result.returncode == 0
