"""PGD/CDR: one owner thread for CorelDRAW 2024 COM, with a timeout on every call and modal-dialog dismissal.

    from cdr_com import Corel
    cd = Corel()                       # starts / attaches CorelDRAW.Application.25 (never .23 = 2021)
    n = cd.call(lambda app: app.Documents.Count, timeout=30)

Every call runs on a dedicated COM thread. If it does not return within `timeout`, a modal dialog is assumed: every
visible top-level window of the CorelDRAW 2024 process except the main frame gets its Cancel / Close / OK / No button
invoked through UI Automation (aimed at that window; no global keyboard or mouse, so no host_lock needed), and the
call gets `grace` more seconds. A call that still hangs raises CallTimeout; the COM thread is then stuck and the
caller should restart (cd.kill() + new Corel()).

cd.kill() kills ONLY the CorelDRAW 2024 process(es) that appeared while THIS Corel() started (cd.pids), with their
child processes. It never kills every CorelDRAW 2024 on the box: on 2026-10-06 two agents were driving CorelDRAW at
once and a kill-everything restart in one of them took the other's app down. When Corel() attached to an instance that
was already running (cd.pids empty), kill() does nothing and says so; Corel(own=True) refuses to attach at all.
"""
import queue, threading, time
from pathlib import Path

import pythoncom
import win32com

# Private makepy cache. The shared %TEMP%/gen_py maps Corel's interface IIDs (identical across versions) to the
# CorelDRAW 2021 typelib (23.0) another pipeline generated lazily, so EnsureDispatch on .25 died with
# "module ...x0x23x0 has no attribute CLSIDToClassMap". Our own cache generates VGCore 25.1 cleanly.
GEN = Path(__file__).resolve().parents[2] / "work" / "cdr" / "gen_py"
GEN.mkdir(parents=True, exist_ok=True)
win32com.__gen_path__ = str(GEN)
import win32com.gen_py  # noqa: E402
win32com.gen_py.__path__ = [str(GEN)]
import win32com.client  # noqa: E402
from win32com.client import gencache  # noqa: E402

PROGID = "CorelDRAW.Application.25"
EXE_DIR = r"\CorelDRAW Graphics Suite\25\Programs64"   # 2021 lives under ...\Suite 2021 / \23: never touch it
LOG = Path(__file__).resolve().parents[2] / "work" / "cdr" / "dialogs.log"


class CallTimeout(RuntimeError):
    pass


def corel_pids():
    import psutil
    out = []
    for p in psutil.process_iter(["name", "exe"]):
        try:
            if (p.info["name"] or "").lower() == "coreldrw.exe" and EXE_DIR.lower() in (p.info["exe"] or "").lower():
                out.append(p.pid)
        except Exception:  # noqa: BLE001
            pass
    return out


def dismiss_dialogs(note=""):
    """Invoke Cancel/Close/OK/No on every visible non-main top-level window of CorelDRAW 2024. -> list of titles."""
    from pywinauto import Desktop
    import win32api, win32con, win32gui, win32process
    done = []
    # Pass 1, plain Win32 (never blocks): every visible #32770 dialog of the 2024 process gets WM_COMMAND IDCANCEL
    # posted to its own handle. The UIA pass below HUNG for minutes while "Change Document Defaults" was up (tools
    # stage 2026-10-04: activating the Callout tool with nothing selected raises it); IDCANCEL closed it at once.
    pids = set(corel_pids())

    def enum(h, acc):
        if win32gui.IsWindowVisible(h) and win32gui.GetClassName(h) == "#32770" and \
                win32process.GetWindowThreadProcessId(h)[1] in pids:
            acc.append(h)
        return True
    dlgs = []
    win32gui.EnumWindows(enum, dlgs)
    for h in dlgs:
        win32api.PostMessage(h, win32con.WM_COMMAND, win32con.IDCANCEL, 0)
        done.append(f"{win32gui.GetWindowText(h)!r} [#32770] -> IDCANCEL")
    if dlgs:
        time.sleep(2)
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {note}: {done}\n")
        return done
    for pid in pids:
        try:
            wins = Desktop(backend="uia").windows(process=pid, visible_only=True)
        except Exception:  # noqa: BLE001
            continue
        for w in wins:
            try:
                title = w.window_text()
                cls = w.element_info.class_name
            except Exception:  # noqa: BLE001
                continue
            # the main frame: class "CorelDRAW25" on 25.1 (title "CorelDRAW - Untitled-1*"). The old test (Afx class or
            # "CorelDRAW 25.0") missed it and UIA Invoked a "Cancel" button INSIDE the main window (dialogs.log
            # 2026-10-04 13:48-13:57, tools stage). Never touch the main frame.
            if (cls or "").startswith("CorelDRAW") or (title.startswith("CorelDRAW") and "Afx" in (cls or "")):
                continue
            hit = None
            for want in ("Cancel", "Close", "No", "OK", "Don't Save", "Don't save"):
                try:
                    btns = [b for b in w.descendants(control_type="Button") if b.window_text().replace("&", "") == want]
                except Exception:  # noqa: BLE001
                    btns = []
                if btns:
                    try:
                        btns[0].invoke()
                        hit = want
                        break
                    except Exception:  # noqa: BLE001
                        pass
            if not hit:
                try:
                    w.close()          # WM_CLOSE posted to that window only
                    hit = "WM_CLOSE"
                except Exception:  # noqa: BLE001
                    hit = "none"
            done.append(f"{title!r} [{cls}] -> {hit}")
    if done:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {note}: {done}\n")
    return done


class NotOurCorel(RuntimeError):
    pass


class Corel:
    def __init__(self, start_timeout=300, own=False):
        """own=True: we must START CorelDRAW 2024 ourselves; attaching to one somebody else runs raises NotOurCorel"""
        before = set(corel_pids())
        self.q = queue.Queue()
        self.t = threading.Thread(target=self._loop, daemon=True)
        self.t.start()
        self.call(self._start, timeout=start_timeout, grace=60)
        self.pids = set(corel_pids()) - before   # the instance this Corel() started (empty = attached)
        if own and not self.pids:
            self.q.put((None, None, None))
            raise NotOurCorel(f"CorelDRAW 2024 was already running (pids {sorted(before)}) and COM attached to it; "
                              "it belongs to another client, so this run will not drive it")

    @staticmethod
    def _start(app):
        app.Visible = True
        return True

    def _loop(self):
        pythoncom.CoInitialize()
        app = None
        while True:
            fn, box, ev = self.q.get()
            if fn is None:
                break
            try:
                if app is None:
                    app = gencache.EnsureDispatch(PROGID)  # starts CorelDRAW 2024 if it is not running
                box["r"] = fn(app)
            except Exception as e:  # noqa: BLE001
                box["e"] = e
            ev.set()

    def call(self, fn, timeout=60, grace=45, note=""):
        box, ev = {}, threading.Event()
        self.q.put((fn, box, ev))
        if not ev.wait(timeout):
            closed = dismiss_dialogs(note or getattr(fn, "__name__", "call"))
            if not ev.wait(grace):
                closed += dismiss_dialogs("retry " + note)
                if not ev.wait(grace):
                    raise CallTimeout(f"no return after {timeout + 2 * grace}s; dismissed {closed}")
            box.setdefault("dismissed", closed)
        if "e" in box:
            raise box["e"]
        return box.get("r")

    def kill(self):
        """kill the CorelDRAW 2024 this Corel() started (and its children); never any other instance"""
        import psutil
        if not self.pids:
            print("  Corel.kill: this client attached to a CorelDRAW it did not start; nothing killed", flush=True)
            return []
        done = []
        for pid in sorted(self.pids):
            try:
                p = psutil.Process(pid)
                procs = p.children(recursive=True) + [p]
            except psutil.NoSuchProcess:
                continue
            for q in procs:
                try:
                    q.kill()
                    done.append(q.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        return done


if __name__ == "__main__":  # smoke check: attach, report version and open documents
    cd = Corel()
    print(cd.call(lambda a: (a.VersionMajor, a.VersionMinor, a.VersionBuild, a.Version, a.Documents.Count), 30))
