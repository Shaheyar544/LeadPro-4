import os
def validate_production_config():
 if os.getenv('APP_ENV','local')!='production': return True
 required=('DATABASE_URL','REDIS_URL','CAMOFOX_ACCESS_KEY','INITIAL_ADMIN_PASSWORD')
 missing=[k for k in required if not os.getenv(k)]
 if missing: raise RuntimeError('Missing production configuration: '+','.join(missing))
 if len(os.getenv('INITIAL_ADMIN_PASSWORD',''))<12: raise RuntimeError('INITIAL_ADMIN_PASSWORD must be 12+ characters')
 return True
