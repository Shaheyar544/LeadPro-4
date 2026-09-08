import os
def validate_production_settings():
 if os.getenv('APP_ENV','local')!='production': return True
 checks={'DATABASE_URL':lambda v:v.startswith(('postgresql://','postgresql+psycopg://')),'REDIS_URL':bool,'SESSION_SECRET':lambda v:bool(v and len(v)>=32),'SECURE_COOKIES':lambda v:v.lower()=='true','DEBUG':lambda v:v.lower()=='false','IN_PROCESS_WORKER':lambda v:v.lower()=='false','SCHEDULER_ENABLED':lambda v:v.lower()=='false','OUTREACH_ENABLED':lambda v:v.lower()=='false','CORS_ALLOW_WILDCARD':lambda v:v.lower()=='false','CAMOFOX_ACCESS_KEY':bool}
 bad=[k for k,f in checks.items() if not os.getenv(k) or not f(os.getenv(k))]
 if bad: raise RuntimeError('Unsafe production configuration: '+','.join(bad))
 return True
