"""PGD / Illustrator: read a whole top-level menu (default Effect) -> work/ai/menu_<name>.json

    python menu_walk.py [Effect]

Illustrator draws its own menu BAR (GetMenu = 0, UIA Invoke on the bar items fails), but the dropped menu is a native
#32768 popup. So: one mouse click on the bar item (inside host_lock("ui")), MN_GETHMENU on the popup window, then walk
that HMENU and all its submenus with GetMenuItemInfoW (no hovering), then Escape posted to the popup.
Node: {name, label (raw, with & accelerators and the tab-separated shortcut), shortcut, cmd_id, enabled, checked,
children}. Separators and section headers are kept with flags so the caller can drop them.
"""
import ctypes, ctypes.wintypes as W, json, sys, time
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

import uiautomation as auto

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tools/hostlock.py: vendored, same host mutex
from hostlock import host_lock  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from aicom import main_hwnd, ai_windows, u32  # noqa: E402

WORK = (PGD / "work/ai")
MN_GETHMENU = 0x01E1


class MENUITEMINFOW(ctypes.Structure):
    _fields_ = [("cbSize", W.UINT), ("fMask", W.UINT), ("fType", W.UINT), ("fState", W.UINT), ("wID", W.UINT),
                ("hSubMenu", W.HMENU), ("hbmpChecked", W.HBITMAP), ("hbmpUnchecked", W.HBITMAP),
                ("dwItemData", ctypes.c_size_t), ("dwTypeData", W.LPWSTR), ("cch", W.UINT), ("hbmpItem", W.HBITMAP)]


u32.GetMenuItemInfoW.argtypes = [W.HMENU, W.UINT, W.BOOL, ctypes.POINTER(MENUITEMINFOW)]
u32.GetMenuItemCount.argtypes = [W.HMENU]
u32.SendMessageW.restype = ctypes.c_ssize_t
u32.SendMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
u32.WindowFromPoint.argtypes = [W.POINT]
u32.GetAncestor.restype = W.HWND
u32.WindowFromPoint.restype = W.HWND
u32.GetForegroundWindow.restype = W.HWND


def clean(label):
    name = label.split("\t")[0].split("\x08")[0]
    name = name.replace("&&", "\0").replace("&", "").replace("\0", "&").strip()
    sc = label.split("\t")[1] if "\t" in label else label.split("\x08")[1] if "\x08" in label else ""
    return name, sc.strip()


def walk(hm, depth=0):
    out = []
    for i in range(u32.GetMenuItemCount(hm)):
        mi = MENUITEMINFOW(cbSize=ctypes.sizeof(MENUITEMINFOW), fMask=0x1 | 0x2 | 0x4 | 0x100 | 0x40)
        # MIIM_STATE|MIIM_ID|MIIM_SUBMENU|MIIM_FTYPE|MIIM_STRING; first call gets the length
        u32.GetMenuItemInfoW(hm, i, True, ctypes.byref(mi))
        buf = ctypes.create_unicode_buffer(mi.cch + 1)
        mi.dwTypeData, mi.cch = ctypes.cast(buf, W.LPWSTR), mi.cch + 1
        u32.GetMenuItemInfoW(hm, i, True, ctypes.byref(mi))
        if mi.fType & 0x800:  # MFT_SEPARATOR
            out.append({"separator": True})
            continue
        name, sc = clean(buf.value)
        d = {"name": name, "label": buf.value, "cmd_id": mi.wID, "enabled": not (mi.fState & 0x3),
             "checked": bool(mi.fState & 0x8)}
        if sc:
            d["shortcut"] = sc
        if mi.hSubMenu:
            d["children"] = walk(mi.hSubMenu, depth + 1)
        out.append(d)
    return out


def to_front(h):
    fg = u32.GetForegroundWindow()
    a = u32.GetWindowThreadProcessId(fg, None)
    b = ctypes.windll.kernel32.GetCurrentThreadId()
    u32.AttachThreadInput(b, a, True)
    try:
        u32.BringWindowToTop(h)
        u32.SetForegroundWindow(h)
    finally:
        u32.AttachThreadInput(b, a, False)


def read_menu(top="Effect"):
    h = main_hwnd()
    w = auto.ControlFromHandle(h)
    r = w.MenuBarControl(Name="menu bar").MenuItemControl(Name=top).BoundingRectangle
    x, y = (r.left + r.right) // 2, (r.top + r.bottom) // 2
    with host_lock("ui", timeout=600):
        prev = u32.GetForegroundWindow()
        try:
            # the click must land on Illustrator: another app in front gets it otherwise (it opened a Photoshop
            # menu once). Bring Illustrator forward (AttachThreadInput, no keystroke: an Alt tap would drop the front app into its menu bar) and check the point.
            to_front(h)
            time.sleep(0.4)
            under = u32.GetAncestor(u32.WindowFromPoint(W.POINT(x, y)), 2)  # GA_ROOT
            if u32.GetForegroundWindow() != h or under != h:
                raise RuntimeError(f"Illustrator is not in front / not under the click (fg={u32.GetForegroundWindow()}, "
                                   f"under={under}, ai={h}); nothing clicked")
            u32.SetCursorPos(x, y)
            time.sleep(0.05)
            u32.mouse_event(2, 0, 0, 0, 0)
            u32.mouse_event(4, 0, 0, 0, 0)
            pop = None
            for _ in range(20):
                time.sleep(0.2)
                pop = next((x[0] for x in ai_windows() if x[1] == "#32768"), None)
                if pop:
                    break
            if not pop:
                raise RuntimeError("menu popup did not open")
            hm = u32.SendMessageW(pop, MN_GETHMENU, 0, 0)
            tree = walk(hm)
        finally:
            for _ in range(4):
                for hh, c, t, en in ai_windows():
                    if hh != h and c == "#32768":
                        for msg in (0x100, 0x101):
                            u32.PostMessageW(hh, msg, 0x1B, 0)
                time.sleep(0.3)
            if prev and prev != h:
                to_front(prev)  # hand focus back to whoever had it
    return tree


def main(top="Effect"):
    WORK.mkdir(parents=True, exist_ok=True)
    tree = read_menu(top)
    (WORK / f"menu_{top}.json").write_text(json.dumps(tree, indent=1), encoding="utf-8")

    def show(t, d=0):
        for n in t:
            if "name" in n:
                print("  " * d + n["name"], n.get("shortcut", ""), n["cmd_id"], "" if n["enabled"] else "(disabled)")
                show(n.get("children", []), d + 1)
    show(tree)


if __name__ == "__main__":
    main(*(sys.argv[1:] or ["Effect"]))
