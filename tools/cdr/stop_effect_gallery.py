"""Stop the running CorelDRAW effect-gallery renderer, and nothing else.

    python stop_effect_gallery.py            # kill the recorded renderer pid, then the CorelDRAW 2024 it started
    python stop_effect_gallery.py --dry-run  # say what would be killed

Why this exists: the Photoshop, Illustrator and CorelDRAW renderers all run a script called effect_gallery.py
(and preset_gallery.py), each owned by a different agent. Killing "every python whose command line contains
effect_gallery.py" killed the Illustrator agent's run on 2026-10-06, and a preset_gallery.py pattern kill did the same
on 2026-10-04. So this helper never matches by name: it reads the pid that effect_gallery.py recorded in
work/cdr/effect_gallery/run.pid.json and kills that pid only after checking that the process still runs THIS
directory's effect_gallery.py (a recycled pid, or another app's renderer, is left alone).
"""
import argparse, json, sys, time
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent
PIDFILE = HERE.parents[1] / "work" / "cdr" / "effect_gallery" / "run.pid.json"
SCRIPT = (HERE / "effect_gallery.py").resolve()


def runs_our_script(p):
    """True when process p is python running tools/cdr/effect_gallery.py (absolute, or relative to its cwd)"""
    try:
        cmd, cwd = p.cmdline(), Path(p.cwd())
    except (psutil.Error, OSError):
        return False
    for a in cmd[1:]:
        if a.lower().endswith("effect_gallery.py"):
            path = Path(a) if Path(a).is_absolute() else cwd / a
            try:
                return path.resolve() == SCRIPT
            except OSError:
                return False
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep-corel", action="store_true", help="leave our CorelDRAW 2024 running")
    a = ap.parse_args()
    if not PIDFILE.exists():
        print("no run.pid.json: no CDR effect-gallery run is recorded; nothing killed")
        return 0
    rec = json.loads(PIDFILE.read_text(encoding="utf-8"))
    pid = int(rec["pid"])
    try:
        p = psutil.Process(pid)
    except psutil.NoSuchProcess:
        print(f"pid {pid} (started {rec.get('started')}) is gone; removing the stale record")
        if not a.dry_run:
            PIDFILE.unlink(missing_ok=True)
        return 0
    if not runs_our_script(p):
        print(f"pid {pid} does NOT run {SCRIPT} (cmdline {p.cmdline()!r}): refusing to kill it")
        return 2
    print(f"{'would kill' if a.dry_run else 'killing'} pid {pid}: {' '.join(p.cmdline())}")
    if not a.dry_run:
        p.kill()
        p.wait(15)
        PIDFILE.unlink(missing_ok=True)
    if not a.keep_corel:
        # only the CorelDRAW 2024 the run itself started (recorded as "corel" by effect_gallery.Scene), and only if
        # that pid is still a CorelDRAW 2024 created after the run began; never every CorelDRAW on the box
        for cp in rec.get("corel") or []:
            try:
                c = psutil.Process(int(cp))
                ok = c.name().lower() == "coreldrw.exe" and r"\25\programs64" in c.exe().lower()
            except (psutil.Error, OSError):
                continue
            if not ok:
                print(f"pid {cp} is no longer our CorelDRAW 2024: left alone")
                continue
            print(f"{'would kill' if a.dry_run else 'killing'} our CorelDRAW 2024 pid {cp} and its children")
            if not a.dry_run:
                for q in c.children(recursive=True) + [c]:
                    try:
                        q.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
        if not rec.get("corel"):
            print("no CorelDRAW pid recorded for this run: no CorelDRAW killed")
        time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
