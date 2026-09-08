"""Pure helpers shared by the browser and both storage implementations."""
from datetime import datetime, timezone
from urllib.parse import urlsplit
import uuid

def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

def uid():
    return uuid.uuid4().hex

def domain(url):
    try:
        return (urlsplit(url or '').hostname or '').lower().removeprefix('www.')
    except ValueError:
        return ''
