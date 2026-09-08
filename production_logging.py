"""Structured event logging; never log request bodies or exception payloads."""
import json
import logging
import time
from log_redaction import redact

class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({'ts': time.time(), 'level': record.levelname,
                           'logger': record.name, 'message': redact(record.getMessage())})

def configure_logging():
    logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler()], force=True)
    logging.getLogger().handlers[0].setFormatter(JsonFormatter())
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
