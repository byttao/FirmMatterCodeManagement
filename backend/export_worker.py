"""One separate, supervised process; imports neither the web app nor heartbeats."""
import os
import sys
import time
from database import DATA_DIR


def run():
    os.environ['FIRM_EXPORT_WORKER']='1'
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    lock=(DATA_DIR/'export-worker.lock').open('a+b')
    try:
        if os.name=='nt':
            import msvcrt
            lock.write(b'0');lock.flush();lock.seek(0)
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:return
    from exports import cleanup,claim,generate
    # Exit with the service even if the parent crashes, rather than becoming orphaned.
    parent=int(os.getenv('FIRM_EXPORT_PARENT_PID','0'))
    def monitor():
        if os.name=='nt':
            import ctypes
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.OpenProcess.restype=ctypes.c_void_p
            handle=kernel.OpenProcess(0x00100000,False,parent)
            if not handle:os._exit(0)
            kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
            kernel.WaitForSingleObject(handle,0xFFFFFFFF)
            os._exit(0)
        while True:
            if os.getppid()!=parent:os._exit(0)
            time.sleep(1)
    if parent:
        import threading
        threading.Thread(target=monitor,daemon=True).start()
    cleanup(restart=True)
    while True:
        cleanup()
        job=claim()
        if job:generate(job)
        else:time.sleep(1)


def main():
    try:
        run()
    except Exception as error:
        from runtime_log import event
        event('export.worker.failed',reason_code=type(error).__name__)
        raise


if __name__=='__main__':main()
