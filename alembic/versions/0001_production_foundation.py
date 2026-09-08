revision='0001'; down_revision=None
from alembic import op
import sqlalchemy as sa
def upgrade():
 for name in ('search_jobs','businesses','audit_evidence','lead_scores'): pass
def downgrade(): pass
