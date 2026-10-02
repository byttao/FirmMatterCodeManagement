"""Bounded operational logs with a strict field allowlist."""
import json
import logging
import os
import threading
import time
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from database import DATA_DIR

logger = logging.getLogger('firm.operations')
logger.setLevel(logging.INFO)
logger.propagate = False
from log_health import LogHealth
health=LogHealth()
drop_count = 0
guard = threading.Lock()
last_cleanup = 0


class SafeHandler(RotatingFileHandler):
    def handleError(self, record):
        global drop_count
        drop_count += 1
        health.failure()


def event(name, **fields):
    global drop_count, last_cleanup
    try:
        with guard:
            directory = DATA_DIR / 'logs'
            directory.mkdir(parents=True, exist_ok=True)
            filename = 'exports.jsonl' if os.getenv('FIRM_EXPORT_WORKER') == '1' else 'operations.jsonl'
            if not logger.handlers:
                handler = SafeHandler(directory / filename, maxBytes=3*1024*1024,
                                      backupCount=15, encoding='utf-8', delay=True)
                handler.setFormatter(logging.Formatter('%(message)s'))
                logger.addHandler(handler)
            if time.monotonic() - last_cleanup > 3600:
                for path in directory.glob(filename + '.*'):
                    if path.stat().st_mtime < time.time() - 30*86400:
                        path.unlink(missing_ok=True)
                last_cleanup = time.monotonic()
        allowed = {'request_id','target_url','result','reason_code','duration_ms','operation','job_id','row_count','exit_code','level','method','route','status_code','client_ip','actor_id','category','exception_type','exception_location'}
        record = {key: ("".join(c for c in value if ord(c) >= 32)[:500] if isinstance(value,str) else value) for key,value in fields.items() if key in allowed}
        record.update(event=name,timestamp=datetime.now(timezone.utc).isoformat())
        health.recover(logger)
        logger.info(json.dumps(record,ensure_ascii=False))
    except (OSError,ValueError):
        drop_count += 1
        health.failure()
