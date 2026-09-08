from production_db import engine
from production_models import Base
Base.metadata.create_all(engine())
