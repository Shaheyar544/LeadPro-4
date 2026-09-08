from sqlalchemy import text

class ProductionRepository:
    """Small PostgreSQL repository used by the dedicated worker path."""
    def __init__(self, session):
        self.session = session

    def claim_job(self):
        return self.session.execute(text(
            "SELECT id FROM search_jobs WHERE status='queued' "
            "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"
        )).scalar_one_or_none()

    def complete(self, job_id):
        self.session.execute(text(
            "UPDATE search_jobs SET status='completed' WHERE id=:id"), {'id': job_id})
