"""PGD / Illustrator: run ExtendScript in the live Illustrator over COM with a timeout.

    from aicom import js, ai_windows, dismiss
    js("app.version")                      -> str (last expression of the script)

Every call runs in a worker thread with its own COM apartment; a call that does not return in `timeout` seconds
means a modal dialog is up -> TimeoutError (the thread is left blocked; call dismiss() and it returns).
Payload crosses COM percent-encoded and is eval'd after decodeURIComponent (backslashes / quotes survive).
"""
import ctypes, ctypes.wintypes as W, threading, time, urllib.parse

import pythoncom, win32com.client

u32 = ctypes.windll.user32
try:  # physical pixels everywhere (PrintWindow captures were cropped in a DPI-unaware process)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:  # noqa: BLE001
    pass


def js(src, timeout=60):
    payload = 'eval(decodeURIComponent("%s"))' % urllib.parse.quote(src, safe="")
    box = {}

    def work():
        pythoncom.CoInitialize()
        try:
            app = win32com.client.GetActiveObject("Illustrator.Application")
            box["r"] = app.DoJavaScript(payload)
        except Exception as e:  # noqa: BLE001
            box["e"] = e
        finally:
            pythoncom.CoUninitialize()

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"Illustrator did not return in {timeout}s (modal dialog?)")
    if "e" in box:
        raise RuntimeError(str(box["e"]))
    return box["r"]


def ai_pid():
    import subprocess
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Illustrator.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].lower().strip('"') == "illustrator.exe":
            return int(parts[1])
    return None


def ai_windows(pid=None, visible_only=True):
    """[(hwnd, class, title, enabled)] top-level windows of the Illustrator process."""
    pid = pid or ai_pid()
    res = []

    @ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def cb(h, _):
        p = W.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and (u32.IsWindowVisible(h) or not visible_only):
            t = ctypes.create_unicode_buffer(256)
            c = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(h, t, 256)
            u32.GetClassNameW(h, c, 256)
            res.append((h, c.value, t.value, bool(u32.IsWindowEnabled(h))))
        return True

    u32.EnumWindows(cb, 0)
    return res


def main_hwnd():
    for h, c, t, en in ai_windows():
        if c == "illustrator":
            return h
    return None


PANELS = ("illustrator", "OWL.Dock", "OWL.ShadowView", "SysShadow", "OWL.FrameDrawer")  # FrameDrawer: untitled helper, not a dialog


def dialogs():
    """visible Illustrator top-level windows that are not the main frame or docked panels."""
    return [w for w in ai_windows() if w[1] not in PANELS]


def dismiss(key="enter", exclude=()):
    """Post Enter (OK, defaults apply) or Escape (Cancel) to every enabled, visible Illustrator dialog window.
    Targeted by window handle: no focus change, no host lock needed."""
    vk = {"enter": 0x0D, "escape": 0x1B}[key]
    hit = []
    for h, c, t, en in dialogs():
        if not en or h in exclude:
            continue
        for msg in (0x100, 0x101):
            u32.PostMessageW(h, msg, vk, 0)
        hit.append((h, c, t))
    return hit


if __name__ == "__main__":
    assert "%" in urllib.parse.quote('a\\b"c', safe="")
    print(js("app.version + ' docs=' + app.documents.length + ' uil=' + app.userInteractionLevel", 30))
    for w in ai_windows():
        print(w)


def js_watch(src, timeout=60, key="enter", settle=0.4, shot_dir=None):
    """Run src; whenever an Illustrator dialog shows up while it runs, record its title (and a PrintWindow PNG into
    shot_dir) and post `key` to it ('Progress' windows are left alone). -> (result or None, error or None, [titles])."""
    box, seen, done = {}, [], set()

    def work():
        try:
            box["r"] = js(src, timeout)
        except Exception as e:  # noqa: BLE001
            box["e"] = str(e)

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t0 = time.time()
    while t.is_alive() and time.time() - t0 < timeout:
        time.sleep(0.25)
        for h, c, title, en in dialogs():
            # 'Progress' (Image Trace 'Fitting Curves...', raster effects): Enter / Escape press its Stop button and
            # cancel the work (the High Fidelity Photo / Shades of Gray traces came out untraced that way)
            if h in done or not en or title.startswith("Progress"):
                continue
            time.sleep(settle)  # let the dialog finish building before reading / answering it
            seen.append(title)
            if shot_dir:
                try:
                    from shot import shot
                    shot(h, f"{shot_dir}/dlg_{int(time.time() * 1000)}.png")
                except Exception:  # noqa: BLE001
                    pass
            for msg in (0x100, 0x101):
                u32.PostMessageW(h, msg, {"enter": 0x0D, "escape": 0x1B}[key], 0)
            done.add(h)
    t.join(2)
    if t.is_alive():
        return None, f"no return in {timeout}s; dialogs seen {seen}", seen
    return box.get("r"), box.get("e"), seen
