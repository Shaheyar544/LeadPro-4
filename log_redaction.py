import re
_SECRET=re.compile(r'(?i)(api[_-]?key|authorization|cookie|csrf|password|secret|token|redis_url|database_url|camofox)[=:][^, ]+')
def redact(value): return _SECRET.sub(lambda m:m.group(1)+'=[REDACTED]',str(value))
