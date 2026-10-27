"""Keep one customer workspace per local profile; each worker has its own account lock."""
from pathlib import Path
import msvcrt

def acquire(path):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    lock=open(path,"a+b")
    lock.seek(0)
    try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        lock.close()
        raise RuntimeError("AZT Client is already open for this Windows profile.") from None
    return lock
