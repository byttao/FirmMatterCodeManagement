import asyncio
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timedelta
from database import SessionLocal
from exports import MAX_SECONDS
import models
from runtime_log import event


async def supervise():
    process=None
    try:
        while True:
            if process is None or process.poll() is not None:
                if process is not None:
                    event('export.worker.exited',exit_code=process.returncode)
                    await asyncio.sleep(10)
                command=[sys.executable,'--export-worker'] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).with_name('export_worker.py'))]
                try:
                    process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                        env={**os.environ,'FIRM_EXPORT_PARENT_PID':str(os.getpid()),'FIRM_EXPORT_WORKER':'1'})
                    event('export.worker.started',result='accepted')
                except OSError as error:
                    event('export.worker.start_failed',reason_code=type(error).__name__)
                    await asyncio.sleep(10)
                    continue
            def overdue():
                with SessionLocal() as db:
                    return db.query(models.ExportJob.id).filter(models.ExportJob.status=='running',
                        models.ExportJob.started_at<datetime.utcnow()-timedelta(seconds=MAX_SECONDS+15)).first() is not None
            try:
                timed_out=await asyncio.to_thread(overdue)
            except Exception as error:
                event('export.worker.monitor_failed',reason_code=type(error).__name__)
                await asyncio.sleep(5)
                continue
            if timed_out:
                event('export.worker.timeout',reason_code='budget_exceeded')
                process.terminate()
                try:await asyncio.to_thread(process.wait,10)
                except subprocess.TimeoutExpired:process.kill();await asyncio.to_thread(process.wait)
                process=None
            await asyncio.sleep(2)
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:await asyncio.to_thread(process.wait,10)
            except subprocess.TimeoutExpired:process.kill();await asyncio.to_thread(process.wait)
