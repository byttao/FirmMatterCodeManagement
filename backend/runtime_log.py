"""Bounded operational logs with a strict field allowlist."""
import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from database import DATA_DIR

logger = logging.getLogger('firm.operations')
logger.setLevel(logging.INFO)
logger.propagate = False
drop_count = 0


class SafeHandler(RotatingFileHandler):
    def handleError(self, record):
        global drop_count
        drop_count += 1


def event(name, **fields):
    global drop_count
    try:
        if not logger.handlers:
            directory = DATA_DIR / 'logs'
            directory.mkdir(parents=True, exist_ok=True)
            handler = SafeHandler(directory / 'operations.jsonl', maxBytes=3*1024*1024,
                                  backupCount=30, encoding='utf-8', delay=True)
            handler.setFormatter(logging.Formatter('%(message)s'))
            logger.addHandler(handler)
        allowed = {'request_id','target_url','result','reason_code','duration_ms','operation','job_id','row_count'}
        record = {key: value for key,value in fields.items() if key in allowed}
        record.update(event=name,timestamp=datetime.now(timezone.utc).isoformat())
        logger.info(json.dumps(record,ensure_ascii=False))
    except (OSError,ValueError):
        drop_count += 1
