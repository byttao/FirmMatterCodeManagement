"""Nonrecursive process-local operational log health (never business audit)."""
from datetime import datetime, timezone
import threading

class LogHealth:
    def __init__(self):
        self.started_at=datetime.now(timezone.utc).isoformat()
        self.drops=0;self.last_failure_at=None;self.last_reason=None;self.pending=False
        self.lock=threading.Lock()
    def failure(self, reason='log_write_failed'):
        with self.lock:
            self.drops+=1;self.last_failure_at=datetime.now(timezone.utc).isoformat();self.last_reason=reason;self.pending=True
    def snapshot(self):
        with self.lock:
            return {'process_started_at':self.started_at,'log_drops':self.drops,'last_log_failure_at':self.last_failure_at,'last_log_failure_code':self.last_reason}
    def recover(self,logger):
        import json
        with self.lock:
            pending=self.pending;self.pending=False;before=self.drops
        if pending:
            logger.info(json.dumps({'timestamp':datetime.now(timezone.utc).isoformat(),'event':'log.health_recovered','level':'WARNING','reason_code':'log_write_recovered','result':str(before)}))
