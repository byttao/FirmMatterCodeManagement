"""Administrator-only cross-user operational diagnostics."""
from datetime import datetime
import io
import asyncio
from limited_response import LimitedStreamingResponse
import json
import threading
import time
import zipfile
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from auth import get_current_user
from permissions import require
from database import DATA_DIR
from version import APP_VERSION
from runtime_log import event
from error_messages import category, public_error
from diagnostic_reader import window, read_records, scan_records

LOG_DIR = DATA_DIR / "logs"
LOG_PATTERNS = ("operations.jsonl*", "exports.jsonl*")

def administrator(user=Depends(get_current_user)):
    require(user, "diagnostics.read")
    return user

router = APIRouter(prefix="/api/diagnostics", dependencies=[Depends(administrator)])

def record_request(request, status, started):
    event("http.request", level="ERROR" if status >= 500 else "WARNING" if status >= 400 else "INFO",
          request_id=request.state.request_id, method=request.method,
          route=getattr(request.scope.get("route"), "path", "unmatched"), status_code=status,
          duration_ms=round((time.monotonic()-started)*1000,2),
          client_ip=request.client.host if request.client else None,
          actor_id=getattr(request.state,"actor_id",None), category=category(status),
          reason_code=getattr(request.state,"reason_code",public_error(status)["code"] if status >= 400 else "ok"),
          exception_type=getattr(request.state,"exception_type",None),
          exception_location=getattr(request.state,"exception_location",None))

@router.get("/summary")
def summary():
    import runtime_log
    return {"version":APP_VERSION,**runtime_log.health.snapshot()}

scan_slot = threading.BoundedSemaphore(1)
export_slot = threading.BoundedSemaphore(1)

class Filters:
    def __init__(self, since: datetime | None = None, until: datetime | None = None,
                 request_id: str | None = Query(None, max_length=64),
                 actor_id: int | None = Query(None, ge=1),
                 level: str | None = Query(None, regex="^(INFO|WARNING|ERROR)$"),
                 customer_id: int | None = Query(None, ge=1),
                 instance_id: str | None = Query(None, max_length=200)):
        self.raw_since, self.raw_until = since, until
        self.since, self.until = window(since, until)
        self.values = {"request_id": request_id, "actor_id": actor_id, "level": level,
                       "customer_id": customer_id, "instance_id": instance_id}


def selected(filters):
    if not scan_slot.acquire(blocking=False):
        raise HTTPException(429, "已有日志查询或导出正在处理，请稍后重试",headers={"Retry-After":"5"})
    try: return read_records(LOG_DIR, LOG_PATTERNS, filters.since, filters.until, filters.values)
    finally: scan_slot.release()


def selected_scan(filters, subject, cursor=None, page_size=50):
    if not scan_slot.acquire(blocking=False):
        raise HTTPException(429, "已有日志查询或导出正在处理，请稍后重试", headers={"Retry-After":"5"})
    try:
        return scan_records(LOG_DIR, LOG_PATTERNS, filters.raw_since, filters.raw_until, filters.values, str(subject), cursor, page_size)
    finally: scan_slot.release()


@router.get("/logs")
def logs(filters: Filters = Depends(), cursor: str | None = Query(None,max_length=100),
         page_size: int = Query(50,ge=1,le=200), user=Depends(administrator)):
    return selected_scan(filters, user.id, cursor, page_size)


@router.post("/export")
def export_logs(filters: Filters = Depends(), user=Depends(administrator)):
    if not export_slot.acquire(blocking=False):
        raise HTTPException(429, "已有诊断导出正在处理，请稍后重试",headers={"Retry-After":"5"})
    try: return build_export(filters, user.id)
    except BaseException:
        export_slot.release()
        raise


def build_export(filters, subject):
    result = selected_scan(filters, subject, page_size=400)
    output = io.BytesIO()
    summary = {k:v for k,v in result.items() if k != 'items'}
    summary.update(version=APP_VERSION,filters=filters.values,records=len(result['items']),
        说明="有界脱敏诊断；仅本次范围，最多400条/5MiB输出。扫描未完成请在网页继续检索；新查询获取新增记录。")
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        lines, size = [], 0
        for record in result['items']:
            line = (json.dumps(record, ensure_ascii=False)+"\n").encode("utf-8")
            if size+len(line) > 5*1024*1024:
                summary.update(truncated=True,scan_complete=False,truncated_reason='output_5MiB_budget'); break
            lines.append(line); size += len(line)
        summary["records"] = len(lines)
        archive.writestr("logs.jsonl", b"".join(lines))
        archive.writestr("summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
    payload = output.getvalue()
    async def chunks():
        for index in range(0, len(payload), 16384):
            chunk = payload[index:index+16384]
            yield chunk
            await asyncio.sleep(len(chunk)/102400)
    return LimitedStreamingResponse(chunks(), slot=export_slot, media_type="application/zip", headers={
        "Content-Disposition": "attachment; filename=diagnostics.zip", "Cache-Control": "no-store"})
