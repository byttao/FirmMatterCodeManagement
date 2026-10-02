"""Instance-wide, single-process big-file admission and monotonic bandwidth pacing."""
import asyncio
import os
import threading
import time
from fastapi import HTTPException

CHUNK=16384
RATE=int(os.getenv('LARGE_DOWNLOAD_BYTES_PER_SECOND','102400'))
if not 16384 <= RATE <= 1048576:raise RuntimeError('大文件下载速率配置须在16KiB/s至1MiB/s之间')

class Lease:
    def __init__(self, budget):self.budget=budget;self.released=False;self.guard=threading.Lock()
    def release(self):
        with self.guard:
            if self.released:return
            self.released=True
            self.budget.slot.release()
    async def pace(self, source):
        deadline=time.monotonic()
        async for value in source:
            for start in range(0,len(value),CHUNK):
                chunk=value[start:start+CHUNK]
                deadline=max(deadline,time.monotonic())+len(chunk)/self.budget.rate
                await asyncio.sleep(max(0,deadline-time.monotonic()))
                yield chunk

class TransferBudget:
    def __init__(self, rate=RATE):self.rate=rate;self.slot=threading.BoundedSemaphore(1)
    def acquire(self):
        if not self.slot.acquire(blocking=False):
            raise HTTPException(429,'已有大文件正在生成或下载，请稍后重试',headers={'Retry-After':'5'})
        return Lease(self)

budget=TransferBudget()

def check_single_process():
    import sys
    for index,arg in enumerate(sys.argv):
        if arg.startswith('--workers=') and arg.split('=',1)[1]!='1':raise RuntimeError('只允许1个Web进程')
        if arg=='--workers' and index+1<len(sys.argv) and sys.argv[index+1]!='1':raise RuntimeError('只允许1个Web进程')
    for name in ('WEB_CONCURRENCY','UVICORN_WORKERS'):
        try:workers=int(os.getenv(name,'1'))
        except ValueError:raise RuntimeError('Web进程数配置必须为1')
        if workers!=1:raise RuntimeError('本部署仅支持1个Web进程；多进程会破坏统一下载预算，请移除workers配置')

def byte_chunks(value):
    for start in range(0,len(value),CHUNK):yield value[start:start+CHUNK]
