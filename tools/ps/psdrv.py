"""PGD Photoshop driver: run ExtendScript in Photoshop 2026 over COM with a timeout and modal-dialog rescue.

    import sys; sys.path.insert(0, r"<PGD_HOME>/tools/ps"); import psdrv
    psdrv.js('app.version')                 -> "27.4.0"
    psdrv.jsj('JSON-ish source ending in a string expression')  -> parsed json

Every call runs in its own COM thread with a timeout. A call that does not return means a modal dialog is up:
psdrv dismisses Photoshop's dialog windows by window handle (Cancel/Escape via PostMessage, no global input,
so no host lock is needed) and records what it saw in work/ps/dialogs.log.
"""
import ctypes, ctypes.wintypes as wt, json, subprocess, threading, time, urllib.parse
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

import pythoncom, win32com.client

WORK = (PGD / "work/ps")
WORK.mkdir(parents=True, exist_ok=True)
U = ctypes.windll.user32
LIB = (Path(__file__).with_name("pslib.jsx")).read_text(encoding="ascii") if Path(__file__).with_name("pslib.jsx").exists() else ""


class PSError(RuntimeError):
    pass


def _ps_pids():
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh", "/fi", "imagename eq Photoshop.exe"],
                         capture_output=True, text=True).stdout
    return {int(r.split('","')[1]) for r in out.splitlines() if r.startswith('"Photoshop.exe')}


def ps_windows():
    """Visible top-level windows of Photoshop.exe as dicts {hwnd, cls, title, w, h, owner}."""
    pids, out = _ps_pids(), []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, _):
        pid, cls, t, r = wt.DWORD(), ctypes.create_unicode_buffer(128), ctypes.create_unicode_buffer(256), wt.RECT()
        U.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value in pids and U.IsWindowVisible(h):
            U.GetClassNameW(h, cls, 128)
            U.GetWindowTextW(h, t, 256)
            U.GetWindowRect(h, ctypes.byref(r))
            out.append({"hwnd": h, "cls": cls.value, "title": t.value, "w": r.right - r.left, "h": r.bottom - r.top,
                        "owner": U.GetWindow(h, 4)})  # GW_OWNER
        return True
    U.EnumWindows(cb, 0)
    return out


def _click_button(hwnd, names=("Cancel", "Don't Save", "No", "OK")):
    """BM_CLICK the first plain win32 child button with one of these captions (plug-in dialogs such as Smart Blur
    ignore Escape and UIA Invoke but take BM_CLICK). Targeted at the handle: no global input."""
    found = {}

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, _):
        c, t = ctypes.create_unicode_buffer(64), ctypes.create_unicode_buffer(64)
        U.GetClassNameW(h, c, 64)
        U.GetWindowTextW(h, t, 64)
        if c.value == "Button" and t.value.replace("&", "") in names:
            found.setdefault(t.value.replace("&", ""), h)
        return True
    U.EnumChildWindows(hwnd, cb, 0)
    for n in names:
        if n in found:
            U.PostMessageW(found[n], 0x00F5, 0, 0)  # BM_CLICK
            return True
    return False


def dismiss_dialogs(log_tag=""):
    """Cancel every owned (modal) Photoshop window: click a Cancel/OK button via BM_CLICK if it has one, else Escape.
    Returns the titles seen. Targets window handles only (no global input)."""
    seen = []
    for w in ps_windows():
        if not w["owner"] or w["cls"].startswith("OWL."):
            continue  # main frame, panels and OWL shadow/frame helpers are left alone
        done, text = _click_button(w["hwnd"]), ""
        try:
            from pywinauto import Application
            dlg = Application(backend="uia").connect(handle=w["hwnd"]).window(handle=w["hwnd"])
            if done:
                raise StopIteration  # already clicked; skip UIA
            try:
                text = " / ".join(c.window_text() for c in dlg.descendants(control_type="Text") if c.window_text())[:300]
            except Exception:  # noqa: BLE001
                pass
            for name in ("Cancel", "Don't Save", "No", "OK", "Close"):
                b = dlg.child_window(title=name, control_type="Button")
                if b.exists(timeout=0.3):
                    b.invoke()
                    done = True
                    break
        except Exception:  # noqa: BLE001
            pass
        seen.append(f'{w["cls"]}|{w["title"]}|{text}')
        if not done:
            for msg in (0x100, 0x101):
                U.PostMessageW(w["hwnd"], msg, 0x1B, 0)  # Escape
    if seen:
        with open(WORK / "dialogs.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%X')} {log_tag} {seen}\n")
    return seen


def _worker(code, box):
    pythoncom.CoInitialize()
    try:
        box["r"] = win32com.client.Dispatch("Photoshop.Application").DoJavaScript(code)
    except Exception as e:  # noqa: BLE001
        box["e"] = str(e)
    finally:
        pythoncom.CoUninitialize()


def js(src, timeout=60, tag="", lib=True):
    """Run ExtendScript source; returns the last expression as a string. Raises PSError on script error / hang."""
    inner = (LIB + "\n" if lib else "") + src
    wrapped = ('try { eval(decodeURIComponent("%s")) } catch (e) { "__ERR__" + String(e) + " @line " + e.line }'
               % urllib.parse.quote(inner, safe=""))
    box = {}
    t = threading.Thread(target=_worker, args=(wrapped, box), daemon=True)
    t.start()
    t.join(timeout)
    rescued = []
    while t.is_alive():  # modal dialog (or a very slow filter): dismiss, then give it a little longer
        rescued += dismiss_dialogs(tag)
        t.join(5)
        if len(rescued) > 20:
            raise PSError(f"HANG {tag}: dialogs would not close {rescued[-3:]}")
        if not rescued and not t.is_alive():
            break
        if not rescued:
            t.join(timeout)  # nothing to dismiss: it is just slow; one more full wait
            if t.is_alive():
                raise PSError(f"HANG {tag}: no dialog found, call still running")
    if "e" in box:
        raise PSError(f"COM {tag}: {box['e']}")
    r = box.get("r")
    if rescued:
        raise PSError(f"DIALOG {tag}: had to dismiss {rescued}; result {str(r)[:200]}")
    if isinstance(r, str) and r.startswith("__ERR__"):
        raise PSError(r[7:])
    return r


EXE = os.environ.get("PGD_PS_EXE") or r"C:\Program Files\Adobe\Adobe Photoshop 2026\Photoshop.exe"
PIDFILE = WORK / "ps.pid"  # the Photoshop this pipeline started; only this pid is ever killed


def owned_pid():
    """pid recorded in work/ps/ps.pid when that process is still a running Photoshop.exe, else None."""
    try:
        pid = int(PIDFILE.read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if pid in _ps_pids() else None


def kill_owned(exit_wait=900):
    """Kill the Photoshop this pipeline started (recorded pid only, never by name) and wait for it to exit."""
    pid = owned_pid()
    if pid is None:
        return False
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    t0 = time.time()
    while pid in _ps_pids() and time.time() - t0 < exit_wait:  # a killed Photoshop with GBs of RAM takes minutes to exit
        time.sleep(3)
    return True


def restart_ps(wait=300, exit_wait=900):
    """Kill the Photoshop this pipeline started (by its recorded pid) and start a new one, recording its pid. A
    Photoshop this pipeline did not start is never killed: then PSError. Returns when a script runs."""
    kill_owned(exit_wait)
    foreign = _ps_pids()
    if foreign:
        raise PSError(f"Photoshop pid {sorted(foreign)} was not started by this pipeline (work/ps/ps.pid): not killing it")
    t0 = time.time()
    p = subprocess.Popen([EXE], creationflags=0x00000008 | 0x00000200, close_fds=True)  # DETACHED | NEW_PROCESS_GROUP
    PIDFILE.write_text(str(p.pid))
    while time.time() - t0 < wait:
        time.sleep(5)
        if any(w["cls"] == "Photoshop" for w in ps_windows()):
            try:
                js("app.version", timeout=60, tag="restart")
                time.sleep(5)
                with open(WORK / "dialogs.log", "a", encoding="utf-8") as f:
                    f.write(time.strftime('%X') + " restarted Photoshop" + chr(10))
                return True
            except PSError:
                pass
    raise PSError("Photoshop did not come back after restart")


def jsj(src, **kw):
    return json.loads(js(src, **kw))


if __name__ == "__main__":
    assert js("1+1") == "2", js("1+1")
    try:
        js("throw new Error('boom')")
        raise AssertionError("no error")
    except PSError as e:
        assert "boom" in str(e), e
    print("psdrv ok", js("app.version"), js("app.documents.length"))
