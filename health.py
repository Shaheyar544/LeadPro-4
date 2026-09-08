from production_db import check_database
from redis_coordination import redis_ready
def liveness(): return {'status':'ok'}
def readiness():
 db=check_database(); rd=redis_ready(); production=__import__('os').getenv('APP_ENV','local')=='production'; ok=db and (rd if production else True)
 return {'status':'ok' if ok else 'not_ready','postgres':db,'redis':rd,'production':production}
