"""Bounded newest-first diagnostics, strict projection, and timezone-aware filters."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from fastapi import HTTPException

FIELDS = {"timestamp","event","level","request_id","client_request_id","method","route","status_code","duration_ms",
          "client_ip","actor_id","category","reason_code","exception_type","exception_location",
          "customer_id","customer_code","customer_name","identity_verified","instance_id","app_version",
          "enabled_practitioner_count","result","operation","job_id","row_count","exit_code"}
MAX_SCAN = 12 * 1024 * 1024
MAX_ROWS = 5000

def window(since, until):
    def utc(value):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    until = utc(until) if until else datetime.now(timezone.utc)
    since = utc(since) if since else until - timedelta(days=1)
    if since > until or until - since > timedelta(days=31):
        raise HTTPException(422, "日志时间范围须为先开始后结束，且不能超过31天")
    return since, until

def read_records(directory, patterns, since, until, filters):
    paths = []
    for pattern in patterns:
        for path in directory.glob(pattern):
            try:
                if path.is_file() and not path.is_symlink(): paths.append((path.stat().st_mtime, path))
            except OSError: pass
    rows, scanned, truncated = [], 0, False
    for _, path in sorted(paths, reverse=True)[:64]:
        remaining = MAX_SCAN - scanned
        if remaining <= 0:
            truncated = True; break
        try:
            with path.open("rb") as source:
                size = source.seek(0, 2)
                start = max(0, size - remaining)
                source.seek(start)
                data = source.read(remaining)
                scanned += len(data)
                if start:
                    data = data.partition(b"\n")[2]; truncated = True
            for line in reversed(data.splitlines()):
                if len(line) > 10000: continue
                try:
                    record = json.loads(line)
                    if not isinstance(record, dict): continue
                    stamp = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00"))
                    if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=timezone.utc)
                    if not since <= stamp <= until: continue
                    def matches(key, value):
                        if value is None: return True
                        if key == "request_id" and record.get("identity_verified") is True:
                            return str(value) in (str(record.get(key)), str(record.get("client_request_id")))
                        return str(record.get(key)) == str(value)
                    if not all(matches(key, value) for key, value in filters.items()): continue
                    rows.append({k: (v[:500] if isinstance(v,str) else v) for k,v in record.items()
                                 if k in FIELDS and (v is None or isinstance(v,(str,int,float,bool)))})
                except (ValueError, KeyError, TypeError): continue
                if len(rows) >= MAX_ROWS:
                    truncated = True; break
        except OSError: continue
        if len(rows) >= MAX_ROWS: break
    rows.sort(key=lambda row: row["timestamp"], reverse=True)
    return rows, truncated
