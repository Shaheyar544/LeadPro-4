"""Explicit one-time local administrator bootstrap, after Alembic."""
import os
import bcrypt
from sqlalchemy import select
from production_models import User
from production_db import transaction, check_database
from production_config import validate_production_config

def seed_admin():
    validate_production_config()
    if not check_database():
        raise RuntimeError('Run Alembic first')
    with transaction() as db:
        if db.scalar(select(User).where(User.username == 'admin')) is None:
            password = os.environ['INITIAL_ADMIN_PASSWORD'].encode()
            if len(password) > 72:
                raise RuntimeError('Administrator password exceeds bcrypt limit')
            db.add(User(username='admin', password_hash=bcrypt.hashpw(password, bcrypt.gensalt()).decode()))

if __name__ == '__main__':
    seed_admin()
