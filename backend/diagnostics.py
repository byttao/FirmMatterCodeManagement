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
from diagnostic_reader import window, read_records

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
    return {"version":APP_VERSION,"log_drops":runtime_log.drop_count}

scan_slot = threading.BoundedSemaphore(1)
export_slot = threading.BoundedSemaphore(1)

class Filters:
    def __init__(self, since: datetime | None = None, until: datetime | None = None,
                 request_id: str | None = Query(None, max_length=64),
                 actor_id: int | None = Query(None, ge=1),
                 level: str | None = Query(None, regex="^(INFO|WARNING|ERROR)$"),
                 customer_id: int | None = Query(None, ge=1),
                 instance_id: str | None = Query(None, max_length=200)):
        self.since, self.until = window(since, until)
        self.values = {"request_id": request_id, "actor_id": actor_id, "level": level,
                       "customer_id": customer_id, "instance_id": instance_id}


def selected(filters):
    if not scan_slot.acquire(blocking=False):
        raise HTTPException(429, "已有日志查询或导出正在处理，请稍后重试")
    try: return read_records(LOG_DIR, LOG_PATTERNS, filters.since, filters.until, filters.values)
    finally: scan_slot.release()


@router.get("/logs")
def logs(filters: Filters = Depends(), page: int = Query(1, ge=1, le=100), page_size: int = Query(50, ge=1, le=200)):
    rows, truncated = selected(filters)
    start = (page - 1) * page_size
    return {"items": rows[start:start+page_size], "has_more": start+page_size < len(rows),
            "page": page, "truncated": truncated}


@router.post("/export")
def export_logs(filters: Filters = Depends()):
    if not export_slot.acquire(blocking=False):
        raise HTTPException(429, "已有诊断导出正在处理，请稍后重试")
    try: return build_export(filters)
    except BaseException:
        export_slot.release()
        raise


def build_export(filters):
    rows, truncated = selected(filters)
    output = io.BytesIO()
    summary = {"version": APP_VERSION, "since": filters.since.isoformat(), "until": filters.until.isoformat(),
               "filters": filters.values, "truncated": truncated, "records": len(rows),
               "说明": "脱敏运行诊断；不含请求正文、密码、Cookie、授权原文、银行信息或完整异常堆栈。扫描上限12MiB/5000条，请缩小范围定位。"}
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        lines, size = [], 0
        for record in rows:
            line = (json.dumps(record, ensure_ascii=False)+"\n").encode("utf-8")
            if size+len(line) > 5*1024*1024:
                summary["truncated"] = True; break
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
