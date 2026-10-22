"""Heavy IFC work runs in a fresh worker process per job, scheduled against
the computer's memory.

Opening a large IFC, tessellating it and building the pedestrian model each
hold the whole IFC in memory (measured peaks: about 6x the file size to open
it, about 13x to tessellate it; a 371 MB IFC used 4.8 GB in one job). Before,
the server process opened IFCs itself and two tessellation workers could run
at once, so a large model could exhaust memory and fail without a clear
reason. Now:

* every job gets its own process, which exits afterwards, so its memory goes
  back to the system and the server process stays small;
* jobs run side by side only while their estimated peaks fit in the memory
  budget; otherwise they wait their turn;
* a worker that dies (typically out of memory) is reported in plain words,
  with the estimate and the computer's memory;
* each job's time and peak memory go to runtime/logs/performance.jsonl.

``VBB_GEOMETRY_IN_PROCESS=1`` (tests) runs jobs in the calling process.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

# Peak memory per MB of IFC, measured on 109 / 162 / 371 MB models (IFC2X3):
# opening 5.4-5.8x, tessellating 9.8-13.0x. Rounded up, plus the interpreter.
RAM_FACTOR = {"open": 6.5, "geometry": 14.0}
BASE_MB = 400
# Share of physical memory the jobs together may plan to use.
BUDGET_SHARE = 0.75

LOG_PATH: Path | None = None          # set by the app


class JobFailed(RuntimeError):
    """A heavy job could not finish; the message is shown to the engineer."""


# ---------------------------------------------------------------------------
# Memory facts (Windows and Linux, standard library only)
# ---------------------------------------------------------------------------

def total_memory_mb() -> int | None:
    try:
        if sys.platform == "win32":
            import ctypes

            class MemoryStatusEx(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = MemoryStatusEx()
            status.dwLength = ctypes.sizeof(MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys // (1024 * 1024))
            return None
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024))
    except Exception:  # noqa: BLE001
        return None


def peak_rss_mb() -> int | None:
    """Peak memory of the current process."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            counters = Counters()
            counters.cb = ctypes.sizeof(Counters)
            process = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
                return int(counters.PeakWorkingSetSize // (1024 * 1024))
            return None
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(peak // 1024 if sys.platform != "darwin" else peak // (1024 * 1024))
    except Exception:  # noqa: BLE001
        return None


def estimate_mb(paths: list[Path], kind: str) -> int:
    size = sum(p.stat().st_size for p in paths if p and p.exists()) / (1024 * 1024)
    return int(BASE_MB + RAM_FACTOR.get(kind, RAM_FACTOR["geometry"]) * size)


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

class _Scheduler:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._running: dict[int, int] = {}
        self._next = 0

    def budget_mb(self) -> int | None:
        total = total_memory_mb()
        return int(total * BUDGET_SHARE) if total else None

    @contextmanager
    def slot(self, est_mb: int) -> Iterator[dict[str, Any]]:
        budget = self.budget_mb()
        info: dict[str, Any] = {"est_mb": est_mb, "budget_mb": budget, "waited_s": 0.0}
        started = time.time()
        with self._cond:
            ticket = self._next
            self._next += 1
            # Alone it always runs (it may still not fit: reported if it dies);
            # side by side only while the estimates fit the budget.
            while self._running and (budget is None or sum(self._running.values()) + est_mb > budget):
                self._cond.wait()
            self._running[ticket] = est_mb
            info["parallel"] = len(self._running) - 1
        info["waited_s"] = round(time.time() - started, 1)
        try:
            yield info
        finally:
            with self._cond:
                self._running.pop(ticket, None)
                self._cond.notify_all()


SCHEDULER = _Scheduler()


# ---------------------------------------------------------------------------
# Running a job
# ---------------------------------------------------------------------------

def _resolve(target: str) -> Any:
    module, _, name = target.partition(":")
    return getattr(importlib.import_module(module), name)


def _child(target: str, args: tuple, kwargs: dict) -> tuple[Any, dict[str, Any]]:
    started = time.time()
    result = _resolve(target)(*args, **kwargs)
    return result, {"sec": round(time.time() - started, 2), "peak_mb": peak_rss_mb()}


def _log(entry: dict[str, Any]) -> None:
    if LOG_PATH is None:
        return
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def run(label: str, target: str, *args: Any, files: list[Path], kind: str = "geometry",
        **kwargs: Any) -> Any:
    """Run ``module:function(*args, **kwargs)`` as one heavy job and return its result.

    ``files`` are the IFCs the job opens (for the memory estimate and the log).
    """
    est = estimate_mb(files, kind)
    total = total_memory_mb()
    entry: dict[str, Any] = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "job": label,
                             "files": [p.name for p in files if p],
                             "size_mb": round(sum(p.stat().st_size for p in files if p and p.exists()) / 1048576, 1),
                             "est_mb": est, "ram_mb": total}
    in_process = os.environ.get("VBB_GEOMETRY_IN_PROCESS") == "1"
    with SCHEDULER.slot(est) as info:
        entry.update(waited_s=info["waited_s"], parallel=info["parallel"], budget_mb=info["budget_mb"])
        started = time.time()
        try:
            if in_process:
                result, stats = _child(target, args, kwargs)
            else:
                result, stats = _run_in_fresh_process(target, args, kwargs, est, total)
        except Exception as exc:
            entry.update(outcome="failed", sec=round(time.time() - started, 1), error=f"{type(exc).__name__}: {exc}"[:500])
            _log(entry)
            raise
    entry.update(outcome="ok", sec=round(time.time() - started, 1), job_sec=stats["sec"], peak_mb=stats["peak_mb"])
    if isinstance(result, dict) and result.get("outcome"):
        entry["outcome"] = result["outcome"]
    _log(entry)
    return result


def _run_in_fresh_process(target: str, args: tuple, kwargs: dict, est: int, total: int | None) -> tuple[Any, dict]:
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor
    from concurrent.futures.process import BrokenProcessPool

    # "spawn" (the Windows default) everywhere: a forked copy of the running
    # server would inherit uvicorn's state. One process per job: it exits after
    # the job, so the memory of a large IFC is returned to the system.
    pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    try:
        return pool.submit(_child, target, args, kwargs).result()
    except BrokenProcessPool as exc:
        ram = f"{total / 1024:.0f} GB" if total else "unknown"
        raise JobFailed(
            "ตัวประมวลผล IFC หยุดกลางคัน มักเป็นเพราะหน่วยความจำไม่พอ "
            f"(งานนี้ประมาณ {est / 1024:.1f} GB · เครื่องมี {ram}) · "
            "ปิดโปรแกรมอื่นแล้วลองใหม่ หรือเปิดโมเดลทีละชั้น"
        ) from exc
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
