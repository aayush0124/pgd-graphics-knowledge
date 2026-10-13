"""
Host-level mutex for heavy local jobs on this box.

    from hostlock import host_lock
    with host_lock("encode", timeout=1800):
        subprocess.run([...])

    python hostlock.py run --slot encode --timeout 1800 -- ffmpeg -i in.mp4 ... out.mp4
    python hostlock.py status

WHY THIS EXISTS (skill-observations obs 51)
-------------------------------------------
Every heavy system on this machine documents "ONE heavy job at a time" -- ComfyLocal,
F5 TTS, the ffmpeg assembles. That rule is scoped to its own pipeline, so N pipelines
each obeying it still produce N concurrent heavy jobs. On 2026-09-03 five daily runs
overlapped and Flux failed with 74 MB free; each individual gate was correct and nothing
scheduled around them, so whichever task ran last simply lost.

A Win32 NAMED MUTEX is the right primitive rather than a lockfile: the kernel releases it
when the holding process dies, so a killed run cannot leave a stale lock that blocks the
box until someone notices. Lockfiles need staleness heuristics; this needs none.

SLOTS
  gpu     ComfyUI / Flux / Wan / any CUDA job        (VRAM + RAM commit)
  encode  large ffmpeg encodes, analysis passes      (CPU; NVENC is separate silicon
                                                      but the decode/filter graph is not)
  tts     F5 / local TTS                             (RAM commit)
  ui      global keyboard / mouse input (SendKeys, pyautogui, focus changes): keystrokes go
          to whatever window has focus, so two jobs dismissing dialogs in different apps
          at once type into each other's windows. Hold it only around the input itself.
Take the narrowest slot that is true. Two different slots may run together on purpose.
"""
import argparse
import contextlib
import ctypes
import os
import subprocess
import sys
import time

SLOTS = ("gpu", "encode", "tts", "ui", "_selftest")
# `_selftest` exists so the selftest never contends with real work. Without it the suite
# asserted "clean box should report encode free" and FAILED while the lock was doing its
# job -- another pipeline legitimately held `encode`. A shared-host primitive whose test
# requires an idle host is untestable exactly when it matters most.
_WAIT_OBJECT_0, _WAIT_ABANDONED, _WAIT_TIMEOUT = 0x0, 0x80, 0x102


class LockBusy(RuntimeError):
    pass


@contextlib.contextmanager
def host_lock(slot, timeout=1800, poll_note=None):
    """Hold the named host mutex for `slot`. Raises LockBusy on timeout."""
    if slot not in SLOTS:
        raise ValueError(f"unknown slot {slot!r}; use one of {SLOTS}")
    if os.name != "nt":                       # worker node / CI: no-op, single tenant
        yield
        return
    k32 = ctypes.windll.kernel32
    # NB the r-prefix. Written once as "Global\aisys_host_..." the \a is a BELL character,
    # so the mutex silently left the Global\ namespace and stopped spanning sessions and
    # elevated processes -- while every selftest passed, because all of them agreed on the
    # same wrong name. A name is shared state: it cannot be checked by agreement with
    # yourself.
    name = rf"Global\aisys_host_{slot}"
    h = k32.CreateMutexW(None, False, name)
    if not h:
        raise OSError(f"CreateMutexW failed: {ctypes.get_last_error()}")
    waited, step = 0.0, 2.0
    try:
        while True:
            r = k32.WaitForSingleObject(h, int(step * 1000))
            if r in (_WAIT_OBJECT_0, _WAIT_ABANDONED):
                break                          # ABANDONED = holder died; we inherit it
            if r != _WAIT_TIMEOUT:
                raise OSError(f"WaitForSingleObject -> {r}")
            waited += step
            if poll_note and waited % 30 < step:
                print(f"[hostlock] waiting {waited:.0f}s for '{slot}' ({poll_note})",
                      file=sys.stderr, flush=True)
            if waited >= timeout:
                raise LockBusy(
                    f"slot '{slot}' held by another job for {timeout}s. Another pipeline "
                    f"is mid-run; retry later rather than forcing it.")
        try:
            yield
        finally:
            k32.ReleaseMutex(h)
    finally:
        k32.CloseHandle(h)


def _held(slot):
    """True if the slot is held. MUST be called from a process that does not hold it.

    A Win32 mutex is re-entrant per THREAD: the owning thread re-acquires instantly, so
    this returns False when asked from inside the holder. That is the point -- the lock
    guards against OTHER processes, which is the failure mode obs 51 describes. `status`
    is therefore only truthful when run as its own process, which is how the CLI runs it.
    """
    try:
        with host_lock(slot, timeout=0):
            return False
    except LockBusy:
        return True


def headroom():
    """(free_physical_mb, commit_used_gb, commit_limit_gb, top_consumer) on Windows.

    RAM COMMIT is the real constraint on this box, not free physical memory -- a job can
    run fine at 1.4 GB physical free and die at 56/62 GB commit. Check commit headroom
    before a heavy allocation so the failure names its cause: an allocator error raised
    deep inside OpenCV or torch reads as a code bug and costs an hour of the wrong search.
    """
    if os.name != "nt":
        return (None, None, None, None)
    ps = ("$o=Get-CimInstance Win32_OperatingSystem;"
          "$p=Get-Process|Sort-Object WS -Descending|Select-Object -First 1;"
          "'{0};{1};{2};{3};{4}' -f [int]($o.FreePhysicalMemory/1KB),"
          "[int]((($o.TotalVirtualMemorySize-$o.FreeVirtualMemory))/1KB),"
          "[int]($o.TotalVirtualMemorySize/1KB),$p.ProcessName,[int]($p.WS/1MB)")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True)
    try:
        f, used, lim, name, mb = r.stdout.strip().split(";")
        return (int(f), int(used) / 1024.0, int(lim) / 1024.0, f"{name} {mb} MB")
    except Exception:
        return (None, None, None, None)


def require_headroom(commit_gb=3.0, what="this job"):
    """Raise with a DIAGNOSIS when the box cannot fit `commit_gb` more commit."""
    free_mb, used, lim, top = headroom()
    if used is None:
        return
    if lim - used < commit_gb:
        raise MemoryError(
            f"{what} needs ~{commit_gb:.1f} GB of commit headroom; the box has "
            f"{lim - used:.1f} GB ({used:.1f}/{lim:.1f} GB committed, {free_mb} MB "
            f"physical free). Largest consumer: {top}. Another pipeline is mid-run -- "
            f"wait for it rather than reading the allocator error as a code bug.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("WHY")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a command holding the lock")
    r.add_argument("--slot", required=True, choices=SLOTS)
    r.add_argument("--timeout", type=float, default=1800)
    r.add_argument("cmdline", nargs=argparse.REMAINDER)
    sub.add_parser("status", help="which slots are held")
    a = ap.parse_args()

    if a.cmd == "status":
        for s in SLOTS:
            print(f"{s:8} {'HELD' if _held(s) else 'free'}")
        return 0

    cmd = a.cmdline[1:] if a.cmdline and a.cmdline[0] == "--" else a.cmdline
    if not cmd:
        print("nothing to run (put the command after `--`)", file=sys.stderr)
        return 2
    t0 = time.time()
    try:
        with host_lock(a.slot, timeout=a.timeout, poll_note=" ".join(cmd[:3])):
            if time.time() - t0 > 1:
                print(f"[hostlock] acquired '{a.slot}' after {time.time()-t0:.0f}s",
                      file=sys.stderr, flush=True)
            return subprocess.run(cmd).returncode
    except LockBusy as e:
        print(f"[hostlock] {e}", file=sys.stderr)
        return 75          # EX_TEMPFAIL: retryable, distinct from a real failure


def _probe(slot):
    """Ask a CHILD process whether `slot` is held -- the only honest probe (see _held)."""
    r = subprocess.run([sys.executable, os.path.abspath(__file__), "--is-held", slot],
                       capture_output=True, text=True)
    return r.returncode == 1


def _selftest():
    n = 0
    A, B = "_selftest", "gpu"
    if _probe(A):
        raise AssertionError(f"slot {A!r} is held -- another selftest is running")
    held_elsewhere = _probe(B)
    assert not _probe(A), "the selftest slot starts free"; n += 1
    with host_lock(A, timeout=5):
        assert _probe(A), "another process must be blocked while we hold it"; n += 1
        if not held_elsewhere:
            assert not _probe(B), "a different slot must stay free"; n += 1
            with host_lock(B, timeout=5):
                assert _probe(B), "the second slot must read held once taken"; n += 1
            assert not _probe(B), "the second slot must free when its block exits"; n += 1
        else:
            print("  (skipped 3 cross-slot checks: another pipeline holds "
                  f"{B!r}, which is the lock working)")
    assert not _probe(A), "slot must free on context exit"; n += 1

    rc = subprocess.run([sys.executable, os.path.abspath(__file__), "run",
                         "--slot", A, "--timeout", "5", "--",
                         sys.executable, "-c", "print('held')"],
                        capture_output=True, text=True).returncode
    assert rc == 0, f"run wrapper should pass through exit 0, got {rc}"; n += 1

    with host_lock(A, timeout=5):
        rc = subprocess.run([sys.executable, os.path.abspath(__file__), "run",
                             "--slot", A, "--timeout", "0", "--",
                             sys.executable, "-c", "pass"],
                            capture_output=True, text=True).returncode
        assert rc == 75, f"contended run must exit 75 (retryable), got {rc}"; n += 1
    print(f"hostlock selftest: {n}/{n} OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    elif "--is-held" in sys.argv:              # internal: honest cross-process probe
        sys.exit(1 if _held(sys.argv[sys.argv.index("--is-held") + 1]) else 0)
    else:
        sys.exit(main())
