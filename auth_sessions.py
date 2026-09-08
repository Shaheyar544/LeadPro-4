import hashlib,secrets,time
def issue_session(user,ttl=28800): return secrets.token_urlsafe(32), secrets.token_urlsafe(32), int(time.time())+ttl
def fingerprint(session_id): return hashlib.sha256(session_id.encode()).hexdigest()
def csrf_valid(expected,provided): return bool(expected and provided and secrets.compare_digest(expected,provided))
