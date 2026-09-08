import os
import re
_SECRET = re.compile(r"""(?ix)(api[_-]?key|authorization|cookie|csrf|password|secret|token|redis_url|database_url|camofox)[\s"']*[=:][\s"']*(?:Bearer\s+)?[^,\s"'}]+""")
_URL = re.compile(r'(postgres(?:ql)?(?:\+psycopg)?|rediss?)://[^\s]+')
_BEARER = re.compile(r'(?i)Bearer\s+[^\s,]+')

def redact(value):
    result = str(value)
    for key, secret in os.environ.items():
        if len(secret) >= 8 and any(word in key.upper() for word in ('KEY', 'PASSWORD', 'SECRET', 'TOKEN', 'DATABASE_URL', 'REDIS_URL')):
            result = result.replace(secret, '[REDACTED]')
    result = _URL.sub('[REDACTED_URL]', result)
    result = _BEARER.sub('Bearer [REDACTED]', result)
    return _SECRET.sub(lambda m: m.group(1) + '=[REDACTED]', result)
